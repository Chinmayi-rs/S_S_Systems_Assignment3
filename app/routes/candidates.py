import json

from flask import Blueprint, jsonify, request

from app import db
from app.models.candidate import Candidate
from app.services.audit_log import append_audit
from app.services.elections import current_election
from app.utils.constants import CHAMBER_HOUSE, CHAMBER_SENATE
from app.utils.helpers import json_error, validate_required_fields
from app.utils.rbac import require_permission

candidates_bp = Blueprint('candidates', __name__)


def _list_payload():
    election = current_election()
    if not election:
        return {'election': None, 'candidates': []}
    rows = (
        Candidate.query.filter_by(election_id=election.id)
        .order_by(Candidate.chamber, Candidate.ballot_order, Candidate.id)
        .all()
    )
    return {'election': election.to_dict(), 'candidates': [row.to_dict() for row in rows]}


@candidates_bp.route('', methods=['GET'], strict_slashes=False)
def list_candidates():
    return jsonify(_list_payload()), 200


@candidates_bp.route('', methods=['POST'], strict_slashes=False)
@require_permission('candidate.write')
def create_candidate(current_user):
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    data = request.get_json(silent=True) or {}
    ok, message = validate_required_fields(data, ['name', 'party', 'chamber'])
    if not ok:
        return json_error(message, 400)
    chamber = data['chamber']
    if chamber not in (CHAMBER_HOUSE, CHAMBER_SENATE):
        return json_error('Chamber must be house or senate', 400)
    try:
        order = int(data.get('ballot_order') or 1)
    except (TypeError, ValueError):
        return json_error('Ballot order must be a number', 400)

    candidate = Candidate(
        election_id=election.id,
        chamber=chamber,
        name=data['name'].strip(),
        party=data['party'].strip(),
        ballot_order=order,
        active=True,
    )
    db.session.add(candidate)
    db.session.flush()
    append_audit(
        'candidate.create',
        json.dumps({'after': candidate.to_dict()}),
        actor=current_user,
    )
    db.session.commit()
    return jsonify({'candidate': candidate.to_dict()}), 201


@candidates_bp.route('/<int:candidate_id>', methods=['PATCH'])
@require_permission('candidate.write')
def update_candidate(current_user, candidate_id):
    candidate = Candidate.query.get(candidate_id)
    if not candidate:
        return json_error('Candidate not found', 404)
    data = request.get_json(silent=True) or {}
    before = candidate.to_dict()
    if 'name' in data and data['name']:
        candidate.name = data['name'].strip()
    if 'party' in data and data['party']:
        candidate.party = data['party'].strip()
    if 'chamber' in data:
        if data['chamber'] not in (CHAMBER_HOUSE, CHAMBER_SENATE):
            return json_error('Chamber must be house or senate', 400)
        candidate.chamber = data['chamber']
    if 'ballot_order' in data:
        try:
            candidate.ballot_order = int(data['ballot_order'])
        except (TypeError, ValueError):
            return json_error('Ballot order must be a number', 400)
    if 'active' in data:
        candidate.active = bool(data['active'])
    append_audit(
        'candidate.update',
        json.dumps({'id': candidate.id, 'before': before, 'after': candidate.to_dict()}),
        actor=current_user,
    )
    db.session.commit()
    return jsonify({'candidate': candidate.to_dict()}), 200
