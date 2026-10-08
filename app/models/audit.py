from datetime import datetime

from app import db


class AuditEvent(db.Model):
    """Plain append-only table. GR-15 adds the hash chain on top of this shape."""

    __tablename__ = 'audit_events'

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer)
    actor_username = db.Column(db.String(80))
    action = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'actor_id': self.actor_id,
            'actor_username': self.actor_username,
            'action': self.action,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
