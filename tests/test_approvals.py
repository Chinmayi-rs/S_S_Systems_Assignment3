import json
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import create_app, db
from app.models.approval import PendingApproval
from app.models.audit import AuditEvent
from app.models.candidate import Candidate
from app.models.election import Election


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
        yield client, app


def login(client, username, password):
    res = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def two_delegates(client):
    return login(client, 'delegate', 'delegate1234'), login(client, 'delegate2', 'delegate21234')


def propose_close(client, headers):
    res = client.post('/api/approvals', json={'action_type': 'election.status', 'status': 'closed'}, headers=headers)
    assert res.status_code == 201
    return res.get_json()['approval']['id']


def poll_status(app):
    with app.app_context():
        return Election.query.order_by(Election.id.desc()).first().status


def test_proposer_cannot_approve_own_request(ctx):
    client, app = ctx
    first, _ = two_delegates(client)
    approval_id = propose_close(client, first)
    res = client.post(f'/api/approvals/{approval_id}/approve', headers=first)
    assert res.status_code == 403
    assert poll_status(app) == 'open'  # nothing ran
    with app.app_context():
        assert db.session.get(PendingApproval, approval_id).status == 'proposed'
        assert AuditEvent.query.filter_by(action='approval.self_approval_blocked').count() == 1


def test_second_delegate_approval_runs_the_action_and_records_both_people(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    approval_id = propose_close(client, first)
    res = client.post(f'/api/approvals/{approval_id}/approve', headers=second)
    assert res.status_code == 200
    body = res.get_json()['approval']
    assert body['status'] == 'executed'
    assert body['proposer_username'] == 'delegate' and body['decided_by_username'] == 'delegate2'
    assert poll_status(app) == 'closed'
    with app.app_context():
        executed = AuditEvent.query.filter_by(action='election.status').one()
        assert 'proposed by delegate' in executed.detail and 'approved by delegate2' in executed.detail
        assert executed.actor_username == 'delegate2'
        assert AuditEvent.query.filter_by(action='approval.proposed').one().actor_username == 'delegate'


def test_only_delegates_can_propose_or_decide(ctx):
    client, _ = ctx
    first, _ = two_delegates(client)
    approval_id = propose_close(client, first)
    body = {'action_type': 'election.status', 'status': 'closed'}
    for user, password in (('voter', 'voter1234'), ('officer', 'officer1234'), ('auditor', 'auditor1234')):
        headers = login(client, user, password)
        assert client.post('/api/approvals', json=body, headers=headers).status_code == 403
        assert client.post(f'/api/approvals/{approval_id}/approve', headers=headers).status_code == 403
        assert client.post(f'/api/approvals/{approval_id}/reject', headers=headers).status_code == 403
    assert client.post('/api/approvals', json=body).status_code == 401
    # the auditor may read the queue but not change it
    assert client.get('/api/approvals', headers=login(client, 'auditor', 'auditor1234')).status_code == 200
    assert client.get('/api/approvals', headers=login(client, 'voter', 'voter1234')).status_code == 403


def test_a_request_can_only_be_decided_once(ctx):
    client, _ = ctx
    first, second = two_delegates(client)
    approval_id = propose_close(client, first)
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 200
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 409
    assert client.post(f'/api/approvals/{approval_id}/reject', headers=second).status_code == 409


def test_two_approvals_at_the_same_time_run_the_action_once(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    approval_id = propose_close(client, first)

    def approve(_):
        with app.test_client() as other:
            return other.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(approve, range(2)))
    assert codes[0] == 200 and codes[1] in (409, 500)
    with app.app_context():
        assert AuditEvent.query.filter_by(action='election.status').count() == 1


def test_rejected_request_never_runs(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    approval_id = propose_close(client, first)
    assert client.post(f'/api/approvals/{approval_id}/reject', headers=second).status_code == 200
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 409
    assert poll_status(app) == 'open'


def test_direct_routes_no_longer_change_the_result(ctx):
    client, app = ctx
    first, _ = two_delegates(client)
    assert client.post('/api/elections/current/status', json={'status': 'closed'}, headers=first).status_code == 409
    with app.app_context():
        candidate_id = Candidate.query.filter_by(chamber='house').first().id
    assert client.patch(f'/api/candidates/{candidate_id}', json={'active': False}, headers=first).status_code == 409
    # ordinary edits are still direct (GR-04)
    assert client.patch(f'/api/candidates/{candidate_id}', json={'party': 'Renamed'}, headers=first).status_code == 200
    assert poll_status(app) == 'open'
    with app.app_context():
        assert db.session.get(Candidate, candidate_id).active is True


def test_candidate_withdrawal_needs_two_delegates(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    with app.app_context():
        candidate_id = Candidate.query.filter_by(chamber='house').first().id
    res = client.post('/api/approvals', json={'action_type': 'candidate.set_active', 'candidate_id': candidate_id, 'active': False}, headers=first)
    assert res.status_code == 201
    approval_id = res.get_json()['approval']['id']
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=first).status_code == 403
    with app.app_context():
        assert db.session.get(Candidate, candidate_id).active is True
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 200
    with app.app_context():
        assert db.session.get(Candidate, candidate_id).active is False
        update = AuditEvent.query.filter_by(action='candidate.update').one()
        assert 'approved by delegate2' in update.detail and '"before"' in update.detail


def test_bad_proposals_are_refused(ctx):
    client, _ = ctx
    first, _ = two_delegates(client)
    post = lambda body: client.post('/api/approvals', json=body, headers=first).status_code  # noqa: E731
    assert post({'action_type': 'nope'}) == 400
    assert post({'action_type': 'election.status', 'status': 'paused'}) == 400
    assert post({'action_type': 'election.status', 'status': 'open'}) == 409  # already open
    assert post({'action_type': 'candidate.set_active', 'candidate_id': 99999, 'active': False}) == 404
    assert post({'action_type': 'candidate.set_active', 'candidate_id': 1, 'active': 'no'}) == 400


def test_database_itself_refuses_a_self_approval(ctx):
    """Even if the app code had a bug, the table constraint blocks proposer == approver."""
    client, app = ctx
    first, _ = two_delegates(client)
    approval_id = propose_close(client, first)
    with app.app_context():
        proposer = db.session.get(PendingApproval, approval_id).proposer_id
        with pytest.raises(IntegrityError):
            db.session.execute(
                text("UPDATE pending_approvals SET status = 'executed', decided_by_id = :p WHERE id = :i"),
                {'p': proposer, 'i': approval_id},
            )
        db.session.rollback()


def test_both_people_are_signed_in_the_audit_log(ctx):
    """GR-16 reuse: the proposal is signed by the proposer, the execution by the approver."""
    client, app = ctx
    first, second = two_delegates(client)
    client.post(f'/api/approvals/{propose_close(client, first)}/approve', headers=second)
    result = client.get('/api/audit/verify', headers=login(client, 'auditor', 'auditor1234')).get_json()
    assert result['valid'] is True and result['signatures']['valid'] is True
    assert result['signatures']['checked'] >= 6  # 2 key registrations + login x2 + proposed + approved + executed
