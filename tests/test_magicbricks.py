from pathlib import Path

from bs4 import BeautifulSoup

from scrapers.magicbricks import MagicBricksScraper

FIXTURE = Path(__file__).parent / "fixtures" / "magicbricks_rent_cards.html"


def _parse():
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "lxml")
    return MagicBricksScraper()._parse_cards(soup, "Chennai")


def test_parses_real_cards():
    props = _parse()
    assert len(props) == 3
    # Every listing gets its own ID from the /propertyDetails/...&id=<hex> link
    assert len({p["property_id"] for p in props}) == 3
    for p in props:
        assert p["title"] and p["price"] > 0 and p["bhk"] > 0 and p["area_sqft"] > 0
        assert p["locality"] and not p["locality"].lower().endswith("chennai")
        assert p["url"].startswith("https://www.magicbricks.com/propertyDetails/")
        assert "magicbricks.comhttps" not in p["url"]


def test_first_card_fields():
    p = _parse()[0]
    assert p["bhk"] == 2
    assert p["price"] == 40_000
    assert p["area_sqft"] == 1027.0
    assert p["locality"] == "Karapakkam"
    assert p["furnishing"] == "Furnished"
    assert p["floor"] == "10 out of 19" and p["total_floors"] == 19
    assert p["facing"] == "East"
    assert p["address"] == "Doshi Risington"
    assert p["image_url"].startswith("https://img.staticmb.com/")


def test_card_without_detail_link_is_skipped():
    soup = BeautifulSoup(
        '<div class="mb-srp__card"><h2 class="mb-srp__card--title">2 BHK in X</h2>'
        '<a href="/some-project-pdpid-abc">p</a></div>',
        "lxml",
    )
    assert MagicBricksScraper()._parse_cards(soup, "Chennai") == []
