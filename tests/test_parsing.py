import pytest

from scrapers.base_scraper import BaseScraper

parse_price = BaseScraper._parse_price
parse_area = BaseScraper._parse_area


@pytest.mark.parametrize(
    "text, expected",
    [
        ("45 Lac", 4_500_000),
        ("45L", 4_500_000),
        ("₹ 85 Lakhs", 8_500_000),
        ("1 Lakh", 100_000),
        ("1.2 Cr", 12_000_000),
        ("₹2.5 Crore", 25_000_000),
        ("25K", 25_000),
        ("₹ 18,500", 18_500),
        ("45 - 60 Lac", 4_500_000),
        ("1.1 to 1.4 Cr", 11_000_000),
        ("12000000", 12_000_000),
        (12000000, 12_000_000),
        ("", 0),
        (None, 0),
        ("Price on Request", 0),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1,200 sqft", 1200.0),
        ("950 sq.ft", 950.0),
        ("1100 sq ft", 1100.0),
        ("", 0.0),
        ("n/a", 0.0),
    ],
)
def test_parse_area(text, expected):
    assert parse_area(text) == expected


def test_headers_never_request_brotli():
    # requests can't decode br without the brotli package → sites return garbage bodies
    from scrapers.base_scraper import HEADERS_POOL

    for h in HEADERS_POOL:
        assert "br" not in h.get("Accept-Encoding", "")


@pytest.mark.parametrize(
    "lat, lng, kept",
    [
        (13.08, 80.27, True),  # Chennai
        (0.0019, -0.0347, False),  # CommonFloor (0,0)-ish placeholder
        (None, None, False),
        (51.5, -0.12, False),  # London
    ],
)
def test_normalize_drops_coords_outside_india(lat, lng, kept):
    p = BaseScraper._normalize({"latitude": lat, "longitude": lng})
    assert (p["latitude"] is not None) == kept and (p["longitude"] is not None) == kept


def test_normalize_fills_defaults():
    p = BaseScraper._normalize({"source": "x", "property_id": "9", "price": 10})
    assert p["price"] == 10
    assert p["listing_type"] == "buy"
    assert p["amenities"] == []
    assert p["furnishing"] == "Unknown"
