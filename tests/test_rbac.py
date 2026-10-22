"""GR-03: role-based access control with a deny-by-default permission policy."""
import os
import re
import tempfile

import pyotp
import pytest

from app import create_app
from app.models.audit import AuditEvent
from app.services.seed import deterministic_totp_secret
from app.utils.rbac import PERMISSIONS, require_permission

ROUTES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'routes')

# The only /api endpoints an anonymous caller may reach. Everything else must
# answer 401 without a valid token - that is what deny-by-default means.
PUBLIC_API = {
    ('/api/auth/register', 'POST'),
    ('/api/auth/login', 'POST'),
    ('/api/candidates', 'GET'),
    ('/api/elections/current', 'GET'),
    ('/api/results', 'GET'),           # guarded by publication state, not auth
    ('/api/results/public-key', 'GET'),
    ('/api/results/verify', 'GET'),
    ('/api/ballots/public-key', 'GET'),  #GR-10: ballot verify key, public by design
}


@pytest.fixture()
def ctx():
    directory = tempfile.mkdtemp()
    os.environ['IDENTITY_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'identity.db')
    os.environ['BALLOT_DATABASE_URL'] = 'sqlite:///' + os.path.join(directory, 'ballot.db')
    os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret'
    os.environ['SECRET_KEY'] = 'test-secret'
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client, app


def login(client, username, password):
    code = pyotp.TOTP(deterministic_totp_secret(username)).now()
    res = client.post('/api/auth/login', json={'username': username, 'password': password, 'totp_code': code})
    assert res.status_code == 200
    return {'Authorization': 'Bearer ' + res.get_json()['access_token']}


def test_every_api_route_denies_anonymous_callers_by_default(ctx):
    """Walk the real routing table: anything not on the public list is 401."""
    client, app = ctx
    checked = 0
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith('/api'):
            continue
        path = re.sub(r'<[^>]+>', '1', rule.rule)
        for method in rule.methods - {'HEAD', 'OPTIONS'}:
            if (path, method) in PUBLIC_API:
                continue
            response = client.open(path, method=method)
            assert response.status_code == 401, f'{method} {path} answered {response.status_code} anonymously'
            checked += 1
    assert checked >= 20  # the walk really covered the API, not an empty map


def test_every_permission_used_by_a_route_exists_in_the_map():
    """A typo in a permission name fails closed, but it should also fail CI."""
    used = set()
    for filename in os.listdir(ROUTES_DIR):
        if not filename.endswith('.py'):
            continue
        with open(os.path.join(ROUTES_DIR, filename), encoding='utf-8') as handle:
            used.update(re.findall(r"require_permission\('([^']+)'\)", handle.read()))
    assert used, 'no permissions found - did the routes move?'
    missing = used - set(PERMISSIONS)
    assert not missing, f'routes reference permissions missing from PERMISSIONS: {missing}'


def test_unlisted_permission_denies_every_role(ctx):
    """Deny by default: a permission nobody granted stops even a delegate."""
    client, app = ctx

    # Registered before the first request, so Flask accepts the extra route.
    @app.route('/api/_test/unlisted-permission')
    @require_permission('does.not.exist')
    def _unlisted(current_user):  # pragma: no cover - must never run
        return 'reached'

    delegate = login(client, 'delegate', 'delegate1234')
    assert client.get('/api/_test/unlisted-permission', headers=delegate).status_code == 403


def test_role_permission_matrix(ctx):
    client, _ = ctx
    matrix = [
        # (username, password, path, expected status)
        ('voter', 'voter1234', '/api/ballots/status', 200),
        ('voter', 'voter1234', '/api/enrolment/voters', 403),
        ('voter', 'voter1234', '/api/audit', 403),
        ('voter', 'voter1234', '/api/approvals', 403),
        ('officer', 'officer1234', '/api/enrolment/voters', 200),
        ('officer', 'officer1234', '/api/ballots/status', 403),
        ('officer', 'officer1234', '/api/audit', 403),
        ('delegate', 'delegate1234', '/api/approvals', 200),
        ('delegate', 'delegate1234', '/api/audit', 403),
        ('delegate', 'delegate1234', '/api/enrolment/voters', 403),
        ('auditor', 'auditor1234', '/api/audit', 200),
        ('auditor', 'auditor1234', '/api/approvals', 200),
        ('auditor', 'auditor1234', '/api/enrolment/voters', 403),
        ('auditor', 'auditor1234', '/api/ballots/status', 403),
    ]
    for username, password, path, expected in matrix:
        headers = login(client, username, password)
        response = client.get(path, headers=headers)
        assert response.status_code == expected, f'{username} GET {path}: {response.status_code} != {expected}'


def test_denied_attempts_land_in_the_audit_chain(ctx):
    client, app = ctx
    voter = login(client, 'voter', 'voter1234')
    assert client.post('/api/candidates', json={'name': 'X', 'party': 'Y', 'chamber': 'house'},
                       headers=voter).status_code == 403
    with app.app_context():
        denial = AuditEvent.query.filter_by(action='rbac.denied').order_by(AuditEvent.id.desc()).first()
        assert denial is not None
        assert 'voter' in denial.detail and 'candidate.write' in denial.detail


def test_permissions_endpoint_reflects_the_map(ctx):
    client, _ = ctx
    voter = login(client, 'voter', 'voter1234')
    body = client.get('/api/auth/permissions', headers=voter).get_json()
    assert body['role'] == 'voter'
    assert body['permissions'] == ['ballot.cast', 'enrolment.address']

    auditor = login(client, 'auditor', 'auditor1234')
    body = client.get('/api/auth/permissions', headers=auditor).get_json()
    assert 'audit.read' in body['permissions']
    assert 'candidate.write' not in body['permissions']
