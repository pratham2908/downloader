"""JSON-file persistence for saved channels and settings.

Deliberately dependency-free and thread-safe. Two small files live under
``data/``: ``channels.json`` (a list) and ``settings.json`` (an object).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

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


# --- settings -------------------------------------------------------------

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
    with _lock:
        raw = _read_json(CHANNELS_FILE, [])
        return [SavedChannel(**c) for c in raw]


def _persist_channels(channels: list[SavedChannel]) -> None:
    _write_json(CHANNELS_FILE, [c.model_dump() for c in channels])


def add_channel(channel: SavedChannel) -> list[SavedChannel]:
    with _lock:
        channels = list_channels()
        # De-dupe on normalized URL; update name/thumbnail if it already exists.
        existing = next((c for c in channels if c.url == channel.url), None)
        if existing:
            existing.name = channel.name
            existing.handle = channel.handle
            existing.thumbnail = channel.thumbnail or existing.thumbnail
        else:
            channels.append(channel)
        _persist_channels(channels)
        return channels


def remove_channel(channel_id: str) -> list[SavedChannel]:
    with _lock:
        channels = [c for c in list_channels() if c.id != channel_id]
        _persist_channels(channels)
        return channels


# --- download history / library -------------------------------------------

def list_history() -> list[HistoryEntry]:
    with _lock:
        raw = _read_json(HISTORY_FILE, [])
        entries = [HistoryEntry(**e) for e in raw]
        entries.sort(key=lambda e: e.downloaded_at, reverse=True)  # newest first
        return entries


def _persist_history(entries: list[HistoryEntry]) -> None:
    _write_json(HISTORY_FILE, [e.model_dump() for e in entries])


def add_history(entry: HistoryEntry) -> list[HistoryEntry]:
    """Record a completed download. Re-downloading the same video in the same
    format updates the existing row (path/size/time) instead of duplicating."""
    with _lock:
        entries = list_history()
        existing = next(
            (e for e in entries if e.video_id == entry.video_id and e.format == entry.format),
            None,
        )
        if existing:
            entries = [e for e in entries if e is not existing]
        entries.append(entry)
        _persist_history(entries)
        return list_history()


def remove_history(entry_id: str) -> list[HistoryEntry]:
    with _lock:
        entries = [e for e in list_history() if e.id != entry_id]
        _persist_history(entries)
        return entries


def clear_history() -> list[HistoryEntry]:
    with _lock:
        _persist_history([])
        return []


def history_presence() -> tuple[set[str], set[str]]:
    """Split library entries into (present, missing) video-id sets by whether
    their file is still on disk.

    This is a second, download-dir-independent source of truth for
    "already downloaded": it survives changing the download folder, and it
    notices when you delete a file. An id counts as *present* if any of its
    entries (video/audio) still has a file; *missing* only if it has entries
    and none of them resolve to an existing file.
    """
    present: set[str] = set()
    seen: set[str] = set()
    for entry in list_history():
        seen.add(entry.video_id)
        if entry.filepath and Path(entry.filepath).expanduser().exists():
            present.add(entry.video_id)
    return present, seen - present
