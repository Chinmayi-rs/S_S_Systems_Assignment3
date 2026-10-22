"""GR-11: SHA-256 hash chain over committed ballots, one chain per election.

    record_hash(n) = SHA-256( prev_hash | election | seq | id | nonce | ciphertext | signature | hour )
    prev_hash(n)   = record_hash(n - 1), or the election's genesis hash for n = 1

Changing any stored field of ballot n changes its recomputed hash. Removing or
reordering ballots breaks the link between neighbours. Both are found by
services/ballot_integrity.py.
"""

import hashlib
import threading

CHAIN_SCHEME = 'ballot-chain-v1'

# Serialises "read chain head, append next link" inside one process. The unique
# (election_id, seq) constraint is the backstop across processes; on Postgres
# use SELECT ... FOR UPDATE on the head row instead.
append_lock = threading.Lock()


def genesis_hash(election_id):
    return hashlib.sha256(f'{CHAIN_SCHEME}|genesis|{election_id}'.encode('ascii')).hexdigest()


def compute_record_hash(prev_hash, election_id, seq, ballot_id, nonce, ciphertext, signature, recorded_hour):
    hour = recorded_hour.isoformat() if recorded_hour else ''
    material = '|'.join([
        CHAIN_SCHEME, prev_hash, str(election_id), str(seq), ballot_id, nonce, ciphertext, signature, hour,
    ])
    return hashlib.sha256(material.encode('ascii')).hexdigest()


def row_hash(row):
    return compute_record_hash(
        row.prev_hash, row.election_id, row.seq, row.id, row.nonce, row.ciphertext, row.signature,
        row.recorded_hour,
    )


def link(row, head):
    """Fill seq, prev_hash and record_hash on a new row, given the current chain head (or None)."""
    row.seq = 1 if head is None else head.seq + 1
    row.prev_hash = genesis_hash(row.election_id) if head is None else head.record_hash
    row.record_hash = row_hash(row)
    return row
