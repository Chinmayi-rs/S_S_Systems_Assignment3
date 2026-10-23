"""Ballot encryption primitives (GR-09).

Nothing in here touches the database. ``ballot_store`` calls these functions,
and the tally and integrity scan call them again when they read a ballot back.
"""

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services import ballot_keys

SCHEME = 'ballot-v1'
NONCE_BYTES = 12  # 96-bit nonce, the size AES-GCM is designed for
# Every plaintext is padded to the same length before encryption. Without this,
# ciphertext length leaks the vote: "Labor" and "Liberal" are different lengths.
PADDED_PLAINTEXT_BYTES = 512


class BallotCryptoError(Exception):
    """A ballot could not be encrypted or decrypted."""


def b64e(data):
    return base64.b64encode(data).decode('ascii')


def b64d(text):
    return base64.b64decode(text.encode('ascii'), validate=True)


# --- GR-09: unlinkable token tag ------------------------------------------

def token_tag(raw_token):
    """Ballot-side lookup value for a one-time ballot token.

    The identity database stores SHA-256(token) next to the voter id. If the
    ballot database stored the same value, joining the two tables would reveal
    who cast which ballot. Instead the ballot side stores HMAC(tag_key, token).
    Neither value can be derived from the other without the raw token, which
    only the voter's browser ever holds.
    """
    return hmac.new(ballot_keys.tag_key(), raw_token.encode('utf-8'), hashlib.sha256).hexdigest()


# --- GR-09: coarse timestamps ---------------------------------------------

def coarse_time(moment=None):
    """Round down to the hour so ballot rows cannot be matched to login times."""
    moment = moment or datetime.utcnow()
    return moment.replace(minute=0, second=0, microsecond=0)


# --- GR-09: AES-256-GCM ---------------------------------------------------

def _aad(election_id, ballot_id):
    # Binds the ciphertext to its row. Copying a ciphertext into another
    # ballot id or election makes decryption fail.
    return f'{SCHEME}|{election_id}|{ballot_id}'.encode('utf-8')


def _pad(plaintext):
    if len(plaintext) > PADDED_PLAINTEXT_BYTES - 2:
        raise BallotCryptoError('Ballot content is larger than the padded block')
    length = len(plaintext).to_bytes(2, 'big')
    return length + plaintext + b'\x00' * (PADDED_PLAINTEXT_BYTES - 2 - len(plaintext))


def _unpad(padded):
    if len(padded) != PADDED_PLAINTEXT_BYTES:
        raise BallotCryptoError('Unexpected plaintext length')
    length = int.from_bytes(padded[:2], 'big')
    if length > PADDED_PLAINTEXT_BYTES - 2:
        raise BallotCryptoError('Corrupt padding')
    return padded[2:2 + length]


def encrypt_preferences(election_id, ballot_id, preferences):
    """Return (nonce_b64, ciphertext_b64) for a preferences dict."""
    plaintext = json.dumps(preferences, sort_keys=True, separators=(',', ':')).encode('utf-8')
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(ballot_keys.encryption_key()).encrypt(
        nonce, _pad(plaintext), _aad(election_id, ballot_id)
    )
    return b64e(nonce), b64e(ciphertext)


def decrypt_preferences(election_id, ballot_id, nonce_b64, ciphertext_b64):
    try:
        padded = AESGCM(ballot_keys.encryption_key()).decrypt(
            b64d(nonce_b64), b64d(ciphertext_b64), _aad(election_id, ballot_id)
        )
        return json.loads(_unpad(padded))
    except (InvalidTag, ValueError, TypeError) as exc:
        raise BallotCryptoError('Ballot could not be decrypted') from exc