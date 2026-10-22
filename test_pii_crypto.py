import base64

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.pii_crypto import PIICipher


def make_cipher():
    return PIICipher(AESGCM.generate_key(bit_length=256))


def test_personal_details_can_be_recovered():
    cipher = make_cipher()

    details = {
        "date_of_birth": "2000-05-12",
        "address": "10 Example Street",
    }

    for field, original in details.items():
        context = f"voter:123:{field}"
        encrypted = cipher.encrypt(original, context=context)

        assert encrypted != original
        assert cipher.decrypt(encrypted, context=context) == original


def test_repeated_encryption_produces_different_values():
    cipher = make_cipher()
    context = "voter:123:address"

    first = cipher.encrypt("10 Example Street", context=context)
    second = cipher.encrypt("10 Example Street", context=context)

    assert first != second


def test_modified_ciphertext_is_rejected():
    cipher = make_cipher()
    context = "voter:123:address"
    encrypted = cipher.encrypt("10 Example Street", context=context)

    payload = bytearray(base64.b64decode(encrypted[3:]))
    payload[-1] ^= 1
    modified = "v1:" + base64.b64encode(payload).decode("ascii")

    with pytest.raises(InvalidTag):
        cipher.decrypt(modified, context=context)


def test_wrong_key_is_rejected():
    first_cipher = make_cipher()
    second_cipher = make_cipher()
    context = "voter:123:address"

    encrypted = first_cipher.encrypt(
        "10 Example Street",
        context=context,
    )

    with pytest.raises(InvalidTag):
        second_cipher.decrypt(encrypted, context=context)


def test_wrong_voter_or_field_is_rejected():
    cipher = make_cipher()
    encrypted = cipher.encrypt(
        "10 Example Street",
        context="voter:123:address",
    )

    for context in (
        "voter:456:address",
        "voter:123:date_of_birth",
    ):
        with pytest.raises(InvalidTag):
            cipher.decrypt(encrypted, context=context)


def test_missing_key_stops_initialisation(monkeypatch):
    monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError):
        PIICipher.from_environment()


def test_environment_key_can_be_loaded(monkeypatch):
    key = AESGCM.generate_key(bit_length=256)
    monkeypatch.setenv(
        "PII_ENCRYPTION_KEY",
        base64.b64encode(key).decode("ascii"),
    )

    cipher = PIICipher.from_environment()
    context = "voter:123:address"
    encrypted = cipher.encrypt("10 Example Street", context=context)

    assert cipher.decrypt(
        encrypted,
        context=context,
    ) == "10 Example Street"