import os
import tempfile

import pyotp
import pytest

from app import create_app, db
from app.services import ballot_keys
from app.services.seed import deterministic_totp_secret


@pytest.fixture(autouse=True)
def isolated_ballot_keys(tmp_path, monkeypatch):
    """Every test gets fresh ballot keys in a temp folder, never the repo's instance/."""
    monkeypatch.setenv('BALLOT_KEY_DIR', str(tmp_path / 'keys'))
    for name in ('BALLOT_ENC_KEY', 'BALLOT_TAG_KEY', 'BALLOT_SIGNING_KEY'):
        monkeypatch.delenv(name, raising=False)
    # The background integrity scan would race the tests; they call it directly.
    monkeypatch.setenv('INTEGRITY_SCAN_SECONDS', '0')
    ballot_keys.clear_cache()
    yield
    ballot_keys.clear_cache()


@pytest.fixture()
def app():
    directory = tempfile.mkdtemp()
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'identity.db')
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    application = create_app()
    application.config['TESTING'] = True
    yield application
    with application.app_context():
        db.session.remove()
        db.engines['ballot'].dispose()
        db.engine.dispose()


@pytest.fixture()
def api(app):
    with app.test_client() as test_client:
        yield test_client


def auth_headers(client, username, password):
    # GR-01: sign-in needs the password plus a TOTP code. Seeded and test
    # accounts use the deterministic secret from services/seed.py.
    code = pyotp.TOTP(deterministic_totp_secret(username)).now()
    response = client.post('/api/auth/login', json={
        'username': username, 'password': password, 'totp_code': code,
    })
    assert response.status_code == 200, response.get_json()
    return {'Authorization': 'Bearer ' + response.get_json()['access_token']}


def ballot_choices(client, senate_index=0, reverse_house=False):
    catalogue = client.get('/api/candidates').get_json()['candidates']
    house = [row['id'] for row in catalogue if row['chamber'] == 'house']
    if reverse_house:
        house.reverse()
    senate = [row['party'] for row in catalogue if row['chamber'] == 'senate'][senate_index]
    return house, senate


def cast_ballot(client, headers, senate_index=0, reverse_house=False):
    """Full voter journey: issue token, stage, commit. Returns the commit response JSON."""
    house, senate = ballot_choices(client, senate_index, reverse_house)
    issued = client.post('/api/ballots/issue', headers=headers)
    assert issued.status_code == 201, issued.get_json()
    token = issued.get_json()['token']
    staged = client.post('/api/ballots/stage', json={
        'token': token, 'house': house, 'senate_party': senate,
    }, headers=headers)
    assert staged.status_code == 200, staged.get_json()
    committed = client.post('/api/ballots/commit', json={'token': token}, headers=headers)
    assert committed.status_code == 201, committed.get_json()
    body = committed.get_json()
    body['token'] = token
    return body


def add_verified_voters(app, count):
    """Extra eligible voters so a test can cast several ballots. Returns usernames."""
    from app.models.user import User

    names = []
    with app.app_context():
        for index in range(count):
            name = f'extra{index}'
            user = User(
                username=name,
                email=f'{name}@example.test',
                password='voter1234',
                full_name=f'Extra Voter {index}',
                role='voter',
                date_of_birth='1990-01-01',
                address='1 Test Street',
                division='Melbourne',
                enrolled=True,
                eligible=True,
            )
            # GR-01: give test voters MFA so they can sign in like seeded accounts.
            user.totp_secret = deterministic_totp_secret(name)
            user.mfa_enabled = True
            db.session.add(user)
            names.append(name)
        db.session.commit()
    return names


def tamper_as_db_admin(sql, params=None):
    """Simulate an attacker with full database admin rights on the ballot DB.

    They can drop the GR-11 append-only triggers and then edit rows directly.
    Run inside an app context. The point of the hash chain is that this is
    still detected.
    """
    from sqlalchemy import text

    from app.models.ballot import APPEND_ONLY_TABLES

    with db.engines['ballot'].begin() as conn:
        for table in APPEND_ONLY_TABLES:
            conn.execute(text(f'DROP TRIGGER IF EXISTS {table}_no_update'))
            conn.execute(text(f'DROP TRIGGER IF EXISTS {table}_no_delete'))
        conn.execute(text(sql), params or {})
    db.session.expire_all()



def _test_double_second_counter(ballots):
    """Stand-in for counter B until a teammate lands app/services/tally_secondary.py.

    Remove this and the fixture below once the real module is implemented.
    """
    result = {'total': len(ballots), 'house': {}, 'senate': {}}
    for ballot in ballots:
        if ballot.get('house'):
            key = str(ballot['house'][0])
            result['house'][key] = result['house'].get(key, 0) + 1
        if ballot.get('senate_party'):
            key = ballot['senate_party']
            result['senate'][key] = result['senate'].get(key, 0) + 1
    return result


@pytest.fixture()
def second_counter(monkeypatch):
    """Use when a test needs results to publish while tally_secondary is still a stub."""
    from app.services import tally_secondary

    try:
        tally_secondary.count([])
    except NotImplementedError:
        monkeypatch.setattr(tally_secondary, 'count', _test_double_second_counter)
    return tally_secondary