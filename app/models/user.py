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
    date_of_birth = db.Column(db.String(10))
    address = db.Column(db.String(240))
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
        self.date_of_birth = date_of_birth
        self.address = address
        self.division = division
        self.enrolled = enrolled
        self.eligible = eligible
        self.set_password(password)

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
