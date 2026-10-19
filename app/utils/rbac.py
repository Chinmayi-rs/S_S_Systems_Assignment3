from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required, verify_jwt_in_request

from app.models.user import User
from app.utils.constants import (
    ROLE_AUDITOR,
    ROLE_DELEGATE,
    ROLE_OFFICER,
    ROLE_VOTER,
)

# GR-03: the single place for who may do what. Routes never hard-code roles;
# they declare a permission and this map decides. A permission that is not
# listed here is denied for every role (deny by default), so a typo in a
# route fails closed, never open.
PERMISSIONS = {
    'enrolment.review': {ROLE_OFFICER},
    'enrolment.verify': {ROLE_OFFICER},
    'enrolment.address': {ROLE_VOTER},
    'candidate.write': {ROLE_DELEGATE},
    'election.status': {ROLE_DELEGATE},
    'ballot.cast': {ROLE_VOTER},
    'audit.read': {ROLE_AUDITOR},
    'results.preview': {ROLE_DELEGATE, ROLE_AUDITOR},
    'approval.propose': {ROLE_DELEGATE},
    'approval.decide': {ROLE_DELEGATE},
    'approval.read': {ROLE_DELEGATE, ROLE_AUDITOR},
}


def _active_user():
    # GR-01: the provisional MFA-enrolment token is not a signed-in session.
    # It can only reach the /api/auth/mfa/* endpoints below.
    if get_jwt().get('scope') == 'mfa_setup':
        return None
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


def permissions_for_role(role):
    """GR-03: every permission the map grants to this role."""
    return sorted(name for name, allowed in PERMISSIONS.items() if role in allowed)


def _audit_denial(user, permission):
    """GR-03: a signed-in user crossing a role boundary is security signal,
    so it lands in the GR-15 audit chain for the auditor to see."""
    from app import db
    from app.services.audit_log import append_audit

    append_audit(
        'rbac.denied',
        f'{user.username} ({user.role}) was denied permission {permission}',
        actor=None,  # system event; the subject is named in the detail
    )
    db.session.commit()


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
                _audit_denial(user, permission)
                return jsonify({'error': 'You do not have permission for this action'}), 403
            return fn(*args, current_user=user, **kwargs)

        return wrapper

    return decorator


def require_mfa_setup_token(fn):
    """GR-01: for the MFA enrolment endpoints only.

    Accepts the short-lived mfa_setup token (new accounts finishing
    enrolment) as well as a full session, but still demands a valid JWT
    and an active account.
    """

    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        identity = get_jwt_identity()
        user = User.query.get(int(identity)) if identity else None
        if not user or not user.is_active:
            return jsonify({'error': 'Access denied'}), 403
        return fn(*args, current_user=user, **kwargs)

    return wrapper


def optional_user():
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return None
    identity = get_jwt_identity()
    if not identity:
        return None
    return _active_user()
