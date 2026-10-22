"""GR-12 counter B (secondary).

Written independently of tally_primary.py: it does not import or read it.
GR-12 needs two separately written counters, so a bug in one shows up as a
mismatch at the gate instead of a wrong published result.

Input:  ``ballots``, a list of dicts like {'house': [3, 1, 4, 2], 'senate_party': 'Greens'}.
        The house list is candidate ids in preference order (first item = first preference).
Output: {'total': <number of ballots>,
         'house': {'<candidate id>': <first-preference votes>, ...},
         'senate': {'<party>': <votes>, ...}}
        Candidates or parties with zero votes are left out.
"""


def count(ballots):
    total = 0
    house_votes = {}
    senate_votes = {}

    for ballot in ballots:
        total += 1

        preferences = ballot.get('house') or []
        if preferences:
            candidate = str(preferences[0])
            house_votes[candidate] = house_votes.get(candidate, 0) + 1

        party = ballot.get('senate_party')
        if party:
            senate_votes[party] = senate_votes.get(party, 0) + 1

    return {'total': total, 'house': house_votes, 'senate': senate_votes}