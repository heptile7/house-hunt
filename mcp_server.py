"""
House Hunt India — MCP Server
Exposes property search tools to Claude Desktop or any MCP client. Uses the same
scrapers and SQLite DB as the web app (plain HTTP; no browser needed).

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

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import logging

from mcp.server.fastmcp import FastMCP

from config import INDIAN_CITIES, SOURCE_LABELS, SOURCES
from database.db import (
    get_localities,
    get_property_count,
    get_source_status,
    init_db,
    log_scrape,
    query_properties,
    upsert_properties,
)
from scheduler.update_scheduler import get_scraper_classes, run_scrapers

logging.basicConfig(level=logging.WARNING)
init_db()

mcp = FastMCP(
    "house-hunt-india",
    instructions=(
        "Search rental and sale property listings across Indian cities. "
        f"Sources: {', '.join(SOURCE_LABELS[s] for s in SOURCES)}. "
        "Prices: 'buy' amounts are in lakhs, 'rent' amounts are monthly rupees. "
        "Call fetch tools before query_saved_listings if the DB might be stale. "
        "Pass localities (e.g. ['Velachery', 'Adyar']) to target specific areas of a city."
    ),
)


def _price(value: float, listing_type: str) -> int | None:
    """Amounts are in lakhs for 'buy' but plain monthly ₹ for 'rent'. 0 = no limit."""
    if not value:
        return None
    return int(value * (100_000 if listing_type == "buy" else 1))


# ── Tool 1: Fetch from one source ─────────────────────────────────────────────


@mcp.tool()
def fetch_source(
    city: str,
    source: str = "nobroker",
    listing_type: str = "buy",
    bhk: list[int] | None = None,
    max_price_lac: float = 0,
    localities: list[str] | None = None,
    pages: int = 3,
) -> dict:
    """
    Fetch listings from a single source, save them to the local DB and return a sample.

    city: Indian city name e.g. 'Chennai', 'Bangalore'
    source: one of 'nobroker', 'squareyards', 'magicbricks', 'commonfloor'
    listing_type: 'buy' or 'rent'
    bhk: bedroom filter e.g. [2, 3]. None = all.
    max_price_lac: max price in Lakhs for 'buy'; monthly rent in ₹ for 'rent' (0 = no limit).
    localities: optional list of areas, e.g. ['Velachery']. NoBroker and SquareYards search
                these directly; other sources fetch city-wide.
    pages: result pages to fetch (per locality when localities are given), 1–10.
    """
    classes = get_scraper_classes()
    if source not in classes:
        return {"error": f"source must be one of {list(classes)}, got '{source}'"}
    scraper = classes[source]()
    scraper.max_pages = scraper.locality_pages = max(1, min(pages, 10))
    props = scraper.scrape(
        city,
        bhk=bhk or None,
        max_price=_price(max_price_lac, listing_type),
        listing_type=listing_type,
        localities=localities or None,
    )
    saved = upsert_properties(props)
    log_scrape(source, city, "success" if props else "blocked", saved)
    return {
        "source": source,
        "city": city,
        "listing_type": listing_type,
        "scraped": len(props),
        "saved_to_db": saved,
        "listings": _normalize_output(props[:10]),
    }


# ── Tool 2: Query local database ──────────────────────────────────────────────


@mcp.tool()
def query_saved_listings(
    city: str,
    listing_type: str = "buy",
    bhk: list[int] | None = None,
    price_min_lac: float = 0,
    price_max_lac: float = 0,
    source: str | None = None,
    localities: list[str] | None = None,
    pets_allowed: bool = False,
    non_veg_allowed: bool = False,
    posted_within_days: int = 0,
    available_by: str | None = None,
    sort_by: str = "price",
    limit: int = 20,
) -> dict:
    """
    Query property listings already saved in the local database (no network calls).

    city: Indian city name
    listing_type: 'buy' or 'rent'
    bhk: bedroom filter e.g. [2, 3]. None = all.
    price_min_lac / price_max_lac: price range in Lakhs for 'buy', monthly ₹ for 'rent' (0 = no limit).
    source: filter to one source e.g. 'nobroker'. None = all sources.
    localities: match any of these areas (substring of locality/title/address), e.g. ['Adyar'].
    pets_allowed / non_veg_allowed: only listings that explicitly allow pets / non-veg food.
    posted_within_days: only listings posted (or updated) in the last N days (0 = any).
    available_by: ISO date 'YYYY-MM-DD' — only listings you can move into by then.
    sort_by: 'price', 'area_sqft', 'bhk', or 'posted' (newest first)
    Each listing includes posted_date, available_from, tenant_preference, pets_allowed,
    non_veg_allowed (1/0/null = unknown), amenities, deposit, maintenance and description.
    limit: max results to return (max 100)
    """
    props = query_properties(
        city=city,
        listing_type=listing_type,
        sources=[source] if source else None,
        bhk=bhk or None,
        price_min=_price(price_min_lac, listing_type),
        price_max=_price(price_max_lac, listing_type),
        localities=localities or None,
        pets_allowed=pets_allowed,
        non_veg_allowed=non_veg_allowed,
        posted_within_days=posted_within_days or None,
        available_by=available_by or None,
        limit=min(limit, 100),
    )
    if sort_by in ("price", "area_sqft", "bhk"):
        props.sort(key=lambda p: p.get(sort_by) or 0)
    elif sort_by == "posted":
        props.sort(key=lambda p: p.get("posted_date") or p.get("updated_date") or "", reverse=True)

    return {
        "city": city,
        "listing_type": listing_type,
        "total_in_db": get_property_count(city, listing_type),
        "returned": len(props),
        "listings": _normalize_output(props),
    }


# ── Tool 3: Localities in the DB ──────────────────────────────────────────────


@mcp.tool()
def list_localities(city: str, listing_type: str = "buy", limit: int = 50) -> dict:
    """List localities that have saved listings for a city, with listing counts."""
    return {
        "city": city,
        "listing_type": listing_type,
        "localities": get_localities(city, listing_type, limit=min(limit, 300)),
    }


# ── Tool 4: Source health status ──────────────────────────────────────────────


@mcp.tool()
def get_source_health(city: str = "Chennai") -> dict:
    """
    Return the last fetch status for each data source for a given city.
    Shows whether each source is working, blocked, or has never been fetched.
    """
    rows = [r for r in get_source_status(city) if r["source"] in SOURCES]
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
    bhk: list[int] | None = None,
    max_price_lac: float = 0,
    localities: list[str] | None = None,
) -> dict:
    """
    Fetch from all active sources for a city in one call (same as the web app's Fetch Now).
    max_price_lac: max price in Lakhs for 'buy'; monthly rent in ₹ for 'rent' (0 = no limit).
    localities: optional areas to target, e.g. ['Velachery', 'Adyar'].
    Returns a summary of results per source.
    """
    results = run_scrapers(
        city,
        bhk=bhk or None,
        max_price=_price(max_price_lac, listing_type),
        listing_type=listing_type,
        localities=localities or None,
    )
    return {
        "city": city,
        "listing_type": listing_type,
        "localities": localities or [],
        "results_by_source": results,
        "total_saved": sum(r["saved"] for r in results.values()),
        "db_count": get_property_count(city, listing_type),
    }


def _normalize_output(props: list[dict]) -> list[dict]:
    """Strip DB-only fields for cleaner MCP output."""
    keep = {
        "source",
        "listing_type",
        "title",
        "price",
        "price_text",
        "area_sqft",
        "bhk",
        "locality",
        "city",
        "url",
        "furnishing",
        "image_url",
        "property_id",
        "floor",
        "facing",
        "parking",
        "latitude",
        "longitude",
        "posted_date",
        "updated_date",
        "available_from",
        "tenant_preference",
        "pets_allowed",
        "non_veg_allowed",
        "amenities",
        "deposit",
        "maintenance",
        "occupancy",
        "description",
    }
    return [{k: v for k, v in p.items() if k in keep} for p in props]


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
