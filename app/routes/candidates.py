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

# GR-04: sane bounds on free-text fields so the admin screen cannot be used
# to stuff junk (or script payloads) into what every voter's ballot renders.
MAX_NAME_LENGTH = 120
MAX_PARTY_LENGTH = 80


def _validated_text(value, label, max_length):
    text = (value or '').strip()
    if not text:
        return None, f'{label} is required'
    if len(text) > max_length:
        return None, f'{label} must be at most {max_length} characters'
    return text, None


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
    name, error = _validated_text(data.get('name'), 'Name', MAX_NAME_LENGTH)
    if error:
        return json_error(error, 400)
    party, error = _validated_text(data.get('party'), 'Party', MAX_PARTY_LENGTH)
    if error:
        return json_error(error, 400)

    candidate = Candidate(
        election_id=election.id,
        chamber=chamber,
        name=name,
        party=party,
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
    # GR-14: withdrawing or restoring a candidate changes the result, so it needs two delegates.
    if 'active' in data and bool(data['active']) != candidate.active:
        return json_error(
            'Withdrawing or restoring a candidate needs two delegates. Propose it with POST /api/approvals '
            '(action_type "candidate.set_active"); a different delegate must approve it.',
            409,
        )
    before = candidate.to_dict()
    if 'name' in data and data['name']:
        name, error = _validated_text(data['name'], 'Name', MAX_NAME_LENGTH)
        if error:
            return json_error(error, 400)
        candidate.name = name
    if 'party' in data and data['party']:
        party, error = _validated_text(data['party'], 'Party', MAX_PARTY_LENGTH)
        if error:
            return json_error(error, 400)
        candidate.party = party
    if 'chamber' in data:
        if data['chamber'] not in (CHAMBER_HOUSE, CHAMBER_SENATE):
            return json_error('Chamber must be house or senate', 400)
        candidate.chamber = data['chamber']
    if 'ballot_order' in data:
        try:
            candidate.ballot_order = int(data['ballot_order'])
        except (TypeError, ValueError):
            return json_error('Ballot order must be a number', 400)
    append_audit(
        'candidate.update',
        json.dumps({'id': candidate.id, 'before': before, 'after': candidate.to_dict()}),
        actor=current_user,
    )
    db.session.commit()
    return jsonify({'candidate': candidate.to_dict()}), 200


@candidates_bp.route('/reorder', methods=['POST'])
@require_permission('candidate.write')
def reorder_candidates(current_user):
    """GR-04: party/ballot ordering is a delegate-only, fully audited change.

    Body: { "chamber": "house" | "senate", "order": [candidate ids, new order] }.
    The list must contain exactly the ids of that chamber's candidates, so a
    reorder can never silently drop or smuggle in a candidate.
    """
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    data = request.get_json(silent=True) or {}
    chamber = data.get('chamber')
    if chamber not in (CHAMBER_HOUSE, CHAMBER_SENATE):
        return json_error('Chamber must be house or senate', 400)
    try:
        wanted = [int(candidate_id) for candidate_id in (data.get('order') or [])]
    except (TypeError, ValueError):
        return json_error('Order must be a list of candidate ids', 400)

    rows = Candidate.query.filter_by(election_id=election.id, chamber=chamber).all()
    by_id = {row.id: row for row in rows}
    if sorted(wanted) != sorted(by_id):
        return json_error(
            'Order must list every candidate of that chamber exactly once', 400
        )

    before = {row.id: row.ballot_order for row in rows}
    for position, candidate_id in enumerate(wanted, start=1):
        by_id[candidate_id].ballot_order = position
    after = {row.id: row.ballot_order for row in rows}
    append_audit(
        'candidate.reorder',
        json.dumps({'chamber': chamber, 'before': before, 'after': after}),
        actor=current_user,
    )
    db.session.commit()
    return jsonify(_list_payload()), 200


@candidates_bp.route('/<int:candidate_id>', methods=['DELETE'])
@require_permission('candidate.write')
def delete_candidate(current_user, candidate_id):
    # GR-04: deletion would erase audit context, so it does not exist.
    # Withdrawing a candidate is the GR-14 two-delegate flow instead.
    return json_error(
        'Candidates are never deleted. Withdraw one with the two-delegate approval '
        'flow (POST /api/approvals, action_type "candidate.set_active").',
        405,
    )
