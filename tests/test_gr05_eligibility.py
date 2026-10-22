
import os
import tempfile

import pytest
import pyotp
from app import create_app, db
from app.models.user import User
from app.services.ballot_box import _eligibility_error
from app.services.elections import current_election
from app.services.seed import deterministic_totp_secret

# Create temporary databases for testing

@pytest.fixture()
def client():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["IDENTITY_DATABASE_URL"] = (
            "sqlite:///" + os.path.join(directory, "identity.db")
        )
        os.environ["BALLOT_DATABASE_URL"] = (
            "sqlite:///" + os.path.join(directory, "ballot.db")
        )
        os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-at-least-32-bytes-long"
        os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long"

        app = create_app()
        app.config["TESTING"] = True

        try:
            with app.test_client() as test_client:
                yield test_client
        finally:
            # Close SQLAlchemy sessions and database connections
            # before Windows deletes the temporary SQLite files.
            with app.app_context():
                db.session.remove()
                db.engines[None].dispose()

                for bind_name, engine in db.engines.items():
                    if bind_name is not None:
                        engine.dispose()



# Login and receive authentication token
def login(client, username="voter", password="voter1234"):
    code = pyotp.TOTP(deterministic_totp_secret(username)).now()
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password, "totp_code": code}
    )

    assert response.status_code == 200

    token = response.get_json()["access_token"]
    return {"Authorization": "Bearer " + token}


# Test 1: Unverified voters cannot request a ballot
def test_ineligible_voter(client):
    headers = login(client, "pending", "voter1234")

    response = client.post(
        "/api/ballots/issue",
        headers=headers
    )

    assert response.status_code == 403


# Test 2: Eligible voters can request a ballot
def test_eligible_voter(client):
    headers = login(client)

    response = client.post(
        "/api/ballots/issue",
        headers=headers
    )

    assert response.status_code == 201
    assert "token" in response.get_json()


# Test 3: Inactive voters fail eligibility validation
def test_inactive_voter(client):
    with client.application.app_context():
        user = User.query.filter_by(username="voter").first()
        user.is_active = False
        db.session.commit()

        election = current_election()
        error = _eligibility_error(user, election)

        assert error is not None
        assert error[1] == 403


# Test 4: Voters in the wrong division are rejected
def test_wrong_division(client):
    with client.application.app_context():
        user = User.query.filter_by(username="voter").first()
        user.division = "Sydney"
        db.session.commit()

        election = current_election()
        error = _eligibility_error(user, election)

        assert error is not None
        assert error[1] == 403


# Test 5: A voter cannot successfully vote twice
def test_duplicate_vote(client):
    headers = login(client)

    candidates = client.get("/api/candidates").get_json()["candidates"]

    house = [
        candidate["id"]
        for candidate in candidates
        if candidate["chamber"] == "house"
    ]

    senate = next(
        candidate["party"]
        for candidate in candidates
        if candidate["chamber"] == "senate"
    )

    issued = client.post(
        "/api/ballots/issue",
        headers=headers
    )
    assert issued.status_code == 201

    token = issued.get_json()["token"]

    staged = client.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )
    assert staged.status_code == 200

    first_vote = client.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )
    assert first_vote.status_code == 201

    second_vote = client.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )
    assert second_vote.status_code == 409

    new_token = client.post(
        "/api/ballots/issue",
        headers=headers
    )
    assert new_token.status_code == 409

# GR-06: Test that an invalid ballot token is rejected
def test_invalid_ballot_token(client):
    headers = login(client)

    # Generate an invalid token
    invalid_token = "invalid-token-12345"

    # Attempt to stage a ballot using the invalid token
    response = client.post(
        "/api/ballots/stage",
        json={
            "token": invalid_token,
            "house": [1, 2, 3],
            "senate_party": "Invalid"
        },
        headers=headers
    )

    # Invalid tokens must be rejected
    assert response.status_code == 409



# GR-06: Test that a ballot token cannot be reused
def test_reused_ballot_token(client):
    headers = login(client)

    # Retrieve valid candidates
    response = client.get("/api/candidates")
    candidates = response.get_json()["candidates"]

    house = [
        candidate["id"]
        for candidate in candidates
        if candidate["chamber"] == "house"
    ]

    senate = next(
        candidate["party"]
        for candidate in candidates
        if candidate["chamber"] == "senate"
    )

    # Request a ballot token
    issued = client.post(
        "/api/ballots/issue",
        headers=headers
    )

    assert issued.status_code == 201
    token = issued.get_json()["token"]

    # Stage the ballot
    staged = client.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )

    assert staged.status_code == 200

    # Submit the ballot for the first time
    first_vote = client.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )

    assert first_vote.status_code == 201

    # Attempt to submit the same token again
    second_vote = client.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )

    # Reusing the token must be rejected
    assert second_vote.status_code == 409
