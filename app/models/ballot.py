from datetime import datetime

from app import db


class BallotToken(db.Model):
    """Lives in the identity database. Links a voter to a one-time token hash, never to preferences."""

    __tablename__ = 'ballot_tokens'

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, nullable=False)
    voter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    # issued | used | expired
    status = db.Column(db.String(20), nullable=False, default='issued')
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    used_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'id': self.id,
            'election_id': self.election_id,
            'status': self.status,
            'issued_at': self.issued_at.isoformat() if self.issued_at else None,
            'used_at': self.used_at.isoformat() if self.used_at else None,
        }


class Ballot(db.Model):
    """Lives in the ballot database. No voter id column — that split is the GR-06 / GR-09 seam."""

    __bind_key__ = 'ballot'
    __tablename__ = 'ballots'

    id = db.Column(db.String(36), primary_key=True)
    election_id = db.Column(db.Integer, nullable=False, index=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    preferences_json = db.Column(db.Text, nullable=False)
    # staged | committed
    status = db.Column(db.String(20), nullable=False, default='staged')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    committed_at = db.Column(db.DateTime)

    def to_dict(self, include_preferences=False):
        payload = {
            'id': self.id,
            'election_id': self.election_id,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'committed_at': self.committed_at.isoformat() if self.committed_at else None,
        }
        if include_preferences:
            payload['preferences_json'] = self.preferences_json
        return payload
