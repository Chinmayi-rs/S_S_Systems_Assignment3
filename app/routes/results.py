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
    if payload['release_blocked']:
        # GR-12: never publish counts that two independent tallies do not agree on.
        # Delegates and auditors still get the details so they can investigate.
        user = optional_user()
        if user and user.role in ('commissioner_delegate', 'auditor'):
            payload['preview'] = True
            return jsonify(payload), 200
        return json_error(payload['release_reason'], 503)
    payload['preview'] = False
    return jsonify(payload), 200
