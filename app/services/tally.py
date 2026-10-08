import json

from app.models.ballot import Ballot
from app.models.candidate import Candidate


def tally_first_preference(election_id):
    """Count committed ballots by House first preference and Senate group.

    GR-12 needs a second function, written by someone else, that does not
    import this one. This skeleton only has the first counter.
    """
    ballots = Ballot.query.filter_by(election_id=election_id, status='committed').all()
    house_counts = {}
    senate_counts = {}
    for ballot in ballots:
        try:
            prefs = json.loads(ballot.preferences_json)
        except (TypeError, json.JSONDecodeError):
            continue
        house = prefs.get('house') or []
        if house:
            first = house[0]
            house_counts[first] = house_counts.get(first, 0) + 1
        party = prefs.get('senate_party')
        if party:
            senate_counts[party] = senate_counts.get(party, 0) + 1
    return house_counts, senate_counts, len(ballots)


def build_results(election):
    house_counts, senate_counts, total = tally_first_preference(election.id)
    house_rows = (
        Candidate.query.filter_by(election_id=election.id, chamber='house')
        .order_by(Candidate.ballot_order, Candidate.id)
        .all()
    )
    senate_rows = (
        Candidate.query.filter_by(election_id=election.id, chamber='senate')
        .order_by(Candidate.ballot_order, Candidate.id)
        .all()
    )
    house = []
    for candidate in house_rows:
        row = candidate.to_dict()
        row['votes'] = house_counts.get(candidate.id, 0)
        house.append(row)
    senate = []
    for candidate in senate_rows:
        row = candidate.to_dict()
        row['votes'] = senate_counts.get(candidate.party, 0)
        senate.append(row)
    return {
        'election': election.to_dict(),
        'total_ballots': total,
        'house': house,
        'senate': senate,
        'method': 'first-preference',
    }
