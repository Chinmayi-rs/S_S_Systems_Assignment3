"""GR-10: Ed25519 signatures on ballots.

A ballot is signed over its ciphertext at the moment it is encrypted
(``seal``). A SQLAlchemy ``before_insert`` hook (registered in models/ballot.py)
re-checks the signature on every Ballot row before it reaches the database,
so a code path that forgets to sign, or a forged row added to the session,
is refused at the storage layer rather than trusted. The tally verifies every
signature again before it counts anything.
"""

from cryptography.exceptions import InvalidSignature

from app.services import ballot_crypto, ballot_keys
from app.services.ballot_crypto import b64d, b64e


class UnsignedBallotError(Exception):
    """Raised when something tries to store a ballot without a valid signature."""


def signing_message(election_id, ballot_id, nonce_b64, ciphertext_b64):
    """The exact bytes that are signed. The plaintext is never signed or exposed."""
    return f'{ballot_crypto.SCHEME}|{election_id}|{ballot_id}|{nonce_b64}|{ciphertext_b64}'.encode('ascii')


def sign(election_id, ballot_id, nonce_b64, ciphertext_b64):
    message = signing_message(election_id, ballot_id, nonce_b64, ciphertext_b64)
    return b64e(ballot_keys.signing_key().sign(message))


def verify(election_id, ballot_id, nonce_b64, ciphertext_b64, signature_b64, public_key=None):
    """True only for a present, well-formed, valid signature. Never raises."""
    if not signature_b64 or not nonce_b64 or not ciphertext_b64:
        return False
    try:
        message = signing_message(election_id, ballot_id, nonce_b64, ciphertext_b64)
        (public_key or ballot_keys.verify_key()).verify(b64d(signature_b64), message)
        return True
    except (InvalidSignature, ValueError, TypeError, UnicodeEncodeError):
        return False


def verify_row(ballot, public_key=None):
    return verify(ballot.election_id, ballot.id, ballot.nonce, ballot.ciphertext, ballot.signature, public_key)


def seal(election_id, ballot_id, preferences):
    """Encrypt then sign in one call, so no code path can produce an encrypted but unsigned ballot."""
    nonce_b64, ciphertext_b64 = ballot_crypto.encrypt_preferences(election_id, ballot_id, preferences)
    return nonce_b64, ciphertext_b64, sign(election_id, ballot_id, nonce_b64, ciphertext_b64)


def reject_unsigned(mapper, connection, target):
    """SQLAlchemy before_insert hook, registered on Ballot in models/ballot.py."""
    if not verify_row(target):
        raise UnsignedBallotError('Ballot rejected: missing or invalid signature')