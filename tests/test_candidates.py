"""GR-04: candidate and ballot-order changes are delegate-only and fully audited."""
import json
import os
import tempfile

import pyotp
import pytest

from app import create_app
from app.models.audit import AuditEvent
from app.services.seed import deterministic_totp_secret


@pytest.fixture()
def ctx():
    directory = tempfile.mkdtemp()
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'identity.db')
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client, app


def login(client, username, password):
    code = pyotp.TOTP(deterministic_totp_secret(username)).now()
    res = client.post('/api/auth/login', json={'username': username, 'password': password, 'totp_code': code})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def house_ids(client):
    catalogue = client.get('/api/candidates').get_json()
    rows = [row for row in catalogue['candidates'] if row['chamber'] == 'house']
    return [row['id'] for row in sorted(rows, key=lambda row: row['ballot_order'])]


def last_audit(app, action):
    with app.app_context():
        return AuditEvent.query.filter_by(action=action).order_by(AuditEvent.id.desc()).first()


def test_create_is_audited_with_actor_and_after_state(ctx):
    client, app = ctx
    delegate = login(client, 'delegate', 'delegate1234')
    created = client.post('/api/candidates', json={
        'name': 'Dana Wells', 'party': 'Independent', 'chamber': 'house', 'ballot_order': 9,
    }, headers=delegate)
    assert created.status_code == 201
    event = last_audit(app, 'candidate.create')
    assert event.actor_username == 'delegate'
    detail = json.loads(event.detail)
    assert detail['after']['name'] == 'Dana Wells'


def test_update_records_before_and_after_values(ctx):
    client, app = ctx
    delegate = login(client, 'delegate', 'delegate1234')
    candidate_id = house_ids(client)[0]
    updated = client.patch(f'/api/candidates/{candidate_id}', json={'party': 'Renamed Party'}, headers=delegate)
    assert updated.status_code == 200
    detail = json.loads(last_audit(app, 'candidate.update').detail)
    assert detail['before']['party'] != detail['after']['party']
    assert detail['after']['party'] == 'Renamed Party'


def test_reorder_renumbers_the_ballot_and_is_audited(ctx):
    client, app = ctx
    delegate = login(client, 'delegate', 'delegate1234')
    original = house_ids(client)
    reversed_order = list(reversed(original))
    response = client.post('/api/candidates/reorder', json={
        'chamber': 'house', 'order': reversed_order,
    }, headers=delegate)
    assert response.status_code == 200
    assert house_ids(client) == reversed_order
    detail = json.loads(last_audit(app, 'candidate.reorder').detail)
    assert detail['before'] != detail['after']


def test_reorder_must_list_every_candidate_exactly_once(ctx):
    client, _ = ctx
    delegate = login(client, 'delegate', 'delegate1234')
    ids = house_ids(client)
    missing_one = client.post('/api/candidates/reorder', json={
        'chamber': 'house', 'order': ids[:-1],
    }, headers=delegate)
    assert missing_one.status_code == 400
    duplicated = client.post('/api/candidates/reorder', json={
        'chamber': 'house', 'order': ids[:-1] + [ids[0]],
    }, headers=delegate)
    assert duplicated.status_code == 400


def test_only_delegates_touch_candidates(ctx):
    client, _ = ctx
    for username, password in (('voter', 'voter1234'), ('officer', 'officer1234'), ('auditor', 'auditor1234')):
        headers = login(client, username, password)
        assert client.post('/api/candidates', json={
            'name': 'X', 'party': 'Y', 'chamber': 'house',
        }, headers=headers).status_code == 403
        assert client.post('/api/candidates/reorder', json={
            'chamber': 'house', 'order': [],
        }, headers=headers).status_code == 403


def test_deletion_does_not_exist_even_for_delegates(ctx):
    client, _ = ctx
    delegate = login(client, 'delegate', 'delegate1234')
    candidate_id = house_ids(client)[0]
    response = client.delete(f'/api/candidates/{candidate_id}', headers=delegate)
    assert response.status_code == 405
    assert 'approval' in response.get_json()['error'].lower()
    # The candidate is still there.
    assert candidate_id in house_ids(client)


def test_overlong_names_are_rejected(ctx):
    client, _ = ctx
    delegate = login(client, 'delegate', 'delegate1234')
    response = client.post('/api/candidates', json={
        'name': 'x' * 200, 'party': 'Y', 'chamber': 'house',
    }, headers=delegate)
    assert response.status_code == 400
