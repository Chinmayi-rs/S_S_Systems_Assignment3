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

| Username | Password | Role |
| --- | --- | --- |
| voter | voter1234 | Eligible voter, division of Melbourne |
| pending | voter1234 | Voter, not verified yet |
| officer | officer1234 | Enrolment officer |
| delegate | delegate1234 | Commissioner's delegate |
| delegate2 | delegate21234 | Second commissioner's delegate (two-person approvals) |
| auditor | auditor1234 | Auditor |

Sign out before switching accounts. The token lives in the browser's local storage.

## What already works

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
| POST | /api/auth/register | public, voters only |
| POST | /api/auth/login | public |
| POST | /api/auth/logout | signed in |
| GET | /api/auth/profile | signed in |
| GET, PATCH | /api/enrolment/me | signed in / voter |
| GET | /api/enrolment/voters | enrolment officer |
| POST | /api/enrolment/voters/{id}/verify | enrolment officer |
| GET | /api/candidates | public |
| POST | /api/candidates | delegate |
| PATCH | /api/candidates/{id} | delegate |
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
| GR-01 | `User.set_password` / `check_password` and `routes/auth.py` login. Add TOTP, lockout, attempt log. |
| GR-02 | `JWT_ACCESS_TOKEN_EXPIRES` in `app/__init__.py`, plus an idle check in `utils/rbac.py`. |
| GR-03 | `PERMISSIONS` in `utils/rbac.py`. Routes already call `require_permission`. |
| GR-04 | `routes/candidates.py` already writes an audit row with before/after. |
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

Passwords are bcrypt, matching the banking template, until GR-01 switches them to Argon2.

## GR-13 Signed publication of results

- Publishing is a two-delegate action (`results.release`, GR-14). The poll must be closed first. The count is made when the second delegate approves.
- The result is written as canonical JSON (sorted keys, no spaces) together with who proposed it, who approved it and the audit log head. SHA-256 of that JSON is signed with the election's own Ed25519 key, with the prefix `BALLOTDESK-RESULTS-v1|`.
- Stored in `published_results` (one row per election, UPDATE and DELETE blocked by triggers). The key's fingerprint is written to the audit chain (`results.key.registered`).
- The key is encrypted with AES-GCM using `RESULTS_KEY_SECRET` (set it; do not reuse `DELEGATE_KEY_SECRET`).
- Before publication anybody who is not a delegate or auditor gets 403, whether the poll is open or closed. A published poll cannot be reopened.
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
