"""GR-01: password + TOTP authentication, Argon2 hashing, lockout, attempt logging."""
import os
import tempfile
from datetime import datetime, timedelta

import bcrypt
import pyotp
import pytest

from app import create_app, db
from app.models.audit import AuditEvent
from app.models.user import User
from app.services.seed import deterministic_totp_secret

NEW_VOTER = {
    'username': 'freshvoter',
    'email': 'fresh@example.test',
    'password': 'fresh12345',
    'full_name': 'Fresh Voter',
    'date_of_birth': '1999-09-09',
    'address': '9 New Street, Carlton',
    'division': 'Melbourne',
}


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
        yield client, app


def totp_now(username):
    return pyotp.TOTP(deterministic_totp_secret(username)).now()


def login_payload(username, password, with_code=True):
    payload = {'username': username, 'password': password}
    if with_code:
        payload['totp_code'] = totp_now(username)
    return payload


def test_new_password_hashes_are_argon2(ctx):
    client, app = ctx
    assert client.post('/api/auth/register', json=NEW_VOTER).status_code == 201
    with app.app_context():
        user = User.query.filter_by(username='freshvoter').first()
        assert user.password_hash.startswith('$argon2')


def test_legacy_bcrypt_hash_verifies_and_upgrades_on_login(ctx):
    client, app = ctx
    with app.app_context():
        user = User.query.filter_by(username='voter').first()
        user.password_hash = bcrypt.hashpw(b'voter1234', bcrypt.gensalt()).decode('utf-8')
        db.session.commit()
        assert not user.password_hash.startswith('$argon2')

    response = client.post('/api/auth/login', json=login_payload('voter', 'voter1234'))
    assert response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(username='voter').first()
        assert user.password_hash.startswith('$argon2')


def test_password_alone_is_never_enough(ctx):
    client, _ = ctx
    response = client.post('/api/auth/login', json=login_payload('voter', 'voter1234', with_code=False))
    assert response.status_code == 200
    body = response.get_json()
    assert body['mfa_required'] is True
    assert 'access_token' not in body


def test_wrong_totp_code_is_rejected_and_logged(ctx):
    client, app = ctx
    response = client.post(
        '/api/auth/login',
        json={'username': 'voter', 'password': 'voter1234', 'totp_code': '000000'},
    )
    assert response.status_code == 401
    with app.app_context():
        failure = AuditEvent.query.filter_by(action='auth.login_failed').order_by(AuditEvent.id.desc()).first()
        assert failure is not None
        assert 'voter' in failure.detail and 'authenticator' in failure.detail


def test_lockout_after_five_failures_rejects_even_correct_credentials(ctx):
    client, app = ctx
    for _ in range(5):
        response = client.post('/api/auth/login', json={'username': 'voter', 'password': 'wrong-pass'})
        assert response.status_code == 401

    # The unit test the group plan asks for: a correct sign-in is still refused.
    response = client.post('/api/auth/login', json=login_payload('voter', 'voter1234'))
    assert response.status_code == 423
    assert 'locked' in response.get_json()['error'].lower()

    with app.app_context():
        assert AuditEvent.query.filter_by(action='auth.lockout').count() == 1
        user = User.query.filter_by(username='voter').first()
        assert user.locked_until is not None


def test_wrong_totp_codes_count_toward_lockout(ctx):
    client, _ = ctx
    for _ in range(5):
        response = client.post(
            '/api/auth/login',
            json={'username': 'voter', 'password': 'voter1234', 'totp_code': '000000'},
        )
        assert response.status_code == 401
    response = client.post('/api/auth/login', json=login_payload('voter', 'voter1234'))
    assert response.status_code == 423


def test_lock_expires_after_the_window(ctx):
    client, app = ctx
    for _ in range(5):
        client.post('/api/auth/login', json={'username': 'voter', 'password': 'wrong-pass'})
    with app.app_context():
        user = User.query.filter_by(username='voter').first()
        user.locked_until = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
    response = client.post('/api/auth/login', json=login_payload('voter', 'voter1234'))
    assert response.status_code == 200


def test_registration_requires_totp_enrolment_before_any_access(ctx):
    client, app = ctx
    created = client.post('/api/auth/register', json=NEW_VOTER)
    assert created.status_code == 201
    body = created.get_json()
    assert body['mfa_setup_required'] is True
    provisional = {'Authorization': 'Bearer ' + body['access_token']}

    # The provisional token is not a session: no profile, no ballot, no admin.
    assert client.get('/api/auth/profile', headers=provisional).status_code == 403
    assert client.get('/api/ballots/status', headers=provisional).status_code == 403
    assert client.post('/api/candidates', json={}, headers=provisional).status_code == 403

    setup = client.post('/api/auth/mfa/setup', headers=provisional)
    assert setup.status_code == 200
    payload = setup.get_json()
    assert payload['qr'].startswith('data:image/svg+xml;base64,')
    assert payload['otpauth_uri'].startswith('otpauth://totp/')

    wrong = client.post('/api/auth/mfa/enable', json={'totp_code': '000000'}, headers=provisional)
    assert wrong.status_code == 400

    code = pyotp.TOTP(payload['secret']).now()
    enabled = client.post('/api/auth/mfa/enable', json={'totp_code': code}, headers=provisional)
    assert enabled.status_code == 200
    full = {'Authorization': 'Bearer ' + enabled.get_json()['access_token']}
    assert client.get('/api/auth/profile', headers=full).status_code == 200

    with app.app_context():
        user = User.query.filter_by(username='freshvoter').first()
        assert user.mfa_enabled is True

    # From now on password-only sign-ins only get the TOTP prompt.
    again = client.post('/api/auth/login', json={'username': 'freshvoter', 'password': 'fresh12345'})
    assert again.status_code == 200
    assert again.get_json()['mfa_required'] is True


def test_every_attempt_lands_in_the_audit_log(ctx):
    client, app = ctx
    client.post('/api/auth/login', json={'username': 'ghost', 'password': 'nope'})
    client.post('/api/auth/login', json={'username': 'voter', 'password': 'nope'})
    client.post('/api/auth/login', json=login_payload('voter', 'voter1234'))
    with app.app_context():
        actions = [event.action for event in AuditEvent.query.order_by(AuditEvent.id).all()]
        assert actions.count('auth.login_failed') >= 2
        assert 'auth.login' in actions
