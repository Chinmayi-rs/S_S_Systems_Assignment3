"""Print fresh ballot keys for a .env file or Docker secrets (GR-09, GR-10).

    python scripts/generate_ballot_keys.py >> .env

Never commit the output. Without these variables the app creates key files in
instance/keys/ on first run, which is fine for local development only.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ballot_keys import generate_env_values  # noqa: E402

if __name__ == '__main__':
    for name, value in generate_env_values().items():
        print(f'{name}={value}')