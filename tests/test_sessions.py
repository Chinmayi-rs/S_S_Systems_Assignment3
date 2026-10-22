"""GR-02: 15-minute inactivity timeout and server-side revocation for every endpoint."""
import os
import tempfile
from datetime import datetime, timedelta

import pyotp
import pytest
from flask_jwt_extended import create_access_token

from app import create_app, db
from app.models.session import UserSession
from app.models.user import User
from app.services.seed import deterministic_totp_secret


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


def login(client, username, password):
    code = pyotp.TOTP(deterministic_totp_secret(username)).now()
    res = client.post('/api/auth/login', json={'username': username, 'password': password, 'totp_code': code})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def backdate_sessions(app, username, minutes):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        UserSession.query.filter_by(user_id=user.id).update(
            {'last_seen': datetime.utcnow() - timedelta(minutes=minutes)}
        )
        db.session.commit()


def test_idle_session_is_rejected_on_every_endpoint(ctx):
    client, app = ctx
    headers = login(client, 'voter', 'voter1234')
    assert client.get('/api/auth/profile', headers=headers).status_code == 200

    backdate_sessions(app, 'voter', 16)

    expired = client.get('/api/auth/profile', headers=headers)
    assert expired.status_code == 401
    assert 'expired' in expired.get_json()['error'].lower()
    # The same dead token is refused everywhere, not just on one route.
    assert client.get('/api/ballots/status', headers=headers).status_code == 401
    assert client.post('/api/ballots/issue', headers=headers).status_code == 401

    with app.app_context():
        user = User.query.filter_by(username='voter').first()
        session = UserSession.query.filter_by(user_id=user.id).first()
        assert session.revoked is True
        assert session.revoked_reason == 'idle_timeout'


def test_activity_slides_the_inactivity_window(ctx):
    client, app = ctx
    headers = login(client, 'voter', 'voter1234')
    backdate_sessions(app, 'voter', 10)

    # 10 idle minutes is inside the window; the request succeeds and resets the clock.
    assert client.get('/api/auth/profile', headers=headers).status_code == 200
    with app.app_context():
        user = User.query.filter_by(username='voter').first()
        session = UserSession.query.filter_by(user_id=user.id).first()
        assert datetime.utcnow() - session.last_seen < timedelta(minutes=1)


def test_privileged_sessions_time_out_too(ctx):
    client, app = ctx
    headers = login(client, 'delegate', 'delegate1234')
    assert client.get('/api/approvals', headers=headers).status_code == 200
    backdate_sessions(app, 'delegate', 16)
    assert client.get('/api/approvals', headers=headers).status_code == 401


def test_logout_revokes_the_token_server_side(ctx):
    client, _ = ctx
    headers = login(client, 'voter', 'voter1234')
    assert client.post('/api/auth/logout', headers=headers).status_code == 200
    # The JWT itself has not expired, but the session behind it is gone.
    assert client.get('/api/auth/profile', headers=headers).status_code == 401


def test_token_without_a_session_row_is_rejected(ctx):
    client, app = ctx
    with app.app_context():
        user = User.query.filter_by(username='voter').first()
        orphan = create_access_token(identity=str(user.id), additional_claims={'role': user.role})
    headers = {'Authorization': 'Bearer ' + orphan}
    # A structurally valid JWT that the session store never issued is refused.
    assert client.get('/api/auth/profile', headers=headers).status_code == 401


def test_staff_accounts_require_mfa(ctx):
    client, app = ctx
    # GR-02: privileged users cannot hold a session without a second factor.
    with app.app_context():
        user = User.query.filter_by(username='officer').first()
        user.mfa_enabled = False
        db.session.commit()
    res = client.post('/api/auth/login', json={'username': 'officer', 'password': 'officer1234'})
    assert res.status_code == 200
    body = res.get_json()
    assert body['mfa_setup_required'] is True
    provisional = {'Authorization': 'Bearer ' + body['access_token']}
    # Until enrolment finishes the officer cannot reach officer endpoints.
    assert client.get('/api/enrolment/voters', headers=provisional).status_code == 403
