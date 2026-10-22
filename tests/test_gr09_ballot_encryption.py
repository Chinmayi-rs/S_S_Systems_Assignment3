"""GR-09: ballots encrypted at rest (AES-256-GCM) and separated from voter identity."""

import hashlib

import pytest
from sqlalchemy import inspect, text

from app import db
from app.models.ballot import Ballot, BallotToken, StagedBallot
from app.services import ballot_crypto
from tests.conftest import add_verified_voters, auth_headers, ballot_choices, cast_ballot


def ballot_engine():
    return db.engines['ballot']


def raw_ballot_rows():
    with ballot_engine().connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text('SELECT * FROM ballots'))]


def test_ballot_database_stores_only_ciphertext(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    with app.app_context():
        rows = raw_ballot_rows()
        candidate_names = ['Labor', 'Liberal', 'Greens', 'Independent', 'house', 'senate_party']
    assert len(rows) == 1
    dumped = repr(rows)
    for word in candidate_names:
        assert word not in dumped, f'plaintext {word!r} found in the ballot table'


def test_ballot_tables_have_no_identity_columns(app):
    with app.app_context():
        inspector = inspect(ballot_engine())
        for table in inspector.get_table_names():
            columns = {column['name'] for column in inspector.get_columns(table)}
            assert not columns & {'voter_id', 'user_id', 'username', 'token_hash', 'ip_address'}, table
            assert not inspector.get_foreign_keys(table), f'{table} has a foreign key'


def test_ballot_side_tag_differs_from_identity_side_hash(app, api):
    headers = auth_headers(api, 'voter', 'voter1234')
    house, senate = ballot_choices(api)
    token = api.post('/api/ballots/issue', headers=headers).get_json()['token']
    api.post('/api/ballots/stage', json={'token': token, 'house': house, 'senate_party': senate}, headers=headers)
    with app.app_context():
        identity_hash = BallotToken.query.one().token_hash
        staged = StagedBallot.query.one()
        assert identity_hash == hashlib.sha256(token.encode()).hexdigest()
        assert staged.token_tag != identity_hash
        # Holding both databases is not enough to join them without the raw token.
        assert StagedBallot.query.filter_by(token_tag=identity_hash).count() == 0


def test_staged_ballot_is_removed_when_committed(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    with app.app_context():
        assert StagedBallot.query.count() == 0
        assert Ballot.query.count() == 1


def test_timestamps_are_rounded_to_the_hour(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    with app.app_context():
        stamp = Ballot.query.one().recorded_hour
        assert (stamp.minute, stamp.second, stamp.microsecond) == (0, 0, 0)


def test_ciphertext_length_does_not_reveal_the_vote(app, api):
    names = add_verified_voters(app, 2)
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'), senate_index=0)
    cast_ballot(api, auth_headers(api, names[0], 'voter1234'), senate_index=1, reverse_house=True)
    cast_ballot(api, auth_headers(api, names[1], 'voter1234'), senate_index=2)
    with app.app_context():
        lengths = {len(row.ciphertext) for row in Ballot.query.all()}
    assert len(lengths) == 1


def test_ciphertext_is_bound_to_its_ballot_id(app):
    with app.app_context():
        nonce, ciphertext = ballot_crypto.encrypt_preferences(1, 'ballot-a', {'house': [1, 2]})
        assert ballot_crypto.decrypt_preferences(1, 'ballot-a', nonce, ciphertext) == {'house': [1, 2]}
        with pytest.raises(ballot_crypto.BallotCryptoError):
            ballot_crypto.decrypt_preferences(1, 'ballot-b', nonce, ciphertext)
        with pytest.raises(ballot_crypto.BallotCryptoError):
            ballot_crypto.decrypt_preferences(2, 'ballot-a', nonce, ciphertext)


def test_flipped_ciphertext_byte_fails_authentication(app):
    with app.app_context():
        nonce, ciphertext = ballot_crypto.encrypt_preferences(1, 'b', {'house': [1]})
        raw = bytearray(ballot_crypto.b64d(ciphertext))
        raw[10] ^= 0x01
        with pytest.raises(ballot_crypto.BallotCryptoError):
            ballot_crypto.decrypt_preferences(1, 'b', nonce, ballot_crypto.b64e(bytes(raw)))


def test_tally_still_counts_encrypted_ballots(app, api):
    cast_ballot(api, auth_headers(api, 'voter', 'voter1234'))
    delegate = auth_headers(api, 'delegate', 'delegate1234')
    preview = api.get('/api/results', headers=delegate).get_json()
    assert preview['total_ballots'] == 1
    assert sum(row['votes'] for row in preview['house']) == 1
