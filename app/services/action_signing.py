"""GR-16 Non-repudiation of delegate actions.

Every audit entry written by a Commissioner's delegate is signed with that
delegate's own Ed25519 key. The signature covers the entry's hash, and the
hash covers actor, action, detail, time and the previous entry's hash. So the
signature proves: this delegate, this action, this exact point in the log.

Why it adds something over the hash chain (GR-15): anyone with write access to
the database can rewrite the whole chain and recompute every hash. Nobody can
recompute a delegate's signature without that delegate's private key.
"""
import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from app import db
from app.models.signing import ActionSignature, DelegateKey
from app.models.user import User
from app.utils.constants import ROLE_DELEGATE

ALGORITHM = 'Ed25519'
SIGN_PREFIX = b'BALLOTDESK-DELEGATE-ACTION-v1|'  # domain separation: this key signs nothing else
KEY_REGISTERED = 'delegate.key.registered'


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def signed_message(entry_hash: str) -> bytes:
    return SIGN_PREFIX + entry_hash.encode('ascii')


def _kek() -> bytes:
    # Key-encryption key. Comes from the environment (Docker secret in production), never from the database.
    secret = os.environ.get('DELEGATE_KEY_SECRET', 'dev-delegate-key-secret-change-me')
    return hashlib.sha256(secret.encode('utf-8')).digest()


def get_or_create_key(user: User) -> DelegateKey:
    """Return the delegate's key, creating it on first use. The creation is itself written to the audit chain."""
    key = DelegateKey.query.filter_by(user_id=user.id).first()
    if key:
        return key

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    raw_public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    nonce = os.urandom(12)
    # user id is bound in as associated data, so a sealed key cannot be moved to another delegate
    sealed = nonce + AESGCM(_kek()).encrypt(nonce, raw_private, str(user.id).encode('ascii'))

    key = DelegateKey(
        user_id=user.id,
        public_key=_b64(raw_public),
        fingerprint=hashlib.sha256(raw_public).hexdigest(),
        private_key_enc=_b64(sealed),
    )
    db.session.add(key)
    db.session.flush()

    from app.services.audit_log import append_audit  # imported here: audit_log imports this module

    append_audit(
        KEY_REGISTERED,
        json.dumps({'user_id': user.id, 'fingerprint': key.fingerprint, 'algorithm': ALGORITHM}),
        actor=user,
    )
    return key


def _load_private(key: DelegateKey) -> Ed25519PrivateKey:
    sealed = base64.b64decode(key.private_key_enc)
    raw = AESGCM(_kek()).decrypt(sealed[:12], sealed[12:], str(key.user_id).encode('ascii'))
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_event(event, user: User) -> ActionSignature:
    """Sign a freshly appended audit entry. Runs in the caller's transaction: if signing fails, the action fails."""
    key = get_or_create_key(user)
    signature = _load_private(key).sign(signed_message(event.entry_hash))
    row = ActionSignature(
        audit_event_id=event.id,
        signer_id=user.id,
        key_id=key.id,
        algorithm=ALGORITHM,
        signature=_b64(signature),
    )
    db.session.add(row)
    db.session.flush()
    return row


def verify_signatures(events) -> dict:
    """Check that every delegate entry carries a valid signature from that delegate's registered key.

    `events` are the audit entries, ordered by id ascending.
    """
    signatures = {row.audit_event_id: row for row in ActionSignature.query.all()}
    keys = {row.id: row for row in DelegateKey.query.all()}
    roles = {row.id: row.role for row in User.query.all()}

    # fingerprints that were written into the (hash-chained) log when each key was registered
    registered = {}
    for event in events:
        if event.action == KEY_REGISTERED:
            detail = json.loads(event.detail)
            registered[detail['user_id']] = detail['fingerprint']

    checked, problems = 0, []
    for event in events:
        if roles.get(event.actor_id) != ROLE_DELEGATE:
            continue
        checked += 1
        row = signatures.get(event.id)
        if row is None:
            problems.append({'event_id': event.id, 'reason': 'delegate action has no signature'})
            continue
        key = keys.get(row.key_id)
        if key is None or key.user_id != event.actor_id or row.signer_id != event.actor_id:
            problems.append({'event_id': event.id, 'reason': 'signed by a key that does not belong to the acting delegate'})
            continue
        raw_public = base64.b64decode(key.public_key)
        fingerprint = hashlib.sha256(raw_public).hexdigest()
        if fingerprint != key.fingerprint or fingerprint != registered.get(event.actor_id):
            problems.append({'event_id': event.id, 'reason': 'public key does not match the key registered in the audit log'})
            continue
        try:
            Ed25519PublicKey.from_public_bytes(raw_public).verify(
                base64.b64decode(row.signature), signed_message(event.entry_hash)
            )
        except InvalidSignature:
            problems.append({'event_id': event.id, 'reason': 'signature is invalid for this entry'})
    return {'valid': not problems, 'checked': checked, 'problems': problems}
