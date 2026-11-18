from conftest import make_prop


def test_properties_endpoint_filters_and_sorts(client, tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", price=9_000_000),
            make_prop(property_id="2", price=5_000_000),
            make_prop(property_id="3", price=20_000, listing_type="rent"),
        ]
    )
    r = client.get("/api/properties?city=Chennai&sort=price&order=asc")
    data = r.get_json()
    assert r.status_code == 200
    assert [p["property_id"] for p in data["properties"]] == ["2", "1"]

    # Buy price filter is in lakhs
    data = client.get("/api/properties?city=Chennai&price_max=60").get_json()
    assert [p["property_id"] for p in data["properties"]] == ["2"]

    # Rent price filter is in plain rupees
    data = client.get("/api/properties?city=Chennai&listing_type=rent&price_max=25000").get_json()
    assert [p["property_id"] for p in data["properties"]] == ["3"]


def test_properties_and_analytics_locality_filter(client, tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", locality="Velachery"),
            make_prop(property_id="2", locality="Adyar"),
            make_prop(property_id="3", locality="Adyar"),
        ]
    )
    d = client.get("/api/properties?city=Chennai&locality=Adyar").get_json()
    assert {p["property_id"] for p in d["properties"]} == {"2", "3"}
    d = client.get("/api/properties?city=Chennai&locality=Adyar&locality=Velachery").get_json()
    assert d["total"] == 3
    a = client.get("/api/analytics?city=Chennai&locality=Velachery").get_json()
    assert sum(a["bhk_counts"].values()) == 1
    locs = client.get("/api/localities?city=Chennai&listing_type=buy").get_json()
    assert locs[0] == {"locality": "Adyar", "count": 2}


def test_index_lists_active_sources_only(client):
    html = client.get("/").get_data(as_text=True)
    for label in ("NoBroker", "SquareYards", "MagicBricks", "CommonFloor"):
        assert label in html
    assert "src-99acres" not in html and "src-housing" not in html


def test_properties_bad_params_do_not_500(client):
    r = client.get("/api/properties?city=Chennai&price_min=abc&area_max=xyz")
    assert r.status_code == 200


def test_emi_endpoint(client):
    r = client.post("/api/emi", json={"city": "Coimbatore", "price": 5_000_000})
    d = r.get_json()
    assert r.status_code == 200
    assert d["gst"] == 0
    assert d["stamp_rate"] == 7.0  # Tamil Nadu
    assert d["emi_fmt"].startswith("₹")

    d = client.post("/api/emi", json={"price": 9_000_000, "under_construction": True}).get_json()
    assert d["gst"] == 450_000


def test_analytics_buy_buckets(client, tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", price=3_000_000),
            make_prop(property_id="2", price=13_000_000),
            make_prop(property_id="3", price=4_000_000),
        ]
    )
    d = client.get("/api/analytics?city=Chennai").get_json()
    assert d["price_unit"] == "₹L"
    assert d["price_buckets"] == {"25-50L": 2, "125-150L": 1}
    assert list(d["price_buckets"]) == ["25-50L", "125-150L"]  # numeric order


def test_analytics_rent_buckets(client, tmp_db):
    tmp_db.upsert_properties(
        [
            make_prop(property_id="1", price=18_000, listing_type="rent"),
            make_prop(property_id="2", price=32_000, listing_type="rent"),
            make_prop(property_id="3", price=19_500, listing_type="rent"),
        ]
    )
    d = client.get("/api/analytics?city=Chennai&listing_type=rent").get_json()
    assert d["price_unit"] == "₹"
    assert d["price_buckets"] == {"15k-20k": 2, "30k-35k": 1}
    assert d["source_data"]["magicbricks"]["avg_price"] == round((18_000 + 32_000 + 19_500) / 3, 1)


def test_analytics_empty(client):
    assert client.get("/api/analytics?city=Nowhere").get_json() == {}


def test_fetch_rent_price_not_multiplied(client, monkeypatch):
    import app as app_module

    captured = {}

    class FakeThread:
        def __init__(self, target, args, daemon):
            captured["args"] = args

        def start(self):
            pass

    monkeypatch.setattr(app_module.threading, "Thread", FakeThread)
    client.post("/api/fetch", json={"city": "Chennai", "listing_type": "rent", "max_price_lac": 30000})
    assert captured["args"][2] == 30_000
    client.post("/api/fetch", json={"city": "Chennai", "listing_type": "buy", "max_price_lac": 50})
    assert captured["args"][2] == 5_000_000
    assert captured["args"][4] is None  # no localities
    client.post(
        "/api/fetch", json={"city": "Chennai", "listing_type": "rent", "localities": ["Velachery", " ", "Adyar "]}
    )
    assert captured["args"][4] == ["Velachery", "Adyar"]
