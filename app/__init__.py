import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

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
    # Fixed lifetime for the skeleton. GR-02 replaces this with a 15-minute idle timeout.
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(minutes=int(os.environ.get('JWT_MINUTES', '60')))
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('IDENTITY_DATABASE_URL', identity_default)
    app.config['SQLALCHEMY_BINDS'] = {
        'ballot': os.environ.get('BALLOT_DATABASE_URL', ballot_default),
    }
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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

    from app.models import audit, ballot, candidate, election, user  # noqa: F401
    from app.routes.audit import audit_bp
    from app.routes.auth import auth_bp
    from app.routes.ballots import ballots_bp
    from app.routes.candidates import candidates_bp
    from app.routes.elections import elections_bp
    from app.routes.enrolment import enrolment_bp
    from app.routes.main import main_bp
    from app.routes.results import results_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(enrolment_bp, url_prefix='/api/enrolment')
    app.register_blueprint(candidates_bp, url_prefix='/api/candidates')
    app.register_blueprint(elections_bp, url_prefix='/api/elections')
    app.register_blueprint(ballots_bp, url_prefix='/api/ballots')
    app.register_blueprint(results_bp, url_prefix='/api/results')
    app.register_blueprint(audit_bp, url_prefix='/api/audit')

    with app.app_context():
        db.create_all()
        from app.services.seed import seed_if_empty
        seed_if_empty()

    return app
