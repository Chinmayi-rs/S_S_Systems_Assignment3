# Ballot Desk

A small federal-election prototype converted from the class Flask banking template
(Flask, SQLAlchemy, JWT, HTML pages that call a JSON API).

This is a **skeleton**. The voter journey works. The 20 security requirements are
not implemented yet. The seams they plug into are listed at the bottom.

## Run

```bash
cd votingapp
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
| auditor | auditor1234 | Auditor |

Sign out before switching accounts. The token lives in the browser's local storage.

## What already works

- Register a voter (not eligible until an officer verifies them).
- Update address and division until a ballot is accepted.
- Officer verifies a voter onto the Melbourne roll.
- Delegate adds or withdraws a candidate and opens or closes the poll.
- Voter numbers every House candidate and picks one Senate group above the line, reviews, then submits.
- A second ballot for the same voter is rejected.
- Results are a first-preference count. Hidden while the poll is open, except to a delegate or auditor. Public after close.
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
| GET | /api/results | public only after close; delegate and auditor may preview |
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
| GR-13 | `routes/results.py` publication gate. |
| GR-14 | New approvals table in front of close / exclude / publish. |
| GR-15 | Hash-chain `AuditEvent` in `services/audit_log.py`. |
| GR-16 | Per-delegate signing key, stored with the audit row. |
| GR-17 | nginx in `docker-compose.yml`. The app itself is still plain HTTP. |
| GR-18 | `date_of_birth` and `address` on `User` are still plaintext. |
| GR-19 | `tests/test_flow.py` is the start. CI workflow is not added. |
| GR-20 | `commit` returns a reference id, not a hash of ciphertext. |

Passwords are bcrypt, matching the banking template, until GR-01 switches them to Argon2.
