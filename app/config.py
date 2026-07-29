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
import tempfile
from pathlib import Path
from typing import Optional

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


def resolve_cookie_file(content: Optional[str], file: Optional[str],
                        directory: str) -> Optional[str]:
    """Decide the cookie file path yt-dlp should use.

    An explicit ``file`` wins. Otherwise, if raw cookies.txt ``content`` was
    provided (via env — the only way on hosts with no shell/disk, like Render's
    free tier), write it to a temp file and use that. Returns None if neither.
    """
    if file:
        return file
    if content and content.strip():
        path = Path(directory) / "reel_cookies.txt"
        path.write_text(content, encoding="utf-8")
        return str(path)
    return None


# MongoDB
MONGODB_URI = os.getenv("MONGODB_URI") or None
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "youtube_automation")

# Deployment mode
HOSTED = _bool("REEL_HOSTED")
PASSWORD = os.getenv("REEL_PASSWORD") or None
DOWNLOAD_DIR_OVERRIDE = os.getenv("REEL_DOWNLOAD_DIR") or None

# yt-dlp cookies (to get past datacenter-IP bot checks when hosted).
#   REEL_COOKIES_FILE      — path to a cookies.txt (needs a disk/shell)
#   REEL_COOKIES_CONTENT   — the cookies.txt *contents* pasted into an env var
#                            (works on diskless/shell-less hosts like Render free)
#   REEL_COOKIES_FROM_BROWSER — pull from a local browser (local use only)
COOKIES_FILE = resolve_cookie_file(
    os.getenv("REEL_COOKIES_CONTENT"),
    os.getenv("REEL_COOKIES_FILE") or None,
    tempfile.gettempdir(),
)
COOKIES_FROM_BROWSER = os.getenv("REEL_COOKIES_FROM_BROWSER") or None
