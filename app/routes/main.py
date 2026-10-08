from flask import Blueprint, jsonify, render_template

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    return render_template('index.html')


@main_bp.route('/login')
def login_page():
    return render_template('login.html')


@main_bp.route('/register')
def register_page():
    return render_template('register.html')


@main_bp.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')


@main_bp.route('/vote')
def vote_page():
    return render_template('vote.html')


@main_bp.route('/candidates')
def candidates_page():
    return render_template('candidates.html')


@main_bp.route('/enrolment')
def enrolment_page():
    return render_template('enrolment.html')


@main_bp.route('/results')
def results_page():
    return render_template('results.html')


@main_bp.route('/audit')
def audit_page():
    return render_template('audit.html')


@main_bp.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'service': 'ballot-desk'}), 200
