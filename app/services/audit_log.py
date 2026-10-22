from datetime import datetime

from app import db
from app.models.audit import AuditEvent
from app.services import action_signing
from app.services.audit_chain import GENESIS_HASH, compute_hash
from app.utils.constants import ROLE_DELEGATE


def append_audit(action, detail='', actor=None):
    """Record an administrative action in the hash-chained log. Does not commit.

    Ballot events must be written with actor=None and without vote content.
    GR-07 forbids voter id next to a ballot event.

    GR-16: when the actor is a Commissioner's delegate the entry is also signed with
    that delegate's own key, in the same transaction. If signing fails, the action fails.
    """
    is_delegate = actor is not None and actor.role == ROLE_DELEGATE
    if is_delegate:
        # make sure the key exists first, so its registration lands in the chain before the first signed action
        action_signing.get_or_create_key(actor)

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
    if is_delegate:
        action_signing.sign_event(event, actor)
    return event
