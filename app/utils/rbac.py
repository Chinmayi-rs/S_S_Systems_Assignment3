from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required, verify_jwt_in_request

from app.models.user import User
from app.utils.constants import (
    ROLE_AUDITOR,
    ROLE_DELEGATE,
    ROLE_OFFICER,
    ROLE_VOTER,
)

# Single place for who may do what. GR-03 grows this map; routes should not
# hard-code roles of their own.
PERMISSIONS = {
    'enrolment.review': {ROLE_OFFICER},
    'enrolment.verify': {ROLE_OFFICER},
    'enrolment.address': {ROLE_VOTER},
    'candidate.write': {ROLE_DELEGATE},
    'election.status': {ROLE_DELEGATE},
    'ballot.cast': {ROLE_VOTER},
    'audit.read': {ROLE_AUDITOR},
    'results.preview': {ROLE_DELEGATE, ROLE_AUDITOR},
}


def _active_user():
    identity = get_jwt_identity()
    if identity is None:
        return None
    user = User.query.get(int(identity))
    if not user or not user.is_active:
        return None
    return user


def require_login(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = _active_user()
        if not user:
            return jsonify({'error': 'Access denied'}), 403
        return fn(*args, current_user=user, **kwargs)

    return wrapper


def require_permission(permission):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            user = _active_user()
            if not user:
                return jsonify({'error': 'Access denied'}), 403
            allowed = PERMISSIONS.get(permission, set())
            if user.role not in allowed:
                return jsonify({'error': 'You do not have permission for this action'}), 403
            return fn(*args, current_user=user, **kwargs)

        return wrapper

    return decorator


def optional_user():
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return None
    identity = get_jwt_identity()
    if not identity:
        return None
    user = User.query.get(int(identity))
    if not user or not user.is_active:
        return None
    return user
