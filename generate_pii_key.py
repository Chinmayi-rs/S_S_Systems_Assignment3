import base64
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


project_dir = Path(__file__).resolve().parent.parent
secret_dir = project_dir / ".secrets"
secret_dir.mkdir(parents=True, exist_ok=True)

key_path = secret_dir / "pii.key"

try:
    with key_path.open("x", encoding="ascii") as key_file:
        key = AESGCM.generate_key(bit_length=256)
        encoded_key = base64.b64encode(key).decode("ascii")
        key_file.write(encoded_key)
except FileExistsError:
    raise SystemExit(
        "A PII key already exists. It has not been overwritten."
    )

print("PII key created in .secrets/pii.key.")
print("Keep this file private. Do not delete it or upload it.")