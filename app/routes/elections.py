from flask import Blueprint, jsonify

from app.services.elections import current_election
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
    """GR-14: closing or reopening the poll affects the result, so it can no longer be done by one delegate."""
    return json_error(
        'Changing the poll status needs two delegates. Propose it with POST /api/approvals '
        '(action_type "election.status"); a different delegate must approve it.',
        409,
    )
