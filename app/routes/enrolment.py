from flask import Blueprint, jsonify, request

from app import db
from app.models.user import User
from app.services.audit_log import append_audit
from app.utils.constants import ROLE_VOTER
from app.utils.helpers import json_error
from app.utils.rbac import require_login, require_permission

enrolment_bp = Blueprint('enrolment', __name__)


@enrolment_bp.route('/me', methods=['GET'])
@require_login
def my_enrolment(current_user):
    return jsonify({'enrolment': current_user.to_dict()}), 200


@enrolment_bp.route('/me', methods=['PATCH'])
@require_permission('enrolment.address')
def update_address(current_user):
    if current_user.has_voted:
        return json_error('Address can no longer be changed after a ballot is accepted', 409)
    data = request.get_json(silent=True) or {}
    address = (data.get('address') or '').strip()
    division = (data.get('division') or '').strip()
    if not address:
        return json_error('Address is required', 400)
    current_user.address = address
    if division:
        current_user.division = division
    # Detail deliberately omits the address itself.
    append_audit('enrolment.address_updated', 'Voter updated enrolment details', actor=current_user)
    db.session.commit()
    return jsonify({'enrolment': current_user.to_dict()}), 200


@enrolment_bp.route('/voters', methods=['GET'])
@require_permission('enrolment.review')
def list_voters(current_user):
    voters = (
        User.query.filter_by(role=ROLE_VOTER)
        .order_by(User.created_at.desc())
        .all()
    )
    return jsonify({'voters': [voter.to_dict() for voter in voters]}), 200


@enrolment_bp.route('/voters/<int:voter_id>/verify', methods=['POST'])
@require_permission('enrolment.verify')
def verify_voter(current_user, voter_id):
    voter = User.query.get(voter_id)
    if not voter or voter.role != ROLE_VOTER:
        return json_error('Voter not found', 404)
    data = request.get_json(silent=True) or {}
    division = (data.get('division') or voter.division or '').strip()
    if not division:
        return json_error('A division is required', 400)
    eligible = bool(data.get('eligible', True))
    voter.division = division
    voter.enrolled = True
    voter.eligible = eligible
    append_audit(
        'enrolment.verified',
        f'Verified {voter.username} in {division}; eligible={eligible}',
        actor=current_user,
    )
    db.session.commit()
    return jsonify({'voter': voter.to_dict()}), 200
