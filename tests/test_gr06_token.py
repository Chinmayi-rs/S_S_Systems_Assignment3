
import secrets

from app.services.ballot_box import hash_token


# GR-06 Test 1: Each token must be unique
def test_tokens_are_unique():
    token1 = secrets.token_urlsafe(32)
    token2 = secrets.token_urlsafe(32)

    assert token1 != token2


# GR-06 Test 2: Token hashing must be consistent
def test_token_hash_consistency():
    token = secrets.token_urlsafe(32)

    first_hash = hash_token(token)
    second_hash = hash_token(token)

    assert first_hash == second_hash


# GR-06 Test 3: Different tokens produce different hashes
def test_different_token_hashes():
    token1 = secrets.token_urlsafe(32)
    token2 = secrets.token_urlsafe(32)

    assert hash_token(token1) != hash_token(token2)


# GR-06 Test 4: Raw token must differ from stored hash
def test_raw_token_not_equal_hash():
    token = secrets.token_urlsafe(32)

    assert token != hash_token(token)


# GR-06 Test 5: Hash must have SHA-256 length
def test_sha256_hash_length():
    token = secrets.token_urlsafe(32)

    assert len(hash_token(token)) == 64
