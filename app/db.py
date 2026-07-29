"""MongoDB connection for shared state (saved channels + download history).

Uses the *synchronous* pymongo driver because the downloader is a synchronous
app that also writes from worker threads (the download pool) — pymongo's client
is thread-safe, whereas an async driver would need the event loop.

The same Atlas cluster / database as automation-server is reused, but under
**separate collections** (``reel_channels`` / ``reel_history``) so the two apps
never touch each other's data.

If ``MONGODB_URI`` is not set — or Mongo is unreachable — the app transparently
falls back to local JSON files (see ``store.py``), so it still runs standalone.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import certifi

try:
    from pymongo import MongoClient
    from pymongo.collection import Collection
    from pymongo.errors import PyMongoError
except ImportError:  # pymongo not installed -> Mongo simply disabled
    MongoClient = None  # type: ignore
    Collection = None  # type: ignore
    PyMongoError = Exception  # type: ignore


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "youtube_automation")
CHANNELS_COLLECTION = "reel_channels"
HISTORY_COLLECTION = "reel_history"

_lock = threading.Lock()
_client = None
_db = None
_state: Optional[bool] = None  # None = unchecked, True/False = ping result


def _ensure() -> bool:
    """Connect + ping once; cache the result. Returns True if Mongo is usable."""
    global _client, _db, _state
    if os.getenv("REEL_DISABLE_MONGO") == "1":
        return False
    if _state is not None:
        return _state
    with _lock:
        if _state is not None:
            return _state
        if not MONGODB_URI or MongoClient is None:
            _state = False
            return _state
        try:
            _client = MongoClient(
                MONGODB_URI,
                tlsCAFile=certifi.where(),
                serverSelectionTimeoutMS=4000,
            )
            _client.admin.command("ping")  # fail fast if unreachable
            _db = _client[MONGODB_DB_NAME]
            _ensure_indexes(_db)
            _state = True
        except Exception:  # noqa: BLE001 - any failure => fall back to JSON
            _client = _db = None
            _state = False
        return _state


def _ensure_indexes(db) -> None:
    db[CHANNELS_COLLECTION].create_index("url", unique=True)
    db[HISTORY_COLLECTION].create_index(
        [("video_id", 1), ("format", 1)], unique=True)
    db[HISTORY_COLLECTION].create_index("downloaded_at")


def mongo_enabled() -> bool:
    return _ensure()


def channels_col() -> "Collection":
    return _db[CHANNELS_COLLECTION]


def history_col() -> "Collection":
    return _db[HISTORY_COLLECTION]


def reset_for_test() -> None:
    """Drop cached connection state (used by tests)."""
    global _client, _db, _state
    _client = _db = None
    _state = None
