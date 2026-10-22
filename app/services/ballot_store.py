"""The only module that reads or writes the ballot database.

ballot_box (voter journey) calls stage / commit here; the tally reads through
``read_ballots``. Keeping every ballot-table access in one place means the
encryption rules (GR-09) cannot be skipped by another route.
"""

import uuid

from app import db
from app.models.ballot import Ballot, StagedBallot
from app.services import ballot_crypto


def stage(election_id, raw_token, preferences):
    """Encrypt and store (or replace) the ballot under review for this token."""
    tag = ballot_crypto.token_tag(raw_token)
    staged = StagedBallot.query.filter_by(token_tag=tag).first()
    if staged is None:
        staged = StagedBallot(id=str(uuid.uuid4()), election_id=election_id, token_tag=tag)
        db.session.add(staged)
    nonce, ciphertext = ballot_crypto.encrypt_preferences(election_id, staged.id, preferences)
    staged.nonce = nonce
    staged.ciphertext = ciphertext
    staged.created_hour = ballot_crypto.coarse_time()
    return staged


def find_staged(election_id, raw_token):
    return StagedBallot.query.filter_by(
        token_tag=ballot_crypto.token_tag(raw_token), election_id=election_id
    ).first()


def commit(staged):
    """Move a staged ballot into the committed store. Does not call db.session.commit().

    The committed row gets a fresh random id and a fresh encryption, so nothing
    about the staged row (its id, its token tag) carries over.
    """
    preferences = ballot_crypto.decrypt_preferences(
        staged.election_id, staged.id, staged.nonce, staged.ciphertext
    )
    ballot_id = str(uuid.uuid4())
    nonce, ciphertext = ballot_crypto.encrypt_preferences(staged.election_id, ballot_id, preferences)
    ballot = Ballot(
        id=ballot_id,
        election_id=staged.election_id,
        nonce=nonce,
        ciphertext=ciphertext,
        recorded_hour=ballot_crypto.coarse_time(),
    )
    db.session.add(ballot)
    db.session.delete(staged)
    return ballot


def read_ballots(election_id):
    """Decrypted preferences for every committed ballot in an election."""
    rows = Ballot.query.filter_by(election_id=election_id).all()
    return [
        ballot_crypto.decrypt_preferences(row.election_id, row.id, row.nonce, row.ciphertext)
        for row in rows
    ]