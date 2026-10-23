"""GR-20: anonymous inclusion receipts for committed ballots."""

import base64
import hashlib
import re

from app import db
from app.models.ballot import Ballot
from app.models.election import Election
from app.services import ballot_chain

RECEIPT_ALGORITHM = "sha256-ciphertext-v1"


class ReceiptError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def receipt_for_ballot(ballot):
    """Hash the final encrypted ballot without voter information."""
    ciphertext_bytes = base64.b64decode(
        ballot.ciphertext,
        validate=True,
    )
    return hashlib.sha256(ciphertext_bytes).hexdigest()


def published_receipts(election_id):
    """Return sorted receipt hashes after election closure."""
    if (
        isinstance(election_id, bool)
        or not isinstance(election_id, int)
        or election_id < 1
    ):
        raise ReceiptError("election_id must be a positive integer", 400)

    election = db.session.get(Election, election_id)
    if election is None:
        raise ReceiptError("Election not found", 404)

    if election.status != "closed":
        raise ReceiptError(
            "Receipts are available after the election closes",
            403,
        )

    with ballot_chain.append_lock:
        ballots = (
            Ballot.query
            .filter_by(election_id=election_id)
            .order_by(Ballot.seq)
            .all()
        )

        previous_hash = ballot_chain.genesis_hash(election_id)
        receipts = []

        for expected_seq, ballot in enumerate(ballots, start=1):
            if (
                ballot.seq != expected_seq
                or ballot.prev_hash != previous_hash
                or ballot_chain.row_hash(ballot) != ballot.record_hash
            ):
                raise ReceiptError(
                    "Ballot integrity check failed; receipts unavailable",
                    503,
                )

            receipts.append(receipt_for_ballot(ballot))
            previous_hash = ballot.record_hash

    return {
        "election_id": election_id,
        "algorithm": RECEIPT_ALGORITHM,
        "receipts": sorted(receipts),
    }


def check_receipt(election_id, receipt):
    """Check inclusion without returning voter details or preferences."""
    if (
        not isinstance(receipt, str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt) is None
    ):
        raise ReceiptError(
            "receipt must be a 64-character lowercase SHA-256 hash",
            400,
        )

    published = published_receipts(election_id)

    return {
        "election_id": election_id,
        "algorithm": RECEIPT_ALGORITHM,
        "included": receipt in set(published["receipts"]),
    }