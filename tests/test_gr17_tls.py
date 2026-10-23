"""GR-17: plain HTTP is redirected or refused, and the nginx config is TLS 1.3 only."""
import re
from pathlib import Path

NGINX_CONF = Path(__file__).resolve().parents[1] / 'nginx' / 'default.conf'


def test_nginx_allows_only_tls_1_3():
    text = NGINX_CONF.read_text(encoding='utf-8')
    assert 'ssl_protocols TLSv1.3;' in text
    assert 'ssl_conf_command MinProtocol TLSv1.3;' in text
    assert 'return 308 https://localhost:8443$request_uri;' in text
    # No older protocol is enabled. A comment may mention TLS 1.2 as rejected.
    enabled = re.findall(r'^\s*ssl_protocols\s+([^;]+);', text, flags=re.MULTILINE)
    assert enabled == ['TLSv1.3']
    assert not re.search(r'^\s*listen\s+443(?!.*ssl)', text, flags=re.MULTILINE)


def test_plain_http_pages_redirect_and_api_calls_are_refused(api):
    api.application.config['ENFORCE_TLS'] = True
    page = api.get('/login')
    assert page.status_code == 308
    assert page.headers['Location'] == 'https://localhost:8443/login'

    api_call = api.post('/api/auth/login', json={'username': 'voter', 'password': 'voter1234'})
    assert api_call.status_code == 403
    assert 'TLS' in api_call.get_json()['error']


def test_proxied_https_and_local_health_are_allowed(api):
    api.application.config['ENFORCE_TLS'] = True
    health = api.get('/health')
    assert health.status_code == 200

    page = api.get('/login', headers={'X-Forwarded-Proto': 'https'})
    assert page.status_code == 200


def test_tls_enforcement_is_off_unless_configured(api):
    api.application.config['ENFORCE_TLS'] = False
    assert api.get('/login').status_code == 200
