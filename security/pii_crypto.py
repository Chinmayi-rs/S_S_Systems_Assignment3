import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class PIICipher:
    """Encrypt and decrypt voter fields using an externally supplied key."""

    def __init__(self, key):
        if len(key) != 32:
            raise ValueError("PII encryption requires a 32-byte key.")

        self._cipher = AESGCM(key)

    @classmethod
    def from_environment(cls):
        encoded_key = os.environ.get("PII_ENCRYPTION_KEY")

        if not encoded_key:
            raise RuntimeError("PII_ENCRYPTION_KEY is not configured.")

        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError) as error:
            raise RuntimeError(
                "PII_ENCRYPTION_KEY must contain valid Base64."
            ) from error

        return cls(key)

    def encrypt(self, value, *, context):
        nonce = os.urandom(12)

        ciphertext = self._cipher.encrypt(
            nonce,
            value.encode("utf-8"),
            context.encode("utf-8"),
        )

        encoded = base64.b64encode(nonce + ciphertext).decode("ascii")
        return "v1:" + encoded

    def decrypt(self, encrypted_value, *, context):
        if not encrypted_value.startswith("v1:"):
            raise ValueError("Unsupported encrypted value format.")

        payload = base64.b64decode(
            encrypted_value[3:],
            validate=True,
        )

        if len(payload) < 28:
            raise ValueError("Encrypted value is too short.")

        plaintext = self._cipher.decrypt(
            payload[:12],
            payload[12:],
            context.encode("utf-8"),
        )

        return plaintext.decode("utf-8")