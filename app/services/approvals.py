"""GR-14 Two-person authorisation for result-affecting actions.

A delegate proposes and CHOOSES which other delegate must approve. Only that delegate can approve
or reject. While the request is waiting, nobody can send another request for the same target
(the poll, or one candidate) - not other delegates, and not the chosen approver either.
Only then does the action run.

Add a new protected action by adding one entry to HANDLERS (validate + execute). By default the
whole action type is locked while a request is waiting; add an entry to TARGETS to lock something
narrower (like one candidate).
GR-13 adds 'results.release' here (sign and publish the final results); a recount would be another entry.

execute(payload, note, ctx) gets ctx = {'approval_id', 'proposer', 'approver'}: the two people involved.
"""
import json
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.approval import PendingApproval
from app.models.candidate import Candidate
from app.models.election import Election
from app.models.user import User
from app.services.audit_log import append_audit
from app.services import results_publication
from app.services.elections import current_election
from app.utils.constants import ELECTION_CLOSED, ELECTION_OPEN, ROLE_DELEGATE

PROPOSED, APPROVED, EXECUTED, REJECTED = 'proposed', 'approved', 'executed', 'rejected'


class ApprovalError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---- election.status: close or reopen the poll -------------------------------------------------

def _validate_election_status(data):
    status = data.get('status')
    if status not in (ELECTION_OPEN, ELECTION_CLOSED):
        raise ApprovalError('Status must be open or closed')
    election = current_election()
    if not election:
        raise ApprovalError('No election is configured', 404)
    if election.status == status:
        raise ApprovalError('The poll is already ' + status, 409)
    _refuse_reopen_after_publication(election.id, status)
    return {'election_id': election.id, 'status': status}


def _refuse_reopen_after_publication(election_id, status):
    # GR-13: a signed result is final. Reopening would let new ballots make the published count wrong.
    if status == ELECTION_OPEN and results_publication.get_published(election_id):
        raise ApprovalError('The results are already published, so the poll cannot be reopened', 409)


def _execute_election_status(payload, note, ctx=None):
    election = db.session.get(Election, payload['election_id'])
    if election.status == payload['status']:  # state changed since it was proposed
        raise ApprovalError('The poll is already ' + payload['status'], 409)
    _refuse_reopen_after_publication(election.id, payload['status'])
    previous = election.status
    election.status = payload['status']
    return 'election.status', f"{previous} -> {payload['status']} [{note}]"


# ---- candidate.set_active: exclude (withdraw) or restore a candidate ---------------------------

def _validate_candidate_active(data):
    active = data.get('active')
    if not isinstance(active, bool):
        raise ApprovalError('active must be true or false')
    try:
        candidate = db.session.get(Candidate, int(data.get('candidate_id')))
    except (TypeError, ValueError):
        raise ApprovalError('candidate_id must be a number')
    if not candidate:
        raise ApprovalError('Candidate not found', 404)
    if candidate.active == active:
        raise ApprovalError('The candidate is already ' + ('on the paper' if active else 'withdrawn'), 409)
    return {'candidate_id': candidate.id, 'active': active}


def _execute_candidate_active(payload, note, ctx=None):
    candidate = db.session.get(Candidate, payload['candidate_id'])
    if candidate.active == payload['active']:
        raise ApprovalError('The candidate is already in that state', 409)
    before = candidate.to_dict()
    candidate.active = payload['active']
    detail = json.dumps({'id': candidate.id, 'before': before, 'after': candidate.to_dict(), 'approval': note})
    return 'candidate.update', detail


# ---- results.release: sign and publish the final results (GR-13) ------------------------------

def _validate_results_release(data):
    election = current_election()
    if not election:
        raise ApprovalError('No election is configured', 404)
    if election.status != ELECTION_CLOSED:
        raise ApprovalError('Close the poll before publishing the results', 409)
    if results_publication.get_published(election.id):
        raise ApprovalError('The results of this election are already published', 409)
    return {'election_id': election.id}


def _execute_results_release(payload, note, ctx):
    election = db.session.get(Election, payload['election_id'])
    # the poll may have been reopened while the request was waiting; the count is made now, not at proposal time
    if election.status != ELECTION_CLOSED:
        raise ApprovalError('The poll is no longer closed, so the results cannot be published', 409)
    try:
        row = results_publication.publish(election, ctx['proposer'], ctx['approver'], ctx['approval_id'])
    except results_publication.PublicationError as err:
        raise ApprovalError(err.message, err.status)
    detail = json.dumps({
        'election_id': election.id,
        'sha256': row.sha256,
        'key_fingerprint': row.key_fingerprint,
        'published_at': row.published_at.isoformat() + 'Z',
        'approval': note,
    })
    return 'results.release', detail


HANDLERS = {
    'election.status': (_validate_election_status, _execute_election_status),
    'candidate.set_active': (_validate_candidate_active, _execute_candidate_active),
    'results.release': (_validate_results_release, _execute_results_release),
}


# What each request is "about". One waiting request per target.
TARGETS = {
    'election.status': lambda payload: f"election:{payload['election_id']}",
    'candidate.set_active': lambda payload: f"candidate:{payload['candidate_id']}",
    'results.release': lambda payload: f"results:{payload['election_id']}",
}


def _target_key(action_type, payload):
    return TARGETS.get(action_type, lambda _payload: action_type)(payload)


# ---- the workflow ------------------------------------------------------------------------------

def _choose_approver(proposer, data):
    """The proposer must name another active delegate."""
    raw = data.get('approver_id')
    if isinstance(raw, bool):
        raw = None
    try:
        approver_id = int(raw)
    except (TypeError, ValueError):
        raise ApprovalError('Choose which delegate must approve this request (approver_id)')
    if approver_id == proposer.id:
        raise ApprovalError('You cannot send a request to yourself. Choose another delegate.')
    approver = db.session.get(User, approver_id)
    if not approver or not approver.is_active or approver.role != ROLE_DELEGATE:
        raise ApprovalError('The approver must be an active delegate')
    return approver


def propose(proposer, data):
    handler = HANDLERS.get(data.get('action_type'))
    if not handler:
        raise ApprovalError('Unknown action_type. Use one of: ' + ', '.join(sorted(HANDLERS)))
    payload = handler[0](data)
    target = _target_key(data['action_type'], payload)

    # One waiting request per target. This also stops the chosen approver (and everyone else)
    # from sending their own request for the same poll or candidate.
    waiting = PendingApproval.query.filter_by(target_key=target, status=PROPOSED).first()
    if waiting:
        waiting_for = db.session.get(User, waiting.approver_id)
        raise ApprovalError(
            f'Request #{waiting.id} for this is already waiting for {waiting_for.username}. '
            'No new request can be sent until it is approved or rejected.',
            409,
        )

    approver = _choose_approver(proposer, data)
    row = PendingApproval(
        action_type=data['action_type'],
        payload=json.dumps(payload, sort_keys=True),
        target_key=target,
        proposer_id=proposer.id,
        approver_id=approver.id,
        status=PROPOSED,
    )
    db.session.add(row)
    try:
        db.session.flush()
    except IntegrityError:
        # two delegates sent a request for the same target at the same moment; the database let only one in
        db.session.rollback()
        raise ApprovalError('Another request for this was sent at the same moment. Refresh and check the Approvals page.', 409)
    append_audit(
        'approval.proposed',
        json.dumps({
            'approval_id': row.id,
            'action_type': row.action_type,
            'payload': payload,
            'approver_id': approver.id,
            'approver': approver.username,
        }),
        actor=proposer,
    )
    db.session.commit()
    return row


def _load_open_request(approval_id):
    row = db.session.get(PendingApproval, approval_id)
    if not row:
        raise ApprovalError('Approval request not found', 404)
    if row.status != PROPOSED:
        raise ApprovalError('This request was already ' + row.status, 409)
    return row


def _require_chosen_approver(row, delegate, attempt):
    """Only the delegate the request was sent to may decide it. Anyone else leaves a trace."""
    if row.approver_id == delegate.id:
        return
    append_audit(
        'approval.wrong_approver_blocked',
        json.dumps({'approval_id': row.id, 'attempt': attempt}),
        actor=delegate,
    )
    db.session.commit()
    raise ApprovalError('This request was sent to another delegate. Only that delegate can approve or reject it.', 403)


def approve(approver, approval_id):
    row = _load_open_request(approval_id)

    if row.proposer_id == approver.id:
        # Single-person attempt: refuse, and leave a signed trace of the attempt.
        append_audit('approval.self_approval_blocked', json.dumps({'approval_id': row.id}), actor=approver)
        db.session.commit()
        raise ApprovalError('The person who proposed an action cannot approve it. A second delegate is needed.', 403)
    _require_chosen_approver(row, approver, 'approve')

    # Atomic claim: if two approvals race, only one UPDATE matches status='proposed'.
    claimed = PendingApproval.query.filter_by(id=row.id, status=PROPOSED, approver_id=approver.id).update(
        {'status': APPROVED, 'decided_by_id': approver.id, 'decided_at': datetime.utcnow()},
        synchronize_session=False,
    )
    if claimed != 1:
        raise ApprovalError('This request was already decided', 409)
    db.session.expire(row)

    proposer = db.session.get(User, row.proposer_id)
    note = f'approval #{row.id}, proposed by {proposer.username}, approved by {approver.username}'
    handler = HANDLERS.get(row.action_type)
    if not handler:
        raise ApprovalError('This action type is no longer supported', 409)

    # If execute() raises, the route rolls back everything above and the request stays "proposed".
    ctx = {'approval_id': row.id, 'proposer': proposer, 'approver': approver}
    action, detail = handler[1](json.loads(row.payload), note, ctx)
    append_audit(
        'approval.approved',
        json.dumps({
            'approval_id': row.id,
            'action_type': row.action_type,
            'proposer_id': row.proposer_id,
            'approver_id': approver.id,
        }),
        actor=approver,
    )
    append_audit(action, detail, actor=approver)
    row.status = EXECUTED
    db.session.commit()
    return row


def reject(delegate, approval_id):
    """Only the delegate the request was sent to may reject it (the proposer cannot withdraw it)."""
    row = _load_open_request(approval_id)
    _require_chosen_approver(row, delegate, 'reject')
    row.status = REJECTED
    row.decided_by_id = delegate.id
    row.decided_at = datetime.utcnow()
    append_audit(
        'approval.rejected',
        json.dumps({'approval_id': row.id, 'action_type': row.action_type, 'proposer_id': row.proposer_id}),
        actor=delegate,
    )
    db.session.commit()
    return row
