"""GR-11: append-only, hash-chained ballot store with an automated integrity scan."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app import db
from app.models.audit import AuditEvent
from app.models.ballot import AppendOnlyViolation, Ballot, IntegrityScan, QuarantinedBallot
from app.services import ballot_chain, ballot_integrity
from tests.conftest import add_verified_voters, auth_headers, cast_ballot, tamper_as_db_admin


def cast_several(app, api, count):
    names = ['voter'] + add_verified_voters(app, count - 1)
    return [cast_ballot(api, auth_headers(api, name, 'voter1234'), senate_index=i % 3) for i, name in enumerate(names)]


def chain(election_id=1):
    return Ballot.query.filter_by(election_id=election_id).order_by(Ballot.seq).all()


def test_ballots_form_a_hash_chain(app, api):
    cast_several(app, api, 3)
    with app.app_context():
        rows = chain()
        assert [row.seq for row in rows] == [1, 2, 3]
        assert rows[0].prev_hash == ballot_chain.genesis_hash(1)
        assert rows[1].prev_hash == rows[0].record_hash
        assert rows[2].prev_hash == rows[1].record_hash
        assert all(ballot_chain.row_hash(row) == row.record_hash for row in rows)


def test_orm_refuses_update_and_delete(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    with app.app_context():
        row = Ballot.query.one()
        row.ciphertext = 'changed'
        with pytest.raises(AppendOnlyViolation):
            db.session.flush()
        db.session.rollback()
        db.session.delete(Ballot.query.one())
        with pytest.raises(AppendOnlyViolation):
            db.session.flush()
        db.session.rollback()


@pytest.mark.parametrize('statement', [
    "UPDATE ballots SET ciphertext = 'x'",
    'DELETE FROM ballots',
])
def test_database_trigger_refuses_raw_sql(app, api, statement):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    with app.app_context():
        with pytest.raises(DatabaseError, match='append-only'):
            with db.engines['ballot'].begin() as conn:
                conn.execute(text(statement))
        assert Ballot.query.count() == 1


def test_clean_chain_passes_the_scan(app, api):
    cast_several(app, api, 3)
    with app.app_context():
        result = ballot_integrity.scan_election(1)
    assert result['ok'] is True
    assert result['ballots_checked'] == 3
    assert result['findings'] == []


def test_edited_ballot_is_quarantined_and_not_counted(app, api):
    receipts = cast_several(app, api, 3)
    target = receipts[1]['reference']
    with app.app_context():
        # Swap in another ballot's valid ciphertext: an attempt to change a vote.
        donor = Ballot.query.filter(Ballot.id == receipts[0]['reference']).one().ciphertext
        tamper_as_db_admin('UPDATE ballots SET ciphertext = :c WHERE id = :i', {'c': donor, 'i': target})
        result = ballot_integrity.scan_election(1)
        assert result['ok'] is False
        assert result['newly_quarantined'] == 1
        quarantined = QuarantinedBallot.query.one()
        assert quarantined.ballot_id == target
        assert 'record hash mismatch' in quarantined.reason
        assert 'invalid signature' in quarantined.reason
        assert AuditEvent.query.filter_by(action='ballot.quarantined').count() == 1

    delegate = auth_headers(api, 'delegate', 'delegate1234')
    preview = api.get('/api/results', headers=delegate).get_json()
    assert preview['total_ballots'] == 2
    assert preview['rejected_ballots'] == 1


def test_attacker_who_rehashes_still_fails_signature_check(app, api):
    receipts = cast_several(app, api, 2)
    target = receipts[0]['reference']
    with app.app_context():
        row = Ballot.query.get(target)
        forged = ballot_chain.compute_record_hash(
            row.prev_hash, row.election_id, row.seq, row.id, row.nonce, 'Zm9yZ2Vk', row.signature, row.recorded_hour,
        )
        tamper_as_db_admin(
            'UPDATE ballots SET ciphertext = :c, record_hash = :h WHERE id = :i',
            {'c': 'Zm9yZ2Vk', 'h': forged, 'i': target},
        )
        result = ballot_integrity.scan_election(1)
    types = {finding['type'] for finding in result['findings']}
    assert 'tampered_ballot' in types  # signature and decryption fail
    assert 'broken_link' in types      # the next ballot no longer points at it


def test_deleted_ballot_is_detected(app, api):
    receipts = cast_several(app, api, 3)
    with app.app_context():
        tamper_as_db_admin('DELETE FROM ballots WHERE id = :i', {'i': receipts[1]['reference']})
        result = ballot_integrity.scan_election(1)
    types = {finding['type'] for finding in result['findings']}
    assert {'sequence_gap', 'broken_link', 'count_mismatch'} <= types


def test_truncated_tail_is_detected_by_count(app, api):
    receipts = cast_several(app, api, 2)
    with app.app_context():
        tamper_as_db_admin('DELETE FROM ballots WHERE id = :i', {'i': receipts[-1]['reference']})
        result = ballot_integrity.scan_election(1)
    assert [finding['type'] for finding in result['findings']] == ['count_mismatch']


def test_repeat_scans_do_not_repeat_alerts(app, api):
    receipts = cast_several(app, api, 2)
    with app.app_context():
        tamper_as_db_admin("UPDATE ballots SET nonce = 'AAAAAAAAAAAAAAAA' WHERE id = :i", {'i': receipts[0]['reference']})
        ballot_integrity.scan_election(1)
        ballot_integrity.scan_election(1)
        ballot_integrity.scan_election(1)
        assert QuarantinedBallot.query.count() == 1
        assert AuditEvent.query.filter_by(action='ballot.quarantined').count() == 1
        assert IntegrityScan.query.count() == 3


def test_background_scan_quarantines_within_a_minute(app, api, monkeypatch):
    receipts = cast_several(app, api, 2)
    with app.app_context():
        tamper_as_db_admin("UPDATE ballots SET signature = 'AAAA' WHERE id = :i", {'i': receipts[0]['reference']})
    monkeypatch.setenv('INTEGRITY_SCAN_SECONDS', '1')
    app.config['TESTING'] = False
    thread = ballot_integrity.start_background_scan(app)
    assert thread is not None
    try:
        import time

        deadline = time.time() + 10
        while time.time() < deadline:
            with app.app_context():
                if QuarantinedBallot.query.count():
                    break
            time.sleep(0.2)
        with app.app_context():
            assert QuarantinedBallot.query.one().ballot_id == receipts[0]['reference']
    finally:
        app.extensions['ballot_integrity_thread'][1].set()
        thread.join(timeout=5)


def test_integrity_api_is_limited_to_auditor_and_delegate(api):
    voter = auth_headers(api, 'voter', 'voter1234')
    assert api.get('/api/integrity', headers=voter).status_code == 403
    assert api.post('/api/integrity/scan', headers=voter).status_code == 403
    assert api.post('/api/integrity/scan').status_code == 401
    auditor = auth_headers(api, 'auditor', 'auditor1234')
    scanned = api.post('/api/integrity/scan', headers=auditor)
    assert scanned.status_code == 200
    assert scanned.get_json()['ok'] is True
    assert api.get('/api/integrity', headers=auditor).get_json()['scans']
