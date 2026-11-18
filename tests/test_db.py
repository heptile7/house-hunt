from conftest import make_prop


def test_upsert_and_query_filters(tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", bhk=2, price=5_000_000),
            make_prop(property_id="2", bhk=3, price=9_000_000, area_sqft=1500),
            make_prop(property_id="3", bhk=2, price=30_000, listing_type="rent"),
            make_prop(property_id="4", bhk=2, price=6_000_000, source="housing"),
            make_prop(property_id="5", bhk=2, price=6_000_000, city="Pune"),
        ]
    )
    q = tmp_db.query_properties

    assert len(q("Chennai")) == 3
    assert len(q("Chennai", listing_type="rent")) == 1
    assert {p["property_id"] for p in q("Chennai", bhk=[3])} == {"2"}
    assert {p["property_id"] for p in q("Chennai", price_max=6_000_000)} == {"1", "4"}
    assert {p["property_id"] for p in q("Chennai", price_min=6_000_000)} == {"2", "4"}
    assert {p["property_id"] for p in q("Chennai", sources=["housing"])} == {"4"}
    assert {p["property_id"] for p in q("Chennai", area_min=1200)} == {"2"}
    assert tmp_db.get_property_count("Chennai", "buy") == 3


def test_locality_filter_and_list(tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", locality="Velachery"),
            make_prop(property_id="2", locality="Velachery Main Road"),
            make_prop(property_id="3", locality="Adyar"),
            make_prop(property_id="4", locality="", title="2 BHK in Adyar Depot"),  # only in title
            make_prop(property_id="5", locality="Tambaram"),
        ]
    )
    q = tmp_db.query_properties
    assert {p["property_id"] for p in q("Chennai", localities=["velachery"])} == {"1", "2"}
    assert {p["property_id"] for p in q("Chennai", localities=["Adyar", "Tambaram"])} == {"3", "4", "5"}
    assert len(q("Chennai", localities=[])) == 5
    locs = tmp_db.get_localities("Chennai", "buy")
    assert locs[0]["count"] == 1 and {x["locality"] for x in locs} == {
        "Velachery",
        "Velachery Main Road",
        "Adyar",
        "Tambaram",
    }  # blank locality excluded


def test_same_id_buy_and_rent_are_distinct(tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", listing_type="buy"),
            make_prop(property_id="1", listing_type="rent", price=25_000),
        ]
    )
    assert tmp_db.get_property_count("Chennai", "buy") == 1
    assert tmp_db.get_property_count("Chennai", "rent") == 1


def test_conflict_updates_but_keeps_known_values(tmp_db):
    tmp_db.upsert_properties([make_prop(property_id="1", price=5_000_000, locality="Adyar", bhk=2)])
    # Re-scrape: new price, but locality/bhk/image missing this time.
    tmp_db.upsert_properties(
        [make_prop(property_id="1", price=5_500_000, locality="", bhk=0, image_url="", title="Updated title")]
    )
    [p] = tmp_db.query_properties("Chennai")
    assert p["price"] == 5_500_000
    assert p["title"] == "Updated title"
    assert p["locality"] == "Adyar"
    assert p["bhk"] == 2
    assert p["image_url"] == "https://example.com/1.jpg"


def test_scrape_logs_and_source_status(tmp_db):
    tmp_db.log_scrape("magicbricks", "Chennai", "success", 30)
    tmp_db.log_scrape("housing", "Chennai", "blocked", 0)
    status = {r["source"]: r for r in tmp_db.get_source_status("Chennai")}
    assert status["magicbricks"]["status"] == "success"
    assert status["magicbricks"]["best_count"] == 30
    assert status["housing"]["status"] == "blocked"
    assert status["housing"]["last_success_at"] is None
    assert tmp_db.get_last_scrape("Chennai") is not None
    assert tmp_db.get_last_scrape("Nowhere") is None
