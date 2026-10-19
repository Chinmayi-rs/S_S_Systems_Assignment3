from datetime import datetime, timedelta

import pyotp
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt

from app import db
from app.models.user import User
from app.services.audit_log import append_audit
from app.services.sessions import issue_mfa_setup_token, issue_session_token, revoke_session
from app.utils.constants import ROLES
from app.utils.helpers import json_error, qr_data_uri, validate_required_fields
from app.utils.rbac import require_login, require_mfa_setup_token

auth_bp = Blueprint('auth', __name__)

TOTP_ISSUER = 'Ballot Desk'


def _failed_attempt(user, reason, message):
    """GR-01: count a consecutive failure, lock on the 5th, log everything."""
    user.failed_logins += 1
    append_audit('auth.login_failed', f'Failed sign-in for {user.username} ({reason})')
    threshold = current_app.config['LOGIN_LOCKOUT_THRESHOLD']
    if user.failed_logins >= threshold:
        minutes = current_app.config['LOGIN_LOCKOUT_MINUTES']
        user.locked_until = datetime.utcnow() + timedelta(minutes=minutes)
        user.failed_logins = 0
        append_audit(
            'auth.lockout',
            f'{user.username} locked for {minutes} minutes after {threshold} consecutive failures',
        )
    db.session.commit()
    return json_error(message, 401)


def _mfa_setup_response(user, status=200):
    """Password is right but TOTP is not enrolled yet: hand out the
    provisional token that can only call the /mfa endpoints (GR-01)."""
    token = issue_mfa_setup_token(user)
    db.session.commit()
    return jsonify({
        'mfa_setup_required': True,
        'access_token': token,
        'user': user.to_dict(),
        'message': 'Scan the QR code with your authenticator app to finish setting up sign-in.',
    }), status


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    ok, message = validate_required_fields(
        data, ['username', 'email', 'password', 'full_name', 'date_of_birth', 'address', 'division']
    )
    if not ok:
        return json_error(message, 400)

    username = data['username'].strip()
    email = data['email'].strip().lower()
    password = data['password']
    full_name = data['full_name'].strip()
    division = data['division'].strip()

    if len(username) < 3:
        return json_error('Username must be at least 3 characters', 400)
    if len(password) < 8:
        return json_error('Password must be at least 8 characters', 400)
    if '@' not in email:
        return json_error('Enter a valid email address', 400)
    role = data.get('role') or 'voter'
    if role not in ROLES:
        return json_error('Unknown role', 400)
    # Self-service registration is voters only. Staff accounts are seeded.
    if role != 'voter':
        return json_error('Only voter accounts can be registered here', 403)

    if User.query.filter_by(username=username).first():
        return json_error('Username already exists', 409)
    if User.query.filter_by(email=email).first():
        return json_error('Email already registered', 409)

    user = User(
        username=username,
        email=email,
        password=password,
        full_name=full_name,
        role='voter',
        date_of_birth=data['date_of_birth'].strip(),
        address=data['address'].strip(),
        division=division,
        enrolled=False,
        eligible=False,
    )
    db.session.add(user)
    append_audit('enrolment.requested', f'New voter account {username}', actor=None)
    db.session.flush()
    # GR-01: no session until the second factor is enrolled.
    return _mfa_setup_response(user, status=201)


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    ok, message = validate_required_fields(data, ['username', 'password'])
    if not ok:
        return json_error(message, 400)

    username = data['username'].strip()
    password = data['password']
    user = User.query.filter_by(username=username).first()
    if not user:
        append_audit('auth.login_failed', f'Failed sign-in for {username} (unknown username)')
        db.session.commit()
        return json_error('Invalid username or password', 401)

    now = datetime.utcnow()
    if user.locked_until and user.locked_until <= now:
        # The lock has run out; the counter starts fresh.
        user.locked_until = None
        user.failed_logins = 0

    if user.locked_until:
        minutes_left = int((user.locked_until - now).total_seconds() // 60) + 1
        append_audit('auth.login_blocked', f'Sign-in attempt while {username} is locked')
        db.session.commit()
        return json_error(
            f'Account locked after repeated failures. Try again in {minutes_left} minute(s).', 423
        )

    if not user.check_password(password):
        return _failed_attempt(user, 'wrong password', 'Invalid username or password')

    if not user.is_active:
        append_audit('auth.login_failed', f'Sign-in for disabled account {username}')
        db.session.commit()
        return json_error('This account is disabled', 401)

    if not user.mfa_enabled:
        return _mfa_setup_response(user)

    code = (data.get('totp_code') or '').strip()
    if not code:
        # Password accepted, waiting on the second factor. Not a failure.
        db.session.commit()
        return jsonify({
            'mfa_required': True,
            'message': 'Enter the 6-digit code from your authenticator app.',
        }), 200

    if not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        return _failed_attempt(user, 'wrong authenticator code', 'Invalid authenticator code')

    user.failed_logins = 0
    user.locked_until = None
    token = issue_session_token(user)
    append_audit('auth.login', 'Signed in', actor=user)
    db.session.commit()
    return jsonify({
        'message': 'Login successful',
        'user': user.to_dict(),
        'access_token': token,
    }), 200


@auth_bp.route('/mfa/setup', methods=['POST'])
@require_mfa_setup_token
def mfa_setup(current_user):
    if current_user.mfa_enabled:
        return json_error('Two-factor authentication is already enabled for this account', 409)
    if not current_user.totp_secret:
        current_user.totp_secret = pyotp.random_base32()
    uri = pyotp.TOTP(current_user.totp_secret).provisioning_uri(
        name=current_user.username, issuer_name=TOTP_ISSUER
    )
    append_audit('auth.mfa_setup', f'TOTP enrolment started for {current_user.username}')
    db.session.commit()
    return jsonify({
        'secret': current_user.totp_secret,
        'otpauth_uri': uri,
        'qr': qr_data_uri(uri),
    }), 200


@auth_bp.route('/mfa/enable', methods=['POST'])
@require_mfa_setup_token
def mfa_enable(current_user):
    if current_user.mfa_enabled:
        return json_error('Two-factor authentication is already enabled for this account', 409)
    if not current_user.totp_secret:
        return json_error('Request a QR code from /api/auth/mfa/setup first', 400)
    data = request.get_json(silent=True) or {}
    code = (data.get('totp_code') or '').strip()
    if not code or not pyotp.TOTP(current_user.totp_secret).verify(code, valid_window=1):
        append_audit('auth.mfa_enable_failed', f'Wrong enrolment code for {current_user.username}')
        db.session.commit()
        return json_error('That code does not match. Check your authenticator app and try again.', 400)

    current_user.mfa_enabled = True
    current_user.failed_logins = 0
    current_user.locked_until = None
    # Both factors were just proven (password at login, TOTP here),
    # so a full session starts now.
    token = issue_session_token(current_user)
    append_audit('auth.mfa_enabled', f'TOTP enabled for {current_user.username}', actor=current_user)
    db.session.commit()
    return jsonify({
        'message': 'Two-factor authentication enabled',
        'access_token': token,
        'user': current_user.to_dict(),
    }), 200


@auth_bp.route('/profile', methods=['GET'])
@require_login
def profile(current_user):
    return jsonify({'user': current_user.to_dict()}), 200


@auth_bp.route('/logout', methods=['POST'])
@require_login
def logout(current_user):
    # GR-02: the session dies server-side; the JWT is useless afterwards.
    revoke_session(get_jwt().get('jti'))
    append_audit('auth.logout', 'Signed out', actor=current_user)
    db.session.commit()
    return jsonify({'message': 'Logged out'}), 200
