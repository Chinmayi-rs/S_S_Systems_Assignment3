import base64
import hashlib

import pytest

from app import db
from app.models.ballot import Ballot
from app.models.election import Election
from conftest import (
    auth_headers,
    ballot_choices,
    cast_ballot,
    tamper_as_db_admin,
)


@pytest.fixture()
def accepted(api):
    headers = auth_headers(api, "voter", "voter1234")
    return cast_ballot(api, headers)


def close_election(app, election_id):
    """Close only the isolated test election."""
    with app.app_context():
        election = db.session.get(Election, election_id)
        election.status = "closed"
        db.session.commit()


def test_receipt_matches_final_ciphertext(app, accepted):
    with app.app_context():
        ballot = db.session.get(Ballot, accepted["reference"])
        expected = hashlib.sha256(
            base64.b64decode(ballot.ciphertext, validate=True)
        ).hexdigest()

    assert accepted["receipt"] == expected
    assert accepted["receipt_algorithm"] == "sha256-ciphertext-v1"


def test_receipts_blocked_before_close(api, accepted):
    election_id = accepted["election_id"]

    published = api.get(
        f"/api/receipts/published/{election_id}"
    )
    checked = api.post("/api/receipts/check", json={
        "election_id": election_id,
        "receipt": accepted["receipt"],
    })

    assert published.status_code == 403
    assert checked.status_code == 403


def test_anonymous_check_after_close(app, api, accepted):
    close_election(app, accepted["election_id"])

    response = api.post("/api/receipts/check", json={
        "election_id": accepted["election_id"],
        "receipt": accepted["receipt"],
    })

    assert response.status_code == 200
    assert response.get_json() == {
        "election_id": accepted["election_id"],
        "algorithm": "sha256-ciphertext-v1",
        "included": True,
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_unknown_receipt_is_not_included(app, api, accepted):
    close_election(app, accepted["election_id"])

    unknown = "0" * 64
    if unknown == accepted["receipt"]:
        unknown = "1" * 64

    response = api.post("/api/receipts/check", json={
        "election_id": accepted["election_id"],
        "receipt": unknown,
    })

    assert response.status_code == 200
    assert response.get_json()["included"] is False


@pytest.mark.parametrize("body", [
    [],
    {},
    {"election_id": True, "receipt": "a" * 64},
    {"election_id": -1, "receipt": "a" * 64},
    {"election_id": "1", "receipt": "a" * 64},
    {"election_id": 1, "receipt": "invalid"},
    {"election_id": 1, "receipt": "A" * 64},
])
def test_invalid_requests_rejected(api, body):
    response = api.post("/api/receipts/check", json=body)
    assert response.status_code == 400


def test_published_list_contains_only_receipt_hashes(app, api, accepted):
    close_election(app, accepted["election_id"])

    response = api.get(
        f"/api/receipts/published/{accepted['election_id']}"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "election_id": accepted["election_id"],
        "algorithm": "sha256-ciphertext-v1",
        "receipts": [accepted["receipt"]],
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_staged_ballot_not_published(app, api):
    headers = auth_headers(api, "voter", "voter1234")
    house, senate = ballot_choices(api)

    issued = api.post("/api/ballots/issue", headers=headers)
    assert issued.status_code == 201
    issued_body = issued.get_json()

    staged = api.post(
        "/api/ballots/stage",
        headers=headers,
        json={
            "token": issued_body["token"],
            "house": house,
            "senate_party": senate,
        },
    )
    assert staged.status_code == 200

    close_election(app, issued_body["election_id"])

    response = api.get(
        f"/api/receipts/published/{issued_body['election_id']}"
    )

    assert response.status_code == 200
    assert response.get_json()["receipts"] == []


def test_duplicate_commit_creates_no_second_receipt(app, api, accepted):
    headers = auth_headers(api, "voter", "voter1234")

    response = api.post(
        "/api/ballots/commit",
        headers=headers,
        json={"token": accepted["token"]},
    )

    assert response.status_code == 409
    assert "receipt" not in response.get_json()

    with app.app_context():
        assert Ballot.query.filter_by(
            election_id=accepted["election_id"]
        ).count() == 1


def test_changed_ballot_chain_blocks_publication(app, api, accepted):
    close_election(app, accepted["election_id"])

    with app.app_context():
        tamper_as_db_admin(
            "UPDATE ballots SET record_hash = :hash WHERE id = :id",
            {"hash": "f" * 64, "id": accepted["reference"]},
        )

    response = api.get(
        f"/api/receipts/published/{accepted['election_id']}"
    )

    assert response.status_code == 503
    assert "receipts" not in response.get_json()