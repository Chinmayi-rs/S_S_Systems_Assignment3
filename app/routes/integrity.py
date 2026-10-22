"""GR-11: ballot-chain integrity endpoints for auditors and delegates."""

from flask import Blueprint, jsonify

from app.services.ballot_integrity import (
    latest_scans,
    quarantine_list,
    scan_all,
    scan_interval_seconds,
)
from app.utils.rbac import require_permission

integrity_bp = Blueprint('integrity', __name__)


@integrity_bp.route('', methods=['GET'], strict_slashes=False)
@require_permission('ballot.integrity')
def status(current_user):
    return jsonify({
        'interval_seconds': scan_interval_seconds(),
        'scans': latest_scans(),
        'quarantined': quarantine_list(),
    }), 200


@integrity_bp.route('/scan', methods=['POST'])
@require_permission('ballot.integrity')
def scan_now(current_user):
    results = scan_all()
    return jsonify({
        'ok': all(result['ok'] for result in results),
        'results': results,
        'quarantined': quarantine_list(),
    }), 200