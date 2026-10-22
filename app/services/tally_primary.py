"""GR-12 counter A (primary). Author: Chinmayi.

Counts first preferences for the House and above-the-line groups for the
Senate. Takes plain decrypted preference dicts, so it never sees the database
or the crypto, and returns the shared result shape that tally_gate compares:

    {'total': int, 'house': {'<candidate id>': votes}, 'senate': {'<party>': votes}}

Counter B (services/tally_secondary.py) must be written by a different team
member without reading or importing this file.
"""

from collections import Counter


def count(ballots):
    house = Counter()
    senate = Counter()
    total = 0
    for preferences in ballots:
        total += 1
        ranked = preferences.get('house') or []
        if ranked:
            house[str(ranked[0])] += 1
        group = preferences.get('senate_party')
        if group:
            senate[str(group)] += 1
    return {'total': total, 'house': dict(house), 'senate': dict(senate)}
