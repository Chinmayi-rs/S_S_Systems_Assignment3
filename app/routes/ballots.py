from flask import Blueprint, jsonify, request

from app import db
from app.services.audit_log import append_audit
from app.services.ballot_box import commit_ballot, issue_token, stage_ballot, voter_status
from app.utils.rbac import require_permission

ballots_bp = Blueprint('ballots', __name__)


@ballots_bp.route('/status', methods=['GET'])
@require_permission('ballot.cast')
def status(current_user):
    payload, error = voter_status(current_user)
    if error:
        message, code = error
        return jsonify({'error': message}), code
    return jsonify(payload), 200


@ballots_bp.route('/issue', methods=['POST'])
@require_permission('ballot.cast')
def issue(current_user):
    # The raw token is returned once. Only its hash is stored.
    payload, error = issue_token(current_user)
    if error:
        message, code = error
        return jsonify({'error': message}), code
    return jsonify(payload), 201


@ballots_bp.route('/stage', methods=['POST'])
@require_permission('ballot.cast')
def stage(current_user):
    data = request.get_json(silent=True) or {}
    payload, error = stage_ballot(
        current_user,
        data.get('token'),
        data.get('house'),
        data.get('senate_party'),
    )
    if error:
        message, code = error
        return jsonify({'error': message}), code
    return jsonify(payload), 200


@ballots_bp.route('/commit', methods=['POST'])
@require_permission('ballot.cast')
def commit(current_user):
    data = request.get_json(silent=True) or {}
    payload, error = commit_ballot(current_user, data.get('token'))
    if error:
        message, code = error
        return jsonify({'error': message}), code
    # No actor and no preferences: the log must not link a person to a vote.
    append_audit('ballot.committed', f"Ballot accepted for election {payload['election_id']}")
    db.session.commit()
    return jsonify({
        'message': 'Ballot accepted',
        'reference': payload['reference'],
    }), 201
