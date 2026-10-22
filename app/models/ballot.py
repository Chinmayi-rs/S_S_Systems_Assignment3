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


# ---------------------------------------------------------------------------
# Ballot database (bind 'ballot'). GR-09 rules for every table below:
#   * no voter id, no foreign key into the identity database
#   * no value shared with the identity database (token_tag is an HMAC, not the
#     SHA-256 stored in ballot_tokens)
#   * content stored only as AES-256-GCM ciphertext
#   * timestamps rounded to the hour
#   * random UUID primary keys, so ids carry no ordering information
# ---------------------------------------------------------------------------


class StagedBallot(db.Model):
    """A ballot the voter is still reviewing (GR-08 stage step).

    Mutable while the voter changes their mind. Deleted in the same transaction
    that appends the final Ballot, so no session-to-ballot link survives commit.
    """

    __bind_key__ = 'ballot'
    __tablename__ = 'staged_ballots'

    id = db.Column(db.String(36), primary_key=True)
    election_id = db.Column(db.Integer, nullable=False, index=True)
    token_tag = db.Column(db.String(64), unique=True, nullable=False)
    nonce = db.Column(db.String(24), nullable=False)
    ciphertext = db.Column(db.Text, nullable=False)
    created_hour = db.Column(db.DateTime, nullable=False)


class Ballot(db.Model):
    """A committed ballot. Encrypted content only."""

    __bind_key__ = 'ballot'
    __tablename__ = 'ballots'

    id = db.Column(db.String(36), primary_key=True)
    election_id = db.Column(db.Integer, nullable=False, index=True)
    nonce = db.Column(db.String(24), nullable=False)
    ciphertext = db.Column(db.Text, nullable=False)
    recorded_hour = db.Column(db.DateTime, nullable=False)

    def to_public_dict(self):
        """What may be shown outside the ballot store: never plaintext."""
        return {
            'id': self.id,
            'election_id': self.election_id,
            'recorded_hour': self.recorded_hour.isoformat() if self.recorded_hour else None,
        }