"""Tests for the download-job size reporting (no network)."""
from app import downloads as dl
from app.models import Job, Settings, VideoItem


def test_file_size_str(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"\0" * (2 * 1024 * 1024))  # 2 MB
    assert dl._file_size_str(str(f)) == "2.0 MB"
    assert dl._file_size_str(str(tmp_path / "missing.mp4")) is None
    assert dl._file_size_str(None) is None


def test_completed_size_is_real_file_not_last_stream(tmp_path, monkeypatch):
    """A finished video must report the merged file's real size, not the tiny
    audio-stream total the progress hook last saw."""
    settings = Settings(download_dir=str(tmp_path))
    monkeypatch.setattr(dl, "get_settings", lambda: settings)
    monkeypatch.setattr(dl.ytdlp_service, "load_archive_ids", lambda s, f=None: set())
    # Don't touch the real library file when exercising _run.
    monkeypatch.setattr(dl.store, "add_history", lambda e: None)

    out = tmp_path / "video.mp4"
    out.write_bytes(b"\0" * (10 * 1024 * 1024))  # true merged size: 10 MB

    def fake_download_one(url, settings, fmt, quality, channel, progress_hook):
        # Video stream, then a small audio stream — the last total the hook sees.
        progress_hook({"status": "downloading", "downloaded_bytes": 10 * 1024 * 1024,
                       "total_bytes": 10 * 1024 * 1024})
        progress_hook({"status": "finished"})
        progress_hook({"status": "downloading", "downloaded_bytes": 3 * 1024 * 1024,
                       "total_bytes": 3 * 1024 * 1024})  # audio stream
        progress_hook({"status": "finished"})
        return {"requested_downloads": [{"filepath": str(out)}]}

    monkeypatch.setattr(dl.ytdlp_service, "download_one", fake_download_one)

    mgr = dl.JobManager()
    mgr._jobs["j1"] = Job(id="j1", video_id="v", title="t", format="video",
                          quality="best", status="queued", url="http://x")
    mgr._run("j1", VideoItem(id="v", url="http://x", title="t"), settings)

    done = mgr._jobs["j1"]
    assert done.status == "completed"
    assert done.size == "10.0 MB"  # not the 3.0 MB audio stream
