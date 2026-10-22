from app.models.candidate import Candidate
from app.services import ballot_store

def tally_first_preference(election_id):
    """Count committed ballots by House first preference and Senate group.

    GR-12 needs a second function, written by someone else, that does not
    import this one. This skeleton only has the first counter.
    """
    ballots, rejected = ballot_store.read_verified_ballots(election_id)
    house_counts = {}
    senate_counts = {}
    for prefs in ballots:
        house = prefs.get('house') or []
        if house:
            first = house[0]
            house_counts[first] = house_counts.get(first, 0) + 1
        party = prefs.get('senate_party')
        if party:
            senate_counts[party] = senate_counts.get(party, 0) + 1
    return house_counts, senate_counts, len(ballots), rejected
def build_results(election):
    house_counts, senate_counts, total, rejected = tally_first_preference(election.id)
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
        #GR-10: ballots that failed re-verification are excluded, never counted.
        'rejected_ballots': len(rejected),
        'house': house,
        'senate': senate,
        'method': 'first-preference',
    }
