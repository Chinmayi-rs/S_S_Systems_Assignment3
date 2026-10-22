import uuid
from flask import current_app

from datetime import datetime

import bcrypt

from app import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    # voter | enrolment_officer | commissioner_delegate | auditor
    role = db.Column(db.String(40), nullable=False, default='voter')
    
    pii_context_id = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
    )
    _date_of_birth_encrypted = db.Column(
        "date_of_birth_encrypted",
        db.Text,
    )
    _address_encrypted = db.Column(
        "address_encrypted",
        db.Text,
    )
    
    division = db.Column(db.String(80))
    enrolled = db.Column(db.Boolean, default=False, nullable=False)
    eligible = db.Column(db.Boolean, default=False, nullable=False)
    has_voted = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, username, email, password, full_name, role='voter',
                 date_of_birth=None, address=None, division=None,
                 enrolled=False, eligible=False):
        self.username = username
        self.email = email
        self.full_name = full_name
        self.role = role
        self.pii_context_id = str(uuid.uuid4())
        self.date_of_birth = date_of_birth
        self.address = address
        self.division = division
        self.enrolled = enrolled
        self.eligible = eligible
        self.set_password(password)

    def _pii_context(self, field):
        if not self.pii_context_id:
            raise RuntimeError("User encryption context is missing.")

        return f"voter:{self.pii_context_id}:{field}"

    def _encrypt_pii(self, value, field):
        if value is None:
            return None

        cipher = current_app.extensions["pii_cipher"]
        return cipher.encrypt(
            value,
            context=self._pii_context(field),
        )

    def _decrypt_pii(self, value, field):
        if value is None:
            return None

        cipher = current_app.extensions["pii_cipher"]
        return cipher.decrypt(
            value,
            context=self._pii_context(field),
        )

    @property
    def date_of_birth(self):
        return self._decrypt_pii(
            self._date_of_birth_encrypted,
            "date_of_birth",
        )

    @date_of_birth.setter
    def date_of_birth(self, value):
        self._date_of_birth_encrypted = self._encrypt_pii(
            value,
            "date_of_birth",
        )

    @property
    def address(self):
        return self._decrypt_pii(
            self._address_encrypted,
            "address",
        )

    @address.setter
    def address(self, value):
        self._address_encrypted = self._encrypt_pii(
            value,
            "address",
        )

    def set_password(self, password):
        # GR-01: swap bcrypt for Argon2.
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'role': self.role,
            'date_of_birth': self.date_of_birth,
            'address': self.address,
            'division': self.division,
            'enrolled': self.enrolled,
            'eligible': self.eligible,
            'has_voted': self.has_voted,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<User {self.username} {self.role}>'
