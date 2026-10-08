from flask import Blueprint, jsonify, request

from app import db
from app.services.audit_log import append_audit
from app.services.elections import current_election
from app.utils.constants import ELECTION_CLOSED, ELECTION_OPEN
from app.utils.helpers import json_error
from app.utils.rbac import require_permission

elections_bp = Blueprint('elections', __name__)


@elections_bp.route('/current', methods=['GET'])
def get_current():
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    return jsonify({'election': election.to_dict()}), 200


@elections_bp.route('/current/status', methods=['POST'])
@require_permission('election.status')
def set_status(current_user):
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in (ELECTION_OPEN, ELECTION_CLOSED):
        return json_error('Status must be open or closed', 400)
    previous = election.status
    election.status = status
    append_audit(
        'election.status',
        f'{previous} -> {status}',
        actor=current_user,
    )
    db.session.commit()
    return jsonify({'election': election.to_dict()}), 200
