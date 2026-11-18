import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Load .env before any module reads os.getenv (e.g. SCRAPER_API_KEY in base_scraper)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import threading
import logging
from datetime import datetime

from flask import Flask, render_template, request, jsonify

from config import INDIAN_CITIES, PROPERTY_TYPES, BHK_OPTIONS, SOURCE_LABELS, CITY_STATE
from database.db import init_db, query_properties, get_last_scrape, get_property_count, get_source_status
from scheduler.update_scheduler import run_scrapers
from utils.emi_calculator import total_cost_breakdown, format_inr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.json.sort_keys = False  # keep insertion order (e.g. price buckets sorted numerically)
init_db()

_fetch_status = {
    "running": False, "last_count": 0, "last_time": None,
    "results": {}, "progress": [], "city": None, "total_sources": 4,
}


def _num(value, cast=int, default=0):
    """Parse a user-supplied number, falling back to `default` on blank/invalid input."""
    try:
        return cast(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _price_multiplier(listing_type: str) -> int:
    """Buy prices are entered in lakhs; rent prices are entered in plain rupees."""
    return 100_000 if listing_type == "buy" else 1


def _run_scrapers_bg(city, bhk, max_price, listing_type):
    _fetch_status["running"] = True
    _fetch_status["results"] = {}
    _fetch_status["progress"] = []
    _fetch_status["city"] = city

    def on_progress(source, result):
        _fetch_status["progress"].append({"source": source, **result})

    try:
        results = run_scrapers(city, bhk=bhk, max_price=max_price,
                               listing_type=listing_type, progress_cb=on_progress)
        _fetch_status["results"] = results
        _fetch_status["last_count"] = sum(r.get("saved", 0) for r in results.values())
        _fetch_status["last_time"] = datetime.now().isoformat()
    except Exception as e:
        _fetch_status["results"] = {"error": {"status": "error", "error": str(e)}}
    finally:
        _fetch_status["running"] = False


@app.route("/")
def index():
    return render_template(
        "index.html",
        cities=INDIAN_CITIES,
        property_types=PROPERTY_TYPES,
        bhk_options=BHK_OPTIONS,
        sources=SOURCE_LABELS,
    )


@app.route("/api/properties")
def api_properties():
    city = request.args.get("city", "Chennai")
    listing_type = request.args.get("listing_type", "buy")
    bhk = [int(x) for x in request.args.getlist("bhk") if x.isdigit()]
    sources = request.args.getlist("source") or list(SOURCE_LABELS.keys())
    prop_types = request.args.getlist("type") or None
    mult = _price_multiplier(listing_type)
    price_min = int(_num(request.args.get("price_min"), float) * mult) or None
    price_max = int(_num(request.args.get("price_max"), float) * mult) or None
    area_min = _num(request.args.get("area_min"), float) or None
    area_max = _num(request.args.get("area_max"), float) or None
    sort_by = request.args.get("sort", "price")
    ascending = request.args.get("order", "asc") == "asc"

    props = query_properties(
        city=city,
        listing_type=listing_type,
        sources=sources,
        bhk=bhk or None,
        prop_types=prop_types,
        price_min=price_min,
        price_max=price_max,
        area_min=area_min,
        area_max=area_max,
        limit=500,
    )

    if sort_by in ("price", "area_sqft", "bhk"):
        props.sort(key=lambda p: p.get(sort_by) or 0, reverse=not ascending)

    last = get_last_scrape(city)
    return jsonify({
        "properties": props,
        "total": len(props),
        "db_count": get_property_count(city, listing_type),
        "last_fetch": last["scraped_at"][:16] if last else None,
    })


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    if _fetch_status["running"]:
        return jsonify({"status": "already_running"})
    data = request.get_json(silent=True) or {}
    city = data.get("city", "Chennai")
    listing_type = data.get("listing_type", "buy")
    bhk = [int(b) for b in (data.get("bhk") or []) if str(b).isdigit()] or None
    # Field is named max_price_lac for historical reasons; for rent it holds plain ₹.
    max_price = int(_num(data.get("max_price_lac"), float) * _price_multiplier(listing_type)) or None
    threading.Thread(target=_run_scrapers_bg, args=(city, bhk, max_price, listing_type), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/fetch/status")
def api_fetch_status():
    return jsonify(_fetch_status)


@app.route("/api/source-status")
def api_source_status():
    city = request.args.get("city", "Chennai")
    return jsonify(get_source_status(city))


@app.route("/api/proxy-status")
def api_proxy_status():
    from scrapers.base_scraper import SCRAPER_API_KEY
    return jsonify({
        "has_key": bool(SCRAPER_API_KEY),
        "working": ["magicbricks"],
        "blocked": {
            "99acres":  "Akamai CDN — blocks all proxy tiers including ultra_premium",
            "housing":  "React SPA + WAF — ScraperAPI gets the shell but listings never render",
            "nobroker": "React SPA — requires auth cookies from real browser session",
        },
        "message": (
            "MagicBricks is the only reliably accessible source. "
            "The other 3 sites use enterprise anti-bot infrastructure that cannot be bypassed "
            "with the current tooling."
        ),
    })


@app.route("/api/emi", methods=["POST"])
def api_emi():
    data = request.get_json(silent=True) or {}
    city = data.get("city", "Bangalore")
    result = total_cost_breakdown(
        price=_num(data.get("price"), int, 5_000_000),
        loan_pct=_num(data.get("loan_pct"), float, 80.0),
        rate=_num(data.get("rate"), float, 8.5),
        tenure=_num(data.get("tenure"), int, 20) or 20,
        state=CITY_STATE.get(city, "Karnataka"),
        under_construction=bool(data.get("under_construction", False)),
    )
    fmt = {f"{k}_fmt": format_inr(v) for k, v in result.items() if isinstance(v, int) and k != "months"}
    result.update(fmt)
    return jsonify(result)


@app.route("/api/analytics")
def api_analytics():
    city = request.args.get("city", "Chennai")
    listing_type = request.args.get("listing_type", "buy")
    props = query_properties(city=city, listing_type=listing_type, limit=500)
    if not props:
        return jsonify({})

    is_buy = listing_type == "buy"
    # Buy: 25 L wide buckets, averages in lakhs. Rent: ₹5k wide buckets, averages in ₹.
    bucket_width = 25 * 100_000 if is_buy else 5_000
    unit_div, unit = (100_000, "₹L") if is_buy else (1, "₹")

    def bucket_label(start: int) -> str:
        if is_buy:
            return f"{start // 100_000}-{(start + bucket_width) // 100_000}L"
        return f"{start // 1000}k-{(start + bucket_width) // 1000}k"

    def avg(total: float, n: int) -> float:
        return round(total / n / unit_div, 1) if n else 0

    bhk_counts: dict = {}
    bucket_counts: dict[int, int] = {}
    source_data: dict = {}
    locality_prices: dict = {}

    for p in props:
        # BHK distribution
        k = f"{p.get('bhk') or 0} BHK"
        bhk_counts[k] = bhk_counts.get(k, 0) + 1

        price = p.get("price") or 0
        if price:
            start = (price // bucket_width) * bucket_width
            bucket_counts[start] = bucket_counts.get(start, 0) + 1

        # Source stats
        src = p.get("source", "")
        if src not in source_data:
            source_data[src] = {"count": 0, "total": 0}
        source_data[src]["count"] += 1
        source_data[src]["total"] += price

        # Locality avg price
        loc = p.get("locality") or "Unknown"
        if loc not in locality_prices:
            locality_prices[loc] = []
        if price:
            locality_prices[loc].append(price)

    top_localities = sorted(
        [{"locality": k, "avg_price": avg(sum(v), len(v)), "count": len(v)}
         for k, v in locality_prices.items() if v],
        key=lambda x: x["avg_price"], reverse=True,
    )[:10]

    source_summary = {
        k: {"count": v["count"], "avg_price": avg(v["total"], v["count"])}
        for k, v in source_data.items()
    }

    price_buckets = {bucket_label(s): bucket_counts[s] for s in sorted(bucket_counts)}

    return jsonify({
        "bhk_counts": bhk_counts,
        "price_buckets": price_buckets,
        "source_data": source_summary,
        "top_localities": top_localities,
        "price_unit": unit,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
