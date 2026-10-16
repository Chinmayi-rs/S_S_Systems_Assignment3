"""GR-13 Results: public only after two delegates have signed and published them.

Closing the poll no longer makes the count public. Until the signed result exists, anybody who is
not a delegate or auditor gets 403 - whether the poll is open or already closed.
"""
import json

from flask import Blueprint, jsonify

from app import db
from app.models.published_result import ResultsKey
from app.services import results_publication as publication
from app.services.elections import current_election
from app.services.tally import build_results
from app.utils.helpers import json_error
from app.utils.rbac import PERMISSIONS, optional_user

results_bp = Blueprint('results', __name__)


def _can_preview(user):
    return bool(user) and user.role in PERMISSIONS['results.preview']


def _published_or_error(election):
    """The published row, or the error response to send instead. Outsiders learn nothing before publication."""
    row = publication.get_published(election.id)
    if row:
        return row, None
    if not _can_preview(optional_user()):
        return None, json_error('Results are not published yet', 403)
    return None, json_error('The results have not been published yet', 404)


@results_bp.route('', methods=['GET'], strict_slashes=False)
def results():
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)

    row = publication.get_published(election.id)
    if row:
        document = json.loads(row.result_json)
        payload = dict(document['results'])  # house, senate, total_ballots, method, election
        payload.update({
            'preview': False,
            'published': True,
            'publication': document['publication'],
            'signature': {
                'algorithm': row.algorithm,
                'value': row.signature,
                'sha256': row.sha256,
                'key_fingerprint': row.key_fingerprint,
                'signed_message_prefix': publication.SIGN_PREFIX.decode('ascii'),
            },
            # the exact text that was signed, so it can be saved and checked offline
            'signed_document': row.result_json,
        })
        return jsonify(payload), 200

    # Not published: only a delegate or auditor may look, and it is marked as a preview.
    if not _can_preview(optional_user()):
        return json_error('Results are not published yet', 403)
    payload = build_results(election)
    payload['preview'] = True
    payload['published'] = False
    return jsonify(payload), 200


@results_bp.route('/public-key', methods=['GET'])
def public_key():
    """The key anybody can use to check the published result."""
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    row, error = _published_or_error(election)
    if error:
        return error
    key = db.session.get(ResultsKey, row.key_id)
    return jsonify({
        'algorithm': publication.ALGORITHM,
        'public_key': key.public_key,
        'fingerprint': key.fingerprint,
        'election_id': election.id,
        'note': 'Compare the fingerprint with a trusted copy (the report, or the results.key.registered audit entry).',
    }), 200


@results_bp.route('/verify', methods=['GET'])
def verify():
    """The server checks its own stored result again. Handy for a demo; a third party should use scripts/verify_results.py."""
    election = current_election()
    if not election:
        return json_error('No election is configured', 404)
    row, error = _published_or_error(election)
    if error:
        return error
    return jsonify(publication.verify_published(row)), 200
