from datetime import datetime

from sqlalchemy import CheckConstraint

from app import db


class PendingApproval(db.Model):
    """A result-affecting request that needs two different delegates (GR-14).

    proposed -> approved -> executed   (approve and execute happen in one transaction)
    proposed -> rejected               (rejected, or withdrawn by the proposer)
    """

    __tablename__ = 'pending_approvals'
    __table_args__ = (
        # Last line of defence: the database itself refuses an approval by the proposer.
        CheckConstraint(
            "status NOT IN ('approved', 'executed') "
            "OR (decided_by_id IS NOT NULL AND decided_by_id != proposer_id)",
            name='two_distinct_people',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(60), nullable=False)
    payload = db.Column(db.Text, nullable=False)  # JSON, validated when proposed
    proposer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    decided_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # approver, or whoever rejected
    status = db.Column(db.String(20), nullable=False, default='proposed')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    decided_at = db.Column(db.DateTime)
