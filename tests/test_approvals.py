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
from app.models.user import User
from app.services.seed import create_user, seed_if_empty


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


def delegate_id(client, headers, username):
    """Id of a delegate the logged-in delegate may send a request to."""
    delegates = client.get('/api/approvals/delegates', headers=headers).get_json()['delegates']
    return next(d['id'] for d in delegates if d['username'] == username)


def propose_close(client, headers, approver='delegate2'):
    body = {'action_type': 'election.status', 'status': 'closed', 'approver_id': delegate_id(client, headers, approver)}
    res = client.post('/api/approvals', json=body, headers=headers)
    assert res.status_code == 201, res.get_json()
    return res.get_json()['approval']['id']


def add_third_delegate(app, client):
    """delegate3 exists only in tests that need a delegate who was NOT chosen."""
    with app.app_context():
        create_user('delegate3', 'delegate3@example.test', 'delegate31234', 'Third Delegate',
                    'commissioner_delegate', '1980-01-01', 'Parliament precinct', 'Melbourne')
        db.session.commit()
    return login(client, 'delegate3', 'delegate31234')


def first_candidate_ids(app, count):
    with app.app_context():
        return [c.id for c in Candidate.query.filter_by(chamber='house').order_by(Candidate.id).limit(count).all()]


def propose_candidate(client, headers, candidate_id, approver_id, active=False):
    return client.post('/api/approvals', headers=headers, json={
        'action_type': 'candidate.set_active', 'candidate_id': candidate_id, 'active': active, 'approver_id': approver_id})


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
    res = propose_candidate(client, first, candidate_id, delegate_id(client, first, 'delegate2'))
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


# ---------------------------------------------------------------------------------------------
# The proposer chooses the approver; only that delegate decides; one waiting request per target
# ---------------------------------------------------------------------------------------------

def test_request_must_name_a_valid_approver(ctx):
    client, app = ctx
    first, _ = two_delegates(client)
    add_third_delegate(app, client)
    with app.app_context():
        voter_id = User.query.filter_by(username='voter').one().id
        delegate3 = User.query.filter_by(username='delegate3').one()
        delegate3.is_active = False  # a deactivated delegate cannot be chosen
        db.session.commit()
        first_id = User.query.filter_by(username='delegate').one().id
        inactive_id = delegate3.id
    base = {'action_type': 'election.status', 'status': 'closed'}
    post = lambda **extra: client.post('/api/approvals', json={**base, **extra}, headers=first).status_code  # noqa: E731
    assert post() == 400                          # nobody chosen
    assert post(approver_id='abc') == 400
    assert post(approver_id=True) == 400
    assert post(approver_id=first_id) == 400      # yourself
    assert post(approver_id=voter_id) == 400      # not a delegate
    assert post(approver_id=99999) == 400         # does not exist
    assert post(approver_id=inactive_id) == 400   # deactivated
    assert poll_status(app) == 'open'


def test_delegate_list_excludes_yourself_and_non_delegates(ctx):
    client, _ = ctx
    first, second = two_delegates(client)
    names = [d['username'] for d in client.get('/api/approvals/delegates', headers=first).get_json()['delegates']]
    assert names == ['delegate2']
    names = [d['username'] for d in client.get('/api/approvals/delegates', headers=second).get_json()['delegates']]
    assert names == ['delegate']
    assert client.get('/api/approvals/delegates', headers=login(client, 'voter', 'voter1234')).status_code == 403
    assert client.get('/api/approvals/delegates', headers=login(client, 'auditor', 'auditor1234')).status_code == 403


def test_only_the_chosen_delegate_can_approve_or_reject(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    third = add_third_delegate(app, client)
    approval_id = propose_close(client, first, approver='delegate2')

    # the proposer, and a delegate who was not chosen, can do neither
    for headers in (first, third):
        assert client.post(f'/api/approvals/{approval_id}/approve', headers=headers).status_code == 403
        assert client.post(f'/api/approvals/{approval_id}/reject', headers=headers).status_code == 403
    assert poll_status(app) == 'open'
    with app.app_context():
        assert db.session.get(PendingApproval, approval_id).status == 'proposed'
        # the attempts by the delegate who was not chosen leave a trace
        assert AuditEvent.query.filter_by(action='approval.wrong_approver_blocked', actor_username='delegate3').count() == 2

    # the chosen delegate can
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 200
    assert poll_status(app) == 'closed'


def test_the_chosen_delegate_can_reject(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    third = add_third_delegate(app, client)
    approval_id = propose_close(client, first, approver='delegate3')
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 403  # delegate2 was not chosen
    assert client.post(f'/api/approvals/{approval_id}/reject', headers=third).status_code == 200
    with app.app_context():
        row = db.session.get(PendingApproval, approval_id)
        assert row.status == 'rejected' and row.decided_by_id == row.approver_id


def test_waiting_poll_request_blocks_every_other_poll_request(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    third = add_third_delegate(app, client)
    approval_id = propose_close(client, first, approver='delegate2')

    body = lambda who: {'action_type': 'election.status', 'status': 'closed', 'approver_id': delegate_id(client, who[0], who[1])}  # noqa: E731
    # another delegate, the proposer again, and the chosen approver himself: all refused
    assert client.post('/api/approvals', json=body((third, 'delegate')), headers=third).status_code == 409
    assert client.post('/api/approvals', json=body((first, 'delegate2')), headers=first).status_code == 409
    assert client.post('/api/approvals', json=body((second, 'delegate')), headers=second).status_code == 409
    with app.app_context():
        assert PendingApproval.query.count() == 1

    # once the chosen delegate decides, the poll can receive a new request
    assert client.post(f'/api/approvals/{approval_id}/reject', headers=second).status_code == 200
    assert client.post('/api/approvals', json=body((third, 'delegate')), headers=third).status_code == 201


def test_waiting_candidate_request_blocks_only_that_candidate(ctx):
    client, app = ctx
    first, second = two_delegates(client)
    third = add_third_delegate(app, client)
    a, b = first_candidate_ids(app, 2)
    approval_id = propose_candidate(client, first, a, delegate_id(client, first, 'delegate2')).get_json()['approval']['id']

    # candidate a: the other delegate, the proposer and the chosen approver are all refused, for both directions
    assert propose_candidate(client, third, a, delegate_id(client, third, 'delegate'), active=False).status_code == 409
    assert propose_candidate(client, second, a, delegate_id(client, second, 'delegate'), active=False).status_code == 409
    assert propose_candidate(client, first, a, delegate_id(client, first, 'delegate2'), active=False).status_code == 409
    # candidate b and the poll itself are separate targets
    assert propose_candidate(client, second, b, delegate_id(client, second, 'delegate')).status_code == 201
    assert propose_close(client, third, approver='delegate') > 0

    # after the decision candidate a is free again (restore it after it was withdrawn)
    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 200
    assert propose_candidate(client, third, a, delegate_id(client, third, 'delegate'), active=True).status_code == 201


def test_database_allows_only_one_waiting_request_per_target(ctx):
    client, app = ctx
    first, _ = two_delegates(client)
    propose_close(client, first)
    with app.app_context():
        existing = PendingApproval.query.one()
        duplicate = PendingApproval(
            action_type=existing.action_type, payload=existing.payload, target_key=existing.target_key,
            proposer_id=existing.approver_id, approver_id=existing.proposer_id, status='proposed')
        db.session.add(duplicate)
        with pytest.raises(IntegrityError):
            db.session.flush()
        db.session.rollback()


def test_database_refuses_a_request_sent_to_yourself_or_decided_by_someone_else(ctx):
    client, app = ctx
    first, _ = two_delegates(client)
    propose_close(client, first)
    with app.app_context():
        row = PendingApproval.query.one()
        other = User.query.filter(User.id.notin_([row.proposer_id, row.approver_id]), User.role == 'voter').first()
        with pytest.raises(IntegrityError):
            db.session.execute(text('UPDATE pending_approvals SET approver_id = proposer_id WHERE id = :i'), {'i': row.id})
        db.session.rollback()
        with pytest.raises(IntegrityError):  # decided by a person who was not the chosen approver
            db.session.execute(
                text("UPDATE pending_approvals SET status = 'rejected', decided_by_id = :o WHERE id = :i"),
                {'o': other.id, 'i': row.id})
        db.session.rollback()


def test_seed_creates_both_delegates_and_adds_missing_people(ctx):
    _, app = ctx
    with app.app_context():
        assert User.query.filter_by(role='commissioner_delegate').count() == 2
        db.session.delete(User.query.filter_by(username='delegate2').one())
        db.session.commit()
        seed_if_empty()  # an older database without delegate2 gets it back
        seed_if_empty()  # and running it again adds nothing twice
        assert User.query.filter_by(username='delegate2').count() == 1
        assert User.query.filter_by(role='commissioner_delegate').count() == 2
