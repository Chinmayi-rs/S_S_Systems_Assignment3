"""GR-11 demo: play an attacker with database admin rights and change a stored ballot.

    python scripts/tamper_demo.py                 # tamper with the newest ballot
    python scripts/tamper_demo.py --try-normally  # first show the trigger blocking a plain UPDATE

What it does:
1. (optional) Runs a normal UPDATE, which the append-only trigger refuses.
2. Drops the append-only triggers, as only a database admin could.
3. Replaces the newest ballot's ciphertext with another ballot's ciphertext,
   i.e. tries to change one vote into a copy of someone else's.

Then open /integrity as the auditor (or wait up to INTEGRITY_SCAN_SECONDS):
the ballot is quarantined and the results page shows it was not counted.
Restart the app afterwards so the triggers are created again on a fresh DB,
or delete data/*.db to start over.
"""

import argparse
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'data', 'ballot.db')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=DEFAULT_DB, help='path to ballot.db')
    parser.add_argument('--try-normally', action='store_true', help='show the trigger refusing an UPDATE first')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    rows = conn.execute('SELECT id, seq, ciphertext FROM ballots ORDER BY seq').fetchall()
    if len(rows) < 2:
        raise SystemExit('Cast at least two ballots first.')
    target_id, target_seq, _ = rows[-1]
    donor_ciphertext = rows[0][2]

    if args.try_normally:
        try:
            conn.execute('UPDATE ballots SET ciphertext = ? WHERE id = ?', (donor_ciphertext, target_id))
            conn.commit()
            print('UPDATE went through: the trigger is missing.')
        except sqlite3.DatabaseError as exc:
            print(f'Normal UPDATE refused by the database: {exc}')

    conn.execute('DROP TRIGGER IF EXISTS ballots_no_update')
    conn.execute('DROP TRIGGER IF EXISTS ballots_no_delete')
    conn.execute('UPDATE ballots SET ciphertext = ? WHERE id = ?', (donor_ciphertext, target_id))
    conn.commit()
    conn.close()
    print(f'Dropped the triggers and rewrote ballot #{target_seq} ({target_id}).')
    print('Now open /integrity as auditor and press "Run scan now", or wait for the background scan.')


if __name__ == '__main__':
    main()