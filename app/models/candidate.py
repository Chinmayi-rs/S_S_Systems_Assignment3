from app import db


class Candidate(db.Model):
    __tablename__ = 'candidates'

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False)
    # house | senate
    chamber = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    party = db.Column(db.String(80), nullable=False)
    ballot_order = db.Column(db.Integer, nullable=False, default=1)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'election_id': self.election_id,
            'chamber': self.chamber,
            'name': self.name,
            'party': self.party,
            'ballot_order': self.ballot_order,
            'active': self.active,
        }
