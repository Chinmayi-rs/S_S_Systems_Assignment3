"""Print the current 6-digit sign-in code for the seeded demo accounts.

    python scripts/totp_codes.py              all seeded accounts
    python scripts/totp_codes.py delegate     one account
    python scripts/totp_codes.py --watch      keep refreshing until Ctrl+C

Run it from the project root. A code is only valid for the 30-second window it was made in,
so a code written down earlier will not work: run the command again and use the new one.
Demo accounts only - the secrets are derived from the username (see app/services/seed.py).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyotp  # noqa: E402

from app.services.seed import PEOPLE, deterministic_totp_secret  # noqa: E402


def usernames(requested):
    seeded = [person[0] for person in PEOPLE]
    if not requested:
        return seeded
    unknown = [name for name in requested if name not in seeded]
    if unknown:
        sys.exit('Not a seeded account: %s. Seeded accounts: %s' % (', '.join(unknown), ', '.join(seeded)))
    return requested


def show(names):
    now = time.time()
    left = 30 - int(now) % 30
    print('%-12s %-8s %s' % ('account', 'code', 'valid for'))
    for name in names:
        code = pyotp.TOTP(deterministic_totp_secret(name)).now()
        print('%-12s %-8s %2d s' % (name, code, left))


def main(argv):
    watch = '--watch' in argv
    names = usernames([arg for arg in argv if not arg.startswith('--')])
    if not watch:
        show(names)
        return
    try:
        while True:
            print('\033[2J\033[H', end='')  # clear the screen
            show(names)
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main(sys.argv[1:])
