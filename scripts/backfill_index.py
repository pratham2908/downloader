#!/usr/bin/env python3
"""One-time backfill: add "N. " index prefixes to already-downloaded files.

Numbering follows *download order*, which is recovered from the yt-dlp archive
files (they list video ids in the order they were downloaded). Files already
carrying a prefix are left alone, and numbering continues after the highest
prefix already present, so this is safe to re-run.

Any matching paths recorded in the library (``history.json``) are updated so
"Reveal" keeps working after the rename.

    python scripts/backfill_index.py            # dry run — prints the plan
    python scripts/backfill_index.py --apply    # actually rename
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402
from app.ytdlp_service import INDEX_RE, highest_index  # noqa: E402

ID_RE = re.compile(r"\[([A-Za-z0-9_-]{6,})\]")


def archive_order(download_dir: Path) -> list[str]:
    """Video ids in the order they were downloaded, from the archive files."""
    order: list[str] = []
    for path in sorted(download_dir.glob(".download-archive*.txt")):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] not in order:
                    order.append(parts[1])
        except OSError:
            continue
    return order


def plan_folder(folder: Path, order: list[str]) -> list[tuple[Path, Path]]:
    """Return [(old_path, new_path)] renames for one channel folder."""
    files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
    unprefixed = [p for p in files if not INDEX_RE.match(p.name)]
    if not unprefixed:
        return []

    # Sort by download order where known; anything unknown goes last, by name.
    def sort_key(p: Path):
        match = ID_RE.search(p.name)
        vid = match.group(1) if match else None
        if vid and vid in order:
            return (0, order.index(vid), p.name)
        return (1, 0, p.name)

    unprefixed.sort(key=sort_key)

    nxt = highest_index(folder) + 1  # continue past any existing prefixes
    renames: list[tuple[Path, Path]] = []
    for path in unprefixed:
        renames.append((path, path.with_name(f"{nxt}. {path.name}")))
        nxt += 1
    return renames


def update_history(mapping: dict[str, str]) -> int:
    """Repoint library entries at their renamed files. Returns rows changed."""
    if not mapping or not store.HISTORY_FILE.exists():
        return 0
    try:
        raw = json.loads(store.HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    changed = 0
    for row in raw:
        old = row.get("filepath")
        if old and old in mapping:
            row["filepath"] = mapping[old]
            changed += 1
    if changed:
        store.HISTORY_FILE.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill index prefixes")
    parser.add_argument("--apply", action="store_true",
                        help="perform the renames (default: dry run)")
    args = parser.parse_args()

    download_dir = Path(store.get_settings().download_dir).expanduser()
    if not download_dir.exists():
        print(f"Download folder not found: {download_dir}")
        return

    order = archive_order(download_dir)
    folders = sorted(p for p in download_dir.iterdir() if p.is_dir())
    if not folders:
        print(f"No channel folders in {download_dir}")
        return

    total = 0
    mapping: dict[str, str] = {}
    for folder in folders:
        renames = plan_folder(folder, order)
        if not renames:
            print(f"\n{folder.name}/  — nothing to do (already numbered)")
            continue
        print(f"\n{folder.name}/")
        for old, new in renames:
            print(f"   {old.name}\n     -> {new.name}")
            mapping[str(old)] = str(new)
        total += len(renames)

    if not total:
        print("\nNothing to rename.")
        return

    if not args.apply:
        print(f"\nDRY RUN — {total} file(s) would be renamed. "
              f"Re-run with --apply to do it.")
        return

    done = 0
    for old_s, new_s in mapping.items():
        old, new = Path(old_s), Path(new_s)
        if new.exists():
            print(f"SKIP (target exists): {new.name}")
            continue
        old.rename(new)
        done += 1
    rows = update_history(mapping)
    print(f"\nRenamed {done} file(s). Updated {rows} library entry/entries.")


if __name__ == "__main__":
    main()
