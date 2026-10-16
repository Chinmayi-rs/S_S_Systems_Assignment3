from datetime import datetime

from sqlalchemy import CheckConstraint, Index, text

from app import db


class PendingApproval(db.Model):
    """A result-affecting request that needs a second delegate (GR-14).

    The proposer names ONE approver when sending the request. Only that delegate can approve
    or reject it, and while it is waiting nobody (the approver included) can send another
    request for the same poll or the same candidate.

    proposed -> approved -> executed   (approve and execute happen in one transaction)
    proposed -> rejected               (rejected by the chosen approver)
    """

    __tablename__ = 'pending_approvals'
    __table_args__ = (
        # Last line of defence: the database itself refuses an approval by the proposer ...
        CheckConstraint(
            "status NOT IN ('approved', 'executed') "
            "OR (decided_by_id IS NOT NULL AND decided_by_id != proposer_id)",
            name='two_distinct_people',
        ),
        # ... a request addressed to yourself ...
        CheckConstraint('approver_id != proposer_id', name='approver_is_someone_else'),
        # ... and a decision by anybody other than the chosen approver.
        CheckConstraint('decided_by_id IS NULL OR decided_by_id = approver_id', name='only_chosen_approver_decides'),
        # At most one waiting request per target (the poll, or one candidate).
        Index(
            'uq_one_open_request_per_target', 'target_key', unique=True,
            sqlite_where=text("status = 'proposed'"),
            postgresql_where=text("status = 'proposed'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(60), nullable=False)
    payload = db.Column(db.Text, nullable=False)  # JSON, validated when proposed
    # What the request is about, e.g. "election:1" or "candidate:7". Used to allow one open request per target.
    target_key = db.Column(db.String(60), nullable=False)
    proposer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # the delegate who must decide
    decided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # set when approved or rejected
    status = db.Column(db.String(20), nullable=False, default='proposed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    decided_at = db.Column(db.DateTime)
