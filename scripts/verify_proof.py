"""Check one delegate action offline, with no access to the app or its database.

    python scripts/verify_proof.py proof.json

Get proof.json from GET /api/audit/<id>/proof. Needs only: pip install cryptography
Exit code 0 = the named delegate signed exactly this entry. Anything else = do not trust it.
"""
import base64
import hashlib
import json
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def main(path):
    proof = json.load(open(path, encoding='utf-8'))

    # 1. Recompute the entry hash from the entry's own fields (same rule as the audit chain).
    canonical = json.dumps(proof['event'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    entry_hash = hashlib.sha256(proof['prev_hash'].encode('ascii') + b'|' + canonical).hexdigest()
    if entry_hash != proof['entry_hash']:
        print('FAIL: entry content does not match its hash')
        return 1

    # 2. Check the public key against its fingerprint, then verify the signature over the entry hash.
    raw_public = base64.b64decode(proof['signer']['public_key'])
    if hashlib.sha256(raw_public).hexdigest() != proof['signer']['fingerprint']:
        print('FAIL: public key does not match its fingerprint')
        return 1
    message = proof['signed_message_prefix'].encode('ascii') + entry_hash.encode('ascii')
    try:
        Ed25519PublicKey.from_public_bytes(raw_public).verify(base64.b64decode(proof['signature']), message)
    except InvalidSignature:
        print('FAIL: signature is not valid')
        return 1

    print('OK: delegate "%s" (key %s...) signed action "%s" at %s' % (
        proof['event']['actor_username'], proof['signer']['fingerprint'][:16],
        proof['event']['action'], proof['event']['created_at']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
