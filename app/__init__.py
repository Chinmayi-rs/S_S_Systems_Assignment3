import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

from security.pii_crypto import PIICipher

load_dotenv()

db = SQLAlchemy()
jwt = JWTManager()


def create_app():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, 'templates'),
        static_folder=os.path.join(project_root, 'static'),
    )

    data_dir = os.path.join(project_root, 'data')
    os.makedirs(data_dir, exist_ok=True)
    identity_default = 'sqlite:///' + os.path.join(data_dir, 'identity.db')
    ballot_default = 'sqlite:///' + os.path.join(data_dir, 'ballot.db')

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-change-in-production')
    # GR-02: the JWT lifetime is only an absolute cap. The effective limit is
    # the inactivity window checked against user_sessions on every request.
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=int(os.environ.get('JWT_MAX_HOURS', '12')))
    app.config['SESSION_IDLE_MINUTES'] = int(os.environ.get('SESSION_IDLE_MINUTES', '15'))
    app.config['MFA_SETUP_TOKEN_MINUTES'] = int(os.environ.get('MFA_SETUP_TOKEN_MINUTES', '10'))
    # GR-01: lock the account for 15 minutes after 5 consecutive failures.
    app.config['LOGIN_LOCKOUT_THRESHOLD'] = int(os.environ.get('LOGIN_LOCKOUT_THRESHOLD', '5'))
    app.config['LOGIN_LOCKOUT_MINUTES'] = int(os.environ.get('LOGIN_LOCKOUT_MINUTES', '15'))
    # GR-17: Docker turns this on. Direct `python run.py` stays plain HTTP for local tests.
    app.config['ENFORCE_TLS'] = os.environ.get('ENFORCE_TLS', '').lower() in ('1', 'true', 'yes')
    app.config['PUBLIC_HTTPS_URL'] = os.environ.get('PUBLIC_HTTPS_URL', 'https://localhost:8443')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('IDENTITY_DATABASE_URL', identity_default)
    app.config['SQLALCHEMY_BINDS'] = {
        'ballot': os.environ.get('BALLOT_DATABASE_URL', ballot_default),
    }
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.extensions["pii_cipher"] = PIICipher.from_environment()
    
    db.init_app(app)
    jwt.init_app(app)
    CORS(app)

    @jwt.unauthorized_loader
    def unauthorized(reason):
        return jsonify({'error': 'Authentication required'}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify({'error': 'Invalid or expired token'}), 401

    @jwt.expired_token_loader
    def expired_token(header, payload):
        return jsonify({'error': 'Session expired. Sign in again.'}), 401

    # GR-02: Reject idle or revoked sessions.
    @jwt.token_in_blocklist_loader
    def token_blocked(jwt_header, jwt_payload):
        from app.services.sessions import session_is_blocked
        return session_is_blocked(jwt_payload)

    @jwt.revoked_token_loader
    def revoked_token(header, payload):
        return jsonify({'error': 'Session expired. Sign in again.'}), 401

    from app.models import (
        approval,
        audit,
        ballot,
        candidate,
        election,
        published_result,
        session,
        signing,
        user,
    )  # noqa: F401

    from app.routes.approvals import approvals_bp
    from app.routes.audit import audit_bp
    from app.routes.auth import auth_bp
    from app.routes.ballots import ballots_bp
    from app.routes.candidates import candidates_bp
    from app.routes.elections import elections_bp
    from app.routes.enrolment import enrolment_bp
    from app.routes.integrity import integrity_bp
    from app.routes.main import main_bp
    from app.routes.receipts import receipts_bp
    from app.routes.results import results_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(enrolment_bp, url_prefix='/api/enrolment')
    app.register_blueprint(candidates_bp, url_prefix='/api/candidates')
    app.register_blueprint(elections_bp, url_prefix='/api/elections')
    app.register_blueprint(ballots_bp, url_prefix='/api/ballots')
    app.register_blueprint(results_bp, url_prefix='/api/results')
    app.register_blueprint(audit_bp, url_prefix='/api/audit')
    app.register_blueprint(approvals_bp, url_prefix='/api/approvals')
    app.register_blueprint(integrity_bp, url_prefix='/api/integrity')
    app.register_blueprint(receipts_bp, url_prefix='/api/receipts')
    from app.utils.tls_guard import install_tls_guard
    install_tls_guard(app)
    with app.app_context():
        db.create_all()
        from app.services.seed import seed_if_empty
        seed_if_empty()

    # GR-11: Periodic ballot-chain integrity scan.
    from app.services.ballot_integrity import start_background_scan
    start_background_scan(app)

    return app