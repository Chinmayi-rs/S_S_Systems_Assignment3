from datetime import datetime

from app import db


class UserSession(db.Model):
    """GR-02: one row per issued access token (keyed by the JWT's jti).

    The JWT alone is stateless, so this table is what lets the server
    idle-expire a session after 15 minutes and revoke it on logout.
    """

    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False)
    revoked_reason = db.Column(db.String(40))

    def __repr__(self):
        return f'<UserSession user={self.user_id} revoked={self.revoked}>'
