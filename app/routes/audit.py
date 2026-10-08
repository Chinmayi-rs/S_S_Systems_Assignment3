from flask import Blueprint, jsonify, request

from app.models.audit import AuditEvent
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
    return jsonify({'events': [event.to_dict() for event in events]}), 200
