"""Unit tests for the JSON persistence layer."""
from pathlib import Path

import pytest

from app import store
from app.models import SavedChannel, Settings


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "CHANNELS_FILE", tmp_path / "channels.json")
    monkeypatch.setattr(store, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(store, "HISTORY_FILE", tmp_path / "history.json")
    yield


def _entry(**kw):
    from app.models import HistoryEntry
    base = dict(id="e1", video_id="v1", title="T", channel="C",
                format="video", quality="best", url="u", downloaded_at=1.0)
    base.update(kw)
    return HistoryEntry(**base)


def test_history_empty_by_default():
    assert store.list_history() == []


def test_history_add_and_sorted_newest_first():
    store.add_history(_entry(id="a", video_id="v1", downloaded_at=1.0))
    store.add_history(_entry(id="b", video_id="v2", downloaded_at=5.0))
    ids = [e.id for e in store.list_history()]
    assert ids == ["b", "a"]  # newest (higher timestamp) first


def test_history_upserts_same_video_and_format():
    store.add_history(_entry(id="a", video_id="v1", format="video", title="old"))
    store.add_history(_entry(id="b", video_id="v1", format="video", title="new", downloaded_at=2.0))
    entries = store.list_history()
    assert len(entries) == 1
    assert entries[0].title == "new"


def test_history_video_and_audio_of_same_id_coexist():
    store.add_history(_entry(id="a", video_id="v1", format="video"))
    store.add_history(_entry(id="b", video_id="v1", format="audio"))
    assert len(store.list_history()) == 2


def test_history_remove_and_clear():
    store.add_history(_entry(id="a", video_id="v1"))
    store.add_history(_entry(id="b", video_id="v2", downloaded_at=2.0))
    store.remove_history("a")
    assert [e.id for e in store.list_history()] == ["b"]
    store.clear_history()
    assert store.list_history() == []


def test_settings_defaults_when_missing():
    s = store.get_settings()
    assert s.default_quality == "best"
    assert s.download_dir.endswith("YouTube")


def test_settings_roundtrip():
    s = Settings(download_dir="/tmp/x", default_quality="1080", concurrency=5)
    store.save_settings(s)
    loaded = store.get_settings()
    assert loaded.download_dir == "/tmp/x"
    assert loaded.default_quality == "1080"
    assert loaded.concurrency == 5


def test_channels_empty_by_default():
    assert store.list_channels() == []


def test_add_and_remove_channel():
    ch = SavedChannel(id="a1", name="Veritasium", url="https://youtube.com/@veritasium")
    store.add_channel(ch)
    channels = store.list_channels()
    assert len(channels) == 1
    assert channels[0].name == "Veritasium"

    store.remove_channel("a1")
    assert store.list_channels() == []


def test_add_channel_dedupes_on_url():
    url = "https://youtube.com/@mkbhd"
    store.add_channel(SavedChannel(id="a", name="MKBHD", url=url))
    store.add_channel(SavedChannel(id="b", name="Marques", url=url))
    channels = store.list_channels()
    assert len(channels) == 1
    assert channels[0].name == "Marques"  # name updated in place


def test_add_channel_preserves_existing_thumbnail():
    url = "https://youtube.com/@x"
    store.add_channel(SavedChannel(id="a", name="X", url=url, thumbnail="thumb.jpg"))
    store.add_channel(SavedChannel(id="b", name="X2", url=url, thumbnail=None))
    assert store.list_channels()[0].thumbnail == "thumb.jpg"
