import json

from flask import Blueprint, jsonify, request

from app import db
from app.models.approval import PendingApproval
from app.models.user import User
from app.services import approvals as service
from app.services.approvals import ApprovalError
from app.utils.constants import ROLE_DELEGATE
from app.utils.helpers import json_error
from app.utils.rbac import require_permission

approvals_bp = Blueprint('approvals', __name__)


def _serialize(rows):
    ids = (
        {row.proposer_id for row in rows}
        | {row.approver_id for row in rows}
        | {row.decided_by_id for row in rows if row.decided_by_id}
    )
    names = {user.id: user.username for user in User.query.filter(User.id.in_(ids)).all()} if ids else {}
    return [{
        'id': row.id,
        'action_type': row.action_type,
        'payload': json.loads(row.payload),
        'status': row.status,
        'proposer_id': row.proposer_id,
        'proposer_username': names.get(row.proposer_id),
        'approver_id': row.approver_id,
        'approver_username': names.get(row.approver_id),
        'decided_by_id': row.decided_by_id,
        'decided_by_username': names.get(row.decided_by_id),
        'created_at': row.created_at.isoformat() if row.created_at else None,
        'decided_at': row.decided_at.isoformat() if row.decided_at else None,
    } for row in rows]


def _run(fn, *args):
    try:
        row = fn(*args)
    except ApprovalError as err:
        db.session.rollback()
        return json_error(err.message, err.status)
    return jsonify({'approval': _serialize([row])[0]}), 200


@approvals_bp.route('', methods=['GET'], strict_slashes=False)
@require_permission('approval.read')
def list_approvals(current_user):
    query = PendingApproval.query
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(PendingApproval.id.desc()).limit(200).all()
    return jsonify({'approvals': _serialize(rows)}), 200


@approvals_bp.route('/delegates', methods=['GET'])
@require_permission('approval.propose')
def list_delegates(current_user):
    """Delegates the current delegate may send a request to (everyone except themselves)."""
    rows = (
        User.query.filter(User.role == ROLE_DELEGATE, User.is_active.is_(True), User.id != current_user.id)
        .order_by(User.username)
        .all()
    )
    return jsonify({'delegates': [
        {'id': user.id, 'username': user.username, 'full_name': user.full_name} for user in rows
    ]}), 200


@approvals_bp.route('', methods=['POST'], strict_slashes=False)
@require_permission('approval.propose')
def propose(current_user):
    data = request.get_json(silent=True) or {}
    try:
        row = service.propose(current_user, data)
    except ApprovalError as err:
        db.session.rollback()
        return json_error(err.message, err.status)
    return jsonify({'approval': _serialize([row])[0]}), 201


@approvals_bp.route('/<int:approval_id>/approve', methods=['POST'])
@require_permission('approval.decide')
def approve(current_user, approval_id):
    return _run(service.approve, current_user, approval_id)


@approvals_bp.route('/<int:approval_id>/reject', methods=['POST'])
@require_permission('approval.decide')
def reject(current_user, approval_id):
    return _run(service.reject, current_user, approval_id)
