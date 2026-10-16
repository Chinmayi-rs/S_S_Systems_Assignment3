import os
import sqlite3
import tempfile

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app import create_app, db
from app.models.audit import AuditEvent
from app.services.audit_chain import GENESIS_HASH


@pytest.fixture()
def ctx():
    directory = tempfile.mkdtemp()
    identity = os.path.join(directory, 'identity.db')
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + identity
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client, app, identity


def login(client, username, password):
    res = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def make_some_events(client):
    # GR-14: poll changes need a proposer and a different approver
    delegate = login(client, 'delegate', 'delegate1234')
    second = login(client, 'delegate2', 'delegate21234')
    approver_id = client.get('/api/approvals/delegates', headers=delegate).get_json()['delegates'][0]['id']  # delegate2
    for status in ('closed', 'open'):
        proposed = client.post('/api/approvals', json={'action_type': 'election.status', 'status': status, 'approver_id': approver_id}, headers=delegate)
        client.post(f"/api/approvals/{proposed.get_json()['approval']['id']}/approve", headers=second)


def test_entries_are_chained_and_verify_is_valid(ctx):
    client, app, _ = ctx
    make_some_events(client)
    auditor = login(client, 'auditor', 'auditor1234')
    result = client.get('/api/audit/verify', headers=auditor).get_json()
    assert result['valid'] is True and result['entries'] >= 4
    with app.app_context():
        events = AuditEvent.query.order_by(AuditEvent.id).all()
        assert events[0].prev_hash == GENESIS_HASH
        for before, after in zip(events, events[1:]):
            assert after.prev_hash == before.entry_hash


def test_only_the_auditor_can_verify(ctx):
    client, _, _ = ctx
    assert client.get('/api/audit/verify').status_code == 401
    assert client.get('/api/audit/verify', headers=login(client, 'voter', 'voter1234')).status_code == 403
    assert client.get('/api/audit/verify', headers=login(client, 'delegate', 'delegate1234')).status_code == 403


def test_database_trigger_blocks_update_and_delete(ctx):
    client, app, _ = ctx
    make_some_events(client)
    with app.app_context():
        with pytest.raises(DatabaseError):
            db.session.execute(text("UPDATE audit_events SET detail = 'x' WHERE id = 1"))
        db.session.rollback()
        with pytest.raises(DatabaseError):
            db.session.execute(text("DELETE FROM audit_events WHERE id = 1"))
        db.session.rollback()


def _tamper(identity_path, sql):
    """Simulate an attacker with the raw database file: remove the guard, then edit."""
    conn = sqlite3.connect(identity_path)
    conn.execute('DROP TRIGGER audit_events_no_update')
    conn.execute('DROP TRIGGER audit_events_no_delete')
    conn.execute(sql)
    conn.commit()
    conn.close()


def test_editing_an_old_entry_is_detected(ctx):
    client, _, identity = ctx
    make_some_events(client)
    _tamper(identity, "UPDATE audit_events SET detail = 'nothing happened' WHERE id = 2")
    result = client.get('/api/audit/verify', headers=login(client, 'auditor', 'auditor1234')).get_json()
    assert result['valid'] is False and result['broken_at'] == 2


def test_deleting_a_middle_entry_is_detected(ctx):
    client, _, identity = ctx
    make_some_events(client)
    _tamper(identity, 'DELETE FROM audit_events WHERE id = 2')
    result = client.get('/api/audit/verify', headers=login(client, 'auditor', 'auditor1234')).get_json()
    assert result['valid'] is False


def test_ballot_event_has_no_voter_and_no_vote_content(ctx):
    client, app, _ = ctx
    voter = login(client, 'voter', 'voter1234')
    token = client.post('/api/ballots/issue', headers=voter).get_json()['token']
    cands = client.get('/api/candidates').get_json()['candidates']
    house = [c['id'] for c in cands if c['chamber'] == 'house']
    party = next(c['party'] for c in cands if c['chamber'] == 'senate')
    client.post('/api/ballots/stage', json={'token': token, 'house': house, 'senate_party': party}, headers=voter)
    assert client.post('/api/ballots/commit', json={'token': token}, headers=voter).status_code == 201
    with app.app_context():
        event = AuditEvent.query.filter_by(action='ballot.committed').one()
        assert event.actor_id is None and event.actor_username is None
        assert 'house' not in event.detail and party not in event.detail
