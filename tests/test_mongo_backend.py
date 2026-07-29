"""Verify the MongoDB backend of the store using an in-memory mongomock server.

These exercise the *same* store functions the app calls, but with Mongo enabled,
proving the Mongo branch (dedupe, upsert, remove, clear, ordering) behaves like
the JSON one.
"""
import mongomock
import pytest

from app import db, store
from app.models import HistoryEntry, SavedChannel


@pytest.fixture
def mongo(monkeypatch):
    """Enable the Mongo path, backed by an in-memory mongomock database."""
    monkeypatch.delenv("REEL_DISABLE_MONGO", raising=False)
    client = mongomock.MongoClient()
    mdb = client["reel_test"]
    monkeypatch.setattr(db, "_db", mdb)
    monkeypatch.setattr(db, "_state", True)
    assert db.mongo_enabled()
    return mdb


def _chan(**kw):
    base = dict(id="c1", name="Chan", url="https://youtube.com/@x", handle=None, thumbnail=None)
    base.update(kw)
    return SavedChannel(**base)


def _hist(**kw):
    base = dict(id="h1", video_id="v1", title="T", channel="C", format="video",
                quality="best", url="u", filepath=None, thumbnail=None, downloaded_at=1.0)
    base.update(kw)
    return HistoryEntry(**base)


# --- channels -------------------------------------------------------------

def test_channel_add_list_remove(mongo):
    store.add_channel(_chan(id="a", url="u1", name="A"))
    store.add_channel(_chan(id="b", url="u2", name="B"))
    assert {c.name for c in store.list_channels()} == {"A", "B"}
    store.remove_channel("a")
    assert [c.name for c in store.list_channels()] == ["B"]


def test_channel_dedupes_on_url(mongo):
    store.add_channel(_chan(id="a", url="u1", name="First", thumbnail="t.jpg"))
    store.add_channel(_chan(id="b", url="u1", name="Second", thumbnail=None))
    chans = store.list_channels()
    assert len(chans) == 1
    assert chans[0].name == "Second"           # updated in place
    assert chans[0].thumbnail == "t.jpg"        # kept existing thumbnail


def test_channels_isolated_collection(mongo):
    store.add_channel(_chan())
    assert mongo[db.CHANNELS_COLLECTION].count_documents({}) == 1
    # never writes to automation-server's own 'channels' collection
    assert mongo["channels"].count_documents({}) == 0


# --- history --------------------------------------------------------------

def test_history_add_sorted_and_upsert(mongo):
    store.add_history(_hist(id="a", video_id="v1", downloaded_at=1.0, title="old"))
    store.add_history(_hist(id="b", video_id="v2", downloaded_at=5.0))
    assert [h.video_id for h in store.list_history()] == ["v2", "v1"]  # newest first

    store.add_history(_hist(id="c", video_id="v1", format="video", downloaded_at=9.0, title="new"))
    v1 = [h for h in store.list_history() if h.video_id == "v1"]
    assert len(v1) == 1 and v1[0].title == "new"   # upsert on (video_id, format)


def test_history_video_and_audio_coexist(mongo):
    store.add_history(_hist(id="a", video_id="v1", format="video"))
    store.add_history(_hist(id="b", video_id="v1", format="audio"))
    assert len(store.list_history()) == 2


def test_history_remove_and_clear(mongo):
    store.add_history(_hist(id="a", video_id="v1"))
    store.add_history(_hist(id="b", video_id="v2", downloaded_at=2.0))
    store.remove_history("a")
    assert [h.video_id for h in store.list_history()] == ["v2"]
    store.clear_history()
    assert store.list_history() == []


def test_history_presence_checks_disk(mongo, tmp_path):
    real = tmp_path / "f.mp4"
    real.write_bytes(b"x")
    store.add_history(_hist(id="a", video_id="KEEP", filepath=str(real)))
    store.add_history(_hist(id="b", video_id="GONE", filepath=str(tmp_path / "nope.mp4")))
    present, missing = store.history_presence()
    assert present == {"KEEP"} and missing == {"GONE"}
