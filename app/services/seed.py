import base64
import hashlib

from app import db
from app.models.candidate import Candidate
from app.models.election import Election
from app.models.user import User


def deterministic_totp_secret(username):
    """Stable TOTP secret for seeded demo accounts, so the README can list
    them and the tests can compute codes. Accounts registered through the
    API get a random secret from /api/auth/mfa/setup instead (GR-01)."""
    digest = hashlib.sha256(f'ballot-desk-totp:{username}'.encode('utf-8')).digest()
    return base64.b32encode(digest[:20]).decode('ascii')


# username, email, password, full name, role, date of birth, address, division, enrolled, eligible
PEOPLE = [
    ('voter', 'voter@example.test', 'voter1234', 'Casey Morgan', 'voter',
     '1998-04-12', '12 Lygon Street, Carlton', 'Melbourne', True, True),
    ('pending', 'pending@example.test', 'voter1234', 'Riley Chen', 'voter',
     '2001-11-02', '8 Smith Street, Fitzroy', 'Melbourne', False, False),
    ('officer', 'officer@example.test', 'officer1234', 'Noor Abdullah', 'enrolment_officer',
     '1984-06-19', '1 Treasury Place', 'Melbourne', False, False),
    ('delegate', 'delegate@example.test', 'delegate1234', 'Helen Okonkwo', 'commissioner_delegate',
     '1976-01-30', 'Parliament precinct', 'Melbourne', False, False),
    # GR-14: a request needs a second delegate to approve it
    ('delegate2', 'delegate2@example.test', 'delegate21234', 'Marcus Reyes', 'commissioner_delegate',
     '1981-03-14', 'Parliament precinct', 'Melbourne', False, False),
    ('auditor', 'auditor@example.test', 'auditor1234', 'Samir Patel', 'auditor',
     '1979-09-08', 'Audit office', 'Melbourne', False, False),
]


def create_user(username, email, password, full_name, role, date_of_birth=None, address=None,
                division=None, enrolled=False, eligible=False):
    """Build a user and add it to the session. The caller commits."""
    user = User(
        username=username,
        email=email,
        password=password,
        full_name=full_name,
        role=role,
        date_of_birth=date_of_birth,
        address=address,
        division=division,
        enrolled=enrolled,
        eligible=eligible,
    )
    # GR-01: seeded accounts arrive with the second factor already enrolled,
    # so the demo credentials in the README work with any authenticator app.
    user.totp_secret = deterministic_totp_secret(username)
    user.mfa_enabled = True
    db.session.add(user)
    return user


def seed_people():
    """Create every person in PEOPLE that does not exist yet. Safe to run on an existing database."""
    existing = {row[0] for row in db.session.query(User.username).all()}
    for person in PEOPLE:
        if person[0] not in existing:
            create_user(*person)


def seed_if_empty():
    fresh = User.query.first() is None

    if fresh:
        _seed_election()
    seed_people()
    db.session.commit()


def _seed_election():
    election = Election(
        name='Federal Election',
        year=2026,
        division='Melbourne',
        status='open',
    )
    db.session.add(election)
    db.session.flush()

    house = [
        (1, 'Amira Hassan', 'Labor'),
        (2, 'Jonah Ellis', 'Liberal'),
        (3, 'Priya Nair', 'Greens'),
        (4, 'Tom Nguyen', 'Independent'),
    ]
    for order, name, party in house:
        db.session.add(Candidate(
            election_id=election.id,
            chamber='house',
            name=name,
            party=party,
            ballot_order=order,
        ))

    senate = [
        (1, 'Australian Labor Party', 'Labor'),
        (2, 'Liberal Party', 'Liberal'),
        (3, 'Australian Greens', 'Greens'),
    ]
    for order, name, party in senate:
        db.session.add(Candidate(
            election_id=election.id,
            chamber='senate',
            name=name,
            party=party,
            ballot_order=order,
        ))

