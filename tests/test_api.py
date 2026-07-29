"""API tests for deploy-ready features: config, auth, file download, hosted guards."""
import base64

from fastapi.testclient import TestClient

from app import config, store
from app.main import app
from app.models import HistoryEntry


def _client():
    return TestClient(app)


def _entry(**kw):
    base = dict(id="h1", video_id="v1", title="t", channel="Chan", format="video",
                quality="best", url="u", filepath=None, thumbnail=None, downloaded_at=1.0)
    base.update(kw)
    return HistoryEntry(**base)


# --- config + auth --------------------------------------------------------

def test_config_reports_hosted(monkeypatch):
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "PASSWORD", None)
    assert _client().get("/api/config").json() == {"hosted": True}


def test_no_auth_when_password_unset(monkeypatch):
    monkeypatch.setattr(config, "PASSWORD", None)
    assert _client().get("/api/config").status_code == 200


def test_auth_required_and_accepts_correct_password(monkeypatch):
    monkeypatch.setattr(config, "PASSWORD", "s3cret")
    c = _client()
    assert c.get("/api/config").status_code == 401             # no creds
    bad = base64.b64encode(b"x:wrong").decode()
    assert c.get("/api/config", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    ok = base64.b64encode(b"anyuser:s3cret").decode()
    assert c.get("/api/config", headers={"Authorization": f"Basic {ok}"}).status_code == 200


def test_pick_folder_and_reveal_blocked_when_hosted(monkeypatch):
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "PASSWORD", None)
    c = _client()
    assert c.post("/api/pick-folder").status_code == 501
    assert c.post("/api/reveal", json={"path": "/tmp/x"}).status_code == 501


# --- settings override ----------------------------------------------------

def test_download_dir_override(monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_DIR_OVERRIDE", "/srv/dl")
    assert store.get_settings().download_dir == "/srv/dl"


# --- file download --------------------------------------------------------

def test_file_download_streams_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASSWORD", None)
    monkeypatch.setattr(config, "DOWNLOAD_DIR_OVERRIDE", str(tmp_path))
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")

    chan = tmp_path / "Chan"
    chan.mkdir()
    f = chan / "1. clip [v1].mp4"
    f.write_bytes(b"hello-bytes")
    store.add_history(_entry(video_id="v1", filepath=str(f)))

    r = _client().get("/api/file/v1?fmt=video")
    assert r.status_code == 200
    assert r.content == b"hello-bytes"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_file_download_404_when_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PASSWORD", None)
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    assert _client().get("/api/file/nope?fmt=video").status_code == 404


def test_file_download_rejects_path_outside_root(tmp_path, monkeypatch):
    """A history entry pointing outside the download folder must be refused."""
    monkeypatch.setattr(config, "PASSWORD", None)
    root = tmp_path / "dl"
    root.mkdir()
    monkeypatch.setattr(config, "DOWNLOAD_DIR_OVERRIDE", str(root))
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")

    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")
    store.add_history(_entry(video_id="v2", filepath=str(outside)))

    assert _client().get("/api/file/v2?fmt=video").status_code == 403


def test_file_download_404_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PASSWORD", None)
    monkeypatch.setattr(config, "DOWNLOAD_DIR_OVERRIDE", str(tmp_path))
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    store.add_history(_entry(video_id="v3", filepath=str(tmp_path / "gone.mp4")))
    assert _client().get("/api/file/v3?fmt=video").status_code == 404
