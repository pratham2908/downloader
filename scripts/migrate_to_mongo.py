#!/usr/bin/env python3
"""One-time migration: push existing local JSON (channels + history) into Mongo.

Idempotent — channels de-dupe on URL, history on (video_id, format) — so it's
safe to run more than once. Settings are intentionally NOT migrated (they stay
local because ``download_dir`` is machine-specific).

    python scripts/migrate_to_mongo.py            # dry run — shows what it'd do
    python scripts/migrate_to_mongo.py --apply    # actually write to Mongo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.models import HistoryEntry, SavedChannel  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write to Mongo (default: dry run)")
    args = ap.parse_args()

    if not db.mongo_enabled():
        print("Mongo is not configured/reachable — set MONGODB_URI in .env first.")
        return

    channels = [SavedChannel(**c) for c in _load(DATA / "channels.json")]
    history = [HistoryEntry(**h) for h in _load(DATA / "history.json")]
    print(f"Local JSON: {len(channels)} channel(s), {len(history)} history entr(y/ies).")
    print(f"Target: DB '{db.MONGODB_DB_NAME}', collections "
          f"'{db.CHANNELS_COLLECTION}' / '{db.HISTORY_COLLECTION}'.")

    if not args.apply:
        print("\nDRY RUN — re-run with --apply to migrate.")
        return

    ch_col, hi_col = db.channels_col(), db.history_col()
    for c in channels:
        existing = ch_col.find_one({"url": c.url})
        if existing:
            ch_col.update_one({"url": c.url}, {"$set": {
                "name": c.name, "handle": c.handle,
                "thumbnail": c.thumbnail or existing.get("thumbnail")}})
        else:
            ch_col.insert_one(c.model_dump())
    for h in history:
        hi_col.replace_one({"video_id": h.video_id, "format": h.format},
                           h.model_dump(), upsert=True)

    print(f"\nDone. Mongo now holds {ch_col.count_documents({})} channel(s), "
          f"{hi_col.count_documents({})} history entr(y/ies).")


if __name__ == "__main__":
    main()
