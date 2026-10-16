from datetime import datetime

from app import db
from app.models.audit import AuditEvent
from app.services.audit_chain import GENESIS_HASH, compute_hash


def append_audit(action, detail='', actor=None):
    """Record an administrative action in the hash-chained log. Does not commit.

    Ballot events must be written with actor=None and without vote content.
    GR-07 forbids voter id next to a ballot event.
    """
    # Query autoflushes, so entries added earlier in the same request are seen as the chain head.
    last = AuditEvent.query.order_by(AuditEvent.id.desc()).first()
    prev_hash = last.entry_hash if last else GENESIS_HASH

    event = AuditEvent(
        actor_id=actor.id if actor else None,
        actor_username=actor.username if actor else None,
        action=action,
        detail=detail or '',
        created_at=datetime.utcnow(),  # set here so it is part of the hash
        prev_hash=prev_hash,
    )
    event.entry_hash = compute_hash(prev_hash, event.chain_fields())
    db.session.add(event)
    db.session.flush()  # the next append in this request must see this entry
    return event
