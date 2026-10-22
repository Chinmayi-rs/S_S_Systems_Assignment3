"""Builds the results payload from the GR-12 dual tally."""

from app.models.candidate import Candidate
from app.services.tally_gate import dual_tally


def build_results(election, tally_outcome=None):
    outcome = tally_outcome if tally_outcome is not None else dual_tally(election.id)
    counted = outcome['counted']
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
        row['votes'] = counted['house'].get(str(candidate.id), 0)
        house.append(row)
    senate = []
    for candidate in senate_rows:
        row = candidate.to_dict()
        row['votes'] = counted['senate'].get(str(candidate.party), 0)
        senate.append(row)
    return {
        'election': election.to_dict(),
        'total_ballots': counted['total'],
        # GR-10 / GR-11: ballots that failed re-verification or were quarantined.
        'rejected_ballots': len(outcome['rejected']),
        'house': house,
        'senate': senate,
        'method': 'first-preference',
        # GR-12: true only when two independent counters agree.
        'release_blocked': not outcome['released'],
        'release_reason': outcome['reason'],
        'tally_differences': outcome['differences'],
    }