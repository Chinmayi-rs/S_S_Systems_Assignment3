"""Key custody for the ballot store (GR-09, GR-10).

Three keys protect ballots, and none of them is ever written to either database:

* ``enc``  - 32-byte AES-256-GCM key that encrypts ballot content (GR-09)
* ``tag``  - 32-byte HMAC-SHA256 key that turns the voter's raw ballot token into
             the ballot-side lookup tag, so the ballot database shares no key value
             with the identity database (GR-09)
* ``sign`` - Ed25519 private key for the election, used to sign every ballot at
             the point of encryption (GR-10)

Where keys come from, in order:

1. Environment variables (production / Docker secrets):
   ``BALLOT_ENC_KEY`` and ``BALLOT_TAG_KEY`` as base64 of 32 bytes,
   ``BALLOT_SIGNING_KEY`` as base64 of the 32-byte Ed25519 private seed.
2. Otherwise, files in ``BALLOT_KEY_DIR`` (default ``<project>/instance/keys``),
   created with mode 0600 on first run. ``instance/`` is git-ignored.

Prototype assumption (state this in the report): a real deployment would keep
these in an HSM or a cloud KMS. That was descoped; see the group plan, section 4.
"""

import base64
import os
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

KEY_BYTES = 32

_ENV_NAMES = {
    'enc': 'BALLOT_ENC_KEY',
    'tag': 'BALLOT_TAG_KEY',
    'sign': 'BALLOT_SIGNING_KEY',
}

_lock = threading.Lock()
_cache = {}


class KeyConfigurationError(RuntimeError):
    """Raised when a configured key is present but unusable."""


def default_key_dir():
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_root, 'instance', 'keys')


def key_dir():
    return os.environ.get('BALLOT_KEY_DIR') or default_key_dir()


def _decode(name, value):
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise KeyConfigurationError(f'{_ENV_NAMES[name]} is not valid base64') from exc
    if len(raw) != KEY_BYTES:
        raise KeyConfigurationError(f'{_ENV_NAMES[name]} must decode to {KEY_BYTES} bytes')
    return raw


def _load_or_create_file(name):
    directory = key_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, f'ballot_{name}.key')
    if os.path.exists(path):
        with open(path, 'rb') as handle:
            return _decode(name, handle.read().strip())
    raw = os.urandom(KEY_BYTES)
    # O_EXCL so two workers starting together cannot both write different keys.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, 'rb') as handle:
            return _decode(name, handle.read().strip())
    with os.fdopen(fd, 'wb') as handle:
        handle.write(base64.b64encode(raw))
    return raw


def _raw_key(name):
    cache_key = (name, key_dir(), os.environ.get(_ENV_NAMES[name]))
    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]
        env_value = os.environ.get(_ENV_NAMES[name])
        raw = _decode(name, env_value) if env_value else _load_or_create_file(name)
        _cache[cache_key] = raw
        return raw


def encryption_key():
    return _raw_key('enc')


def tag_key():
    return _raw_key('tag')


def signing_key():
    return Ed25519PrivateKey.from_private_bytes(_raw_key('sign'))


def verify_key():
    return signing_key().public_key()


def public_key_pem():
    """The election verify key, safe to publish so anyone can check ballot signatures."""
    return verify_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode('ascii')


def load_public_key_pem(pem):
    key = serialization.load_pem_public_key(pem.encode('ascii'))
    if not isinstance(key, Ed25519PublicKey):
        raise KeyConfigurationError('Not an Ed25519 public key')
    return key


def generate_env_values():
    """Fresh values for a .env file or Docker secrets. Used by scripts/generate_ballot_keys.py."""
    return {env: base64.b64encode(os.urandom(KEY_BYTES)).decode('ascii') for env in _ENV_NAMES.values()}


def clear_cache():
    with _lock:
        _cache.clear()
