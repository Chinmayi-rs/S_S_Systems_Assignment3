import base64

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import create_app, db

from sqlalchemy import text

from app.models.user import User

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "IDENTITY_DATABASE_URL",
        "sqlite:///" + (tmp_path / "identity.db").as_posix(),
    )
    monkeypatch.setenv(
        "BALLOT_DATABASE_URL",
        "sqlite:///" + (tmp_path / "ballot.db").as_posix(),
    )
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "test-jwt-secret-for-automated-tests-only",
    )
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    test_key = AESGCM.generate_key(bit_length=256)
    monkeypatch.setenv(
        "PII_ENCRYPTION_KEY",
        base64.b64encode(test_key).decode("ascii"),
    )

    app = create_app()
    app.config["TESTING"] = True

    try:
        with app.test_client() as test_client:
            yield test_client
    finally:
        with app.app_context():
            db.session.remove()
            for engine in db.engines.values():
                engine.dispose()

def login(client, username, password):
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert response.status_code == 200
    token = response.get_json()['access_token']
    return {'Authorization': 'Bearer ' + token}


def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'healthy'


def test_voter_cannot_add_candidate_or_close_election(client):
    headers = login(client, 'voter', 'voter1234')
    created = client.post('/api/candidates', json={
        'name': 'Extra Candidate',
        'party': 'Independent',
        'chamber': 'house',
        'ballot_order': 9,
    }, headers=headers)
    assert created.status_code == 403
    closed = client.post('/api/elections/current/status', json={'status': 'closed'}, headers=headers)
    assert closed.status_code == 403


def test_pending_voter_needs_officer_before_a_ballot(client):
    pending = login(client, 'pending', 'voter1234')
    blocked = client.post('/api/ballots/issue', headers=pending)
    assert blocked.status_code == 403

    officer = login(client, 'officer', 'officer1234')
    listed = client.get('/api/enrolment/voters', headers=officer)
    assert listed.status_code == 200
    pending_row = next(row for row in listed.get_json()['voters'] if row['username'] == 'pending')
    verified = client.post(
        f"/api/enrolment/voters/{pending_row['id']}/verify",
        json={'division': 'Melbourne', 'eligible': True},
        headers=officer,
    )
    assert verified.status_code == 200
    issued = client.post('/api/ballots/issue', headers=pending)
    assert issued.status_code == 201
    assert issued.get_json()['token']


def test_ballot_is_accepted_once(client):
    headers = login(client, 'voter', 'voter1234')
    catalogue = client.get('/api/candidates').get_json()
    house = [row['id'] for row in catalogue['candidates'] if row['chamber'] == 'house']
    senate = next(row['party'] for row in catalogue['candidates'] if row['chamber'] == 'senate')

    issued = client.post('/api/ballots/issue', headers=headers)
    assert issued.status_code == 201
    token = issued.get_json()['token']

    staged = client.post('/api/ballots/stage', json={
        'token': token,
        'house': house,
        'senate_party': senate,
    }, headers=headers)
    assert staged.status_code == 200
    assert staged.get_json()['house'][0]['preference'] == 1

    committed = client.post('/api/ballots/commit', json={'token': token}, headers=headers)
    assert committed.status_code == 201
    assert committed.get_json()['reference']

    again = client.post('/api/ballots/issue', headers=headers)
    assert again.status_code == 409


def test_results_stay_hidden_until_close(client):
    hidden = client.get('/api/results')
    assert hidden.status_code == 403

    delegate = login(client, 'delegate', 'delegate1234')
    preview = client.get('/api/results', headers=delegate)
    assert preview.status_code == 200
    assert preview.get_json()['preview'] is True

    auditor = login(client, 'auditor', 'auditor1234')
    audit = client.get('/api/audit', headers=auditor)
    assert audit.status_code == 200
    voter = login(client, 'voter', 'voter1234')
    denied = client.get('/api/audit', headers=voter)
    assert denied.status_code == 403

    closed = client.post('/api/elections/current/status', json={'status': 'closed'}, headers=delegate)
    assert closed.status_code == 200
    published = client.get('/api/results')
    assert published.status_code == 200
    assert published.get_json()['preview'] is False
    assert published.get_json()['method'] == 'first-preference'

def test_seeded_personal_details_are_encrypted(client):
    with client.application.app_context():
        row = db.session.execute(
            text("""
                SELECT
                    date_of_birth_encrypted,
                    address_encrypted
                FROM users
                WHERE username = :username
            """),
            {"username": "voter"},
        ).one()

        assert row[0].startswith("v1:")
        assert row[1].startswith("v1:")
        assert "1998-04-12" not in row[0]
        assert "12 Lygon Street, Carlton" not in row[1]

        voter = User.query.filter_by(username="voter").one()
        assert voter.date_of_birth == "1998-04-12"
        assert voter.address == "12 Lygon Street, Carlton"


def test_address_update_is_encrypted(client):
    headers = login(client, "voter", "voter1234")

    response = client.patch(
        "/api/enrolment/me",
        json={"address": "20 Example Road"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.get_json()["enrolment"]["address"] == "20 Example Road"

    with client.application.app_context():
        stored = db.session.execute(
            text("""
                SELECT address_encrypted
                FROM users
                WHERE username = :username
            """),
            {"username": "voter"},
        ).scalar_one()

        assert stored.startswith("v1:")
        assert "20 Example Road" not in stored

def test_registration_stores_encrypted_personal_details(client):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "gr18test",
            "email": "gr18test@example.test",
            "password": "ExamplePassword123!",
            "full_name": "Fictional Test Voter",
            "date_of_birth": "2000-05-12",
            "address": "30 Sample Street",
            "division": "Melbourne",
        },
    )

    assert response.status_code == 201

    user = response.get_json()["user"]
    assert user["date_of_birth"] == "2000-05-12"
    assert user["address"] == "30 Sample Street"

    with client.application.app_context():
        row = db.session.execute(
            text("""
                SELECT date_of_birth_encrypted, address_encrypted
                FROM users
                WHERE username = :username
            """),
            {"username": "gr18test"},
        ).one()

        assert row[0].startswith("v1:")
        assert row[1].startswith("v1:")
        assert "2000-05-12" not in row[0]
        assert "30 Sample Street" not in row[1]


def test_personal_details_require_authorisation(client):
    anonymous = client.get("/api/enrolment/me")
    assert anonymous.status_code == 401

    headers = login(client, "voter", "voter1234")

    own_record = client.get("/api/enrolment/me", headers=headers)
    assert own_record.status_code == 200
    assert own_record.get_json()["enrolment"]["username"] == "voter"

    voter_list = client.get("/api/enrolment/voters", headers=headers)
    assert voter_list.status_code == 403