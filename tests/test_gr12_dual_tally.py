"""GR-12: two independently implemented counters; results released only when they agree."""

import ast
import pathlib

import pytest

from app import db
from app.models.audit import AuditEvent
from app.models.ballot import Ballot
from app.services import ballot_integrity, tally_gate, tally_primary
from tests.conftest import add_verified_voters, auth_headers, cast_ballot, tamper_as_db_admin

SERVICES = pathlib.Path(__file__).resolve().parents[1] / 'app' / 'services'


def imported_modules(path):
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or '')
            names.update(f'{node.module}.{alias.name}' for alias in node.names)
    return names


def close_poll(api):
    delegate = auth_headers(api, 'delegate', 'delegate1234')
    assert api.post('/api/elections/current/status', json={'status': 'closed'}, headers=delegate).status_code == 200
    return delegate


def cast_three(app, api):
    names = ['voter'] + add_verified_voters(app, 2)
    return [cast_ballot(api, auth_headers(api, n, 'voter1234'), senate_index=i) for i, n in enumerate(names)]


def test_counters_do_not_share_code():
    secondary = imported_modules(SERVICES / 'tally_secondary.py')
    primary = imported_modules(SERVICES / 'tally_primary.py')
    assert not any('tally_primary' in name for name in secondary)
    assert not any('tally_secondary' in name for name in primary)


def test_primary_counter_counts_first_preferences():
    ballots = [
        {'house': [3, 1, 2], 'senate_party': 'Greens'},
        {'house': [3, 2, 1], 'senate_party': 'Labor'},
        {'house': [1, 2, 3], 'senate_party': 'Greens'},
    ]
    assert tally_primary.count(ballots) == {
        'total': 3, 'house': {'3': 2, '1': 1}, 'senate': {'Greens': 2, 'Labor': 1},
    }


def test_matching_tallies_release_results(app, api, second_counter):
    cast_three(app, api)
    close_poll(api)
    published = api.get('/api/results')
    assert published.status_code == 200
    body = published.get_json()
    assert body['release_blocked'] is False
    assert body['total_ballots'] == 3
    assert sum(row['votes'] for row in body['senate']) == 3


def test_mismatch_blocks_release_and_raises_an_alert(app, api):
    cast_three(app, api)

    def off_by_one(ballots):
        result = tally_primary.count(ballots)
        party = next(iter(result['senate']))
        result['senate'][party] -= 1
        return result

    with app.app_context():
        outcome = tally_gate.dual_tally(1, secondary=off_by_one)
        assert outcome['released'] is False
        assert outcome['differences']
        assert AuditEvent.query.filter_by(action='tally.mismatch').count() == 1


def test_mismatch_returns_503_on_the_public_endpoint(app, api, monkeypatch):
    from app.services import tally_secondary

    cast_three(app, api)
    monkeypatch.setattr(tally_secondary, 'count', lambda ballots: {'total': len(ballots), 'house': {}, 'senate': {}})
    delegate = close_poll(api)
    published = api.get('/api/results')
    assert published.status_code == 503
    assert 'disagree' in published.get_json()['error']
    # Delegates and auditors still see why, with the differences listed.
    preview = api.get('/api/results', headers=delegate).get_json()
    assert preview['release_blocked'] is True
    assert preview['tally_differences']


def test_missing_second_counter_fails_closed(app, api):
    cast_three(app, api)
    close_poll(api)
    published = api.get('/api/results')
    assert published.status_code == 503
    assert 'counter B' in published.get_json()['error']


@pytest.mark.parametrize('bad_counter, expected', [
    (lambda ballots: 1 / 0, 'failed'),
    (lambda ballots: {'total': 99, 'house': {}, 'senate': {}}, 'malformed'),
    (lambda ballots: ['not', 'a', 'dict'], 'malformed'),
    (lambda ballots: {'total': len(ballots)}, 'malformed'),
])
def test_broken_counter_blocks_release(app, api, bad_counter, expected):
    cast_three(app, api)
    with app.app_context():
        outcome = tally_gate.dual_tally(1, secondary=bad_counter)
    assert outcome['released'] is False
    assert expected in outcome['reason']


def test_a_counter_cannot_change_what_the_other_counts(app, api):
    cast_three(app, api)

    def vandal(ballots):
        for ballot in ballots:
            ballot['senate_party'] = 'Liberal'
        return tally_primary.count(ballots)

    with app.app_context():
        outcome = tally_gate.dual_tally(1, primary=vandal)
    assert outcome['released'] is False  # B still counted the real ballots, so they differ


def test_quarantined_ballots_are_excluded_from_both_counts(app, api, second_counter):
    receipts = cast_three(app, api)
    with app.app_context():
        tamper_as_db_admin("UPDATE ballots SET signature = 'AAAA' WHERE id = :i", {'i': receipts[0]['reference']})
        ballot_integrity.scan_election(1)
        outcome = tally_gate.dual_tally(1)
        assert Ballot.query.count() == 3
    assert outcome['released'] is True
    assert outcome['counted']['total'] == 2
    assert outcome['rejected'] == [{'id': receipts[0]['reference'], 'reason': 'quarantined'}]
