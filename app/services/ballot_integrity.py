"""GR-11: integrity scan of the append-only ballot chain.

For every election the scan walks the chain in order and checks, per ballot:

* the stored record_hash matches a fresh recomputation   (content edited)
* the Ed25519 signature verifies                          (forged or edited, GR-10)
* the AES-GCM ciphertext authenticates and decrypts       (edited, GR-09)

and, across the chain:

* sequence numbers run 1, 2, 3 ... with no gaps           (a ballot deleted)
* each prev_hash equals the previous record_hash          (deleted or reordered)
* the number of ballots equals the number of ballot tokens marked used in the
  identity database                                       (tail truncated)

A ballot that fails a per-ballot check is quarantined: a row is added to
quarantined_ballots, the tally stops counting it, and an audit event is
written. Chain-level problems cannot be pinned to one ballot, so they are
reported as alerts. Every run is stored in integrity_scans.

The scan runs on a background thread every INTEGRITY_SCAN_SECONDS (default 30,
so a tampered ballot is flagged well within the 1-minute target) and can be
triggered on demand by an auditor or delegate through /api/integrity/scan.
"""

import json
import logging
import os
import threading

from app import db
from app.models.ballot import Ballot, BallotToken, IntegrityScan, QuarantinedBallot
from app.services import ballot_chain, ballot_crypto, ballot_keys, ballot_signing
from app.services.audit_log import append_audit

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 30
_scan_lock = threading.Lock()


def _ballot_findings(row, public_key):
    problems = []
    if ballot_chain.row_hash(row) != row.record_hash:
        problems.append('record hash mismatch')
    if not ballot_signing.verify_row(row, public_key):
        problems.append('invalid signature')
    try:
        ballot_crypto.decrypt_preferences(row.election_id, row.id, row.nonce, row.ciphertext)
    except ballot_crypto.BallotCryptoError:
        problems.append('ciphertext failed authentication')
    return problems


def scan_election(election_id):
    """Check one election's chain. Writes quarantine rows, audit events and a scan record; commits."""
    public_key = ballot_keys.verify_key()
    already = {q.ballot_id for q in QuarantinedBallot.query.filter_by(election_id=election_id).all()}
    rows = Ballot.query.filter_by(election_id=election_id).order_by(Ballot.seq).all()

    findings = []
    newly_quarantined = []
    expected_seq = 1
    expected_prev = ballot_chain.genesis_hash(election_id)

    for row in rows:
        if row.seq != expected_seq:
            findings.append({
                'type': 'sequence_gap', 'seq': row.seq,
                'detail': f'expected position {expected_seq}, found {row.seq}: ballot(s) missing',
            })
        if row.prev_hash != expected_prev:
            findings.append({
                'type': 'broken_link', 'seq': row.seq, 'ballot_id': row.id,
                'detail': 'prev_hash does not match the previous ballot: chain altered before this point',
            })
        problems = _ballot_findings(row, public_key)
        if problems:
            reason = ', '.join(problems)
            findings.append({'type': 'tampered_ballot', 'seq': row.seq, 'ballot_id': row.id, 'detail': reason})
            if row.id not in already:
                db.session.add(QuarantinedBallot(ballot_id=row.id, election_id=election_id, reason=reason))
                newly_quarantined.append(row.id)
                already.add(row.id)
                # No voter, no preferences: only which ballot row and why.
                append_audit('ballot.quarantined', f'Election {election_id} ballot {row.id}: {reason}')
        expected_seq = row.seq + 1
        expected_prev = row.record_hash

    used_tokens = BallotToken.query.filter_by(election_id=election_id, status='used').count()
    if used_tokens != len(rows):
        findings.append({
            'type': 'count_mismatch',
            'detail': f'{used_tokens} ballots were accepted but {len(rows)} are in the store',
        })

    # Alert on anything new: a fresh quarantine, or chain findings that differ
    # from the last scan. Stops the same alert repeating every 30 seconds.
    previous = (
        IntegrityScan.query.filter_by(election_id=election_id)
        .order_by(IntegrityScan.id.desc()).first()
    )
    findings_changed = previous is None or previous.findings_json != json.dumps(findings)
    alerts = [
        f for f in findings
        if (f['type'] == 'tampered_ballot' and f.get('ballot_id') in newly_quarantined)
        or (f['type'] != 'tampered_ballot' and findings_changed)
    ]
    if alerts:
        append_audit('ballot.integrity_alert', f'Election {election_id}: ' + '; '.join(
            f"{f['type']} {f['detail']}" for f in alerts
        )[:1000])
        log.warning('Ballot integrity alert for election %s: %s', election_id, alerts)

    scan = IntegrityScan(
        election_id=election_id,
        ballots_checked=len(rows),
        newly_quarantined=len(newly_quarantined),
        ok=not findings,
        findings_json=json.dumps(findings),
    )
    db.session.add(scan)
    db.session.commit()
    return scan.to_dict()


def scan_all():
    """Scan every election that has a ballot chain or accepted tokens."""
    from app.models.election import Election

    with _scan_lock:
        return [scan_election(election.id) for election in Election.query.order_by(Election.id).all()]


def latest_scans(limit=20):
    rows = IntegrityScan.query.order_by(IntegrityScan.id.desc()).limit(limit).all()
    return [row.to_dict() for row in rows]


def quarantine_list(election_id=None):
    query = QuarantinedBallot.query
    if election_id is not None:
        query = query.filter_by(election_id=election_id)
    return [row.to_dict() for row in query.order_by(QuarantinedBallot.id).all()]


def scan_interval_seconds():
    try:
        return int(os.environ.get('INTEGRITY_SCAN_SECONDS', DEFAULT_INTERVAL_SECONDS))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def start_background_scan(app):
    """Start the periodic scan thread. Disabled when INTEGRITY_SCAN_SECONDS is 0 or in tests."""
    interval = scan_interval_seconds()
    if interval <= 0 or app.config.get('TESTING') or app.extensions.get('ballot_integrity_thread'):
        return None
    stop = threading.Event()

    def run():
        while not stop.wait(interval):
            try:
                with app.app_context():
                    scan_all()
            except Exception:  # keep the watchdog alive; the failure itself is logged
                log.exception('Ballot integrity scan failed')
                with app.app_context():
                    db.session.rollback()

    thread = threading.Thread(target=run, name='ballot-integrity-scan', daemon=True)
    thread.start()
    app.extensions['ballot_integrity_thread'] = (thread, stop)
    return thread