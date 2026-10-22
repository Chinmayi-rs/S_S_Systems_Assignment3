"""GR-12 counter B (secondary). To be written by: <teammate name>.

This file is deliberately NOT written by the author of tally_primary.py.
GR-12 needs two independently implemented counters, so a bug in one shows up
as a mismatch instead of a wrong published result.

Rules for whoever writes it:
* Do not import or read app/services/tally_primary.py (a test enforces the import rule).
* Input: ``ballots``, a list of dicts like {'house': [3, 1, 4, 2], 'senate_party': 'Greens'}.
  The house list is candidate ids in preference order; the first item is the
  first preference.
* Output, exactly this shape (string keys):
      {'total': <number of ballots>,
       'house': {'<candidate id>': <first-preference votes>, ...},
       'senate': {'<party>': <votes>, ...}}
  Leave out candidates or parties with zero votes.

Until this is implemented, the gate refuses to publish results (fail closed).
"""


def count(ballots):
    raise NotImplementedError('GR-12 second counter has not been implemented yet')
