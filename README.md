# Ballot Desk

A small federal-election prototype converted from the class Flask banking template
(Flask, SQLAlchemy, JWT, HTML pages that call a JSON API).

The voter journey works and requirements GR-01 to GR-19 are implemented. GR-20 (the anonymous inclusion
receipt) is the only one still to do. The status of every requirement is listed near the bottom.

## Quick start (Windows)

You need Python 3.11 or newer. Pick **one** of the two ways below. Do not run both at the same time: both use port 8080.

`setup.ps1` is Windows-only and safe to run again. It never overwrites a key, a certificate or a secret you already have. It creates `venv`, installs `requirements.txt`, writes the PII key to `.secrets/pii.key` (GR-18), fills `.env`, and creates the HTTPS certificate in `nginx/certs/` (GR-17).

On macOS or Linux, `setup.ps1` will not run. Use [Run locally (manual steps)](#run-locally-manual-steps) or [Run with Docker](#run-with-docker).

### Run local

Plain HTTP at http://localhost:8080. No Docker.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Run local
```

That sets the project up and starts the app in this window. Stop it with `Ctrl+C`.

To set up first and start later, run `setup.ps1` with no `-Run`, then in the same folder:

```powershell
.\venv\Scripts\Activate.ps1
python run.py
```

`setup.ps1` does not activate the virtual environment in the window you launched it from. `python run.py` without that `Activate` uses system Python and fails.

### Run Docker

HTTPS with TLS 1.3 at https://localhost:8443. Needs Docker Desktop running. Do not use port 443. The certificate is self-signed: click **Advanced**, then **Proceed to localhost**. `http://localhost:8080` only redirects to that HTTPS address.

Stop `python run.py` first if it is already running.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Run docker
```

Stop the containers with `Ctrl+C`, or `docker compose down` from another terminal.

## Run locally (manual steps)

Do these steps in this order, from the project folder. `scripts/generate_pii_key.py` and
`scripts/generate_certificate.py` import `cryptography`, so they fail if you run them before
`pip install`.

**1. Create a virtual environment and install the requirements.**

PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

If a `venv` folder is already in the project but it was created on another operating system
(for example a Windows `venv\Scripts` tree checked out on Linux), delete that folder and
create it again. A venv cannot be copied between operating systems.

**2. Create `.env` and the PII key.** The app will not start without `PII_ENCRYPTION_KEY`.

PowerShell:

```powershell
Copy-Item .env.example .env
python scripts/generate_pii_key.py
$k = (Get-Content -Raw .secrets/pii.key).Trim()
(Get-Content .env) -replace '^PII_ENCRYPTION_KEY=.*', "PII_ENCRYPTION_KEY=$k" | Set-Content .env
```

macOS / Linux:

```bash
cp .env.example .env
python scripts/generate_pii_key.py
k=$(tr -d '[:space:]' < .secrets/pii.key)
perl -i -pe 's/^PII_ENCRYPTION_KEY=.*/PII_ENCRYPTION_KEY='"$k"'/' .env
```

Then replace every remaining `change-me` value in `.env` (`SECRET_KEY`, `JWT_SECRET_KEY`,
`RESULTS_KEY_SECRET`, `DELEGATE_KEY_SECRET`) with a different long random string:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Keep `.secrets/pii.key` private and do not delete it. Without that key, data that was already
encrypted cannot be read. Both `.env` and `.secrets/` are git-ignored.

Ballot encryption keys are created automatically in `instance/keys/` the first time the app
starts, unless you set `BALLOT_ENC_KEY`, `BALLOT_TAG_KEY` and `BALLOT_SIGNING_KEY`.

**3. Start the app** with the virtual environment still active, from the project folder:

```bash
python run.py
```

The process listens on `127.0.0.1` and port 8080 (`HOST` and `PORT` override those).
Open http://localhost:8080. This local process is plain HTTP. TLS is the Docker path below.

**4. Get the sign-in code.** Every account needs a password and a 6-digit code. The code
changes every 30 seconds. In a second terminal, activate the same virtual environment and
run, from the project folder:

```bash
python scripts/totp_codes.py             # codes for all seeded accounts
python scripts/totp_codes.py delegate    # one account
python scripts/totp_codes.py --watch     # refresh until Ctrl+C
```

**5. Run the tests** (optional), still from the project folder with the venv active:

```bash
python -m pytest
```

The tests create their own temporary databases and a throwaway PII key. They do not use your
`.env` or `data/`.

The first local start creates `data/identity.db` and `data/ballot.db`. If you update from an
older checkout and see `no such column ...`, stop the app, delete those two files, and start
again.

## Run with Docker

Needs Docker Desktop (Windows/macOS) or Docker Engine with the Compose plugin. nginx serves
HTTPS with TLS 1.3 only (GR-17). The Flask process inside the container is not published.

**Before the first start**, from the project folder:

1. Install the requirements (step 1 above) or run `setup.ps1` on Windows. The certificate
   script needs `cryptography`.
2. Create `.env` with a real `PII_ENCRYPTION_KEY` (step 2 above). Compose reads that one
   variable from `.env` in the project folder. If it is missing, `docker compose` stops with
   `Missing PII key`. The container does **not** load the rest of `.env`. `SECRET_KEY`,
   `JWT_SECRET_KEY` and `RESULTS_KEY_SECRET` come from the `environment:` block in
   `docker-compose.yml` (the `dev-...-change-me` values). Change those in the compose file
   before you show or share the app. `DELEGATE_KEY_SECRET` is not passed in; the container
   uses the built-in development default.
3. Create the certificate once (skip this if `setup.ps1` already did it):

```bash
python scripts/generate_certificate.py
```

That writes `nginx/certs/localhost.crt` and `nginx/certs/localhost.key`. If either file
already exists, the script exits and does not overwrite them.

**Start** (stop `python run.py` first, or port 8080 is already taken):

```bash
docker compose up --build
```

**Open https://localhost:8443. Do not use port 443.** The certificate is self-signed, so the
browser shows a warning. Click **Advanced**, then **Proceed to localhost**.

`http://localhost:8080` answers `308` and redirects to `https://localhost:8443`. The health
check is https://localhost:8443/health. Stop with `Ctrl+C`, or `docker compose down` from
another terminal.

| Task | Command (while the containers are running) |
| --- | --- |
| Get the sign-in code for every seeded account | `docker compose exec web python scripts/totp_codes.py` |
| Code for one account | `docker compose exec web python scripts/totp_codes.py delegate` |
| Run the tests | `docker compose exec web python -m pytest` |
| See the app log | `docker compose logs -f web` |
| See the container status | `docker compose ps` |
| Rebuild after changing code or `requirements.txt` | `docker compose up --build` |

Things to know:

- **The database is temporary.** `docker-compose.yml` keeps `/app/data` in memory (`tmpfs`), so
  every time the container stops or restarts the databases are wiped and the seeded accounts and
  election are created again. You do not delete `.db` files when you use Docker.
- **Only nginx is reachable from the host.** It is bound to `127.0.0.1` (ports 8080 and 8443),
  not to your LAN address. The `web` container has no published port.
- **Nothing secret goes into the image.** `.dockerignore` excludes `.env`, `.secrets/`,
  `nginx/certs/`, `venv/`, `.git/` and `data/`. The certificate is mounted into nginx at start.

## Seeded desks

Every account signs in with a password **and** a 6-digit TOTP code (GR-01).
Seeded accounts come with the second factor already enrolled; add the secret
below to any authenticator app (Google Authenticator, Aegis, 1Password, or
`oathtool --totp -b <secret>` on the command line) to get codes.

| Username | Password | TOTP secret | Role |
| --- | --- | --- | --- |
| voter | voter1234 | `F3JDIRDOT2NPZNQD77RM6MG46LP6TEEN` | Eligible voter, division of Melbourne |
| pending | voter1234 | `QQUXICP2GWC4UT265ASHG5VBAJTMBQ4I` | Voter, not verified yet |
| officer | officer1234 | `372NDDK6FFEQHLLAP2SNX5BBVTX5XHCX` | Enrolment officer |
| delegate | delegate1234 | `6XJJFZNCSXNGL7B5ZUWDATKXVBBAADXR` | Commissioner's delegate |
| delegate2 | delegate21234 | `4KP7JD73VZVYRP2NRQN5WCKLNQNHRPRB` | Second commissioner's delegate (two-person approvals) |
| auditor | auditor1234 | `K2B27OBNXWQSCU6EJOM76DE3TW3PYSQS` | Auditor |

**Getting the 6-digit code.** The code changes every 30 seconds, so it cannot be written in the
table: a number copied from here would already have expired. Use the command from step 4 of
"Run locally" (with Docker: `docker compose exec web python scripts/totp_codes.py`), or from the
project root run

```bash
python scripts/totp_codes.py             # current code for every seeded account
python scripts/totp_codes.py delegate    # one account
python scripts/totp_codes.py --watch     # keeps refreshing until Ctrl+C
```

and type the code it prints for the account you are signing in with, within the 30 seconds shown.

Accounts registered through the UI enrol their own authenticator with a QR
code before their first session exists. To demo that flow, just register a
new voter.

Sign out before switching accounts. The token lives in the browser's local storage.

**Upgrading an existing checkout:** GR-01/GR-02 added columns and a table.
Delete `data/identity.db` (or the Docker tmpfs restarts clean anyway) so
`db.create_all()` rebuilds the schema.

## What already works

- Sign-in needs a password (Argon2id-hashed) plus an authenticator code; five consecutive failures lock the account for 15 minutes (GR-01).
- Sessions die after 15 minutes of inactivity and on sign-out, server-side, on every endpoint (GR-02).
- Every API endpoint checks the caller's role against one deny-by-default permission map; denied attempts are audit-logged (GR-03).
- Candidate create, update and ballot reordering are delegate-only with before/after audit rows; deletion is refused by design (GR-04).
- Register a voter (not eligible until an officer verifies them).
- Update address and division until a ballot is accepted.
- Officer verifies a voter onto the Melbourne roll.
- Delegate adds or withdraws a candidate and opens or closes the poll.
- Voter numbers every House candidate and picks one Senate group above the line, reviews, then submits.
- A second ballot for the same voter is rejected.
- Results are a first-preference count. Hidden from everyone but a delegate or auditor (preview) until two delegates publish them with an Ed25519 signature (GR-13). Closing the poll does not publish them.
- Auditor can read an action log. A committed ballot is logged with no voter and no preferences.
- Ballots are encrypted (AES-256-GCM) and signed (Ed25519) before they are stored, and cannot be linked to the voter (GR-09, GR-10).
- The ballot store is append-only and hash-chained; a background scan every 30 seconds quarantines any ballot that was changed (GR-11).
- Two independent counters must agree before results can be published (GR-12).
- Result-affecting actions (close or reopen the poll, withdraw a candidate, publish results) need two different delegates: the proposer picks the approver, and self-approval is refused (GR-14).
- The audit log is hash-chained and cannot be edited or deleted; the auditor can verify the whole chain (GR-15).
- Every delegate action is signed with that delegate's own Ed25519 key and can be checked offline (GR-16).
- In Docker, nginx serves the app over HTTPS with TLS 1.3 only and redirects plain HTTP (GR-17).
- Voter date of birth and address are encrypted at rest; the key is kept outside the database (GR-18).
- GitHub Actions runs the tests, a Bandit scan and a dependency audit on every push and pull request (GR-19).

House counting is first preference only. Senate is above-the-line only. Full preferential distribution and STV are out of this skeleton on purpose.

## Layout

```
app/
  models/          users, elections, candidates, ballot tokens, ballots, audit events
  routes/          one blueprint per resource
  services/        ballot box, tally, audit, seed
  utils/rbac.py    permission map (deny if the role is not listed)
templates/         pages
security/          PII encryption (GR-18)
nginx/             HTTPS settings (GR-17); certificates are generated into nginx/certs/
scripts/           key and certificate generators, sign-in codes, offline verifiers, tamper demo
.github/workflows/ CI pipeline (GR-19)
static/js          same fetch + Bearer token pattern as the banking template
data/              identity.db and ballot.db (created on first run)
```

Two SQLite files stand in for the two databases:

- `identity.db` — people, enrolment, candidates, one-time token hashes, audit
- `ballot.db` — ballots only. The ballot table has no voter id column.

`BallotToken` (identity) stores a SHA-256 of a random token. The ballot side stores a different value, an HMAC of the same token with a key held outside both databases (GR-09), so the two databases cannot be joined without the raw token. The raw token is returned once to the browser.

## API

| Method | Path | Who |
| --- | --- | --- |
| POST | /api/auth/register | public, voters only; returns a provisional token for MFA enrolment |
| POST | /api/auth/login | public, body `{ "username", "password", "totp_code" }`; without `totp_code` it answers `mfa_required` |
| POST | /api/auth/mfa/setup | provisional or signed in; returns TOTP secret, otpauth URI and QR data URI |
| POST | /api/auth/mfa/enable | provisional, body `{ "totp_code" }`; verifies the code and starts the first full session |
| POST | /api/auth/logout | signed in; revokes the session server-side |
| GET | /api/auth/profile | signed in |
| GET, PATCH | /api/enrolment/me | signed in / voter |
| GET | /api/enrolment/voters | enrolment officer |
| POST | /api/enrolment/voters/{id}/verify | enrolment officer |
| GET | /api/auth/permissions | signed in; the caller's role and its allowed permissions |
| GET | /api/candidates | public |
| POST | /api/candidates | delegate |
| PATCH | /api/candidates/{id} | delegate |
| POST | /api/candidates/reorder | delegate, body `{ "chamber", "order": [all ids of that chamber, new order] }` |
| DELETE | /api/candidates/{id} | delegate, always 405: deletion does not exist, withdrawal is the GR-14 approval flow |
| GET | /api/elections/current | public |
| POST | /api/elections/current/status | delegate, body `{ "status": "open" \| "closed" }` |
| GET | /api/ballots/status | voter |
| POST | /api/ballots/issue | voter |
| POST | /api/ballots/stage | voter, body `{ "token", "house": [ids in preference order], "senate_party" }` |
| POST | /api/ballots/commit | voter, body `{ "token" }` |
| GET | /api/ballots/public-key | public: the Ed25519 key that verifies ballot signatures (GR-10) |
| GET | /api/results | public only after the signed publication (403 before); delegate and auditor may preview |
| GET | /api/results/public-key | public after publication: results public key and fingerprint |
| GET | /api/results/verify | public after publication: the server re-checks the stored signature |
| POST | /api/approvals | delegate, body `{ "action_type": "results.release", "approver_id" }` proposes publishing |
| GET | /api/audit | auditor |
| GET | /api/integrity | delegate, auditor: scan history and quarantined ballots (GR-11) |
| POST | /api/integrity/scan | delegate, auditor: run the integrity scan now (GR-11) |

## Status of the 20 requirements

| ID | Status |
| --- | --- |
| GR-01 | Done: Argon2id in `models/user.py`, TOTP + lockout + attempt log in `routes/auth.py`, enrolment UI at `/mfa-setup` (see below). |
| GR-02 | Done: `models/session.py` + `services/sessions.py`; the blocklist hook in `app/__init__.py` idle-expires every endpoint (see below). |
| GR-03 | Done: deny-by-default `PERMISSIONS` map in `utils/rbac.py`, audited denials, `/api/auth/permissions`, and a test that walks every API route (see below). |
| GR-04 | Done: delegate-only create/update/reorder with before/after audit rows, input bounds, and deletion explicitly refused (see below). |
| GR-05 | Done: eligibility checks and an atomic double-vote guard in `services/ballot_box.py` (`issue_token`, `commit_ballot`). |
| GR-06 | Done: single-use token; the two databases hold different values for it (see GR-09). |
| GR-07 | Done: the ballot commit is logged with no voter and no preferences (`services/audit_log.py`). |
| GR-08 | Done: stage, review, commit flow in `templates/vote.html` and `services/ballot_box.py`. |
| GR-09 | Done: `services/ballot_crypto.py`, `ballot_store.py`, `ballot_keys.py` (see below). |
| GR-10 | Done: `services/ballot_signing.py` (see below). |
| GR-11 | Done: `services/ballot_chain.py`, `ballot_integrity.py`, `/integrity` page (see below). |
| GR-12 | Done: counter A (`tally_primary.py`), counter B (`tally_secondary.py`, written independently) and the gate (`tally_gate.py`) (see below). |
| GR-13 | Done: `services/results_publication.py`, `routes/results.py`, `scripts/verify_results.py` (see below). |
| GR-14 | Done: `services/approvals.py`, `routes/approvals.py`, `models/approval.py`. |
| GR-15 | Done: `services/audit_chain.py`, `services/audit_log.py`, `routes/audit.py`. |
| GR-16 | Done: `services/action_signing.py`, `scripts/verify_proof.py`. |
| GR-17 | Done: `nginx/default.conf` (TLS 1.3 only, HTTP redirect), `scripts/generate_certificate.py` (see below). |
| GR-18 | Done: `security/pii_crypto.py` and the encrypted columns in `models/user.py` (see below). |
| GR-19 | Done: `.github/workflows/security-ci.yml` (tests, Bandit, pip-audit). |
| GR-20 | Not done yet: `commit` returns a reference id, not a receipt hash. |

## GR-03 Role-based access control (deny by default)

- One reviewed map (`PERMISSIONS` in `app/utils/rbac.py`) decides who may do
  what. Routes declare a permission name, never a role, so a permission that
  is not in the map denies **everyone** - a typo fails closed.
- Denied attempts by signed-in users are written to the GR-15 audit chain as
  `rbac.denied` (actor, role and the permission they tried).
- `GET /api/auth/permissions` returns the caller's role and allowed
  permissions straight from the real map.
- `tests/test_rbac.py` walks the live routing table and asserts every `/api`
  endpoint outside a short public list answers 401 to anonymous callers, and
  checks a role-by-endpoint matrix for all four roles.

## GR-04 Secure candidate management

- Create, update and ballot reordering are delegate-only (via GR-03) and every
  change writes actor, timestamp and before/after values to the audit chain
  (`candidate.create`, `candidate.update`, `candidate.reorder`).
- `POST /api/candidates/reorder` must list every candidate of the chamber
  exactly once, so a reorder can never drop or smuggle in a candidate.
- `DELETE` is refused by design (405): deletion would erase audit context;
  withdrawing a candidate is the GR-14 two-delegate approval flow.
- Free-text fields are length-bounded so the admin screen cannot stuff junk
  into what every voter's ballot renders.

## GR-01 Password + TOTP sign-in, lockout

- Passwords are hashed with **Argon2id** (`argon2-cffi`). Hashes created before
  this change (bcrypt, from the banking template) still verify and are upgraded
  to Argon2 in place on the next successful sign-in.
- Every account has a **TOTP second factor** (`pyotp`). Sign-in is two steps:
  the password alone only earns the code prompt (`mfa_required`), never a token.
- An account that has not enrolled an authenticator yet gets a **provisional
  token** (10 minutes, claim `scope=mfa_setup`) that can only call
  `/api/auth/mfa/setup` and `/api/auth/mfa/enable`. The RBAC layer rejects it
  everywhere else, so there is no session of any kind before both factors exist.
  This is also what makes GR-02's "privileged users require MFA" hold: staff
  cannot reach staff endpoints without finishing enrolment.
- **Lockout:** 5 consecutive failures (wrong password or wrong code) lock the
  account for 15 minutes. While locked, even the correct password + code gets
  `423`. Configurable via `LOGIN_LOCKOUT_THRESHOLD` / `LOGIN_LOCKOUT_MINUTES`.
- **Every attempt is logged** to the GR-15 audit chain: `auth.login`,
  `auth.login_failed`, `auth.login_blocked`, `auth.lockout`, `auth.mfa_setup`,
  `auth.mfa_enabled`, `auth.logout`.

## GR-02 Sessions: 15-minute idle timeout, server-side revocation

- Every full token is recorded in the `user_sessions` table, keyed by the JWT's
  `jti`. flask-jwt-extended's blocklist hook checks that row on **every**
  verified request, so no route can forget the check.
- A request after more than `SESSION_IDLE_MINUTES` (default 15) of inactivity
  marks the session revoked (`idle_timeout`) and answers 401. Activity slides
  the window: each authenticated request refreshes `last_seen`.
- Sign-out revokes the session row, so the JWT is dead even though its
  signature is still valid. A forged-but-signed token without a session row is
  rejected the same way.
- The JWT's own expiry (`JWT_MAX_HOURS`, default 12) is only an absolute cap.

## GR-13 Signed publication of results

- Publishing is a two-delegate action (`results.release`, GR-14). The poll must be closed first. The count is made when the second delegate approves.
- The result is written as canonical JSON (sorted keys, no spaces) together with who proposed it, who approved it and the audit log head. SHA-256 of that JSON is signed with the election's own Ed25519 key, with the prefix `BALLOTDESK-RESULTS-v1|`.
- Stored in `published_results` (one row per election, UPDATE and DELETE blocked by triggers). The key's fingerprint is written to the audit chain (`results.key.registered`).
- The key is encrypted with AES-GCM using `RESULTS_KEY_SECRET` (set it; do not reuse `DELEGATE_KEY_SECRET`).
- Before publication anybody who is not a delegate or auditor gets 403, whether the poll is open or closed. While a publish request is waiting, nobody can send a request to reopen the poll (and no publish request can be sent while a reopen request is waiting). A published poll cannot be reopened.
- GR-12 is enforced when the second delegate approves the release: `tally_gate.dual_tally()` must release the counts, or the approval is refused (409) and the request stays waiting. The signed result is built from the same checked counts.

Check a result offline (needs only `pip install cryptography`). Download the three files from the Results page, then:

```bash
python scripts/verify_results.py results.json results.sig.json results.pub.json --fingerprint <key fingerprint you trust>
```

Limits to state in the report:

- The public key must come from a trusted channel (the report, or the `results.key.registered` audit entry). If you trust an impostor's key, the signature means nothing.
- The private key sits on the server. Anyone who takes the server and `RESULTS_KEY_SECRET` could sign a false result. Production should use an HSM or KMS.
- The signature shows this is the published result and it was not changed afterwards. It does not show the count was right (GR-11, GR-12).
- One result per election. A recount after publication would need a `version` column.

## GR-09 Ballot encryption and identity separation

- `services/ballot_crypto.py` encrypts each ballot with **AES-256-GCM** and a random 96-bit nonce. The election id and ballot id are bound in as associated data, so a ciphertext copied into another row fails to decrypt.
- Every ballot is **padded to 512 bytes** before encryption, so the ciphertext length does not reveal the vote.
- **Token tag.** The identity database stores `SHA-256(token)` next to the voter. The ballot database stores `HMAC(tag key, token)`. Without the raw token, which only the voter's browser holds, the two cannot be matched.
- **Separate tables.** `staged_ballots` holds a ballot during review and is deleted in the same transaction that writes the final row to `ballots`. The final row gets a fresh random id and a fresh encryption.
- Ballot timestamps are rounded to the hour. No ballot table has a voter column or a foreign key to the identity database.
- **Keys** (`services/ballot_keys.py`) never live in either database. They come from `BALLOT_ENC_KEY`, `BALLOT_TAG_KEY` and `BALLOT_SIGNING_KEY`, or in development from files in `instance/keys/` (created on first run, git-ignored). Generate production values with `python scripts/generate_ballot_keys.py`.

## GR-10 Ballot digital signatures

- `services/ballot_signing.py` signs each ballot with **Ed25519** when it is encrypted. The signature covers the election id, ballot id, nonce and ciphertext, never the plaintext.
- A SQLAlchemy `before_insert` hook verifies the signature. An unsigned or forged ballot raises `UnsignedBallotError`, the whole transaction rolls back, and the voter is not marked as voted.
- Signatures are checked again at tally time (`ballot_store.read_verified_ballots()`). Ballots that fail are not counted and are reported as `rejected_ballots`.
- `GET /api/ballots/public-key` publishes the verify key.

## GR-11 Append-only, hash-chained ballot store

- Each ballot stores `seq`, `prev_hash` and `record_hash = SHA-256(prev_hash | every stored field)`, one chain per election (`services/ballot_chain.py`).
- **Append-only, two layers:** ORM `before_update` / `before_delete` hooks, and database triggers that abort any `UPDATE` or `DELETE`, even raw SQL. SQLite triggers are used now; Postgres trigger DDL is included but untested.
- **Integrity scan** (`services/ballot_integrity.py`) runs on a background thread every 30 seconds (`INTEGRITY_SCAN_SECONDS`, `0` turns it off). It checks each ballot's hash, signature and GCM tag, then the whole chain: sequence gaps, broken links, and the ballot count against tokens marked used in the identity database (this catches a deleted tail).
- A failing ballot is recorded in `quarantined_ballots` and is no longer counted. The audit log gets `ballot.quarantined` and `ballot.integrity_alert` with the ballot id and reason only.
- The **Integrity** page (`/integrity`, delegate and auditor) shows scan history and quarantined ballots, with a **Run scan now** button.
- Demo: `python scripts/tamper_demo.py --try-normally` shows a plain `UPDATE` refused by the trigger, then drops the trigger (as a database admin could) and rewrites a ballot. The next scan quarantines it.

## GR-12 Dual independent tally

- Counter A is `services/tally_primary.py`. Counter B is `services/tally_secondary.py`, written by a different team member without reading or importing counter A (a test checks the imports). Its docstring gives the exact input and output format.
- `services/tally_gate.py` gives each counter its own copy of the same verified ballots, then checks and compares the two results. Release is blocked if a counter is missing, crashes, returns a malformed result, or disagrees. A disagreement writes a `tally.mismatch` alert to the audit log.
- The gate runs when the second delegate approves `results.release`. A blocked tally refuses the approval (409); nothing is signed or published.
- Delegates and auditors see the reason on the Results preview (`release_blocked`, `release_reason`, `tally_differences`).
- **Fail closed.** If a counter is ever missing or broken, results cannot be published. Tests that need a missing counter simulate it with `monkeypatch`.

Limits to state in the report:

- No HSM. Ballot keys are held outside the databases (environment variables, Docker secrets or `instance/keys/`). Production would use an HSM or cloud KMS.
- A database admin can still drop the triggers and edit rows, so tampering cannot be prevented, only detected and quarantined.
- The identity and ballot databases commit through one session without two-phase commit.
- `BallotToken.used_at` is a precise timestamp and ballots are stored in commit order, so the two orders could be compared to link voters to ballots. Rounding or dropping `used_at` would close this.
- Counting is first preference only, matching the skeleton.

## GR-17 HTTPS with TLS 1.3

- nginx (`nginx/default.conf`) terminates TLS and forwards requests to the `web` container. Only **TLS 1.3** is enabled and session tickets are off.
- Plain HTTP on `http://localhost:8080` answers `308` and redirects to `https://localhost:8443`.
- `scripts/generate_certificate.py` creates a self-signed certificate for `localhost` in `nginx/certs/`. The folder is mounted read-only into nginx, and it is git-ignored and kept out of the Docker image.
- Open the app at `https://localhost:8443` (not port 443). The browser warns about the self-signed certificate: click **Advanced**, then **Proceed to localhost**.

Limits to state in the report: the certificate is self-signed, so a real deployment needs one from a trusted authority. TLS protects traffic between the browser and nginx; the hop from nginx to the app stays inside Docker's private network.

## GR-18 Voter PII encryption at rest

- `security/pii_crypto.py` encrypts each voter's `date_of_birth` and `address` before they are saved, and decrypts them when the `User` model reads them.
- Each user has their own `pii_context_id`, which is bound into the encryption, so a value copied into another user's row does not decrypt.
- The key is supplied through `PII_ENCRYPTION_KEY` (a Base64 32-byte key). The app will not start without it. Create one with `python scripts/generate_pii_key.py`; it is saved to `.secrets/pii.key`.
- The identity database holds only the encrypted text (`date_of_birth_encrypted`, `address_encrypted`).
- Tests are in `tests/test_pii_crypto.py`.