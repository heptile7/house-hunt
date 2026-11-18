import os
import time
import random
import re
import logging
from abc import ABC, abstractmethod

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import SCRAPER_CONFIG

# Optional residential proxy via ScraperAPI — set SCRAPER_API_KEY in .env to enable.
# Free tier: 1,000 requests/month at https://scraperapi.com
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "").strip()
SCRAPER_API_URL = "https://api.scraperapi.com/"

logger = logging.getLogger(__name__)

# number [unit] [- number [unit]] — unit is Cr/Crore, L/Lac/Lakh(s), or K.
_UNIT = r"(crores?|cr|lakhs?|lacs?|l|k)\b"
_PRICE_RE = re.compile(
    rf"(\d+(?:\.\d+)?)\s*(?:{_UNIT})?(?:\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:{_UNIT})?)?",
    re.IGNORECASE,
)

HEADERS_POOL = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Connection": "keep-alive",
        "DNT": "1",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    },
]


class BaseScraper(ABC):
    source_name: str = "base"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(random.choice(HEADERS_POOL))
        self.timeout = SCRAPER_CONFIG["timeout_seconds"]
        self.delay = SCRAPER_CONFIG["request_delay_seconds"]
        self.max_pages = SCRAPER_CONFIG["max_pages_per_source"]

    @property
    def has_proxy(self) -> bool:
        return bool(SCRAPER_API_KEY)

    def _get_proxied(self, url: str, render: bool = True, ultra: bool = False) -> requests.Response:
        """
        Fetch url via ScraperAPI residential proxies.
        render=True : ScraperAPI runs headless Chrome on their end — handles JS + WAF.
        ultra=True  : Uses ultra_premium residential IPs (needed for Akamai-protected sites).
        Raises RuntimeError if SCRAPER_API_KEY is not set.
        """
        if not SCRAPER_API_KEY:
            raise RuntimeError("SCRAPER_API_KEY not set — cannot use proxied fetch")
        params = {
            "api_key": SCRAPER_API_KEY,
            "url": url,
            "render": "true" if render else "false",
            "country_code": "in",
        }
        if ultra:
            params["ultra_premium"] = "true"
        resp = self.session.get(SCRAPER_API_URL, params=params, timeout=60)
        resp.raise_for_status()
        return resp

    def _sleep(self, extra: float = 0.0):
        jitter = random.uniform(0.5, 1.5)
        time.sleep(self.delay * jitter + extra)

    @retry(
        stop=stop_after_attempt(SCRAPER_CONFIG["max_retries"]),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
        reraise=True,
    )
    def _get(self, url: str, **kwargs) -> requests.Response:
        self.session.headers["User-Agent"] = random.choice(HEADERS_POOL)["User-Agent"]
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    @retry(
        stop=stop_after_attempt(SCRAPER_CONFIG["max_retries"]),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
        reraise=True,
    )
    def _post(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.post(url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    @abstractmethod
    def scrape(self, city: str, bhk: list[int] = None, max_price: int = None) -> list[dict]:
        """Return list of normalized property dicts."""

    @staticmethod
    def _normalize(p: dict) -> dict:
        defaults = {
            "source": "", "property_id": "", "listing_type": "buy", "title": "", "price": 0,
            "price_text": "", "area_sqft": 0.0, "bhk": 0, "property_type": "Apartment",
            "city": "", "locality": "", "address": "", "latitude": None, "longitude": None,
            "amenities": [], "image_url": "", "url": "", "furnishing": "Unknown",
            "posted_date": "", "is_new_project": 0, "builder_name": "",
            "rera_id": "", "floor": "", "total_floors": 0, "facing": "", "parking": 0,
        }
        return {**defaults, **p}

    @staticmethod
    def _parse_price(text) -> int:
        """Convert price strings like '45 Lac', '₹ 85 Lakhs', '1.2 Cr', '25K', '45 - 60 Lac'
        to integer rupees. For ranges the lower bound is used. Returns 0 if unparseable."""
        if text is None:
            return 0
        text = str(text).replace(",", "")
        m = _PRICE_RE.search(text)
        if not m:
            return 0
        num = float(m.group(1))
        # Unit may follow the number directly, or follow the upper bound of a range.
        unit = (m.group(2) or m.group(3) or "").lower()
        if unit.startswith("c"):
            mult = 1_00_00_000
        elif unit.startswith("l"):
            mult = 1_00_000
        elif unit.startswith("k"):
            mult = 1_000
        else:
            mult = 1
        return int(round(num * mult))

    @staticmethod
    def _parse_area(text: str) -> float:
        if not text:
            return 0.0
        text = text.lower().replace("sq.ft", "").replace("sqft", "").replace("sq ft", "").strip()
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return 0.0
