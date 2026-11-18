"""
House Hunt India — MCP Server
Exposes property search tools to Claude Desktop or any MCP client.

Key capability: uses Playwright network interception for sites that block direct API calls.
The browser loads the page naturally, we capture the JSON responses the page
sends to its own backend — no need to reverse-engineer hashes or auth tokens.

Usage (Claude Desktop):
  Add to claude_desktop_config.json:
  {
    "mcpServers": {
      "house-hunt": {
        "command": "path/to/.venv/Scripts/python.exe",
        "args": ["path/to/mcp_server.py"]
      }
    }
  }
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from database.db import init_db, query_properties, get_property_count, upsert_properties, get_source_status
from config import INDIAN_CITIES, CITY_SLUGS, SOURCE_LABELS

logging.basicConfig(level=logging.WARNING)
init_db()

mcp = FastMCP(
    "house-hunt-india",
    instructions=(
        "Search rental and sale property listings across Indian cities. "
        "Sources: MagicBricks (reliable via HTTP), Housing.com & NoBroker (via browser interception). "
        "Always call fetch tools before query_saved_listings if the DB might be stale."
    ),
)


def _max_price(value: float, listing_type: str) -> Optional[int]:
    """max_price_lac is in lakhs for 'buy' but plain monthly ₹ for 'rent'. 0 = no limit."""
    if not value:
        return None
    return int(value * (100_000 if listing_type == "buy" else 1))


# ── Tool 1: Fetch from MagicBricks ────────────────────────────────────────────

@mcp.tool()
def fetch_magicbricks(
    city: str,
    listing_type: str = "buy",
    bhk: Optional[list[int]] = None,
    max_price_lac: float = 0,
    pages: int = 3,
) -> dict:
    """
    Fetch property listings from MagicBricks — the most reliable source, no bot detection.
    Results are saved to the local database and returned immediately.

    city: Indian city name e.g. 'Chennai', 'Bangalore', 'Mumbai'
    listing_type: 'buy' or 'rent'
    bhk: list of bedroom counts e.g. [2, 3]. None = all.
    max_price_lac: max price in Lakhs (0 = no limit). For rent, enter monthly rent in ₹ (0 = no limit).
    pages: number of result pages to scrape (1 page ≈ 30 listings)
    """
    from scrapers.magicbricks import MagicBricksScraper

    scraper = MagicBricksScraper()
    scraper.max_pages = max(1, min(pages, 10))
    max_price = _max_price(max_price_lac, listing_type)

    props = scraper.scrape(city, bhk=bhk or None, max_price=max_price, listing_type=listing_type)
    saved = upsert_properties(props)

    return {
        "source": "magicbricks",
        "city": city,
        "listing_type": listing_type,
        "scraped": len(props),
        "saved_to_db": saved,
        "listings": _normalize_output(props[:10]),
    }


# ── Tool 2: Fetch via browser interception ────────────────────────────────────

@mcp.tool()
def fetch_via_browser(
    city: str,
    source: str,
    listing_type: str = "buy",
    bhk: Optional[list[int]] = None,
) -> dict:
    """
    Fetch listings from Housing.com or NoBroker using Playwright network interception.
    A real Chromium browser loads the search page; we capture the JSON API responses
    the page makes to its own backend — bypasses hash/session requirements completely.

    city: Indian city name e.g. 'Chennai'
    source: 'housing' or 'nobroker'
    listing_type: 'buy' or 'rent'
    bhk: bedroom filter e.g. [2, 3]
    """
    if source not in ("housing", "nobroker"):
        return {"error": f"source must be 'housing' or 'nobroker', got '{source}'"}

    city_slug_key = "hc" if source == "housing" else "nb"
    city_slug = CITY_SLUGS.get(city, {}).get(city_slug_key, city.lower().replace(" ", "-"))

    URLS = {
        "housing":  f"https://housing.com/in/{listing_type}/{city_slug}",
        "nobroker": f"https://www.nobroker.in/property/residential/{city_slug}/{listing_type}/",
    }
    INTERCEPT = {
        "housing":  "mightyzeus-mum.housing.com/api/gql",
        "nobroker": "nobroker.in/api/v1/search",
    }

    url = URLS[source]
    pattern = INTERCEPT[source]

    props = _intercept_and_parse(url, pattern, source, city, listing_type, bhk)
    saved = upsert_properties(props) if props else 0

    return {
        "source": source,
        "city": city,
        "listing_type": listing_type,
        "scraped": len(props),
        "saved_to_db": saved,
        "listings": _normalize_output(props[:10]),
        "note": "0 results means the site's bot detection prevented rendering" if not props else "",
    }


# ── Tool 3: Query local database ──────────────────────────────────────────────

@mcp.tool()
def query_saved_listings(
    city: str,
    listing_type: str = "buy",
    bhk: Optional[list[int]] = None,
    price_min_lac: float = 0,
    price_max_lac: float = 0,
    source: Optional[str] = None,
    sort_by: str = "price",
    limit: int = 20,
) -> dict:
    """
    Query property listings already saved in the local database (no network calls).

    city: Indian city name
    listing_type: 'buy' or 'rent'
    bhk: bedroom filter e.g. [2, 3]. None = all.
    price_min_lac / price_max_lac: price range in Lakhs for 'buy', monthly ₹ for 'rent' (0 = no limit).
    source: filter to one source e.g. 'magicbricks'. None = all sources.
    sort_by: 'price', 'area_sqft', or 'bhk'
    limit: max results to return (max 100)
    """
    price_min = _max_price(price_min_lac, listing_type)
    price_max = _max_price(price_max_lac, listing_type)
    sources = [source] if source else None

    props = query_properties(
        city=city,
        listing_type=listing_type,
        sources=sources,
        bhk=bhk or None,
        price_min=price_min,
        price_max=price_max,
        limit=min(limit, 100),
    )

    if sort_by in ("price", "area_sqft", "bhk"):
        props.sort(key=lambda p: p.get(sort_by) or 0)

    total = get_property_count(city, listing_type)

    return {
        "city": city,
        "listing_type": listing_type,
        "total_in_db": total,
        "returned": len(props),
        "listings": _normalize_output(props),
    }


# ── Tool 4: Source health status ──────────────────────────────────────────────

@mcp.tool()
def get_source_health(city: str = "Chennai") -> dict:
    """
    Return the last fetch status for each data source for a given city.
    Shows whether each source is working, blocked, or has never been fetched.
    """
    rows = get_source_status(city)
    return {
        "city": city,
        "sources": {
            r["source"]: {
                "label": SOURCE_LABELS.get(r["source"], r["source"]),
                "last_status": r["status"],
                "last_fetched": r["scraped_at"],
                "last_count": r["properties_fetched"],
                "best_count_ever": r.get("best_count", 0),
                "last_success": r.get("last_success_at"),
            }
            for r in rows
        },
        "available_cities": INDIAN_CITIES,
    }


# ── Tool 5: Fetch all sources ─────────────────────────────────────────────────

@mcp.tool()
def fetch_all_sources(
    city: str,
    listing_type: str = "buy",
    bhk: Optional[list[int]] = None,
    max_price_lac: float = 0,
) -> dict:
    """
    Fetch from all available sources for a city in one call.
    MagicBricks uses fast HTTP requests; Housing.com and NoBroker use browser interception.
    max_price_lac: max price in Lakhs for 'buy'; monthly rent in ₹ for 'rent' (0 = no limit).
    Returns a summary of results per source.
    """
    from scrapers.magicbricks import MagicBricksScraper
    from database.db import log_scrape

    results = {}

    # MagicBricks — fast, reliable
    try:
        scraper = MagicBricksScraper()
        max_price = _max_price(max_price_lac, listing_type)
        props = scraper.scrape(city, bhk=bhk or None, max_price=max_price, listing_type=listing_type)
        saved = upsert_properties(props)
        log_scrape("magicbricks", city, "success" if props else "blocked", saved)
        results["magicbricks"] = {"scraped": len(props), "saved": saved, "status": "success" if props else "blocked"}
    except Exception as e:
        log_scrape("magicbricks", city, "error", 0, str(e))
        results["magicbricks"] = {"scraped": 0, "saved": 0, "status": "error", "error": str(e)}

    # Housing.com — browser interception
    for source, key, url_tpl in [
        ("housing",  "hc", "https://housing.com/in/{lt}/{cs}"),
        ("nobroker", "nb", "https://www.nobroker.in/property/residential/{cs}/{lt}/"),
    ]:
        try:
            cs = CITY_SLUGS.get(city, {}).get(key, city.lower())
            url = url_tpl.format(lt=listing_type, cs=cs)
            pattern = "mightyzeus-mum.housing.com/api/gql" if source == "housing" else "nobroker.in/api/v1/search"
            props = _intercept_and_parse(url, pattern, source, city, listing_type, bhk)
            saved = upsert_properties(props) if props else 0
            status = "success" if props else "blocked"
            log_scrape(source, city, status, saved)
            results[source] = {"scraped": len(props), "saved": saved, "status": status}
        except Exception as e:
            log_scrape(source, city, "error", 0, str(e))
            results[source] = {"scraped": 0, "saved": 0, "status": "error", "error": str(e)[:100]}

    total_saved = sum(r["saved"] for r in results.values())
    return {
        "city": city,
        "listing_type": listing_type,
        "results_by_source": results,
        "total_saved": total_saved,
        "db_count": get_property_count(city, listing_type),
    }


# ── Playwright interception helper ────────────────────────────────────────────

def _intercept_and_parse(
    url: str,
    api_pattern: str,
    source: str,
    city: str,
    listing_type: str,
    bhk: Optional[list[int]] = None,
) -> list[dict]:
    """
    Load `url` in headless Chromium, intercept JSON responses matching `api_pattern`,
    parse them into normalized property dicts.
    """
    from playwright.sync_api import sync_playwright
    from scrapers.base_scraper import BaseScraper

    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        page = ctx.new_page()

        def on_response(response):
            if api_pattern in response.url:
                try:
                    data = response.json()
                    captured.append({"url": response.url, "data": data})
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=45_000)
            page.wait_for_timeout(4_000)
        except Exception:
            pass  # timeout is OK — we may have already captured responses

        browser.close()

    return _parse_intercepted(source, captured, city, listing_type)


def _parse_intercepted(source: str, responses: list[dict], city: str, listing_type: str) -> list[dict]:
    """Parse raw intercepted API responses into normalized property dicts."""
    from scrapers.base_scraper import BaseScraper

    norm = BaseScraper._normalize
    results: list[dict] = []

    if source == "housing":
        for r in responses:
            data = r.get("data", {})
            # GraphQL response: data.searchResults.properties
            props = (
                data.get("data", {}).get("searchResults", {}).get("properties") or []
            )
            for p in (props or []):
                if not p:
                    continue
                loc = p.get("location", {})
                locality = loc.get("label", "") if isinstance(loc, dict) else str(loc or "")
                results.append(norm({
                    "source": "housing",
                    "listing_type": listing_type,
                    "property_id": str(p.get("listingId") or p.get("name") or ""),
                    "title": p.get("name") or p.get("title") or "",
                    "price": int(p.get("price") or 0),
                    "price_text": "",
                    "area_sqft": float((p.get("carpetArea") or {}).get("value", 0) if isinstance(p.get("carpetArea"), dict) else 0),
                    "bhk": int(p.get("bhk") or 0),
                    "locality": locality,
                    "city": city,
                    "url": p.get("url") or "",
                    "furnishing": p.get("furnishingType") or "",
                    "image_url": (p.get("coverImage") or {}).get("url", "") if isinstance(p.get("coverImage"), dict) else "",
                }))

    elif source == "nobroker":
        for r in responses:
            data = r.get("data", {})
            props = (
                data.get("data", {}).get("results") or
                data.get("result", []) or
                data.get("properties", []) or []
            )
            for p in (props or []):
                if not p:
                    continue
                results.append(norm({
                    "source": "nobroker",
                    "listing_type": listing_type,
                    "property_id": str(p.get("id") or p.get("propertyId") or ""),
                    "title": f"{p.get('bhk', '')} BHK {p.get('propertyType', 'Property')} in {p.get('locality', '')}",
                    "price": int(p.get("price") or p.get("expectedPrice") or p.get("rent") or 0),
                    "area_sqft": float(p.get("builtArea") or p.get("carpetArea") or p.get("area") or 0),
                    "bhk": int(p.get("bhk") or p.get("bedroom") or 0),
                    "locality": p.get("locality") or p.get("location") or "",
                    "city": city,
                    "url": p.get("url") or "",
                    "furnishing": p.get("furnishing") or "",
                    "image_url": (p.get("images") or [{}])[0].get("url", "") if p.get("images") else "",
                }))

    return results


def _normalize_output(props: list[dict]) -> list[dict]:
    """Strip DB-only fields for cleaner MCP output."""
    keep = {"source", "listing_type", "title", "price", "price_text", "area_sqft",
            "bhk", "locality", "city", "url", "furnishing", "image_url",
            "property_id", "floor", "facing", "parking"}
    return [{k: v for k, v in p.items() if k in keep} for p in props]


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
