from datetime import datetime

from sqlalchemy import DDL, event

from app import db


class AuditEvent(db.Model):
    """Append-only, hash-chained audit table (GR-15)."""

    __tablename__ = 'audit_events'

    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer)
    actor_username = db.Column(db.String(80))
    action = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.Text, nullable=False, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # unique: if two requests append at the same moment, the second one fails instead of forking the chain
    prev_hash = db.Column(db.String(64), nullable=False, unique=True)
    entry_hash = db.Column(db.String(64), nullable=False, unique=True)

    def chain_fields(self) -> dict:
        """Exactly the fields covered by the hash. Do not change without re-creating the database."""
        return {
            'actor_id': self.actor_id,
            'actor_username': self.actor_username,
            'action': self.action,
            'detail': self.detail,
            'created_at': self.created_at.isoformat(timespec='microseconds'),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'actor_id': self.actor_id,
            'actor_username': self.actor_username,
            'action': self.action,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'prev_hash': self.prev_hash,
            'entry_hash': self.entry_hash,
        }


# Database-level guard: the application and anyone using SQL through it cannot change or delete rows.
# (Someone with the raw database file can still drop the trigger - the hash chain is what exposes that.)
for _name, _verb in (('audit_events_no_update', 'UPDATE'), ('audit_events_no_delete', 'DELETE')):
    event.listen(
        AuditEvent.__table__,
        'after_create',
        DDL(
            f"CREATE TRIGGER IF NOT EXISTS {_name} BEFORE {_verb} ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
        ).execute_if(dialect='sqlite'),
    )
