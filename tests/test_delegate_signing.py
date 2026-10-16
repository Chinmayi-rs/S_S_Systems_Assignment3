import json
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

from app import create_app, db
from app.models.audit import AuditEvent
from app.models.signing import ActionSignature, DelegateKey
from app.models.user import User
from app.services.audit_chain import compute_hash

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def ctx():
    directory = tempfile.mkdtemp()
    identity = os.path.join(directory, 'identity.db')
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + identity
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client, app, identity, directory


def login(client, username, password):
    res = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def delegate_acts(client, headers=None):
    headers = headers or login(client, 'delegate', 'delegate1234')
    client.post('/api/candidates', json={'name': 'New One', 'party': 'Independent', 'chamber': 'house', 'ballot_order': 9}, headers=headers)
    proposed = client.post('/api/approvals', json={'action_type': 'election.status', 'status': 'closed'}, headers=headers)
    second = login(client, 'delegate2', 'delegate21234')
    client.post(f"/api/approvals/{proposed.get_json()['approval']['id']}/approve", headers=second)
    return headers


def verify(client):
    return client.get('/api/audit/verify', headers=login(client, 'auditor', 'auditor1234')).get_json()


def raw_edit(identity_path, statements):
    """Attacker with the raw database file: drop the append-only guards, then edit."""
    conn = sqlite3.connect(identity_path)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall():
        conn.execute(f'DROP TRIGGER {name}')
    for sql in statements:
        conn.execute(sql)
    conn.commit()
    conn.close()


def test_every_delegate_action_is_signed_and_verifies(ctx):
    client, app, _, _ = ctx
    delegate_acts(client)
    result = verify(client)
    assert result['valid'] is True and result['chain_valid'] is True
    # key registration + candidate.create + election.status
    assert result['signatures']['valid'] is True and result['signatures']['checked'] >= 3
    with app.app_context():
        delegate = User.query.filter_by(username='delegate').one()
        signed_ids = {row.audit_event_id for row in ActionSignature.query.all()}
        for event in AuditEvent.query.filter_by(actor_id=delegate.id).all():
            assert event.id in signed_ids


def test_each_delegate_has_an_individual_key(ctx):
    client, app, _, _ = ctx
    delegate_acts(client)
    # delegate2 already signed the approval inside delegate_acts, so both delegates have a key now
    with app.app_context():
        keys = DelegateKey.query.all()
        assert len(keys) == 2 and keys[0].fingerprint != keys[1].fingerprint
        assert keys[0].public_key != keys[1].public_key
        # the private key is never stored in the clear: ciphertext is longer than a raw 32-byte key
        assert len(keys[0].private_key_enc) > 64
    assert verify(client)['signatures']['valid'] is True


def test_non_delegate_events_are_not_signed(ctx):
    client, app, _, _ = ctx
    officer = login(client, 'officer', 'officer1234')
    voters = client.get('/api/enrolment/voters', headers=officer).get_json()['voters']
    pending = next(v for v in voters if v['username'] == 'pending')
    client.post(f"/api/enrolment/voters/{pending['id']}/verify", json={'division': 'Melbourne', 'eligible': True}, headers=officer)
    with app.app_context():
        assert ActionSignature.query.count() == 0


def test_rewriting_the_whole_chain_is_caught_by_the_signature(ctx):
    """The attacker edits an entry AND recomputes every hash after it. The chain still looks fine, the signature does not."""
    client, app, identity, _ = ctx
    delegate_acts(client)
    with app.app_context():
        events = AuditEvent.query.order_by(AuditEvent.id).all()
        victim = next(e for e in events if e.action == 'election.status')
        rows = [(e.id, e.actor_id, e.actor_username, e.action, e.detail, e.created_at.isoformat(timespec='microseconds'), e.prev_hash) for e in events]
    statements, prev = [], '0' * 64
    for (eid, actor_id, username, action, detail, created, _old_prev) in rows:
        if eid == victim.id:
            detail = 'closed -> open'  # delegate "never closed the poll"
        fields = {'actor_id': actor_id, 'actor_username': username, 'action': action, 'detail': detail, 'created_at': created}
        new_hash = compute_hash(prev, fields)
        statements.append(
            f"UPDATE audit_events SET detail = '{detail}', prev_hash = '{prev}', entry_hash = '{new_hash}' WHERE id = {eid}"
        )
        prev = new_hash
    raw_edit(identity, statements)
    result = verify(client)
    assert result['chain_valid'] is True          # hash chain alone is fooled
    assert result['signatures']['valid'] is False  # delegate signature is not
    assert any(p['event_id'] == victim.id for p in result['signatures']['problems'])
    assert result['valid'] is False


def test_removed_signature_is_detected(ctx):
    client, _, identity, _ = ctx
    delegate_acts(client)
    raw_edit(identity, ['DELETE FROM action_signatures WHERE id = (SELECT MAX(id) FROM action_signatures)'])
    result = verify(client)
    assert result['signatures']['valid'] is False
    assert result['signatures']['problems'][0]['reason'] == 'delegate action has no signature'


def test_swapped_public_key_is_detected(ctx):
    client, _, identity, _ = ctx
    delegate_acts(client)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    import base64
    import hashlib
    fake = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    raw_edit(identity, [
        f"UPDATE delegate_keys SET public_key = '{base64.b64encode(fake).decode()}', fingerprint = '{hashlib.sha256(fake).hexdigest()}' "
        "WHERE user_id = (SELECT id FROM users WHERE username = 'delegate')"
    ])
    result = verify(client)
    assert result['signatures']['valid'] is False
    assert 'does not match the key registered' in result['signatures']['problems'][0]['reason']


def test_database_blocks_changes_to_signatures_and_keys(ctx):
    client, app, _, _ = ctx
    delegate_acts(client)
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    with app.app_context():
        for sql in ("UPDATE action_signatures SET signature = 'x'", 'DELETE FROM action_signatures',
                    "UPDATE delegate_keys SET public_key = 'x'", 'DELETE FROM delegate_keys'):
            with pytest.raises(DatabaseError):
                db.session.execute(text(sql))
            db.session.rollback()


def test_third_party_can_verify_one_action_offline(ctx):
    client, app, _, directory = ctx
    delegate_acts(client)
    auditor = login(client, 'auditor', 'auditor1234')
    with app.app_context():
        event_id = AuditEvent.query.filter_by(action='election.status').one().id
    proof = client.get(f'/api/audit/{event_id}/proof', headers=auditor)
    assert proof.status_code == 200
    path = os.path.join(directory, 'proof.json')
    json.dump(proof.get_json(), open(path, 'w'))
    script = os.path.join(ROOT, 'scripts', 'verify_proof.py')

    ok = subprocess.run([sys.executable, script, path], capture_output=True, text=True)
    assert ok.returncode == 0 and 'delegate "delegate2"' in ok.stdout  # delegate2 approved, so delegate2 signed the execution

    forged = proof.get_json()
    forged['event']['detail'] = 'closed -> open'
    json.dump(forged, open(path, 'w'))
    bad = subprocess.run([sys.executable, script, path], capture_output=True, text=True)
    assert bad.returncode == 1 and 'FAIL' in bad.stdout


def test_only_the_auditor_can_ask_for_a_proof(ctx):
    client, _, _, _ = ctx
    delegate_acts(client)
    assert client.get('/api/audit/1/proof').status_code == 401
    assert client.get('/api/audit/1/proof', headers=login(client, 'voter', 'voter1234')).status_code == 403
    assert client.get('/api/audit/999999/proof', headers=login(client, 'auditor', 'auditor1234')).status_code == 404
