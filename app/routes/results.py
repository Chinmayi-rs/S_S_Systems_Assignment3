from flask import Blueprint, jsonify

from app.services.elections import current_election
from app.services.tally import build_results
from app.utils.constants import ELECTION_CLOSED
from app.utils.helpers import json_error
from app.utils.rbac import optional_user

results_bp = Blueprint('results', __name__)


@results_bp.route('', methods=['GET'], strict_slashes=False)
def results():
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    if election.status != ELECTION_CLOSED:
        user = optional_user()
        if not user or user.role not in ('commissioner_delegate', 'auditor'):
            return json_error('Results are not published yet', 403)
        payload = build_results(election)
        payload['preview'] = True
        return jsonify(payload), 200
    payload = build_results(election)
    payload['preview'] = False
    return jsonify(payload), 200
