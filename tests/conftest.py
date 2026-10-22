import os
import tempfile

import pytest

from app import create_app, db
from app.services import ballot_keys


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
    response = client.post('/api/auth/login', json={'username': username, 'password': password})
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
            db.session.add(User(
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
            ))
            names.append(name)
        db.session.commit()
    return names