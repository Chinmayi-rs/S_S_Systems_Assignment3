"""GR-02: server-side session management behind the JWTs.

Tokens stay JWTs (so the rest of the app is unchanged), but every full
session is also recorded in the `user_sessions` table. flask-jwt-extended
asks `session_is_blocked` about every verified token, which is where the
15-minute inactivity window and logout revocation are enforced for every
endpoint at once.
"""
from datetime import datetime, timedelta

from flask import current_app
from flask_jwt_extended import create_access_token, get_jti

from app import db
from app.models.session import UserSession

# Claim marking the provisional token handed out between a correct password
# and finished TOTP enrolment (GR-01). It is not a session: it can only call
# the /api/auth/mfa/* endpoints and expires on its own after a few minutes.
MFA_SETUP_SCOPE = 'mfa_setup'


def issue_session_token(user):
    """Create a full access token backed by a session row. Does not commit."""
    token = create_access_token(
        identity=str(user.id),
        additional_claims={'role': user.role},
    )
    now = datetime.utcnow()
    db.session.add(UserSession(jti=get_jti(token), user_id=user.id, created_at=now, last_seen=now))
    return token


def issue_mfa_setup_token(user):
    """Short-lived token that can only finish MFA enrolment (GR-01)."""
    minutes = current_app.config.get('MFA_SETUP_TOKEN_MINUTES', 10)
    return create_access_token(
        identity=str(user.id),
        additional_claims={'role': user.role, 'scope': MFA_SETUP_SCOPE},
        expires_delta=timedelta(minutes=minutes),
    )


def revoke_session(jti, reason='logout'):
    """Mark a session dead server-side. Does not commit."""
    session = UserSession.query.filter_by(jti=jti).first()
    if session and not session.revoked:
        session.revoked = True
        session.revoked_reason = reason


def session_is_blocked(jwt_payload):
    """Blocklist callback run by flask-jwt-extended for every verified token.

    Returning True makes the framework reject the request with 401, so the
    idle timeout and revocation apply to every protected endpoint without
    each route having to remember to check.
    """
    if jwt_payload.get('scope') == MFA_SETUP_SCOPE:
        # No session row by design; the token's own short expiry limits it.
        return False
    session = UserSession.query.filter_by(jti=jwt_payload.get('jti')).first()
    if not session or session.revoked:
        return True
    idle_minutes = current_app.config.get('SESSION_IDLE_MINUTES', 15)
    now = datetime.utcnow()
    if now - session.last_seen > timedelta(minutes=idle_minutes):
        session.revoked = True
        session.revoked_reason = 'idle_timeout'
        db.session.commit()
        return True
    # Activity slides the window: any authenticated request resets the clock.
    session.last_seen = now
    db.session.commit()
    return False
