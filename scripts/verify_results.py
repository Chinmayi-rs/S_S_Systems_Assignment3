"""Check the published election result offline, with no access to the app or its database (GR-13).

    python scripts/verify_results.py results.json results.sig.json results.pub.json
    python scripts/verify_results.py results.json results.sig.json results.pub.json --fingerprint <sha256 hex>

The three files are what the Results page offers for download (or GET /api/results, GET /api/results/public-key):
  results.json      the signed result
  results.sig.json  the signature, the SHA-256 of the result and the signature prefix
  results.pub.json  the public key (a file with just the base64 key works too)

--fingerprint is the fingerprint you got from a source you trust (the report, or the results.key.registered
entry in the audit log). Without it the script only proves the result matches the key you handed it, and
you must decide for yourself that this key is the real one.

Needs only: pip install cryptography
Exit code 0 = the result is exactly what was signed. Anything else = do not trust it.
"""
import argparse
import base64
import hashlib
import json
import sys

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SIGN_PREFIX = 'BALLOTDESK-RESULTS-v1|'  # the app signs this prefix + the SHA-256 hex of the result; nothing else


def _no_duplicate_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('the result file repeats a key')
    return dict(pairs)


def _canonical(document) -> bytes:
    # same rule as the app's audit chain: sorted keys, no spaces, UTF-8
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _read_public_key(path):
    text = open(path, encoding='utf-8').read().strip()
    if text.startswith('{'):
        return json.loads(text)['public_key']
    return text


def verify(results_path, signature_path, public_key_path, expected_fingerprint=None):
    """Returns (ok, message)."""
    try:
        document = json.load(open(results_path, encoding='utf-8'), object_pairs_hook=_no_duplicate_keys)
        sig = json.load(open(signature_path, encoding='utf-8'))
        raw_public = base64.b64decode(_read_public_key(public_key_path), validate=True)
        signature = base64.b64decode(sig['signature'], validate=True)
        Ed25519PublicKey.from_public_bytes(raw_public)
    except (OSError, ValueError, KeyError, TypeError) as err:
        return False, 'FAIL: could not read the input files (%s)' % err

    # 1. The key must be the one you trust.
    fingerprint = hashlib.sha256(raw_public).hexdigest()
    if expected_fingerprint and fingerprint != expected_fingerprint.lower():
        return False, 'FAIL: the public key is not the one you expected (fingerprint %s...)' % fingerprint[:16]

    # 2. Hash the result again. Changing even one number changes the hash.
    digest = hashlib.sha256(_canonical(document)).hexdigest()
    if sig.get('sha256') and digest != sig['sha256']:
        return False, 'FAIL: the result was changed after it was signed (hash does not match)'

    # 3. Check the signature over prefix + hash.
    prefix = sig.get('signed_message_prefix', SIGN_PREFIX)
    if prefix != SIGN_PREFIX:
        return False, 'FAIL: unexpected signature prefix, this is not a results signature'
    try:
        Ed25519PublicKey.from_public_bytes(raw_public).verify(signature, (prefix + digest).encode('ascii'))
    except InvalidSignature:
        return False, 'FAIL: the signature is not valid for this result and this key'

    publication = document.get('publication', {})
    pinned = 'matches the fingerprint you trust' if expected_fingerprint else 'fingerprint NOT checked against a trusted copy'
    return True, 'OK: result signed by key %s... (%s). Published %s, proposed by %s, approved by %s. Ballots counted: %s.' % (
        fingerprint[:16], pinned, publication.get('published_at'), publication.get('proposed_by'),
        publication.get('approved_by'), document.get('results', {}).get('total_ballots'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify a signed election result offline.')
    parser.add_argument('results')
    parser.add_argument('signature')
    parser.add_argument('public_key')
    parser.add_argument('--fingerprint', help='SHA-256 fingerprint of the public key, from a trusted source')
    args = parser.parse_args(argv)
    ok, message = verify(args.results, args.signature, args.public_key, args.fingerprint)
    print(message)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
