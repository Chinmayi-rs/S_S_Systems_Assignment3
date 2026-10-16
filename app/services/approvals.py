"""GR-14 Two-person authorisation for result-affecting actions.

A delegate proposes. A DIFFERENT delegate approves. Only then does the action run.
Add a new protected action by adding one entry to HANDLERS (validate + execute).
GR-13 adds 'results.release' here; a recount would be another entry.
"""
import json
from datetime import datetime

from app import db
from app.models.approval import PendingApproval
from app.models.candidate import Candidate
from app.models.election import Election
from app.models.user import User
from app.services.audit_log import append_audit
from app.services.elections import current_election
from app.utils.constants import ELECTION_CLOSED, ELECTION_OPEN

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
    return {'election_id': election.id, 'status': status}


def _execute_election_status(payload, note):
    election = db.session.get(Election, payload['election_id'])
    if election.status == payload['status']:  # state changed since it was proposed
        raise ApprovalError('The poll is already ' + payload['status'], 409)
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


def _execute_candidate_active(payload, note):
    candidate = db.session.get(Candidate, payload['candidate_id'])
    if candidate.active == payload['active']:
        raise ApprovalError('The candidate is already in that state', 409)
    before = candidate.to_dict()
    candidate.active = payload['active']
    detail = json.dumps({'id': candidate.id, 'before': before, 'after': candidate.to_dict(), 'approval': note})
    return 'candidate.update', detail


HANDLERS = {
    'election.status': (_validate_election_status, _execute_election_status),
    'candidate.set_active': (_validate_candidate_active, _execute_candidate_active),
}


# ---- the workflow ------------------------------------------------------------------------------

def propose(proposer, data):
    handler = HANDLERS.get(data.get('action_type'))
    if not handler:
        raise ApprovalError('Unknown action_type. Use one of: ' + ', '.join(sorted(HANDLERS)))
    payload = handler[0](data)
    row = PendingApproval(
        action_type=data['action_type'],
        payload=json.dumps(payload, sort_keys=True),
        proposer_id=proposer.id,
        status=PROPOSED,
    )
    db.session.add(row)
    db.session.flush()
    append_audit(
        'approval.proposed',
        json.dumps({'approval_id': row.id, 'action_type': row.action_type, 'payload': payload}),
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


def approve(approver, approval_id):
    row = _load_open_request(approval_id)

    if row.proposer_id == approver.id:
        # Single-person attempt: refuse, and leave a signed trace of the attempt.
        append_audit('approval.self_approval_blocked', json.dumps({'approval_id': row.id}), actor=approver)
        db.session.commit()
        raise ApprovalError('The person who proposed an action cannot approve it. A second delegate is needed.', 403)

    # Atomic claim: if two approvals race, only one UPDATE matches status='proposed'.
    claimed = PendingApproval.query.filter_by(id=row.id, status=PROPOSED).update(
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
    action, detail = handler[1](json.loads(row.payload), note)
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
    """Any delegate may reject. The proposer rejecting their own request is a withdrawal."""
    row = _load_open_request(approval_id)
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
