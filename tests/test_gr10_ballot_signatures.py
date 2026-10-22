"""GR-10: every ballot is signed when encrypted, unsigned ones are refused, signatures re-checked at tally."""

import pytest
from sqlalchemy import text

from app import db
from app.models.ballot import Ballot, BallotToken
from app.models.user import User
from app.services import ballot_crypto, ballot_keys, ballot_signing
from app.services.ballot_signing import UnsignedBallotError
from tests.conftest import add_verified_voters, auth_headers, cast_ballot


def make_row(election_id=1, ballot_id='b-1', signature=None, preferences=None):
    nonce, ciphertext = ballot_crypto.encrypt_preferences(election_id, ballot_id, preferences or {'house': [1]})
    if signature == 'valid':
        signature = ballot_signing.sign(election_id, ballot_id, nonce, ciphertext)
    return Ballot(
        id=ballot_id, election_id=election_id, nonce=nonce, ciphertext=ciphertext,
        signature=signature or '', recorded_hour=ballot_crypto.coarse_time(),
    )


def test_committed_ballot_carries_a_valid_signature(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    with app.app_context():
        row = Ballot.query.one()
        assert row.signature
        assert ballot_signing.verify_row(row)


def test_unsigned_ballot_is_refused_before_storage(app):
    with app.app_context():
        db.session.add(make_row(signature=None))
        with pytest.raises(UnsignedBallotError):
            db.session.flush()
        db.session.rollback()
        assert Ballot.query.count() == 0


def test_forged_signature_is_refused_before_storage(app):
    with app.app_context():
        row = make_row(signature='valid')
        row.ciphertext = make_row(ballot_id='b-1', preferences={'house': [2]}).ciphertext
        db.session.add(row)
        with pytest.raises(UnsignedBallotError):
            db.session.flush()
        db.session.rollback()
        assert Ballot.query.count() == 0


def test_signature_from_another_key_is_refused(app):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    with app.app_context():
        row = make_row()
        attacker = Ed25519PrivateKey.generate()
        message = ballot_signing.signing_message(row.election_id, row.id, row.nonce, row.ciphertext)
        row.signature = ballot_crypto.b64e(attacker.sign(message))
        db.session.add(row)
        with pytest.raises(UnsignedBallotError):
            db.session.flush()
        db.session.rollback()


def test_refused_ballot_leaves_voter_able_to_retry(app, api, monkeypatch):
    headers = auth_headers(api, 'voter', 'voter1234')
    monkeypatch.setattr(ballot_signing, 'sign', lambda *args: 'AAAA')
    with pytest.raises(AssertionError):
        cast_ballot(api, headers)
    with app.app_context():
        assert Ballot.query.count() == 0
        assert User.query.filter_by(username='voter').one().has_voted is False
        assert BallotToken.query.filter_by(status='used').count() == 0


def test_tally_skips_a_ballot_tampered_after_storage(app, api):
    names = add_verified_voters(app, 1)
    first = cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    cast_ballot(api, auth_headers(api, names[0], 'voter1234'))
    with app.app_context():
        # An attacker with direct database access swaps the ciphertext of one ballot.
        other = Ballot.query.filter(Ballot.id != first['reference']).one()
        with db.engines['ballot'].begin() as conn:
            conn.execute(
                text('UPDATE ballots SET ciphertext = :c WHERE id = :i'),
                {'c': other.ciphertext, 'i': first['reference']},
            )
    delegate = auth_headers(api, 'delegate', 'delegate1234')
    preview = api.get('/api/results', headers=delegate).get_json()
    assert preview['total_ballots'] == 1
    assert preview['rejected_ballots'] == 1


def test_public_key_is_published_and_verifies_ballots(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    response = api.get('/api/ballots/public-key')
    assert response.status_code == 200
    public_key = ballot_keys.load_public_key_pem(response.get_json()['public_key_pem'])
    with app.app_context():
        assert ballot_signing.verify_row(Ballot.query.one(), public_key)