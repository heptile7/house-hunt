"""Parsers for NoBroker, SquareYards and CommonFloor, against trimmed real pages (2026-11)."""

from pathlib import Path

import pytest

from scrapers.commonfloor import CommonFloorScraper
from scrapers.nobroker import NoBrokerScraper, listing_objects
from scrapers.nobroker import slugify as nb_slug
from scrapers.squareyards import SquareYardsScraper
from scrapers.squareyards import slugify as sy_slug

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _nb(listing_type: str) -> list[dict]:
    s = NoBrokerScraper()
    return [s.map_listing(o, "Chennai", listing_type) for o in listing_objects(_read(f"nobroker_{listing_type}.html"))]


# ── NoBroker ──────────────────────────────────────────────────────────────────


def test_nobroker_rent_from_nextjs_payload():
    props = _nb("rent")
    assert len(props) == 3
    p = props[0]
    assert p["property_id"] == "8a9fc78284560d400184561975ac05e7"
    assert p["listing_type"] == "rent"
    assert (p["bhk"], p["price"], p["area_sqft"]) == (1, 15000, 585.0)
    assert p["locality"] == "Adyar Depot"
    assert p["latitude"] == pytest.approx(12.998486) and p["longitude"] == pytest.approx(80.256122)
    assert p["furnishing"] == "Semi-Furnished"
    assert p["floor"] == "1 out of 3" and p["total_floors"] == 3
    assert p["url"].startswith("https://www.nobroker.in/property/1-bhk-apartment-for-rent-in-adyar-depot")
    # Public image path (assets.nobroker.in/<file> is 403 for everyone)
    assert p["image_url"].startswith(f"https://images.nobroker.in/images/{p['property_id']}/")
    assert p["image_url"].endswith("_medium.jpg")
    assert "  " not in p["title"]


def test_nobroker_buy_from_app_state():
    props = _nb("buy")
    assert len(props) == 3
    p = props[0]
    assert (p["bhk"], p["price"], p["area_sqft"]) == (3, 12_200_000, 1466.0)
    assert p["address"] == "Casagrand Zenith, Medavakkam"
    assert p["url"].startswith("https://www.nobroker.in/property/buy/")
    assert all(x["latitude"] and x["longitude"] for x in props)


def test_nobroker_unrelated_page_gives_nothing():
    assert listing_objects("<html><body>no data</body></html>") == []


def test_nobroker_slugs():
    assert nb_slug("Anna Nagar") == "anna_nagar"
    assert nb_slug(" Velachery ") == "velachery"


# ── SquareYards ───────────────────────────────────────────────────────────────


def test_squareyards_buy_cards():
    props = SquareYardsScraper().parse_page(_read("squareyards_buy.html"), "Chennai", "buy")
    assert len(props) == 3
    p = props[0]
    assert p["property_id"] == "10829392"
    assert (p["bhk"], p["price"], p["area_sqft"]) == (2, 6_900_000, 1043.0)
    assert p["locality"] == "Avadi"
    assert p["address"] == "Ashok Nandavanam Melpaakam"
    assert p["latitude"] == pytest.approx(13.088071)
    assert p["url"].endswith("/10829392")


def test_squareyards_rent_skips_commercial():
    props = SquareYardsScraper().parse_page(_read("squareyards_rent.html"), "Chennai", "rent")
    # fixture has 3 homes + 1 office space
    assert len(props) == 3
    assert all("office" not in p["property_type"].lower() for p in props)
    p = props[0]
    assert (p["bhk"], p["price"]) == (2, 27000)
    assert p["furnishing"] == "Semi-Furnished"


def test_squareyards_slug():
    assert sy_slug("Anna Nagar") == "anna-nagar"


# ── CommonFloor ───────────────────────────────────────────────────────────────


def test_commonfloor_buy_items():
    props = CommonFloorScraper().parse_page(_read("commonfloor_buy.html"), "Chennai", "buy")
    assert len(props) == 3
    villa, plot = props[0], props[1]
    assert villa["property_id"] == "qt7sij6sj8bceoae"
    assert (villa["bhk"], villa["price"], villa["area_sqft"]) == (3, 8_500_000, 1040.0)
    assert villa["locality"] == "Padur"
    assert villa["property_type"] == "Independent House"
    assert villa["title"] == "3BHK Villa for Sale in Padur, Chennai"  # trailing "at Individual House" dropped
    assert plot["property_type"] == "Plot"
    assert plot["image_url"] == ""  # "no-image" placeholder dropped


def test_commonfloor_rent_items_and_placeholders():
    props = CommonFloorScraper().parse_page(_read("commonfloor_rent.html"), "Chennai", "rent")
    assert len(props) == 3
    assert props[0]["price"] == 18000 and props[0]["locality"] == "Kolathur"
    assert props[1]["furnishing"] == "Semi-Furnished"
    for p in props:
        # India-centre placeholder coordinates must never be saved
        assert (p["latitude"], p["longitude"]) != (20.5937, 78.9629)


# ── Shared filtering ──────────────────────────────────────────────────────────


def test_filter_bhk_and_price():
    props = _nb("rent")
    assert {p["bhk"] for p in NoBrokerScraper._filter(props, bhk=[2])} == {2}
    assert all(p["price"] <= 20000 for p in NoBrokerScraper._filter(props, max_price=20000))
