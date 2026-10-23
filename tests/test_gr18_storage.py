"""GR-18: date of birth and address are ciphertext in the identity database.

The encryption key stays outside that database (environment variable or key file).
"""
import os

from sqlalchemy import text

from app import db
from app.models.user import User


def test_stored_pii_is_ciphertext_and_the_key_is_not_in_the_database(app):
    address = '99 Secret Gully Road, Carlton'
    dob = '1988-02-02'
    with app.app_context():
        user = User(
            username='pii-store',
            email='pii-store@example.test',
            password='voter1234',
            full_name='PII Store',
            role='voter',
            date_of_birth=dob,
            address=address,
            division='Melbourne',
            enrolled=True,
            eligible=True,
        )
        db.session.add(user)
        db.session.commit()

        row = db.session.execute(
            text(
                'SELECT date_of_birth_encrypted, address_encrypted '
                'FROM users WHERE username = :username'
            ),
            {'username': 'pii-store'},
        ).one()
        assert row.date_of_birth_encrypted.startswith('v1:')
        assert row.address_encrypted.startswith('v1:')
        assert dob not in row.date_of_birth_encrypted
        assert address not in row.address_encrypted
        assert user.date_of_birth == dob
        assert user.address == address

        identity_url = app.config['SQLALCHEMY_DATABASE_URI']
        assert identity_url.startswith('sqlite:///')
        database_path = identity_url[len('sqlite:///'):]
        blob = open(database_path, 'rb').read()

    assert address.encode('utf-8') not in blob
    assert dob.encode('utf-8') not in blob
    assert os.environ['PII_ENCRYPTION_KEY'].encode('ascii') not in blob


def test_key_file_is_accepted_when_the_environment_variable_is_empty(tmp_path, monkeypatch):
    from security.pii_crypto import PIICipher

    key_file = tmp_path / 'pii.key'
    key_file.write_text(os.environ['PII_ENCRYPTION_KEY'], encoding='ascii')
    monkeypatch.delenv('PII_ENCRYPTION_KEY', raising=False)
    monkeypatch.setenv('PII_ENCRYPTION_KEY_FILE', str(key_file))

    cipher = PIICipher.from_environment()
    encrypted = cipher.encrypt('10 Example Street', context='voter:1:address')
    assert cipher.decrypt(encrypted, context='voter:1:address') == '10 Example Street'
