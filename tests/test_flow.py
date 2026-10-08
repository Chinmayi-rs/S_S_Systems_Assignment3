import os
import tempfile

import pytest

from app import create_app


@pytest.fixture()
def client():
    directory = tempfile.mkdtemp()
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'identity.db')
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as test_client:
        yield test_client


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
