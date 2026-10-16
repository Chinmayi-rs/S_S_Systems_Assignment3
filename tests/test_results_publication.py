"""GR-13 Signed publication of the final results."""
import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app import create_app, db
from app.models.approval import PendingApproval
from app.models.audit import AuditEvent
from app.models.published_result import PublishedResult, ResultsKey
from app.services import results_publication

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'verify_results.py')


def load_script():
    spec = importlib.util.spec_from_file_location('verify_results_script', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def ctx():
    directory = tempfile.mkdtemp()
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'identity.db')
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client, app, directory


def login(client, username, password):
    res = client.post('/api/auth/login', json={'username': username, 'password': password})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def two_delegates(client):
    return login(client, 'delegate', 'delegate1234'), login(client, 'delegate2', 'delegate21234')


def approver_id(client, headers, username='delegate2'):
    delegates = client.get('/api/approvals/delegates', headers=headers).get_json()['delegates']
    return next(d['id'] for d in delegates if d['username'] == username)


def propose(client, headers, body_extra, approver='delegate2'):
    body = {**body_extra, 'approver_id': approver_id(client, headers, approver)}
    return client.post('/api/approvals', json=body, headers=headers)


def close_poll(client, first, second):
    res = propose(client, first, {'action_type': 'election.status', 'status': 'closed'})
    assert res.status_code == 201, res.get_json()
    assert client.post(f"/api/approvals/{res.get_json()['approval']['id']}/approve", headers=second).status_code == 200


def propose_release(client, headers, approver='delegate2'):
    return propose(client, headers, {'action_type': 'results.release'}, approver)


def publish_results(client, first, second):
    close_poll(client, first, second)
    res = propose_release(client, first)
    assert res.status_code == 201, res.get_json()
    done = client.post(f"/api/approvals/{res.get_json()['approval']['id']}/approve", headers=second)
    assert done.status_code == 200, done.get_json()
    return res.get_json()['approval']['id']


def cast_one_ballot(client):
    headers = login(client, 'voter', 'voter1234')
    catalogue = client.get('/api/candidates').get_json()['candidates']
    house = [row['id'] for row in catalogue if row['chamber'] == 'house']
    senate = next(row['party'] for row in catalogue if row['chamber'] == 'senate')
    token = client.post('/api/ballots/issue', headers=headers).get_json()['token']
    assert client.post('/api/ballots/stage', json={'token': token, 'house': house, 'senate_party': senate},
                       headers=headers).status_code == 200
    assert client.post('/api/ballots/commit', json={'token': token}, headers=headers).status_code == 201
    return house[0]


def verification_inputs(client, directory):
    """Save the three files a third party would download, exactly as the Results page does."""
    published = client.get('/api/results').get_json()
    key = client.get('/api/results/public-key').get_json()
    paths = {name: os.path.join(directory, name) for name in ('results.json', 'results.sig.json', 'results.pub.json')}
    with open(paths['results.json'], 'w', encoding='utf-8') as handle:
        handle.write(published['signed_document'])
    with open(paths['results.sig.json'], 'w', encoding='utf-8') as handle:
        json.dump({
            'algorithm': published['signature']['algorithm'],
            'signed_message_prefix': published['signature']['signed_message_prefix'],
            'sha256': published['signature']['sha256'],
            'signature': published['signature']['value'],
            'key_fingerprint': published['signature']['key_fingerprint'],
        }, handle)
    with open(paths['results.pub.json'], 'w', encoding='utf-8') as handle:
        json.dump(key, handle)
    return paths, key


# ---- who may publish ---------------------------------------------------------------------------

def test_one_delegate_cannot_publish_alone(ctx):
    client, app, _ = ctx
    first, second = two_delegates(client)
    close_poll(client, first, second)
    approval_id = propose_release(client, first).get_json()['approval']['id']

    assert client.post(f'/api/approvals/{approval_id}/approve', headers=first).status_code == 403  # the proposer
    assert client.get('/api/results').status_code == 403                                           # still hidden
    with app.app_context():
        assert PublishedResult.query.count() == 0
        assert db.session.get(PendingApproval, approval_id).status == 'proposed'
        assert AuditEvent.query.filter_by(action='approval.self_approval_blocked').count() == 1

    assert client.post(f'/api/approvals/{approval_id}/approve', headers=second).status_code == 200
    assert client.get('/api/results').status_code == 200


def test_only_delegates_can_propose_a_release(ctx):
    client, _, _ = ctx
    first, second = two_delegates(client)
    close_poll(client, first, second)
    body = {'action_type': 'results.release'}
    for user, password in (('voter', 'voter1234'), ('officer', 'officer1234'), ('auditor', 'auditor1234')):
        assert client.post('/api/approvals', json=body, headers=login(client, user, password)).status_code == 403
    assert client.post('/api/approvals', json=body).status_code == 401


def test_a_waiting_release_blocks_every_other_release_request(ctx):
    client, _, _ = ctx
    first, second = two_delegates(client)
    close_poll(client, first, second)
    assert propose_release(client, first).status_code == 201
    assert propose_release(client, second, approver='delegate').status_code == 409
    assert propose_release(client, first).status_code == 409


def test_release_needs_a_closed_poll(ctx):
    client, _, _ = ctx
    first, _ = two_delegates(client)
    refused = propose_release(client, first)
    assert refused.status_code == 409
    assert 'Close the poll' in refused.get_json()['error']


# ---- nothing leaks before publication ----------------------------------------------------------

def test_closed_but_unpublished_results_stay_hidden_from_outsiders(ctx):
    client, _, _ = ctx
    first, second = two_delegates(client)

    # open poll
    assert client.get('/api/results').status_code == 403
    close_poll(client, first, second)

    # closed poll, not published: closing is no longer publishing
    assert client.get('/api/results').status_code == 403
    assert client.get('/api/results/public-key').status_code == 403
    assert client.get('/api/results/verify').status_code == 403
    assert client.get('/api/results', headers=login(client, 'voter', 'voter1234')).status_code == 403
    assert client.get('/api/results', headers=login(client, 'officer', 'officer1234')).status_code == 403

    # delegate and auditor still see a preview
    for headers in (first, login(client, 'auditor', 'auditor1234')):
        body = client.get('/api/results', headers=headers).get_json()
        assert body['preview'] is True and body['published'] is False
        assert 'signature' not in body and 'signed_document' not in body
        assert client.get('/api/results/public-key', headers=headers).status_code == 404


def test_hidden_response_does_not_contain_any_count(ctx):
    client, _, _ = ctx
    cast_one_ballot(client)
    res = client.get('/api/results')
    assert res.status_code == 403
    assert set(res.get_json()) == {'error'}


# ---- the signed result -------------------------------------------------------------------------

def test_published_result_is_signed_and_checks_with_the_public_key(ctx):
    client, _, _ = ctx
    first_choice = cast_one_ballot(client)
    first, second = two_delegates(client)
    publish_results(client, first, second)

    body = client.get('/api/results').get_json()  # no login at all
    assert body['preview'] is False and body['published'] is True
    assert body['total_ballots'] == 1
    assert next(row for row in body['house'] if row['id'] == first_choice)['votes'] == 1
    assert body['publication']['proposed_by'] == 'delegate' and body['publication']['approved_by'] == 'delegate2'
    assert body['signature']['algorithm'] == 'Ed25519'

    key = client.get('/api/results/public-key').get_json()
    assert key['fingerprint'] == body['signature']['key_fingerprint']
    raw_public = base64.b64decode(key['public_key'])
    assert hashlib.sha256(raw_public).hexdigest() == key['fingerprint']

    # check it the way an outsider would, without the app's own code
    digest = hashlib.sha256(body['signed_document'].encode('utf-8')).hexdigest()
    assert digest == body['signature']['sha256']
    message = b'BALLOTDESK-RESULTS-v1|' + digest.encode('ascii')
    Ed25519PublicKey.from_public_bytes(raw_public).verify(base64.b64decode(body['signature']['value']), message)

    # one changed number and the signature no longer matches
    tampered = body['signed_document'].replace('"total_ballots":1', '"total_ballots":2')
    assert tampered != body['signed_document']
    tampered_digest = hashlib.sha256(tampered.encode('utf-8')).hexdigest()
    with pytest.raises(InvalidSignature):
        Ed25519PublicKey.from_public_bytes(raw_public).verify(
            base64.b64decode(body['signature']['value']), b'BALLOTDESK-RESULTS-v1|' + tampered_digest.encode('ascii'))

    verified = client.get('/api/results/verify').get_json()
    assert verified['valid'] is True and all(verified['checks'].values())


def test_signature_is_bound_to_the_audit_log_and_to_both_people(ctx):
    client, app, _ = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    document = json.loads(client.get('/api/results').get_json()['signed_document'])

    with app.app_context():
        release = AuditEvent.query.filter_by(action='results.release').one()
        registered = AuditEvent.query.filter_by(action='results.key.registered').one()
        assert release.actor_username == 'delegate2'
        assert 'proposed by delegate' in release.detail and 'approved by delegate2' in release.detail
        # the log head written into the result is a real entry that came before the release
        head = AuditEvent.query.filter_by(entry_hash=document['publication']['audit_head_hash']).one()
        assert head.id < release.id
        assert json.loads(registered.detail)['fingerprint'] == ResultsKey.query.one().fingerprint
        assert registered.actor_username == 'delegate2'


def test_the_results_key_is_separate_from_the_delegate_keys(ctx):
    client, app, _ = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    with app.app_context():
        from app.models.signing import DelegateKey
        results_key = ResultsKey.query.one()
        assert results_key.fingerprint not in {k.fingerprint for k in DelegateKey.query.all()}
        # the private key is stored sealed, never as plain text
        assert 'PRIVATE' not in results_key.private_key_enc
        assert len(base64.b64decode(results_key.private_key_enc)) > 32


def test_audit_chain_and_delegate_signatures_stay_valid(ctx):
    client, _, _ = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    result = client.get('/api/audit/verify', headers=login(client, 'auditor', 'auditor1234')).get_json()
    assert result['chain_valid'] is True
    assert result['signatures']['valid'] is True
    assert result['valid'] is True


# ---- only once, and never changed --------------------------------------------------------------

def test_results_cannot_be_published_twice(ctx):
    client, app, _ = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    again = propose_release(client, first)
    assert again.status_code == 409
    assert 'already published' in again.get_json()['error']
    with app.app_context():
        assert PublishedResult.query.count() == 1
        duplicate = PublishedResult.query.one()
        copy = PublishedResult(
            election_id=duplicate.election_id, result_json='{}', sha256='0' * 64, signature='x', key_id=duplicate.key_id,
            key_fingerprint=duplicate.key_fingerprint, approval_id=duplicate.approval_id,
            proposer_id=duplicate.proposer_id, approver_id=duplicate.approver_id, published_at=duplicate.published_at)
        db.session.add(copy)
        with pytest.raises(IntegrityError):  # the database allows one result per election
            db.session.flush()
        db.session.rollback()


def test_database_refuses_to_change_or_delete_a_published_result(ctx):
    client, app, _ = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    with app.app_context():
        for statement in (
            "UPDATE published_results SET result_json = '{}'",
            'DELETE FROM published_results',
            "UPDATE results_keys SET public_key = 'x'",
            'DELETE FROM results_keys',
        ):
            with pytest.raises(DatabaseError):
                db.session.execute(text(statement))
            db.session.rollback()
        assert PublishedResult.query.count() == 1


def test_the_poll_cannot_be_reopened_after_publication(ctx):
    client, _, _ = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    refused = propose(client, first, {'action_type': 'election.status', 'status': 'open'})
    assert refused.status_code == 409
    assert 'published' in refused.get_json()['error']


def test_a_release_waiting_when_the_poll_is_reopened_cannot_run(ctx):
    client, app, _ = ctx
    first, second = two_delegates(client)
    close_poll(client, first, second)
    release_id = propose_release(client, first).get_json()['approval']['id']
    reopen = propose(client, second, {'action_type': 'election.status', 'status': 'open'}, approver='delegate')
    assert reopen.status_code == 201
    assert client.post(f"/api/approvals/{reopen.get_json()['approval']['id']}/approve", headers=first).status_code == 200

    assert client.post(f'/api/approvals/{release_id}/approve', headers=second).status_code == 409
    with app.app_context():
        assert PublishedResult.query.count() == 0
        assert db.session.get(PendingApproval, release_id).status == 'proposed'  # undone, not half-done


# ---- GR-12 plug-in point -----------------------------------------------------------------------

def test_publication_is_refused_when_the_counters_disagree(ctx, monkeypatch):
    client, app, _ = ctx
    first, second = two_delegates(client)
    close_poll(client, first, second)
    release_id = propose_release(client, first).get_json()['approval']['id']
    monkeypatch.setattr(results_publication, 'counts_agree', lambda election: False)

    refused = client.post(f'/api/approvals/{release_id}/approve', headers=second)
    assert refused.status_code == 409
    assert 'do not agree' in refused.get_json()['error']
    assert client.get('/api/results').status_code == 403
    with app.app_context():
        assert PublishedResult.query.count() == 0
        assert ResultsKey.query.count() == 0  # not even a key was left behind
        assert AuditEvent.query.filter_by(action='results.release').count() == 0


def test_counts_agree_is_a_placeholder_that_says_yes():
    assert results_publication.counts_agree(None) is True


# ---- a changed stored result is noticed --------------------------------------------------------

def test_verify_endpoint_notices_a_result_changed_behind_the_apps_back(ctx):
    client, app, directory = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    assert client.get('/api/results/verify').get_json()['valid'] is True

    with app.app_context():
        # someone with raw database access removes the guard and edits the stored result
        db.session.execute(text('DROP TRIGGER published_results_no_update'))
        db.session.execute(text("UPDATE published_results SET result_json = replace(result_json, 'first-preference', 'fixed-by-someone')"))
        db.session.commit()

    checked = client.get('/api/results/verify').get_json()
    assert checked['valid'] is False
    assert checked['checks']['hash_matches'] is False


# ---- the offline script ------------------------------------------------------------------------

def test_offline_script_accepts_the_real_result_and_rejects_a_changed_one(ctx):
    client, _, directory = ctx
    cast_one_ballot(client)
    first, second = two_delegates(client)
    publish_results(client, first, second)
    paths, key = verification_inputs(client, directory)
    script = load_script()
    args = [paths['results.json'], paths['results.sig.json'], paths['results.pub.json']]

    assert script.main(args) == 0
    assert script.main(args + ['--fingerprint', key['fingerprint']]) == 0
    assert script.main(args + ['--fingerprint', 'a' * 64]) == 1  # not the key we trust

    # a base64 key on its own (no JSON) works too
    raw_key = os.path.join(directory, 'results.pub.txt')
    with open(raw_key, 'w', encoding='utf-8') as handle:
        handle.write(key['public_key'])
    assert script.main([args[0], args[1], raw_key]) == 0

    # change one vote in the file
    original = open(paths['results.json'], encoding='utf-8').read()
    tampered = original.replace('"votes":1', '"votes":9', 1)
    assert tampered != original
    with open(paths['results.json'], 'w', encoding='utf-8') as handle:
        handle.write(tampered)
    assert script.main(args) == 1

    # a signature made for a different message does not pass even if the hash is "fixed" to match
    sig = json.load(open(paths['results.sig.json'], encoding='utf-8'))
    sig['sha256'] = hashlib.sha256(script._canonical(json.loads(tampered))).hexdigest()
    with open(paths['results.sig.json'], 'w', encoding='utf-8') as handle:
        json.dump(sig, handle)
    assert script.main(args) == 1


def test_offline_script_runs_as_a_command_and_sets_the_exit_code(ctx):
    client, _, directory = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    paths, _ = verification_inputs(client, directory)
    args = [sys.executable, SCRIPT, paths['results.json'], paths['results.sig.json'], paths['results.pub.json']]
    ok = subprocess.run(args, capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.startswith('OK')
    with open(paths['results.json'], 'a', encoding='utf-8') as handle:
        handle.write('garbage')
    bad = subprocess.run(args, capture_output=True, text=True)
    assert bad.returncode == 1 and bad.stdout.startswith('FAIL')


def test_offline_script_rejects_a_repeated_key_in_the_result(ctx):
    client, _, directory = ctx
    first, second = two_delegates(client)
    publish_results(client, first, second)
    paths, _ = verification_inputs(client, directory)
    original = open(paths['results.json'], encoding='utf-8').read()
    with open(paths['results.json'], 'w', encoding='utf-8') as handle:
        handle.write(original.replace('"method":', '"method":"x","method":', 1))
    assert load_script().main([paths['results.json'], paths['results.sig.json'], paths['results.pub.json']]) == 1
