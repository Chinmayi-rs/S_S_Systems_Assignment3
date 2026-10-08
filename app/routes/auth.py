from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token

from app import db
from app.models.user import User
from app.services.audit_log import append_audit
from app.utils.constants import ROLES
from app.utils.helpers import json_error, validate_required_fields
from app.utils.rbac import require_login

auth_bp = Blueprint('auth', __name__)


def _token_for(user):
    return create_access_token(
        identity=str(user.id),
        additional_claims={'role': user.role},
    )


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
    db.session.commit()

    return jsonify({
        'message': 'Account created. An enrolment officer still needs to verify eligibility.',
        'user': user.to_dict(),
        'access_token': _token_for(user),
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    ok, message = validate_required_fields(data, ['username', 'password'])
    if not ok:
        return json_error(message, 400)

    username = data['username'].strip()
    password = data['password']
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        append_audit('auth.login_failed', f'Failed sign-in for {username}')
        db.session.commit()
        return json_error('Invalid username or password', 401)
    if not user.is_active:
        return json_error('This account is disabled', 401)

    append_audit('auth.login', 'Signed in', actor=user)
    db.session.commit()
    return jsonify({
        'message': 'Login successful',
        'user': user.to_dict(),
        'access_token': _token_for(user),
    }), 200


@auth_bp.route('/profile', methods=['GET'])
@require_login
def profile(current_user):
    return jsonify({'user': current_user.to_dict()}), 200


@auth_bp.route('/logout', methods=['POST'])
@require_login
def logout(current_user):
    append_audit('auth.logout', 'Signed out', actor=current_user)
    db.session.commit()
    return jsonify({'message': 'Logged out'}), 200
