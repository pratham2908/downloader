"""FastAPI application: serves the UI and the JSON/SSE API."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import store, ytdlp_service
from .downloads import manager
from .models import (
    DownloadRequest,
    ResolveRequest,
    ResolveResponse,
    SavedChannel,
    Settings,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="YouTube Downloader")


# --- pages ---------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# --- resolve / download ---------------------------------------------------

@app.post("/api/resolve", response_model=ResolveResponse)
def resolve(req: ResolveRequest) -> ResolveResponse:
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "Please paste a URL.")
    try:
        return ytdlp_service.resolve(url, store.get_settings(), tab=req.tab)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, str(exc).strip() or "Could not resolve that URL.")


@app.post("/api/download")
def download(req: DownloadRequest) -> dict:
    if not req.items:
        raise HTTPException(400, "No videos selected.")
    jobs = manager.enqueue(req)
    return {"jobs": [j.model_dump() for j in jobs]}


@app.get("/api/downloads")
def downloads() -> dict:
    return {"jobs": [j.model_dump() for j in manager.all_jobs()]}


@app.post("/api/downloads/clear")
def clear_downloads() -> dict:
    manager.clear_finished()
    return {"jobs": [j.model_dump() for j in manager.all_jobs()]}


@app.post("/api/downloads/{job_id}/retry")
def retry_download(job_id: str) -> dict:
    job = manager.retry(job_id)
    if not job:
        raise HTTPException(404, "Job not found or not retryable.")
    return job.model_dump()


@app.post("/api/downloads/{job_id}/cancel")
def cancel_download(job_id: str) -> dict:
    job = manager.cancel(job_id)
    if not job:
        raise HTTPException(404, "Job not found or already finished.")
    return job.model_dump()


@app.post("/api/downloads/cancel-all")
def cancel_all_downloads() -> dict:
    manager.cancel_all()
    return {"jobs": [j.model_dump() for j in manager.all_jobs()]}


@app.get("/api/downloads/stream")
async def downloads_stream() -> StreamingResponse:
    async def event_gen():
        while True:
            payload = json.dumps({"jobs": [j.model_dump() for j in manager.all_jobs()]})
            yield f"data: {payload}\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# --- saved channels -------------------------------------------------------

class AddChannelRequest(BaseModel):
    name: str
    url: str
    handle: Optional[str] = None
    thumbnail: Optional[str] = None


@app.get("/api/channels")
def get_channels() -> dict:
    return {"channels": [c.model_dump() for c in store.list_channels()]}


@app.post("/api/channels")
def add_channel(req: AddChannelRequest) -> dict:
    channel = SavedChannel(
        id=uuid.uuid4().hex[:8],
        name=req.name.strip() or req.url,
        url=req.url.strip(),
        handle=req.handle,
        thumbnail=req.thumbnail,
    )
    channels = store.add_channel(channel)
    return {"channels": [c.model_dump() for c in channels]}


@app.delete("/api/channels/{channel_id}")
def delete_channel(channel_id: str) -> dict:
    channels = store.remove_channel(channel_id)
    return {"channels": [c.model_dump() for c in channels]}


# --- settings -------------------------------------------------------------

@app.get("/api/settings", response_model=Settings)
def get_settings() -> Settings:
    return store.get_settings()


@app.put("/api/settings", response_model=Settings)
def put_settings(settings: Settings) -> Settings:
    return store.save_settings(settings)


# --- download history / library ------------------------------------------

def _history_payload() -> dict:
    entries = []
    for e in store.list_history():
        d = e.model_dump()
        # Flag rows whose file has since been moved/deleted so the UI can dim them.
        d["exists"] = bool(e.filepath and Path(e.filepath).expanduser().exists())
        entries.append(d)
    return {"entries": entries}


@app.get("/api/history")
def get_history() -> dict:
    return _history_payload()


@app.delete("/api/history/{entry_id}")
def delete_history(entry_id: str) -> dict:
    store.remove_history(entry_id)
    return _history_payload()


@app.post("/api/history/clear")
def clear_history() -> dict:
    store.clear_history()
    return _history_payload()


# --- native folder picker -------------------------------------------------
# The server runs on the same machine as the browser (this is a local tool),
# so we can pop the host OS's real "choose folder" dialog and hand its
# absolute path back to the UI — something a browser can never do itself.


def _tk_choose_folder(start: Path) -> Optional[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        path = filedialog.askdirectory(
            initialdir=str(start) if start.exists() else None,
            title="Choose download folder",
        )
    finally:
        root.destroy()
    return path or None


def native_choose_folder(start: Path) -> Optional[str]:
    """Open a native folder dialog on the host. Returns the chosen absolute
    path, or ``None`` if the user cancelled. Raises ``RuntimeError`` if no
    picker is available on this platform."""
    if sys.platform == "darwin":
        default = ""
        if start.exists():
            loc = str(start).replace("\\", "\\\\").replace('"', '\\"')
            default = f' default location (POSIX file "{loc}")'
        script = (
            'POSIX path of (choose folder with prompt '
            f'"Choose download folder"{default})'
        )
        proc = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
        if proc.returncode != 0:
            err = proc.stderr or ""
            if "User canceled" in err or "-128" in err:
                return None
            raise RuntimeError(err.strip() or "Folder dialog failed.")
        return proc.stdout.strip().rstrip("/") or None

    if sys.platform.startswith("linux") and shutil.which("zenity"):
        proc = subprocess.run(
            ["zenity", "--file-selection", "--directory",
             "--title=Choose download folder"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:  # non-zero == cancelled
            return None
        return proc.stdout.strip() or None

    # Windows and anything else: fall back to Tkinter if it's importable.
    try:
        return _tk_choose_folder(start)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("No native folder picker available here.") from exc


class PickedFolder(BaseModel):
    path: Optional[str] = None
    cancelled: bool = False


@app.post("/api/pick-folder", response_model=PickedFolder)
def pick_folder() -> PickedFolder:
    start = Path(store.get_settings().download_dir).expanduser()
    try:
        chosen = native_choose_folder(start)
    except RuntimeError as exc:
        raise HTTPException(501, str(exc))
    return PickedFolder(cancelled=chosen is None, path=chosen)


# --- reveal in file manager (bonus) --------------------------------------

class RevealRequest(BaseModel):
    path: str


@app.post("/api/reveal")
def reveal(req: RevealRequest) -> dict:
    path = Path(req.path).expanduser()
    target = path if path.exists() else path.parent
    if not target.exists():
        raise HTTPException(404, "Path not found.")
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)] if path.exists() else ["open", str(target)])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(target)])
        elif sys.platform.startswith("win"):
            subprocess.Popen(["explorer", str(target)])
        else:
            raise HTTPException(400, "Unsupported platform.")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc))
    return {"ok": True}


# Static assets (js/css). Mounted last so it doesn't shadow API routes.
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")
