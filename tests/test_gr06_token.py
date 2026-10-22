
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

# GR-06: End-to-end single-use token and anonymity checks

from app import db
from app.models.ballot import Ballot, BallotToken, StagedBallot
from app.services.ballot_crypto import token_tag
from conftest import auth_headers, ballot_choices


def test_gr06_token_replay_rejected(api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    assert issued.status_code == 201
    token = issued.get_json()["token"]

    staged = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate,
        },
        headers=headers,
    )
    assert staged.status_code == 200

    first = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers,
    )
    assert first.status_code == 201

    replay = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers,
    )
    assert replay.status_code == 409


def test_gr06_committed_ballot_has_no_voter_identity(api, app):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    staged = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate,
        },
        headers=headers,
    )
    assert staged.status_code == 200

    committed = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers,
    )
    assert committed.status_code == 201

    with app.app_context():
        ballot = Ballot.query.first()
        assert ballot is not None

        # Committed ballot should have no direct identity fields.
        columns = set(Ballot.__table__.columns.keys())

        assert "voter_id" not in columns
        assert "user_id" not in columns
        assert "token_hash" not in columns


def test_gr06_staged_ballot_removed_after_commit(api, app):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    staged = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate,
        },
        headers=headers,
    )
    assert staged.status_code == 200

    with app.app_context():
        assert StagedBallot.query.count() == 1

    committed = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers,
    )
    assert committed.status_code == 201

    with app.app_context():
        assert StagedBallot.query.count() == 0


def test_gr06_identity_hash_differs_from_ballot_tag(api, app):
    headers = auth_headers(api, "voter", "voter1234")

    issued = api.post("/api/ballots/issue", headers=headers)
    assert issued.status_code == 201
    token = issued.get_json()["token"]

    with app.app_context():
        identity_token = BallotToken.query.first()
        assert identity_token is not None

        identity_hash = identity_token.token_hash
        ballot_tag = token_tag(token)

        # Different representations prevent direct hash matching.
        assert identity_hash != ballot_tag
