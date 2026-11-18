import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import database.db as db  # noqa: E402

# Redirect the DB *before* anything imports app.py (which calls init_db() at import time),
# so the test run never touches the real house_hunting.db.
_session_dir = tempfile.mkdtemp(prefix="hh_tests_")
db.DB_PATH = Path(_session_dir) / "session.db"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Fresh, empty SQLite DB for one test."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


@pytest.fixture
def client(tmp_db):
    import app as app_module
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def make_prop(**overrides) -> dict:
    from scrapers.base_scraper import BaseScraper
    base = {
        "source": "magicbricks", "property_id": "1", "listing_type": "buy",
        "title": "2 BHK Apartment", "price": 5_000_000, "price_text": "50 Lac",
        "area_sqft": 1000.0, "bhk": 2, "city": "Chennai", "locality": "Adyar",
        "url": "https://example.com/1", "image_url": "https://example.com/1.jpg",
    }
    return BaseScraper._normalize({**base, **overrides})
