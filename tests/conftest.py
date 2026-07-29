"""Shared test fixtures.

Force the JSON backend for the whole suite so tests never touch the real
MongoDB (a local ``.env`` would otherwise point pymongo at the live cluster).
Mongo behaviour is covered separately by an integration check, not unit tests.
"""
import os

import pytest

from app import db


@pytest.fixture(autouse=True)
def _disable_mongo(monkeypatch):
    monkeypatch.setenv("REEL_DISABLE_MONGO", "1")
    db.reset_for_test()
    yield
    db.reset_for_test()
