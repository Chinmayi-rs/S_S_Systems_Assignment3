# Ballot Desk

A small federal-election prototype converted from the class Flask banking template
(Flask, SQLAlchemy, JWT, HTML pages that call a JSON API).

This is a **skeleton**. The voter journey works. The 20 security requirements are
not implemented yet. The seams they plug into are listed at the bottom.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The app listens on port 8080. Override with `PORT`.

```bash
pytest
```

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
- Register a voter (not eligible until an officer verifies them).
- Update address and division until a ballot is accepted.
- Officer verifies a voter onto the Melbourne roll.
- Delegate adds or withdraws a candidate and opens or closes the poll.
- Voter numbers every House candidate and picks one Senate group above the line, reviews, then submits.
- A second ballot for the same voter is rejected.
- Results are a first-preference count. Hidden from everyone but a delegate or auditor (preview) until two delegates publish them with an Ed25519 signature (GR-13). Closing the poll does not publish them.
- Auditor can read an action log. A committed ballot is logged with no voter and no preferences.

House counting is first preference only. Senate is above-the-line only. Full preferential distribution and STV are out of this skeleton on purpose.

## Layout

```
app/
  models/          users, elections, candidates, ballot tokens, ballots, audit events
  routes/          one blueprint per resource
  services/        ballot box, tally, audit, seed
  utils/rbac.py    permission map (deny if the role is not listed)
templates/         pages
static/js          same fetch + Bearer token pattern as the banking template
data/              identity.db and ballot.db (created on first run)
```

Two SQLite files stand in for the two databases:

- `identity.db` — people, enrolment, candidates, one-time token hashes, audit
- `ballot.db` — ballots only. The ballot table has no voter id column.

`BallotToken` (identity) and `Ballot` (ballot) meet only by a SHA-256 of a random token. The raw token is returned once to the browser.

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
| GET | /api/results | public only after the signed publication (403 before); delegate and auditor may preview |
| GET | /api/results/public-key | public after publication: results public key and fingerprint |
| GET | /api/results/verify | public after publication: the server re-checks the stored signature |
| POST | /api/approvals | delegate, body `{ "action_type": "results.release", "approver_id" }` proposes publishing |
| GET | /api/audit | auditor |

## Where the 20 requirements plug in

Not built yet. Do not treat the notes below as the implementation.

| ID | Extend |
| --- | --- |
| GR-01 | Done: Argon2id in `models/user.py`, TOTP + lockout + attempt log in `routes/auth.py`, enrolment UI at `/mfa-setup` (see below). |
| GR-02 | Done: `models/session.py` + `services/sessions.py`; the blocklist hook in `app/__init__.py` idle-expires every endpoint (see below). |
| GR-03 | Done: deny-by-default `PERMISSIONS` map in `utils/rbac.py`, audited denials, `/api/auth/permissions`, and a test that walks every API route (see below). |
| GR-04 | Done: delegate-only create/update/reorder with before/after audit rows, input bounds, and deletion explicitly refused (see below). |
| GR-05 | `services/ballot_box.py` `issue_token` and `commit_ballot`, together with `users.has_voted`. |
| GR-06 | Token hash split is already the shape. Still need unlinkability review. |
| GR-07 | `services/audit_log.py`. Ballot commit already omits actor and preferences. |
| GR-08 | `templates/vote.html` review step and stage/commit. |
| GR-09 | `SQLALCHEMY_BINDS`. Swap the two SQLite URLs for Postgres, then encrypt the ballot body. |
| GR-10 | Sign inside `commit_ballot` before the row is stored. |
| GR-11 | Ballot model plus a database role that cannot update or delete. |
| GR-12 | Add a second tally module that does not import `services/tally.py`. |
| GR-13 | Done: `services/results_publication.py`, `routes/results.py`, `scripts/verify_results.py` (see below). |
| GR-14 | New approvals table in front of close / exclude / publish. |
| GR-15 | Hash-chain `AuditEvent` in `services/audit_log.py`. |
| GR-16 | Per-delegate signing key, stored with the audit row. |
| GR-17 | nginx in `docker-compose.yml`. The app itself is still plain HTTP. |
| GR-18 | `date_of_birth` and `address` on `User` are still plaintext. |
| GR-19 | `tests/test_flow.py` is the start. CI workflow is not added. |
| GR-20 | `commit` returns a reference id, not a hash of ciphertext. |

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
- `GR-12` plugs in at `counts_agree()` in `services/results_publication.py`. It returns True until the second counter exists.

Check a result offline (needs only `pip install cryptography`). Download the three files from the Results page, then:

```bash
python scripts/verify_results.py results.json results.sig.json results.pub.json --fingerprint <key fingerprint you trust>
```

Limits to state in the report:

- The public key must come from a trusted channel (the report, or the `results.key.registered` audit entry). If you trust an impostor's key, the signature means nothing.
- The private key sits on the server. Anyone who takes the server and `RESULTS_KEY_SECRET` could sign a false result. Production should use an HSM or KMS.
- The signature shows this is the published result and it was not changed afterwards. It does not show the count was right (GR-11, GR-12).
- One result per election. A recount after publication would need a `version` column.
