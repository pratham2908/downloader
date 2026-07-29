"""Runtime configuration from environment (and an optional local ``.env``).

Centralises every knob so both local and hosted deployments read from one place.
All are optional — with none set, the app behaves exactly like the local tool.

  MONGODB_URI / MONGODB_DB_NAME   shared channels + history (see db.py)
  REEL_HOSTED                     hosted mode: hide local-only UI, expect auth
  REEL_PASSWORD                   if set, require Basic-auth to use the app
  REEL_DOWNLOAD_DIR               force the download folder (server path)
  REEL_COOKIES_FILE               path to a cookies.txt for yt-dlp
  REEL_COOKIES_FROM_BROWSER       e.g. "chrome" — pull cookies from a browser
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv() -> None:
    """Minimal .env loader — real environment variables always win."""
    if not _ENV_PATH.exists():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI") or None
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "youtube_automation")

# Deployment mode
HOSTED = _bool("REEL_HOSTED")
PASSWORD = os.getenv("REEL_PASSWORD") or None
DOWNLOAD_DIR_OVERRIDE = os.getenv("REEL_DOWNLOAD_DIR") or None

# yt-dlp cookies (to get past datacenter-IP bot checks when hosted)
COOKIES_FILE = os.getenv("REEL_COOKIES_FILE") or None
COOKIES_FROM_BROWSER = os.getenv("REEL_COOKIES_FROM_BROWSER") or None
