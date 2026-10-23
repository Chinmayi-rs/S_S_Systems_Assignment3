"""GR-20: public receipt checking after election closure."""

from flask import Blueprint, jsonify, request

from app.services.receipts import (
    ReceiptError,
    check_receipt,
    published_receipts,
)

receipts_bp = Blueprint("receipts", __name__)


def _json_response(payload, status_code=200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status_code


@receipts_bp.route("/published/<int:election_id>", methods=["GET"])
def published(election_id):
    try:
        payload = published_receipts(election_id)
    except ReceiptError as error:
        return _json_response(
            {"error": str(error)},
            error.status_code,
        )

    return _json_response(payload)


@receipts_bp.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return _json_response(
            {"error": "Send a JSON object containing election_id and receipt"},
            400,
        )

    try:
        payload = check_receipt(
            data.get("election_id"),
            data.get("receipt"),
        )
    except ReceiptError as error:
        return _json_response(
            {"error": str(error)},
            error.status_code,
        )

    return _json_response(payload)