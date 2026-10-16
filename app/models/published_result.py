from datetime import datetime

from sqlalchemy import DDL, event

from app import db


class ResultsKey(db.Model):
    """The election's own Ed25519 key for signing the final results (GR-13).

    It is separate from the delegates' keys (GR-16): this key signs one thing only, the
    published result, and the signature prefix is different, so a signature made with one
    key can never be replayed as the other kind.

    The private key is stored only as AES-256-GCM ciphertext. The key-encryption secret
    (RESULTS_KEY_SECRET) lives in the environment, not in this database.
    """

    __tablename__ = 'results_keys'

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False, unique=True)
    public_key = db.Column(db.String(64), nullable=False)  # base64 of the raw 32 bytes
    fingerprint = db.Column(db.String(64), nullable=False, unique=True)  # SHA-256 of the raw public key
    private_key_enc = db.Column(db.Text, nullable=False)  # base64(nonce | ciphertext | tag)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class PublishedResult(db.Model):
    """The signed, published result of one election (GR-13). One row per election, never changed.

    result_json is the exact canonical JSON that was signed, so anybody can hash it again and
    check the signature without trusting this server.
    """

    __tablename__ = 'published_results'

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False, unique=True)
    result_json = db.Column(db.Text, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    algorithm = db.Column(db.String(20), nullable=False, default='Ed25519')
    signature = db.Column(db.String(128), nullable=False)  # base64 of the 64-byte signature
    key_id = db.Column(db.Integer, db.ForeignKey('results_keys.id'), nullable=False)
    key_fingerprint = db.Column(db.String(64), nullable=False)
    approval_id = db.Column(db.Integer, db.ForeignKey('pending_approvals.id'), nullable=False)
    proposer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    published_at = db.Column(db.DateTime, nullable=False)


# Same guard as audit_events: no UPDATE / DELETE through the application.
# (Someone with the raw database file can drop a trigger - the signature is what exposes a changed result.)
for _table in (ResultsKey.__table__, PublishedResult.__table__):
    for _verb in ('UPDATE', 'DELETE'):
        _name = f'{_table.name}_no_{_verb.lower()}'
        event.listen(
            _table,
            'after_create',
            DDL(
                f"CREATE TRIGGER IF NOT EXISTS {_name} BEFORE {_verb} ON {_table.name} "
                f"BEGIN SELECT RAISE(ABORT, '{_table.name} is append-only'); END"
            ).execute_if(dialect='sqlite'),
        )
