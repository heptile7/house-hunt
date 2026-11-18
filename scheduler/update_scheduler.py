"""
Background scheduler that refreshes property data every N hours.
Can be run standalone:   python -m scheduler.update_scheduler
Or imported and started as a daemon thread from app.py.
"""
import logging
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import SCRAPER_CONFIG, SOURCES
from database.db import upsert_properties, log_scrape

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def run_scrapers(city: str, bhk: list[int] = None, max_price: int = None,
                 listing_type: str = "buy", progress_cb=None):
    from scrapers.magicbricks import MagicBricksScraper
    from scrapers.acres99 import Acres99Scraper
    from scrapers.nobroker import NoBrokerScraper
    from scrapers.housing import HousingScraper

    scraper_map = {
        "magicbricks": MagicBricksScraper,
        "99acres":     Acres99Scraper,
        "nobroker":    NoBrokerScraper,
        "housing":     HousingScraper,
    }

    results = {}
    for name, cls in scraper_map.items():
        try:
            logger.info(f"[Scheduler] Scraping {name} for {city} ({listing_type})...")
            scraper = cls()
            props = scraper.scrape(city, bhk=bhk, max_price=max_price, listing_type=listing_type)
            count = upsert_properties(props)
            scraped = len(props)
            status = "success" if scraped > 0 else "blocked"
            log_scrape(name, city, status, count)
            result = {"status": status, "scraped": scraped, "saved": count}
            logger.info(f"[Scheduler] {name}: {scraped} scraped, {count} saved")
        except Exception as e:
            logger.error(f"[Scheduler] {name} failed: {e}")
            log_scrape(name, city, "error", 0, str(e))
            result = {"status": "error", "scraped": 0, "saved": 0, "error": str(e)}

        results[name] = result
        if progress_cb:
            progress_cb(name, result)

    total = sum(r["saved"] for r in results.values())
    logger.info(f"[Scheduler] Done. Total saved for {city} ({listing_type}): {total}")
    return results


def start_scheduler(city: str, bhk: list[int] = None, max_price: int = None) -> BackgroundScheduler:
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            return _scheduler

        interval_hours = SCRAPER_CONFIG["update_interval_hours"]
        _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
        _scheduler.add_job(
            run_scrapers,
            trigger=IntervalTrigger(hours=interval_hours),
            args=[city, bhk, max_price],
            id="property_refresh",
            name=f"Refresh {city} every {interval_hours}h",
            replace_existing=True,
            next_run_time=datetime.now(),  # run immediately on start
        )
        _scheduler.start()
        logger.info(f"[Scheduler] Started — refreshing {city} every {interval_hours} hours")
    return _scheduler


def stop_scheduler():
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            _scheduler = None


def update_city(city: str, bhk: list[int] = None, max_price: int = None):
    """Reschedule with a new city (called when user changes city selection)."""
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            interval_hours = SCRAPER_CONFIG["update_interval_hours"]
            _scheduler.reschedule_job(
                "property_refresh",
                trigger=IntervalTrigger(hours=interval_hours),
            )
            _scheduler.modify_job(
                "property_refresh",
                args=[city, bhk, max_price],
                name=f"Refresh {city} every {interval_hours}h",
                next_run_time=datetime.now(),
            )
        else:
            start_scheduler(city, bhk, max_price)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    city = sys.argv[1] if len(sys.argv) > 1 else "Bangalore"
    logger.info(f"Running standalone scheduler for {city}")
    run_scrapers(city)
