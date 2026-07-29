"""In-memory download-job registry backed by a thread pool.

Each requested video becomes a :class:`Job`. A yt-dlp progress hook keeps the
job's percent / speed / ETA live so the frontend can stream updates. The pool
size is the user's ``concurrency`` setting (read at startup).
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from yt_dlp.utils import DownloadCancelled

from . import store, ytdlp_service
from .models import DownloadRequest, HistoryEntry, Job, Settings, VideoItem
from .store import get_settings


def _human_size(n: Optional[float]) -> Optional[str]:
    if not n:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.1f} {units[i]}"


def _file_size_str(path: Optional[str]) -> Optional[str]:
    """Human-readable size of the finished file on disk, or ``None`` if it can't
    be stat'd. This is ground truth — unlike the per-stream ``total_bytes`` the
    progress hook sees, which for a merged video is just one of the two streams.
    """
    if not path:
        return None
    try:
        return _human_size(os.path.getsize(path))
    except OSError:
        return None


def _human_eta(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class JobManager:
    _ACTIVE = ("queued", "downloading", "processing")

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._cancelled: set[str] = set()  # job ids the user asked to stop
        self._lock = threading.RLock()
        concurrency = max(1, get_settings().concurrency)
        self._executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="dl")

    # -- public API --------------------------------------------------------

    def enqueue(self, req: DownloadRequest) -> list[Job]:
        settings = get_settings()
        channel = req.channel
        created: list[Job] = []
        for item in req.items:
            job = Job(
                id=uuid.uuid4().hex[:12],
                video_id=item.id,
                title=item.title,
                channel=channel or item.uploader,
                format=req.format,
                quality=req.quality,
                status="queued",
                url=item.url,
            )
            with self._lock:
                self._jobs[job.id] = job
            self._executor.submit(self._run, job.id, item, settings)
            created.append(job)
        return created

    def all_jobs(self) -> list[Job]:
        with self._lock:
            # Newest first.
            return list(reversed(list(self._jobs.values())))

    def clear_finished(self) -> None:
        with self._lock:
            self._jobs = {
                jid: j
                for jid, j in self._jobs.items()
                if j.status in ("queued", "downloading", "processing")
            }

    def retry(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ("error", "skipped", "cancelled"):
                return None
            item = VideoItem(id=job.video_id, url=job.url, title=job.title, uploader=job.channel)
            self._cancelled.discard(job_id)  # clear any stale cancel flag
            job.status = "queued"
            job.progress = 0.0
            job.error = None
        settings = get_settings()
        self._executor.submit(self._run, job_id, item, settings)
        return job

    def cancel(self, job_id: str) -> Optional[Job]:
        """Request cancellation of a queued or in-flight job. A running download
        is aborted at its next progress tick; a queued one never starts."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in self._ACTIVE:
                return None
            self._cancelled.add(job_id)
            if job.status == "queued":
                # Not started yet — mark it now; the worker will bail on entry.
                job.status = "cancelled"
                job.error = "Cancelled"
            return job

    def cancel_all(self) -> None:
        with self._lock:
            for jid, job in self._jobs.items():
                if job.status in self._ACTIVE:
                    self._cancelled.add(jid)
                    if job.status == "queued":
                        job.status = "cancelled"
                        job.error = "Cancelled"

    # -- internals ---------------------------------------------------------

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                setattr(job, k, v)

    def _make_hook(self, job_id: str):
        def hook(d: dict) -> None:
            # Abort mid-download if the user hit cancel. yt-dlp turns this
            # exception into a clean stop rather than a crash.
            if job_id in self._cancelled:
                raise DownloadCancelled(f"Cancelled {job_id}")
            status = d.get("status")
            if status == "downloading":
                downloaded = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                percent = (downloaded / total * 100) if total else 0.0
                self._update(
                    job_id,
                    status="downloading",
                    progress=round(min(percent, 100.0), 1),
                    speed=(f"{_human_size(d.get('speed'))}/s" if d.get("speed") else None),
                    eta=_human_eta(d.get("eta")),
                    size=_human_size(total),
                )
            elif status == "finished":
                # Download done; may still be merging / extracting audio.
                self._update(job_id, status="processing", progress=100.0, speed=None, eta=None)

        return hook

    def _run(self, job_id: str, item: VideoItem, settings: Settings) -> None:
        job = self._jobs[job_id]
        # Cancelled while still queued -> never start.
        if job_id in self._cancelled:
            self._update(job_id, status="cancelled", error="Cancelled")
            self._cancelled.discard(job_id)
            return
        # Skip videos already downloaded in this same format.
        if item.id in ytdlp_service.load_archive_ids(settings, job.format):
            self._update(job_id, status="skipped", progress=100.0,
                         error="Already downloaded")
            return

        self._update(job_id, status="downloading")
        try:
            info = ytdlp_service.download_one(
                url=item.url,
                settings=settings,
                fmt=job.format,
                quality=job.quality,
                channel=job.channel,
                progress_hook=self._make_hook(job_id),
            )
            filepath = None
            downloads = info.get("requested_downloads") or []
            if downloads:
                filepath = downloads[0].get("filepath")
            filepath = filepath or info.get("_filename")
            size = _file_size_str(filepath)
            # Report the real merged-file size, not the last stream's total_bytes.
            self._update(job_id, status="completed", progress=100.0,
                         filepath=filepath, size=size, speed=None, eta=None)
            self._record_history(job, item, filepath, size)
        except DownloadCancelled:
            self._update(job_id, status="cancelled", progress=0.0,
                         error="Cancelled", speed=None, eta=None)
        except Exception as exc:  # noqa: BLE001 - surface any yt-dlp error to the UI
            self._update(job_id, status="error", error=str(exc).strip() or "Download failed")
        finally:
            self._cancelled.discard(job_id)

    def _record_history(self, job: Job, item: VideoItem, filepath, size) -> None:
        """Persist a completed download to the library (best-effort)."""
        try:
            store.add_history(HistoryEntry(
                id=uuid.uuid4().hex[:12],
                video_id=job.video_id,
                title=job.title,
                channel=job.channel,
                format=job.format,
                quality=job.quality,
                size=size,
                filepath=filepath,
                thumbnail=item.thumbnail,
                url=job.url,
                downloaded_at=time.time(),
            ))
        except Exception:  # noqa: BLE001 - history must never break a download
            pass


# Single shared instance for the app.
manager = JobManager()
