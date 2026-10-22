
# GR-08: Ballot Review and Confirmation Security Tests
# Verifies ballot staging, review, confirmation and replay prevention.

from app import db
from app.models.ballot import Ballot

from conftest import auth_headers, ballot_choices


# Test 1: A ballot cannot be submitted without review/staging
def test_cannot_commit_without_review(api):
    headers = auth_headers(api, "voter", "voter1234")

    issued = api.post("/api/ballots/issue", headers=headers)
    assert issued.status_code == 201

    token = issued.get_json()["token"]

    response = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )

    assert response.status_code == 400
    assert "review" in response.get_json()["error"].lower()


# Test 2: Incomplete House preferences are rejected
def test_incomplete_ballot_rejected(api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    response = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house[:-1],
            "senate_party": senate
        },
        headers=headers
    )

    assert response.status_code == 400


# Test 3: Valid choices produce a review summary
def test_valid_ballot_review(api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    response = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )

    assert response.status_code == 200

    review = response.get_json()

    assert review["staged"] is True
    assert review["senate_party"] == senate
    assert len(review["house"]) == len(house)

    # Check preference order
    assert [
        item["id"] for item in review["house"]
    ] == house

    assert [
        item["preference"] for item in review["house"]
    ] == list(range(1, len(house) + 1))


# Test 4: Voter can change selections before final commitment
def test_change_ballot_before_confirmation(api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    first = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )
    assert first.status_code == 200

    # Reverse House preferences before confirming
    updated_house = list(reversed(house))

    second = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": updated_house,
            "senate_party": senate
        },
        headers=headers
    )

    assert second.status_code == 200

    review = second.get_json()

    assert [
        item["id"] for item in review["house"]
    ] == updated_house


# Test 5: A reviewed ballot can be successfully committed
def test_confirm_ballot_successfully(api, app):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    staged = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )
    assert staged.status_code == 200

    committed = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )

    assert committed.status_code == 201

    result = committed.get_json()

    assert result["message"] == "Ballot accepted"
    assert result["reference"]

    # Check a committed ballot exists in the ballot database
    with app.app_context():
        assert Ballot.query.count() == 1


# Test 6: Confirmation must not reveal voting preferences
def test_confirmation_does_not_reveal_choices(api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    staged = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )
    assert staged.status_code == 200

    committed = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )
    assert committed.status_code == 201

    result = committed.get_json()

    assert "house" not in result
    assert "senate_party" not in result
    assert "preferences" not in result
    assert "token" not in result


# Test 7: A confirmed ballot cannot be submitted again
def test_cannot_submit_confirmed_ballot_twice(api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    token = issued.get_json()["token"]

    staged = api.post(
        "/api/ballots/stage",
        json={
            "token": token,
            "house": house,
            "senate_party": senate
        },
        headers=headers
    )
    assert staged.status_code == 200

    first = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )
    assert first.status_code == 201

    second = api.post(
        "/api/ballots/commit",
        json={"token": token},
        headers=headers
    )

    assert second.status_code == 409
