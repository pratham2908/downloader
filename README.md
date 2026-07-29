# Reel — YouTube Downloader

A local web app for pulling videos off YouTube with [yt-dlp](https://github.com/yt-dlp/yt-dlp).
Paste a channel, playlist, or video link; browse the uploads in a grid; tick the
ones you want; download. Built for grabbing a handful of videos from a channel
at a time.

![stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20yt--dlp-ff5230)

## Features

- **Browse a channel** — paste a channel URL or `@handle`, see every upload as a
  grid of cards, select and batch-download. Switch between the **Videos** and
  **Shorts** tabs; selections carry across both, so you can queue long-form and
  Shorts together in one download.
- **Sort & paginate** — sort a channel by Newest, Oldest, Most viewed, Longest,
  or Shortest, and reveal more with **Load more**. The header shows *Showing X of
  N* (an `N+` means the channel has more than the fetch cap — raise it in Settings).
- **Published dates** — exact upload dates for a channel's most recent uploads,
  pulled from its RSS feed. (Older videos stay in true newest-first order but
  don't show an exact date — fetching every date needs a YouTube API key.)
- **Direct link** — paste any video or playlist URL.
- **Saved channels** — star a channel to pin it in the sidebar for one-click reopening.
- **Formats** — best-quality **MP4**, or **audio-only** (MP3/M4A). Pick a quality
  cap per download (Best / 4K / 1440p / 1080p / 720p / 480p).
- **Live progress** — per-video progress bars with speed and ETA, streamed over SSE.
- **Cancel** — stop a queued or in-flight download (or **Cancel all**) from the
  downloads drawer; cancelled jobs can be retried.
- **Library** — every completed download is saved to a persistent, searchable
  library (thumbnail, channel, date, size, format). Re-download, reveal the file,
  or remove the entry; rows whose file has been moved/deleted are flagged.
- **Per-channel folders** — files land in `~/Downloads/YouTube/<Channel>/` (configurable).
- **Numbered files** — downloads are prefixed `1. `, `2. `, … within their channel
  folder, in download order. Numbers are never reused or renumbered: the next is
  always the highest present + 1. To number files you downloaded before this
  existed, run `python scripts/backfill_index.py` (dry run) then `--apply`.
- **Pick a folder** — set the download folder by typing an absolute path, or hit
  **Browse…** in Settings to choose one via your OS's native folder dialog.
- **Duplicate detection** — videos you already have are badged **Saved** in listings
  and skipped if re-queued. This survives restarts (it's stored on disk, not in
  memory) and reads from two sources: the yt-dlp archive in your download folder
  **and** the library — so it keeps working if you change the download folder, and
  a file you delete stops being reported as downloaded.
- **Reveal in Finder** — jump straight to a finished file.

## Requirements

- Python 3.10+
- [`ffmpeg`](https://ffmpeg.org/) on your `PATH` (needed for merging video+audio and audio extraction)

## Setup

```bash
cd downloader
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python run.py
```

Opens `http://127.0.0.1:8787` in your browser. `Ctrl+C` to stop.
Options: `--port 9000`, `--host 0.0.0.0`, `--no-open`.

## Settings

Click **⚙ Settings** in the sidebar to change the download folder, default
format/quality, audio codec, how many videos to fetch per channel, and
concurrent-download count. Settings persist in `data/settings.json`; saved
channels in `data/channels.json`.

> Changing **concurrent downloads** takes effect on the next restart.

## Shared storage (MongoDB, optional)

By default, saved channels and download history live in local JSON files under
`data/`. To share them across machines (e.g. your Mac and a hosted instance),
point the app at MongoDB — the **same cluster as automation-server**:

```bash
cp .env.example .env      # then fill in MONGODB_URI
```

```
MONGODB_URI=mongodb+srv://USER:PASS@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=youtube_automation
```

When set, **saved channels** and **download history** are stored in Mongo under
dedicated collections (`reel_channels`, `reel_history`) — separate from
automation-server's own data. If `MONGODB_URI` is unset or the cluster is
unreachable, the app silently falls back to the local JSON files, so it always
runs. **Settings stay local** (the download folder is machine-specific).

> **Atlas note:** the machine running the app must be in your cluster's Network
> Access allowlist, or connections are refused (and it falls back to JSON).

Migrate existing local channels/history into Mongo (idempotent):

```bash
python scripts/migrate_to_mongo.py            # dry run
python scripts/migrate_to_mongo.py --apply
```

## Deploy as a hosted web app

The app can run on a persistent container host (**Render Web Service**, Railway,
Fly.io — *not* Netlify/static hosts). When hosted, downloads land on the server
and you pull each file to your device with the **Download** button.

A `Dockerfile` is included. Deploy flow (Render example):

1. Push this repo; create a **Web Service** from the Dockerfile.
2. Add a **persistent disk** mounted at `/data` (keeps files + cookies across restarts).
3. Set environment variables:
   - `MONGODB_URI` — so channels/history are shared with your local install.
   - `REEL_PASSWORD` — a login (the app is otherwise open to the world).
   - `REEL_COOKIES_FILE=/data/cookies.txt` — upload your YouTube `cookies.txt`
     to the disk so yt-dlp isn't blocked by datacenter-IP bot checks.
   - (`REEL_HOSTED=1` and `REEL_DOWNLOAD_DIR=/data/downloads` are preset in the image.)

Hosted mode automatically hides the local-only controls (folder picker, Reveal
in Finder) and every request is behind the password. See `.env.example` for the
full list of knobs.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Unit tests cover the persistence layer (JSON **and** Mongo backends, via an
in-memory `mongomock`) and URL/format handling — all offline, no live DB.

## Notes

- This is for **personal use** — respect YouTube's Terms of Service and creators' rights.
- Age-restricted or region-locked videos may fail; yt-dlp supports browser
  cookies if you need it (not wired into the UI yet).
- `yt-dlp` moves fast — `pip install -U yt-dlp` occasionally to keep up with
  YouTube changes.

## Project layout

```
app/
  main.py           FastAPI routes + SSE stream
  ytdlp_service.py  resolve URLs · build download options · run yt-dlp
  downloads.py      job registry, thread pool, progress hooks
  store.py          JSON persistence (channels + settings)
  models.py         Pydantic models
web/                single-page UI (index.html · style.css · app.js)
data/               channels.json · settings.json · history.json (created on first run)
tests/              pytest unit tests
run.py              launcher
```
