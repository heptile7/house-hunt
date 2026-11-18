"""Listing details: dates, move-in availability, pets / non-veg, amenities, costs."""

from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from conftest import make_prop

from scrapers.commonfloor import CommonFloorScraper
from scrapers.details import infer_restrictions, ms_to_date, parse_availability, parse_date_text, yes_no
from scrapers.magicbricks import MagicBricksScraper
from scrapers.nobroker import NoBrokerScraper, listing_objects
from scrapers.squareyards import SquareYardsScraper

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 18)


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ── Parsing helpers ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Posted: Nov 06, '26", "2026-11-06"),
        ("Posted : 4 days ago", "2026-11-14"),
        ("Updated today", "2026-11-18"),
        ("Posted: Yesterday", "2026-11-17"),
        ("3 hours ago", "2026-11-18"),
        ("2 weeks ago", "2026-11-04"),
        ("a month ago", "2026-10-19"),
        ("16 Nov 2026", "2026-11-16"),
        ("1st December, 2026", "2026-12-01"),
        ("Jun'27", "2027-06-01"),
        ("Dec 2026", "2026-12-01"),
        ("16/11/2026", "2026-11-16"),
        ("2026-11-17T18:30:00.000", "2026-11-17"),
        ("", ""),
        ("whenever", ""),
    ],
)
def test_parse_date_text(text, expected):
    assert parse_date_text(text, TODAY) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Immediately", "Immediately"),
        ("Immediate", "Immediately"),
        ("Ready To Move", "Ready to move"),
        ("From Dec '26", "2026-12-01"),
        ("Poss. by Jun '27", "2027-06-01"),
        ("Under Construction", "Under construction"),
        ("NA", ""),
        (None, ""),
    ],
)
def test_parse_availability(text, expected):
    assert parse_availability(text, TODAY) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2 BHK with lift and no pets allowed and parking", (0, None)),
        ("Pets are not allowed. Available now.", (0, None)),
        ("Pet-friendly society near the park", (1, None)),
        ("Pets are allowed. Non-veg allowed.", (1, 1)),
        ("This property is available for vegetarian only.", (None, 0)),
        ("Strictly veg, no non-veg cooking", (None, 0)),
        ("Spacious flat with modular kitchen", (None, None)),
        ("", (None, None)),
    ],
)
def test_infer_restrictions(text, expected):
    assert infer_restrictions(text) == expected


def test_yes_no_and_ms_to_date():
    assert yes_no("YES") == 1 and yes_no("No") == 0 and yes_no("NON_VEG_ALLOWED") == 1
    assert yes_no("") is None and yes_no(None) is None
    assert ms_to_date(1794821704000) == "2026-11-16"
    assert ms_to_date(None) == "" and ms_to_date("junk") == ""


def test_normalize_infers_from_description_but_keeps_structured_values():
    from scrapers.base_scraper import BaseScraper

    p = BaseScraper._normalize({"description": "Veg only. Pets are allowed."})
    assert (p["pets_allowed"], p["non_veg_allowed"]) == (1, 0)
    # Structured value from the site wins over the description
    p = BaseScraper._normalize({"description": "no pets", "pets_allowed": 1})
    assert p["pets_allowed"] == 1


# ── Per-source extraction (real fixtures) ─────────────────────────────────────


def test_nobroker_rent_details():
    p = [NoBrokerScraper().map_listing(o, "Chennai", "rent") for o in listing_objects(_read("nobroker_rent.html"))][0]
    assert p["posted_date"] == "2026-11-15"
    assert p["updated_date"] == "2026-11-16"
    assert p["available_from"] == "2026-12-01"
    assert p["tenant_preference"] == "Family"
    assert (p["pets_allowed"], p["non_veg_allowed"]) == (0, 1)
    assert (p["deposit"], p["maintenance"]) == (81000, 200)
    assert p["occupancy"] == "Tenant on Notice Period"
    assert "Rain Water Harvesting" in p["amenities"]
    assert p["description"].startswith("1 BHK on the first floor")


def test_nobroker_buy_amenities():
    p = [NoBrokerScraper().map_listing(o, "Chennai", "buy") for o in listing_objects(_read("nobroker_buy.html"))][0]
    assert {"Gym", "Lift", "Swimming Pool", "Club House", "Power Backup (Full)"} <= set(p["amenities"])
    assert p["maintenance"] == 4000 and p["occupancy"] == "Vacant"


def test_magicbricks_details():
    soup = BeautifulSoup(_read("magicbricks_rent_cards.html"), "lxml")
    p = MagicBricksScraper()._parse_cards(soup, "Chennai")[0]
    assert p["posted_date"] == "2026-11-06"
    assert p["available_from"] == "Immediately"
    assert p["tenant_preference"] == "Bachelors"
    assert p["description"].startswith("A fully furnished 2BHK")


def test_squareyards_details():
    rent = SquareYardsScraper().parse_page(_read("squareyards_rent.html"), "Chennai", "rent")
    assert rent[0]["posted_date"] == "2026-11-17"  # RentAction.startTime
    assert rent[0]["amenities"] == ["Parking (1 Covered Parking)"]
    buy = SquareYardsScraper().parse_page(_read("squareyards_buy.html"), "Chennai", "buy")
    assert buy[0]["available_from"] == "Ready to move"
    assert "Servant Room +4" in buy[0]["amenities"]
    assert buy[0]["description"].startswith("Here is a 2-bedroom")


def test_commonfloor_details():
    rent = CommonFloorScraper().parse_page(_read("commonfloor_rent.html"), "Chennai", "rent")
    assert rent[0]["available_from"] == "Ready to move"
    assert rent[0]["amenities"] == ["Parking", "Power Backup", "Swimming Pool", "Security"]
    assert rent[0]["posted_date"]  # "Posted : N days ago" is relative to when the page was saved
    # "pet-friendly … available for vegetarian only" in the description
    assert (rent[1]["pets_allowed"], rent[1]["non_veg_allowed"]) == (1, 0)
    buy = CommonFloorScraper().parse_page(_read("commonfloor_buy.html"), "Chennai", "buy")
    assert buy[0]["available_from"] == "2027-06-01"  # "Possession On Jun'27"
    assert buy[1]["available_from"] == ""  # "NA"


# ── DB + API ──────────────────────────────────────────────────────────────────


def _seed(tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", listing_type="rent", pets_allowed=1, non_veg_allowed=1,
                      posted_date="2026-11-17", available_from="Immediately", amenities=["Lift", "Gym"]),
            make_prop(property_id="2", listing_type="rent", pets_allowed=0, non_veg_allowed=1,
                      posted_date="2026-09-01", available_from="2026-12-15"),
            make_prop(property_id="3", listing_type="rent", posted_date="", updated_date="2026-11-18",
                      available_from="2027-03-01"),
        ]
    )  # fmt: skip


def test_details_roundtrip_and_conflict_keeps_values(tmp_db):
    _seed(tmp_db)
    p = {r["property_id"]: r for r in tmp_db.query_properties("Chennai", listing_type="rent")}["1"]
    assert p["amenities"] == ["Lift", "Gym"]  # stored as JSON, returned as a list
    assert p["pets_allowed"] == 1 and p["available_from"] == "Immediately"
    # Re-scrape without details must not wipe them
    tmp_db.upsert_properties([make_prop(property_id="1", listing_type="rent", price=26000)])
    p = {r["property_id"]: r for r in tmp_db.query_properties("Chennai", listing_type="rent")}["1"]
    assert p["price"] == 26000 and p["pets_allowed"] == 1 and p["amenities"] == ["Lift", "Gym"]
    assert p["posted_date"] == "2026-11-17"


def test_detail_filters(tmp_db):
    _seed(tmp_db)
    q = lambda **kw: {p["property_id"] for p in tmp_db.query_properties("Chennai", listing_type="rent", **kw)}  # noqa: E731
    assert q(pets_allowed=True) == {"1"}
    assert q(non_veg_allowed=True) == {"1", "2"}
    assert q(available_by="2026-12-31") == {"1", "2"}
    assert q(available_by="2026-11-30") == {"1"}


def test_api_detail_filters_and_sorts(client, tmp_db):
    _seed(tmp_db)

    def ids(qs):
        return [
            p["property_id"]
            for p in client.get(f"/api/properties?city=Chennai&listing_type=rent&{qs}").get_json()["properties"]
        ]

    assert ids("pets=1") == ["1"]
    assert set(ids("available_by=2026-12-31")) == {"1", "2"}
    # newest first, using updated_date when there is no posted_date
    assert ids("sort=posted&order=asc") == ["3", "1", "2"]
    # earliest move-in: Immediately, then by date
    assert ids("sort=available&order=asc") == ["1", "2", "3"]
