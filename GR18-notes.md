# GR-18 Voter PII Encryption at Rest

## Implementation
- Voter dates of birth and addresses are encrypted using AES-256-GCM.
- Each encryption operation uses a fresh random nonce.
- A stable per-user identifier and field name bind each encrypted value
  to its intended user and field.
- The User model encrypts values before database storage and decrypts
  them when application code reads the corresponding properties.
- Route permissions remain responsible for controlling access.
- The encryption key is supplied through PII_ENCRYPTION_KEY.
- Application startup rejects a missing or invalid key.

## Local setup
Run these commands from the project folder in PowerShell.

Create an environment:
python -m venv .venv

Install dependencies:
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

Generate a key once:
.\.venv\Scripts\python.exe scripts/generate_pii_key.py

Load the existing key:
$env:PII_ENCRYPTION_KEY = (Get-Content -Raw .secrets/pii.key).Trim()

Start the application:
.\.venv\Scripts\python.exe run.py

Do not replace the key for an existing encrypted database.
Never upload .secrets/pii.key.

## Tests
Run:
.\.venv\Scripts\python.exe -m pytest -v

Verified locally:
- 16 tests passed.
- Database inspection showed ciphertext for both protected fields.
- Address updates remained encrypted.
- The updated address was recovered after restarting with the same key.
- Tests covered registration, encryption integrity and selected
  enrolment access restrictions.

## Docker
With Docker Desktop running, load the key in the same terminal:
$env:PII_ENCRYPTION_KEY = (Get-Content -Raw .secrets/pii.key).Trim()

Build and start:
docker compose up --build -d

Check status:
docker compose ps

The Docker application built, started and passed its health check.

## Limitations and integration requirements
- Verified using a fresh database.
- Existing plaintext databases require a tested migration or an
  agreed rebuild of disposable development data.
- Docker currently uses temporary tmpfs database storage.
- Local key storage uses an ignored file; production secret management
  and key rotation are not implemented.
- Compatibility with teammates' newer branches requires review.