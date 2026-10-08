from app import db
from app.models.audit import AuditEvent


def append_audit(action, detail='', actor=None):
    """Record an administrative action. Does not commit.

    Ballot events must be written with actor=None and without vote content.
    GR-15 will chain these rows. GR-07 forbids voter id next to a ballot event.
    """
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        action=action,
        detail=detail or '',
    )
    db.session.add(event)
    return event
