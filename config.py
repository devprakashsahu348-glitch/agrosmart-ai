"""Application settings. Nothing secret is hard-coded: the session key is generated on first run."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

DATABASE = Path(os.environ.get("AGROSMART_DB", INSTANCE_DIR / "agrosmart.db"))
SCHEMA_FILE = BASE_DIR / "database" / "schema.sql"
DATA_DIR = BASE_DIR / "data"

HOST = os.environ.get("AGROSMART_HOST", "127.0.0.1")   # localhost only; change deliberately to share on a LAN
PORT = int(os.environ.get("AGROSMART_PORT", "5000"))
MAX_CONTENT_LENGTH = 1 * 1024 * 1024                   # 1 MB request limit (the app has no file uploads)


def _load_secret_key():
    """Use AGROSMART_SECRET if set, otherwise create a random key once and keep it in instance/."""
    env = os.environ.get("AGROSMART_SECRET")
    if env:
        return env
    key_file = INSTANCE_DIR / "secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
    return key_file.read_text().strip()


SECRET_KEY = _load_secret_key()
