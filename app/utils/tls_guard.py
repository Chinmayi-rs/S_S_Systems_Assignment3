"""GR-17: refuse client requests that did not arrive over HTTPS.

nginx is the TLS 1.3 endpoint. This guard is the backstop for the app itself:
when ENFORCE_TLS is on (the Docker deployment), a request is served only if
the connection is HTTPS or nginx has marked it X-Forwarded-Proto: https.
Plain HTTP page loads are redirected. Plain HTTP API calls are rejected.
The container health probe is the only exception, and only from localhost.
"""
from flask import current_app, jsonify, redirect, request


def _https_target():
    public = current_app.config.get('PUBLIC_HTTPS_URL', 'https://localhost:8443').rstrip('/')
    target = public + request.path
    if request.query_string:
        target += '?' + request.query_string.decode('ascii', errors='ignore')
    return target


def install_tls_guard(app):
    @app.before_request
    def require_tls():
        if not current_app.config.get('ENFORCE_TLS'):
            return None
        if request.path == '/health' and request.remote_addr in ('127.0.0.1', '::1'):
            return None
        forwarded = (request.headers.get('X-Forwarded-Proto') or '').split(',')[0].strip().lower()
        if request.is_secure or forwarded == 'https':
            return None
        if request.method in ('GET', 'HEAD'):
            return redirect(_https_target(), code=308)
        return jsonify({'error': 'TLS is required'}), 403
