from datetime import datetime

from app import db


class Election(db.Model):
    __tablename__ = 'elections'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    division = db.Column(db.String(80), nullable=False)
    # open | closed
    status = db.Column(db.String(20), nullable=False, default='open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'year': self.year,
            'division': self.division,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
