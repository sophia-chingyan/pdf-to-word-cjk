"""Settings read from environment variables (Railway → service → Variables)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "app.db"

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAIL = os.environ.get("ALLOWED_EMAIL", "").strip().lower()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
CONVERT_API_KEY = os.environ.get("CONVERT_API_KEY", "")

ON_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PUBLIC_DOMAIN"))
_base = os.environ.get("APP_BASE_URL", "").rstrip("/")
if not _base and os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    _base = "https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"]
APP_BASE_URL = _base

# Local development only: skip Google sign-in. Ignored on Railway.
AUTH_DISABLED = os.environ.get("AUTH_DISABLED") == "1" and not ON_RAILWAY

MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_PAGES = 100
SESSION_DAYS = 30


def check() -> None:
    """Exit at boot with a clear message when a required variable is missing."""
    if AUTH_DISABLED:
        return
    missing = [name for name, val in (
        ("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID),
        ("GOOGLE_CLIENT_SECRET", GOOGLE_CLIENT_SECRET),
        ("ALLOWED_EMAIL", ALLOWED_EMAIL),
        ("SESSION_SECRET", SESSION_SECRET),
    ) if not val]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        raise SystemExit(1)
