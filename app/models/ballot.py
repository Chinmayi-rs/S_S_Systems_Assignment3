import json
from datetime import datetime

from sqlalchemy import DDL, event

from app import db
from app.services import ballot_signing


class AppendOnlyViolation(Exception):
    """Raised when code tries to update or delete a row in an append-only ballot table (GR-11)."""


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
    """A committed ballot. Encrypted content only, signed with the election key (GR-10).

    GR-11: append-only and hash-chained. Each row stores the hash of the row
    before it in the same election, so changing, removing or reordering any
    ballot breaks the chain from that point on.
    """

    __bind_key__ = 'ballot'
    __tablename__ = 'ballots'
    __table_args__ = (db.UniqueConstraint('election_id', 'seq', name='uq_ballot_chain_position'),)

    id = db.Column(db.String(36), primary_key=True)
    election_id = db.Column(db.Integer, nullable=False, index=True)
    nonce = db.Column(db.String(24), nullable=False)
    ciphertext = db.Column(db.Text, nullable=False)
    # GR-10: Ed25519 signature over (scheme, election, id, nonce, ciphertext).
    signature = db.Column(db.String(88), nullable=False)
    recorded_hour = db.Column(db.DateTime, nullable=False)
    # GR-11: position in the election's chain, and the chain hashes.
    seq = db.Column(db.Integer, nullable=False)
    prev_hash = db.Column(db.String(64), nullable=False)
    record_hash = db.Column(db.String(64), nullable=False, unique=True)

    def to_public_dict(self):
        """What may be shown outside the ballot store: never plaintext."""
        return {
            'id': self.id,
            'election_id': self.election_id,
            'seq': self.seq,
            'record_hash': self.record_hash,
            'recorded_hour': self.recorded_hour.isoformat() if self.recorded_hour else None,
        }


class QuarantinedBallot(db.Model):
    """GR-11: a ballot the integrity scan found to be tampered with.

    Quarantine is recorded as a new row rather than a status change, because
    the ballots table can never be updated. Quarantined ballots are not counted.
    """

    __bind_key__ = 'ballot'
    __tablename__ = 'quarantined_ballots'

    id = db.Column(db.Integer, primary_key=True)
    ballot_id = db.Column(db.String(36), unique=True, nullable=False)
    election_id = db.Column(db.Integer, nullable=False, index=True)
    reason = db.Column(db.String(200), nullable=False)
    detected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'ballot_id': self.ballot_id,
            'election_id': self.election_id,
            'reason': self.reason,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
        }


class IntegrityScan(db.Model):
    """GR-11: one row per run of the ballot-chain integrity scan."""

    __bind_key__ = 'ballot'
    __tablename__ = 'integrity_scans'

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, nullable=False, index=True)
    scanned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ballots_checked = db.Column(db.Integer, nullable=False, default=0)
    newly_quarantined = db.Column(db.Integer, nullable=False, default=0)
    ok = db.Column(db.Boolean, nullable=False)
    findings_json = db.Column(db.Text, nullable=False, default='[]')

    def to_dict(self):
        return {
            'id': self.id,
            'election_id': self.election_id,
            'scanned_at': self.scanned_at.isoformat() if self.scanned_at else None,
            'ballots_checked': self.ballots_checked,
            'newly_quarantined': self.newly_quarantined,
            'ok': self.ok,
            'findings': json.loads(self.findings_json or '[]'),
        }


# GR-10: no Ballot row reaches the database unless its signature verifies.
event.listen(Ballot, 'before_insert', ballot_signing.reject_unsigned)


# ---------------------------------------------------------------------------
# GR-11: append-only enforcement, in two independent layers.
#
# 1. Application layer: the ORM refuses to issue UPDATE or DELETE for these
#    models, whatever route or service asks.
# 2. Database layer: triggers abort any UPDATE or DELETE, including raw SQL from
#    a database console. They are created together with the tables.
#
# Someone with full database admin rights can still drop the triggers. That is
# what the hash chain and the integrity scan are for: the change is detected
# and the ballot quarantined, even if it could not be prevented.
# ---------------------------------------------------------------------------

APPEND_ONLY_TABLES = ('ballots', 'quarantined_ballots')


def _refuse_change(mapper, connection, target):
    raise AppendOnlyViolation(f'{mapper.persist_selectable.name} is append-only')


for _model in (Ballot, QuarantinedBallot):
    event.listen(_model, 'before_update', _refuse_change)
    event.listen(_model, 'before_delete', _refuse_change)


def _sqlite_guards(table):
    return [
        DDL(
            f'CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()} BEFORE {verb} ON {table} '
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        ).execute_if(dialect='sqlite')
        for verb in ('UPDATE', 'DELETE')
    ]


def _postgres_guards(table):
    # For the Postgres migration in the group plan. Pair with a database role
    # that is granted only INSERT and SELECT on these tables.
    return [
        DDL(
            'CREATE OR REPLACE FUNCTION refuse_ballot_change() RETURNS trigger AS $$ '
            "BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END; $$ LANGUAGE plpgsql"
        ).execute_if(dialect='postgresql'),
        DDL(
            f'CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} '
            'FOR EACH ROW EXECUTE FUNCTION refuse_ballot_change()'
        ).execute_if(dialect='postgresql'),
    ]


for _model in (Ballot, QuarantinedBallot):
    for _ddl in _sqlite_guards(_model.__tablename__) + _postgres_guards(_model.__tablename__):
        event.listen(_model.__table__, 'after_create', _ddl)