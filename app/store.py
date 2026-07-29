"""Persistence for saved channels, download history, and settings.

Saved channels and download history live in **MongoDB** when it's configured
(shared across every machine that points at the same DB — local and hosted).
When Mongo isn't configured/reachable, they fall back to local JSON files so the
app still runs standalone. See ``db.py``.

Settings always stay local (JSON): ``download_dir`` is machine-specific, so it
can't be shared through a single DB.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import db
from .models import HistoryEntry, SavedChannel, Settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHANNELS_FILE = DATA_DIR / "channels.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"

_lock = threading.RLock()


def _default_download_dir() -> str:
    return str(Path.home() / "Downloads" / "YouTube")


def _read_json(path: Path, fallback):
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # atomic on POSIX


# --- settings (always local) ----------------------------------------------

def get_settings() -> Settings:
    with _lock:
        raw = _read_json(SETTINGS_FILE, {})
        raw.setdefault("download_dir", _default_download_dir())
        return Settings(**raw)


def save_settings(settings: Settings) -> Settings:
    with _lock:
        _write_json(SETTINGS_FILE, settings.model_dump())
        return settings


# --- channels -------------------------------------------------------------

def list_channels() -> list[SavedChannel]:
    if db.mongo_enabled():
        docs = db.channels_col().find({}, {"_id": 0})
        return [SavedChannel(**d) for d in docs]
    with _lock:
        raw = _read_json(CHANNELS_FILE, [])
        return [SavedChannel(**c) for c in raw]


def add_channel(channel: SavedChannel) -> list[SavedChannel]:
    """Add a channel, de-duping on URL. A repeat URL updates name/handle and
    keeps an existing thumbnail if the new one is blank."""
    if db.mongo_enabled():
        col = db.channels_col()
        existing = col.find_one({"url": channel.url})
        if existing:
            col.update_one({"url": channel.url}, {"$set": {
                "name": channel.name,
                "handle": channel.handle,
                "thumbnail": channel.thumbnail or existing.get("thumbnail"),
            }})
        else:
            col.insert_one(channel.model_dump())
        return list_channels()
    with _lock:
        channels = list_channels()
        existing_c = next((c for c in channels if c.url == channel.url), None)
        if existing_c:
            existing_c.name = channel.name
            existing_c.handle = channel.handle
            existing_c.thumbnail = channel.thumbnail or existing_c.thumbnail
        else:
            channels.append(channel)
        _write_json(CHANNELS_FILE, [c.model_dump() for c in channels])
        return channels


def remove_channel(channel_id: str) -> list[SavedChannel]:
    if db.mongo_enabled():
        db.channels_col().delete_one({"id": channel_id})
        return list_channels()
    with _lock:
        channels = [c for c in list_channels() if c.id != channel_id]
        _write_json(CHANNELS_FILE, [c.model_dump() for c in channels])
        return channels


# --- download history / library -------------------------------------------

def list_history() -> list[HistoryEntry]:
    if db.mongo_enabled():
        docs = db.history_col().find({}, {"_id": 0}).sort("downloaded_at", -1)
        return [HistoryEntry(**d) for d in docs]
    with _lock:
        raw = _read_json(HISTORY_FILE, [])
        entries = [HistoryEntry(**e) for e in raw]
        entries.sort(key=lambda e: e.downloaded_at, reverse=True)  # newest first
        return entries


def add_history(entry: HistoryEntry) -> list[HistoryEntry]:
    """Record a completed download. Re-downloading the same video in the same
    format updates the existing row (path/size/time) instead of duplicating."""
    if db.mongo_enabled():
        db.history_col().replace_one(
            {"video_id": entry.video_id, "format": entry.format},
            entry.model_dump(),
            upsert=True,
        )
        return list_history()
    with _lock:
        entries = list_history()
        existing = next(
            (e for e in entries if e.video_id == entry.video_id and e.format == entry.format),
            None,
        )
        if existing:
            entries = [e for e in entries if e is not existing]
        entries.append(entry)
        _write_json(HISTORY_FILE, [e.model_dump() for e in entries])
        return list_history()


def remove_history(entry_id: str) -> list[HistoryEntry]:
    if db.mongo_enabled():
        db.history_col().delete_one({"id": entry_id})
        return list_history()
    with _lock:
        entries = [e for e in list_history() if e.id != entry_id]
        _write_json(HISTORY_FILE, [e.model_dump() for e in entries])
        return entries


def clear_history() -> list[HistoryEntry]:
    if db.mongo_enabled():
        db.history_col().delete_many({})
        return []
    with _lock:
        _write_json(HISTORY_FILE, [])
        return []


def history_presence() -> tuple[set[str], set[str]]:
    """Split library entries into (present, missing) video-id sets by whether
    their file is still on disk *on this machine*.

    A download-dir-independent source of truth for "already downloaded": it
    survives changing the download folder and notices deleted files. An id is
    *present* if any of its entries still resolves to a file here; *missing*
    only if it has entries and none do. (When history is shared via Mongo, this
    correctly reflects what the current machine actually holds.)
    """
    present: set[str] = set()
    seen: set[str] = set()
    for entry in list_history():
        seen.add(entry.video_id)
        if entry.filepath and Path(entry.filepath).expanduser().exists():
            present.add(entry.video_id)
    return present, seen - present
