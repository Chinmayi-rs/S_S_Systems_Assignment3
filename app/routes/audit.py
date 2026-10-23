from flask import Blueprint, jsonify, request

from app import db
from app.models.audit import AuditEvent
from app.models.signing import ActionSignature, DelegateKey
from app.services.action_signing import ALGORITHM, SIGN_PREFIX, verify_signatures
from app.services.audit_chain import verify_chain
from app.utils.helpers import json_error
from app.utils.rbac import require_permission

audit_bp = Blueprint('audit', __name__)


@audit_bp.route('', methods=['GET'], strict_slashes=False)
@require_permission('audit.read')
def list_events(current_user):
    try:
        limit = int(request.args.get('limit', 100))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))
    events = (
        AuditEvent.query.order_by(AuditEvent.id.desc()).limit(limit).all()
    )
    signatures = {row.audit_event_id: row.signature for row in ActionSignature.query.all()}
    payload = []
    for event in events:
        item = event.to_dict()
        item['signature'] = signatures.get(event.id)  # None for entries that need no delegate signature
        payload.append(item)
    return jsonify({'events': payload}), 200


@audit_bp.route('/verify', methods=['GET'], strict_slashes=False)
@require_permission('audit.read')
def verify(current_user):
    """Read-only integrity check: the hash chain (GR-15) and every delegate signature (GR-16)."""
    events = AuditEvent.query.order_by(AuditEvent.id.asc()).all()
    result = verify_chain(events)
    result['chain_valid'] = result['valid']
    result['signatures'] = verify_signatures(events)
    result['valid'] = result['chain_valid'] and result['signatures']['valid']
    return jsonify(result), 200


@audit_bp.route('/<int:event_id>/proof', methods=['GET'])
@require_permission('audit.read')
def proof(current_user, event_id):
    """Everything a third party needs to check one delegate action offline (see scripts/verify_proof.py)."""
    event = db.session.get(AuditEvent, event_id)
    if not event:
        return json_error('Audit entry not found', 404)
    row = ActionSignature.query.filter_by(audit_event_id=event_id).first()
    if not row:
        return json_error('This entry was not signed by a delegate', 404)
    key = db.session.get(DelegateKey, row.key_id)
    return jsonify({
        'event': event.chain_fields(),
        'prev_hash': event.prev_hash,
        'entry_hash': event.entry_hash,
        'algorithm': ALGORITHM,
        'signed_message_prefix': SIGN_PREFIX.decode('ascii'),
        'signature': row.signature,
        'signer': {
            'user_id': key.user_id,
            'public_key': key.public_key,
            'fingerprint': key.fingerprint,
        },
    }), 200
