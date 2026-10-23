"""Hash chain helpers for the audit log (GR-15).

Each entry stores prev_hash (the previous entry's entry_hash) and its own
entry_hash = SHA-256(prev_hash | canonical JSON of the entry's fields).
Changing, deleting or re-ordering any past entry breaks every hash after it.
"""
import hashlib
import json

GENESIS_HASH = '0' * 64


def canonical(fields: dict) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def compute_hash(prev_hash: str, fields: dict) -> str:
    return hashlib.sha256(prev_hash.encode('ascii') + b'|' + canonical(fields)).hexdigest()


def verify_chain(events) -> dict:
    """`events` must be ordered by id ascending."""
    prev = GENESIS_HASH
    count = 0
    for event in events:
        if event.prev_hash != prev:
            return {'valid': False, 'broken_at': event.id, 'reason': 'prev_hash does not match the previous entry'}
        if compute_hash(prev, event.chain_fields()) != event.entry_hash:
            return {'valid': False, 'broken_at': event.id, 'reason': 'entry content does not match its hash'}
        prev = event.entry_hash
        count += 1
    return {'valid': True, 'entries': count, 'head_hash': prev}
