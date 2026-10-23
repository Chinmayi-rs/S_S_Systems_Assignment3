"""GR-13 Signed publication of the final results.

Publishing is a two-delegate action (GR-14, action type 'results.release'). When the second
delegate approves, the app:

    1. requires the GR-12 dual tally gate to release the counts,
  2. builds the result as canonical JSON (sorted keys, no spaces - the same rule as the audit chain),
     together with who proposed it, who approved it and the audit log head at that moment,
  3. signs SHA-256(that JSON) with the election's own Ed25519 key,
  4. stores the JSON, the hash and the signature in an append-only table.

What the signature proves: this is the result that was published, and nobody changed it afterwards.
What it does NOT prove: that the counting was right. That is GR-12 (two counters) and GR-11 (ballot store).
"""
import base64
import hashlib
import json
import os
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.audit import AuditEvent
from app.models.published_result import PublishedResult, ResultsKey
from app.services.audit_chain import GENESIS_HASH, canonical
from app.services.audit_log import append_audit
from app.services.tally import build_results
from app.services.tally_gate import dual_tally

ALGORITHM = 'Ed25519'
SIGN_PREFIX = b'BALLOTDESK-RESULTS-v1|'  # domain separation: this key signs nothing else
SCHEMA = 'ballotdesk.results.v1'
KEY_REGISTERED = 'results.key.registered'


class PublicationError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def signed_message(sha256_hex: str) -> bytes:
    return SIGN_PREFIX + sha256_hex.encode('ascii')


def _kek() -> bytes:
    # Key-encryption key. A different secret from DELEGATE_KEY_SECRET, so one leak does not open both.
    secret = os.environ.get('RESULTS_KEY_SECRET', 'dev-results-key-secret-change-me')
    return hashlib.sha256(secret.encode('utf-8')).digest()


def _aad(election_id: int) -> bytes:
    # the election id is bound in as associated data: a sealed key cannot be moved to another election
    return f'results-key:{election_id}'.encode('ascii')


# ---- the signing key ---------------------------------------------------------------------------

def get_key(election_id: int):
    return ResultsKey.query.filter_by(election_id=election_id).first()


def get_or_create_key(election, actor) -> ResultsKey:
    """Return the election's results key, creating it at the first publication.

    The creation is written to the audit chain, so the public key's fingerprint is on record
    (signed by the approving delegate through GR-16) before the first result is signed with it.
    """
    key = get_key(election.id)
    if key:
        return key

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    nonce = os.urandom(12)
    sealed = nonce + AESGCM(_kek()).encrypt(nonce, raw_private, _aad(election.id))

    key = ResultsKey(
        election_id=election.id,
        public_key=_b64(raw_public),
        fingerprint=hashlib.sha256(raw_public).hexdigest(),
        private_key_enc=_b64(sealed),
    )
    db.session.add(key)
    db.session.flush()
    append_audit(
        KEY_REGISTERED,
        json.dumps({'election_id': election.id, 'fingerprint': key.fingerprint, 'algorithm': ALGORITHM}),
        actor=actor,
    )
    return key


def _load_private(key: ResultsKey) -> Ed25519PrivateKey:
    sealed = base64.b64decode(key.private_key_enc)
    raw = AESGCM(_kek()).decrypt(sealed[:12], sealed[12:], _aad(key.election_id))
    return Ed25519PrivateKey.from_private_bytes(raw)


# ---- publishing --------------------------------------------------------------------------------

def get_published(election_id: int):
    return PublishedResult.query.filter_by(election_id=election_id).first()


def _audit_head() -> str:
    last = AuditEvent.query.order_by(AuditEvent.id.desc()).first()
    return last.entry_hash if last else GENESIS_HASH


def publish(election, proposer, approver, approval_id, tally_outcome=None) -> PublishedResult:
    """Sign and store the result. Runs inside the approval transaction: any failure undoes everything."""
    if get_published(election.id):
        raise PublicationError('The results of this election are already published')
    if tally_outcome is None:
        tally_outcome = dual_tally(election.id)
    if not tally_outcome['released']:
        raise PublicationError(tally_outcome['reason'] or 'The tally gate blocked publication')

    key = get_or_create_key(election, approver)
    published_at = datetime.utcnow().replace(microsecond=0)

    document = {
        'schema': SCHEMA,
        'results': build_results(election),
        'publication': {
            'election_id': election.id,
            'approval_id': approval_id,
            'proposed_by': proposer.username,
            'approved_by': approver.username,
            'audit_head_hash': _audit_head(),  # ties the result to the state of the audit log
            'published_at': published_at.isoformat() + 'Z',
        },
    }
    body = canonical(document)
    digest = hashlib.sha256(body).hexdigest()
    signature = _load_private(key).sign(signed_message(digest))

    row = PublishedResult(
        election_id=election.id,
        result_json=body.decode('utf-8'),
        sha256=digest,
        algorithm=ALGORITHM,
        signature=_b64(signature),
        key_id=key.id,
        key_fingerprint=key.fingerprint,
        approval_id=approval_id,
        proposer_id=proposer.id,
        approver_id=approver.id,
        published_at=published_at,
    )
    db.session.add(row)
    try:
        db.session.flush()
    except IntegrityError:
        # a second publication for the same election; the database allows only one
        db.session.rollback()
        raise PublicationError('The results of this election are already published')
    return row


# ---- checking ----------------------------------------------------------------------------------

def registered_fingerprints(election_id: int) -> list:
    """Fingerprints written into the (hash-chained) audit log when the results key was created."""
    found = []
    for event in AuditEvent.query.filter_by(action=KEY_REGISTERED).order_by(AuditEvent.id.asc()).all():
        detail = json.loads(event.detail)
        if detail.get('election_id') == election_id:
            found.append(detail['fingerprint'])
    return found


def verify_published(row: PublishedResult) -> dict:
    """Re-check the stored result: the hash, the signature, and that the key is the one on record."""
    key = db.session.get(ResultsKey, row.key_id)
    checks = {'hash_matches': False, 'signature_valid': False, 'key_matches_audit_log': False}
    problems = []

    if hashlib.sha256(row.result_json.encode('utf-8')).hexdigest() == row.sha256:
        checks['hash_matches'] = True
    else:
        problems.append('the stored result does not match its hash')

    raw_public = base64.b64decode(key.public_key)
    fingerprint = hashlib.sha256(raw_public).hexdigest()
    if fingerprint == key.fingerprint == row.key_fingerprint and fingerprint in registered_fingerprints(row.election_id):
        checks['key_matches_audit_log'] = True
    else:
        problems.append('the public key does not match the key registered in the audit log')

    try:
        Ed25519PublicKey.from_public_bytes(raw_public).verify(
            base64.b64decode(row.signature), signed_message(row.sha256)
        )
        checks['signature_valid'] = True
    except InvalidSignature:
        problems.append('the signature is not valid for this hash')

    return {'valid': all(checks.values()), 'checks': checks, 'problems': problems, 'sha256': row.sha256,
            'key_fingerprint': row.key_fingerprint}
