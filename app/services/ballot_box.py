import hashlib
import json
import secrets
import uuid
from datetime import datetime

from app import db
from app.models.ballot import Ballot, BallotToken
from app.models.candidate import Candidate
from app.services.elections import current_election


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _house_candidates(election_id):
    return (
        Candidate.query.filter_by(election_id=election_id, chamber='house', active=True)
        .order_by(Candidate.ballot_order, Candidate.id)
        .all()
    )


def _senate_groups(election_id):
    return (
        Candidate.query.filter_by(election_id=election_id, chamber='senate', active=True)
        .order_by(Candidate.ballot_order, Candidate.id)
        .all()
    )


def voter_status(user):
    election = current_election()
    if not election:
        return None, ('No election is configured', 404)
    division_ok = bool(user.division) and user.division == election.division
    return {
        'election': election.to_dict(),
        'enrolled': user.enrolled,
        'eligible': user.eligible,
        'has_voted': user.has_voted,
        'division': user.division,
        'division_ok': division_ok,
        'can_vote': (
            user.role == 'voter'
            and user.enrolled
            and user.eligible
            and division_ok
            and not user.has_voted
            and election.status == 'open'
        ),
    }, None


def _eligibility_error(user, election):
    if user.role != 'voter':
        return 'Only an enrolled voter can request a ballot', 403
    if election.status != 'open':
        return 'This election is not open for voting', 409
    if not user.enrolled or not user.eligible:
        return 'You are not eligible to vote yet. An enrolment officer must verify you.', 403
    if user.division != election.division:
        return f'This ballot is for the division of {election.division}.', 403
    if user.has_voted:
        return 'A ballot has already been accepted for this voter', 409
    return None


def issue_token(user):
    election = current_election()
    if not election:
        return None, ('No election is configured', 404)
    error = _eligibility_error(user, election)
    if error:
        return None, error

    (
        BallotToken.query.filter_by(
            voter_id=user.id, election_id=election.id, status='issued'
        ).update({'status': 'expired'})
    )
    raw = secrets.token_urlsafe(32)
    record = BallotToken(
        election_id=election.id,
        voter_id=user.id,
        token_hash=hash_token(raw),
        status='issued',
    )
    db.session.add(record)
    db.session.commit()
    return {'token': raw, 'election_id': election.id}, None


def _load_open_token(user, raw_token):
    if not raw_token:
        return None, None, ('Ballot token is missing', 400)
    election = current_election()
    if not election:
        return None, None, ('No election is configured', 404)
    if election.status != 'open':
        return None, None, ('This election is not open for voting', 409)
    record = BallotToken.query.filter_by(
        token_hash=hash_token(raw_token),
        voter_id=user.id,
        election_id=election.id,
        status='issued',
    ).first()
    if not record:
        return None, None, ('Ballot token is invalid or already used', 409)
    return election, record, None


def validate_preferences(election_id, house_ids, senate_party):
    if not isinstance(house_ids, list) or not house_ids:
        return None, ('Number every House candidate once', 400)
    try:
        house_ids = [int(item) for item in house_ids]
    except (TypeError, ValueError):
        return None, ('House preferences must be candidate ids', 400)
    expected = [candidate.id for candidate in _house_candidates(election_id)]
    if len(house_ids) != len(expected) or set(house_ids) != set(expected):
        return None, ('Number every House candidate once, and only those candidates', 400)
    groups = _senate_groups(election_id)
    match = next((group for group in groups if group.party == senate_party), None)
    if match is None:
        return None, ('Choose one Senate group above the line', 400)
    payload = {'house': house_ids, 'senate_party': senate_party}
    summary = {
        'house': [],
        'senate_party': senate_party,
        'senate_name': match.name,
    }
    by_id = {candidate.id: candidate for candidate in _house_candidates(election_id)}
    for index, candidate_id in enumerate(house_ids, start=1):
        candidate = by_id[candidate_id]
        summary['house'].append({
            'preference': index,
            'id': candidate.id,
            'name': candidate.name,
            'party': candidate.party,
        })
    return (payload, summary), None


def stage_ballot(user, raw_token, house_ids, senate_party):
    election, record, error = _load_open_token(user, raw_token)
    if error:
        return None, error
    checked, error = validate_preferences(election.id, house_ids, senate_party)
    if error:
        return None, error
    payload, summary = checked
    existing = Ballot.query.filter_by(token_hash=record.token_hash).first()
    if existing and existing.status == 'committed':
        return None, ('This ballot has already been accepted', 409)
    if existing:
        existing.preferences_json = json.dumps(payload)
        existing.status = 'staged'
    else:
        existing = Ballot(
            id=str(uuid.uuid4()),
            election_id=election.id,
            token_hash=record.token_hash,
            preferences_json=json.dumps(payload),
            status='staged',
        )
        db.session.add(existing)
    db.session.commit()
    summary['staged'] = True
    return summary, None


def commit_ballot(user, raw_token):
    election, record, error = _load_open_token(user, raw_token)
    if error:
        return None, error
    if user.has_voted:
        return None, ('A ballot has already been accepted for this voter', 409)
    staged = Ballot.query.filter_by(token_hash=record.token_hash, status='staged').first()
    if not staged:
        return None, ('Review the ballot before it can be accepted', 400)

    # Identity flag and ballot row commit together through one session.
    # GR-05 should tighten this with a row lock when the database is Postgres.
    user.has_voted = True
    record.status = 'used'
    record.used_at = datetime.utcnow()
    staged.status = 'committed'
    staged.committed_at = datetime.utcnow()
    db.session.commit()
    return {
        'accepted': True,
        'reference': staged.id,
        'election_id': election.id,
    }, None
