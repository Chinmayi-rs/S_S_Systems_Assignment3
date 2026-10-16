from datetime import datetime

from sqlalchemy import DDL, event

from app import db


class DelegateKey(db.Model):
    """One Ed25519 keypair per Commissioner's delegate (GR-16).

    The public key is stored as base64 of the raw 32 bytes. The private key is
    stored only as AES-256-GCM ciphertext; the key-encryption secret lives in
    the environment, not in this database.
    """

    __tablename__ = 'delegate_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    public_key = db.Column(db.String(64), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False, unique=True)  # SHA-256 of the raw public key
    private_key_enc = db.Column(db.Text, nullable=False)  # base64(nonce | ciphertext | tag)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class ActionSignature(db.Model):
    """Signature of one audit entry, made with the acting delegate's own key (GR-16)."""

    __tablename__ = 'action_signatures'

    id = db.Column(db.Integer, primary_key=True)
    audit_event_id = db.Column(db.Integer, db.ForeignKey('audit_events.id'), nullable=False, unique=True)
    signer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    key_id = db.Column(db.Integer, db.ForeignKey('delegate_keys.id'), nullable=False)
    algorithm = db.Column(db.String(20), nullable=False, default='Ed25519')
    signature = db.Column(db.String(128), nullable=False)  # base64 of the 64-byte signature
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# Same guard as audit_events: no UPDATE / DELETE through the application.
for _table in (DelegateKey.__table__, ActionSignature.__table__):
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
