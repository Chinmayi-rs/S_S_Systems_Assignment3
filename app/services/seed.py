from app import db
from app.models.candidate import Candidate
from app.models.election import Election
from app.models.user import User


def ensure_second_delegate():
    """GR-14 needs two different delegates. Safe to run on an existing database."""
    if User.query.filter_by(username='delegate2').first():
        return
    db.session.add(User(
        username='delegate2',
        email='delegate2@example.test',
        password='delegate21234',
        full_name='Marcus Reyes',
        role='commissioner_delegate',
        date_of_birth='1981-03-14',
        address='Parliament precinct',
        division='Melbourne',
    ))
    db.session.commit()


def seed_if_empty():
    if User.query.first():
        ensure_second_delegate()
        return

    election = Election(
        name='Federal Election',
        year=2026,
        division='Melbourne',
        status='open',
    )
    db.session.add(election)
    db.session.flush()

    people = [
        ('voter', 'voter@example.test', 'voter1234', 'Casey Morgan', 'voter',
         '1998-04-12', '12 Lygon Street, Carlton', 'Melbourne', True, True),
        ('pending', 'pending@example.test', 'voter1234', 'Riley Chen', 'voter',
         '2001-11-02', '8 Smith Street, Fitzroy', 'Melbourne', False, False),
        ('officer', 'officer@example.test', 'officer1234', 'Noor Abdullah', 'enrolment_officer',
         '1984-06-19', '1 Treasury Place', 'Melbourne', False, False),
        ('delegate', 'delegate@example.test', 'delegate1234', 'Helen Okonkwo', 'commissioner_delegate',
         '1976-01-30', 'Parliament precinct', 'Melbourne', False, False),
        ('auditor', 'auditor@example.test', 'auditor1234', 'Samir Patel', 'auditor',
         '1979-09-08', 'Audit office', 'Melbourne', False, False),
    ]
    for username, email, password, full_name, role, dob, address, division, enrolled, eligible in people:
        db.session.add(User(
            username=username,
            email=email,
            password=password,
            full_name=full_name,
            role=role,
            date_of_birth=dob,
            address=address,
            division=division,
            enrolled=enrolled,
            eligible=eligible,
        ))

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

    db.session.commit()
    ensure_second_delegate()
