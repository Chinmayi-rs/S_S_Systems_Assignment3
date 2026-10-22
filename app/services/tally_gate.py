"""GR-12: run two independent counters over the same ballots; release only if they agree.

Both counters receive the identical list of verified, decrypted ballots
(signature-checked and quarantine-filtered by ballot_store, GR-10/GR-11).
Results may be published only when both counters ran, produced a well-formed
result, and agree exactly. Anything else blocks release and, for a mismatch,
raises an alert in the audit log.
"""

import logging

from app import db
from app.services import ballot_store, tally_primary, tally_secondary
from app.services.audit_log import append_audit

log = logging.getLogger(__name__)


class MalformedTally(ValueError):
    pass


def _normalise(result, total_ballots):
    if not isinstance(result, dict):
        raise MalformedTally('result is not a dict')
    try:
        house = {str(key): int(value) for key, value in result['house'].items() if int(value)}
        senate = {str(key): int(value) for key, value in result['senate'].items() if int(value)}
        total = int(result['total'])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise MalformedTally(f'missing or invalid field: {exc}') from exc
    if total != total_ballots:
        raise MalformedTally(f'counted {total} ballots but was given {total_ballots}')
    if sum(house.values()) > total or sum(senate.values()) > total:
        raise MalformedTally('more votes than ballots')
    return {'total': total, 'house': house, 'senate': senate}


def _run(name, counter, ballots):
    try:
        # Each counter gets its own copy so neither can change what the other sees.
        return _normalise(counter([dict(b) for b in ballots]), len(ballots)), None
    except NotImplementedError:
        return None, f'counter {name} is not implemented'
    except MalformedTally as exc:
        return None, f'counter {name} returned a malformed result ({exc})'
    except Exception as exc:  # a crashing counter must block release, not crash the page
        log.exception('Tally counter %s failed', name)
        return None, f'counter {name} failed ({type(exc).__name__})'


def differences(a, b):
    found = []
    if a['total'] != b['total']:
        found.append(f"total {a['total']} vs {b['total']}")
    for chamber in ('house', 'senate'):
        for key in sorted(set(a[chamber]) | set(b[chamber])):
            left, right = a[chamber].get(key, 0), b[chamber].get(key, 0)
            if left != right:
                found.append(f'{chamber} {key}: {left} vs {right}')
    return found


def dual_tally(election_id, primary=None, secondary=None):
    """Count with both counters. ``primary`` / ``secondary`` override the counters (tests only)."""
    ballots, rejected = ballot_store.read_verified_ballots(election_id)
    a, error_a = _run('A', primary or tally_primary.count, ballots)
    b, error_b = _run('B', secondary or tally_secondary.count, ballots)

    outcome = {
        'counted': a or b or {'total': len(ballots), 'house': {}, 'senate': {}},
        'rejected': rejected,
        'released': False,
        'reason': None,
        'differences': [],
    }
    errors = [error for error in (error_a, error_b) if error]
    if errors:
        outcome['reason'] = 'Release blocked: ' + '; '.join(errors)
        return outcome

    diff = differences(a, b)
    if diff:
        outcome['reason'] = 'Release blocked: the two independent tallies disagree'
        outcome['differences'] = diff
        append_audit('tally.mismatch', f'Election {election_id}: ' + '; '.join(diff)[:1000])
        db.session.commit()
        log.error('GR-12 tally mismatch for election %s: %s', election_id, diff)
        return outcome

    outcome['released'] = True
    return outcome