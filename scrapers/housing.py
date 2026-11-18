import json
import logging
import re

from bs4 import BeautifulSoup

from config import CITY_SLUGS
from scrapers.playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://housing.com"


class HousingScraper(PlaywrightScraper):
    source_name = "housing"

    def scrape(self, city: str, bhk: list[int] = None, max_price: int = None, listing_type: str = "buy") -> list[dict]:
        # Housing.com WAF (406) + React SPA = no data without full session.
        # ScraperAPI render=true gets the page but React never populates listings in their timeout.
        # Fail fast rather than spending 2+ minutes launching browsers.
        if not self.has_proxy:
            logger.warning("[Housing.com] WAF blocks direct access. Set SCRAPER_API_KEY to enable.")
            return []

        city_slug = CITY_SLUGS.get(city, {}).get("hc", city.lower().replace(" ", "-"))
        results = []
        for page in range(1, self.max_pages + 1):
            try:
                props = self._scrape_page(city_slug, city, page, bhk, max_price, listing_type)
                if not props:
                    break
                results.extend(props)
                self._sleep()
            except Exception as e:
                logger.warning(f"[Housing.com] page {page} error: {e}")
                break
        return results

    def _scrape_page(self, city_slug: str, city: str, page: int, bhk, max_price, listing_type: str) -> list[dict]:
        bedroom_str = "&bedrooms=" + ",".join(str(b) for b in bhk) if bhk else ""
        budget_str = f"&max_price={max_price}" if max_price else ""
        offset = (page - 1) * 25
        mode = listing_type

        # Correct URL: /in/rent/chennai (not /in/rent/chennai/chennai)
        url = f"{BASE_URL}/in/{mode}/{city_slug}?{bedroom_str.lstrip('&')}{budget_str}&offset={offset}"

        # ScraperAPI render=true: their headless Chrome on a residential IP
        resp = self._get_proxied(url, render=True)
        html = resp.text

        soup = BeautifulSoup(html, "lxml")
        props = self._extract_json_data(html, city) or self._parse_cards(soup, city)
        for p in props:
            p["listing_type"] = listing_type
        return props

    def _extract_json_data(self, html: str, city: str) -> list[dict]:
        results = []
        patterns = [
            r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;",
            r"__NEXT_DATA__.*?=\s*({.*?})</script>",
        ]
        for pat in patterns:
            m = re.search(pat, html, re.DOTALL)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
                listings = self._dig_listings(data)
                for item in listings:
                    p = self._map_item(item, city)
                    if p:
                        results.append(p)
                if results:
                    return results
            except Exception:
                continue
        return results

    def _dig_listings(self, data: dict) -> list:
        """Traverse nested JSON to find listings array."""
        candidates = [
            data.get("props", {}).get("pageProps", {}).get("listings"),
            data.get("listings"),
            data.get("srp", {}).get("results"),
            data.get("data", {}).get("listings"),
        ]
        for c in candidates:
            if isinstance(c, list) and c:
                return c
        return []

    def _map_item(self, item: dict, city: str) -> dict | None:
        try:
            prop_id = str(item.get("id") or item.get("propertyId", ""))
            if not prop_id:
                return None
            price = item.get("price") or item.get("priceDetails", {}).get("price") or 0
            area = item.get("area") or item.get("builtUpArea") or 0
            bhk = item.get("bedrooms") or item.get("bhk") or 0
            loc = item.get("locality") or item.get("subLocality") or ""
            title = item.get("projectName") or item.get("title") or f"{bhk} BHK in {loc}"
            url_path = item.get("url") or item.get("seoUrl") or f"/in/buy/{city.lower()}/{prop_id}"
            url = url_path if url_path.startswith("http") else BASE_URL + url_path
            images = item.get("images") or item.get("photos") or []
            image_url = (images[0].get("url") or images[0]) if images else ""
            if isinstance(image_url, dict):
                image_url = image_url.get("url", "")

            return self._normalize(
                {
                    "source": self.source_name,
                    "property_id": prop_id,
                    "title": title,
                    "price": int(price),
                    "price_text": self._format_price(int(price)),
                    "area_sqft": float(area),
                    "bhk": int(bhk),
                    "city": city,
                    "locality": loc,
                    "url": url,
                    "image_url": str(image_url),
                    "is_new_project": 1 if item.get("isNewProject") else 0,
                    "builder_name": item.get("developerName") or item.get("builder", ""),
                    "rera_id": item.get("reraId", ""),
                    "furnishing": item.get("furnishing", ""),
                }
            )
        except Exception as e:
            logger.debug(f"[Housing.com] map error: {e}")
            return None

    def _parse_cards(self, soup: BeautifulSoup, city: str) -> list[dict]:
        results = []
        cards = soup.select("[data-id], .listing-card, .srp-card, article")
        for card in cards:
            try:
                prop_id = card.get("data-id", "")
                title_el = card.select_one("h2, h3, .title, .project-name")
                price_el = card.select_one(".price, [class*='price']")
                loc_el = card.select_one(".locality, .location, [class*='locality']")
                area_el = card.select_one(".area, [class*='area']")
                link_el = card.select_one("a[href]")
                img_el = card.select_one("img")

                title = title_el.get_text(strip=True) if title_el else ""
                price_text = price_el.get_text(strip=True) if price_el else ""
                locality = loc_el.get_text(strip=True) if loc_el else ""
                area_text = area_el.get_text(strip=True) if area_el else ""
                url = link_el["href"] if link_el else ""
                if url and not url.startswith("http"):
                    url = BASE_URL + url
                image_url = img_el.get("data-src") or img_el.get("src", "") if img_el else ""

                bhk_match = re.search(r"(\d)\s*BHK", title, re.I)
                bhk = int(bhk_match.group(1)) if bhk_match else 0

                results.append(
                    self._normalize(
                        {
                            "source": self.source_name,
                            "property_id": prop_id or url[-12:],
                            "title": title,
                            "price": self._parse_price(price_text),
                            "price_text": price_text,
                            "area_sqft": self._parse_area(area_text),
                            "bhk": bhk,
                            "city": city,
                            "locality": locality,
                            "url": url,
                            "image_url": image_url,
                        }
                    )
                )
            except Exception as e:
                logger.debug(f"[Housing.com] card parse error: {e}")
        return results

    @staticmethod
    def _format_price(price: int) -> str:
        if price >= 1_00_00_000:
            return f"₹{price / 1_00_00_000:.2f} Cr"
        elif price >= 1_00_000:
            return f"₹{price / 1_00_000:.1f} Lac"
        return f"₹{price:,}"
