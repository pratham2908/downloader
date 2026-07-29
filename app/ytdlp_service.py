"""Thin wrapper around yt-dlp used by the API and the download worker.

Two responsibilities:
  * *resolve* a pasted URL into either a single video or a list of videos
    (channel / playlist), using flat extraction so it stays fast.
  * *download* a single video with a progress hook, honouring the user's
    format / quality / folder settings.
"""
from __future__ import annotations

import re
import threading
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from yt_dlp import YoutubeDL

from .models import ResolveResponse, Settings, VideoItem

_CHANNEL_HINTS = ("/@", "/channel/", "/c/", "/user/")
_VIDEO_TABS = ("/videos", "/streams", "/shorts", "/playlists", "/featured")


def thumbnail_for(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def is_channel_url(url: str) -> bool:
    return any(h in url for h in _CHANNEL_HINTS) and "watch?v=" not in url


def normalize_channel_url(url: str, tab: str = "videos") -> str:
    """Point a channel URL at a content tab (``videos`` / ``shorts``).

    If the URL already targets a tab we honour it (a user who pastes a
    ``/shorts`` link means it); otherwise we append the requested tab so a bare
    channel URL or ``@handle`` lists that content type rather than the channel
    landing page.
    """
    url = url.strip()
    if not is_channel_url(url):
        return url
    if any(t in url for t in _VIDEO_TABS):
        return url
    return url.rstrip("/") + "/" + tab


def strip_channel_tab(url: str) -> str:
    """Drop a trailing content tab, yielding the bare channel URL.

    Used so the API always hands the frontend a tab-free base it can point at
    either ``/videos`` or ``/shorts`` when switching tabs.
    """
    base = url.rstrip("/")
    for t in _VIDEO_TABS:
        if base.endswith(t):
            return base[: -len(t)]
    return base


def sanitize_folder(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', " ", name).strip()
    return re.sub(r"\s+", " ", name) or "Unknown Channel"


# --- per-channel file numbering -------------------------------------------
# Downloads are prefixed "1. ", "2. " … within their channel folder, in the
# order they were downloaded. Numbers are never reused or renumbered: the next
# one is always (highest already present) + 1.

INDEX_RE = re.compile(r"^(\d+)\.\s")

_index_lock = threading.Lock()
_reserved: dict[str, int] = {}  # folder -> highest index handed out this run


def highest_index(folder: Path) -> int:
    """Largest existing "N. " prefix in a folder, or 0 if there are none."""
    best = 0
    try:
        for entry in folder.iterdir():
            match = INDEX_RE.match(entry.name)
            if match:
                best = max(best, int(match.group(1)))
    except (FileNotFoundError, NotADirectoryError):
        pass
    return best


def reserve_index(folder: Path) -> int:
    """Claim the next index for a folder.

    Held under a lock and remembered in ``_reserved`` because several downloads
    run concurrently — without this, two jobs starting together would both read
    the same highest-on-disk value and collide on the same number.
    """
    key = str(folder)
    with _index_lock:
        nxt = max(highest_index(folder), _reserved.get(key, 0)) + 1
        _reserved[key] = nxt
        return nxt


# --- archive (already-downloaded detection) -------------------------------
# Archives are kept per-format so grabbing the MP3 of a video you already have
# as MP4 (same video id) is not wrongly skipped.

def archive_path(settings: Settings, fmt: str = "video") -> Path:
    return Path(settings.download_dir).expanduser() / f".download-archive-{fmt}.txt"


def _read_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    ids.add(parts[1])
    except FileNotFoundError:
        pass
    return ids


def downloaded_ids(settings: Settings) -> set[str]:
    """Ids to badge as already-downloaded in listings.

    Combines two sources so the answer survives a restart *and* a change of
    download folder:
      * the yt-dlp archive files in the current download dir, and
      * the library (``history.json``), which is independent of that folder.
    The library also knows each file's path, so anything it records as gone
    from disk is dropped — a deleted file stops claiming to be downloaded.
    """
    from . import store  # local import keeps module import order simple

    archived = load_archive_ids(settings)
    try:
        present, missing = store.history_presence()
    except Exception:  # noqa: BLE001 - never let history break a listing
        return archived
    return (archived | present) - missing


def load_archive_ids(settings: Settings, fmt: Optional[str] = None) -> set[str]:
    """IDs already downloaded. With ``fmt`` set, only that format's archive;
    otherwise the union of every archive (used for the UI "Saved" badge)."""
    base = Path(settings.download_dir).expanduser()
    if fmt:
        return _read_ids(archive_path(settings, fmt))
    ids: set[str] = set()
    for path in base.glob(".download-archive*.txt"):
        ids |= _read_ids(path)
    return ids


# --- published dates via RSS ---------------------------------------------
# Flat extraction returns no upload dates, and full extraction is ~1.5s/video
# (too slow for a grid). The channel RSS feed carries exact dates for the most
# recent ~15 uploads in a single fast request, so we use it to enrich those.

def fetch_recent_dates(channel_id: str) -> dict[str, str]:
    """Map video id -> upload_date (YYYYMMDD) for a channel's latest ~15 videos.

    Best-effort: any failure returns an empty map rather than raising, so date
    enrichment never blocks a listing.
    """
    if not channel_id or not channel_id.startswith("UC"):
        return {}
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            xml = resp.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - network/parse issues are non-fatal
        return {}
    return parse_rss_dates(xml)


def parse_rss_dates(xml: str) -> dict[str, str]:
    """Extract {video_id: YYYYMMDD} from a YouTube channel RSS document.

    Dates are read per ``<entry>`` so the channel-level ``<published>`` (its
    creation date) is never mistaken for a video's date.
    """
    dates: dict[str, str] = {}
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry)
        pub = re.search(r"<published>(\d{4})-(\d{2})-(\d{2})", entry)
        if vid and pub:
            dates[vid.group(1)] = pub.group(1) + pub.group(2) + pub.group(3)
    return dates


# --- resolve --------------------------------------------------------------

def _entry_to_item(entry: dict, archived: set[str]) -> Optional[VideoItem]:
    vid = entry.get("id")
    if not vid or entry.get("_type") in ("playlist", "url_transparent"):
        # Skip nested tab entries; keep only real videos.
        if entry.get("ie_key") not in (None, "Youtube"):
            return None
    if not vid:
        return None
    return VideoItem(
        id=vid,
        url=entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
        title=entry.get("title") or "(untitled)",
        duration=entry.get("duration"),
        thumbnail=thumbnail_for(vid),
        uploader=entry.get("uploader") or entry.get("channel"),
        upload_date=entry.get("upload_date"),
        view_count=entry.get("view_count"),
        downloaded=vid in archived,
    )


def resolve(
    url: str,
    settings: Settings,
    limit: Optional[int] = None,
    tab: str = "videos",
) -> ResolveResponse:
    """Resolve a pasted URL into a video or a list of videos.

    ``tab`` selects which channel content tab to list (``videos`` or
    ``shorts``); it is ignored for direct video/playlist links.
    """
    url = url.strip()
    limit = limit or settings.list_limit
    archived = downloaded_ids(settings)

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlistend": limit,
        "ignoreerrors": True,
    }
    target = normalize_channel_url(url, tab)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=False)

    if info is None:
        raise ValueError("Could not read anything from that URL. Is it valid and public?")

    # Single video
    if info.get("_type") not in ("playlist", "multi_video") and info.get("id") and not info.get("entries"):
        item = _entry_to_item(info, archived)
        found = [item] if item else []
        return ResolveResponse(kind="video", title=info.get("title"),
                               uploader=info.get("uploader") or info.get("channel"),
                               items=found, total=len(found))

    # Channel / playlist. Flatten one level of nested tab-playlists if present.
    raw_entries = list(info.get("entries") or [])
    flattened: list[dict] = []
    for e in raw_entries:
        if e is None:
            continue
        if e.get("_type") == "playlist" and e.get("entries"):
            flattened.extend([x for x in e["entries"] if x])
        else:
            flattened.append(e)

    items: list[VideoItem] = []
    for e in flattened:
        item = _entry_to_item(e, archived)
        if item:
            items.append(item)
        if len(items) >= limit:
            break

    kind = "channel" if is_channel_url(url) else "playlist"
    channel_url = info.get("channel_url") or info.get("webpage_url") or target

    # Enrich the most-recent uploads with exact published dates from the RSS
    # feed. The feed mixes long-form and shorts, so it enriches either tab.
    channel_id = info.get("channel_id") or info.get("id") or ""
    if kind == "channel":
        recent_dates = fetch_recent_dates(channel_id)
        if recent_dates:
            for item in items:
                if item.id in recent_dates:
                    item.upload_date = recent_dates[item.id]

    # We hit the cap, so the channel likely has more videos than we fetched.
    truncated = len(items) >= limit

    return ResolveResponse(
        kind=kind,
        title=info.get("title"),
        uploader=info.get("uploader") or info.get("channel"),
        channel_url=strip_channel_tab(channel_url),
        items=items,
        total=len(items),
        truncated=truncated,
    )


# --- download -------------------------------------------------------------

def build_download_opts(
    settings: Settings,
    fmt: str,
    quality: str,
    channel: Optional[str],
    progress_hook: Callable[[dict], None],
) -> dict:
    base = Path(settings.download_dir).expanduser()
    name = "%(title).180B [%(id)s].%(ext)s"
    if settings.per_channel_folders and channel:
        base = base / sanitize_folder(channel)
        # Number files within their channel folder, in download order.
        name = f"{reserve_index(base)}. {name}"

    outtmpl = str(base / name)

    opts: dict = {
        "outtmpl": outtmpl,
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "download_archive": str(archive_path(settings, fmt)),
        "windowsfilenames": False,
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,
    }

    if fmt == "audio":
        opts["format"] = "ba/b"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": settings.audio_codec,
                "preferredquality": "0",
            }
        ]
    else:
        if quality and quality != "best":
            h = int(quality)
            opts["format"] = f"bv*[height<=?{h}]+ba/b[height<=?{h}]"
        else:
            opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"

    return opts


def download_one(
    url: str,
    settings: Settings,
    fmt: str,
    quality: str,
    channel: Optional[str],
    progress_hook: Callable[[dict], None],
) -> dict:
    """Download a single video. Returns the yt-dlp info dict. Raises on failure."""
    opts = build_download_opts(settings, fmt, quality, channel, progress_hook)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info or {}
