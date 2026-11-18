import json
import logging
import re

from bs4 import BeautifulSoup

from config import CITY_SLUGS
from scrapers.playwright_base import PlaywrightScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.99acres.com"


class Acres99Scraper(PlaywrightScraper):
    source_name = "99acres"

    def scrape(self, city: str, bhk: list[int] = None, max_price: int = None, listing_type: str = "buy") -> list[dict]:
        city_slug = CITY_SLUGS.get(city, {}).get("99a", city.lower())
        results = []
        if self.has_proxy:
            self._start_browser()  # used only if Playwright path is ever needed
        try:
            for page in range(1, self.max_pages + 1):
                try:
                    props = self._scrape_page(city_slug, city, page, bhk, max_price, listing_type)
                    if not props:
                        break
                    results.extend(props)
                    self._sleep()
                except Exception as e:
                    logger.warning(f"[99acres] page {page} error: {e}")
                    break
        finally:
            if self.has_proxy:
                self._stop_browser()
        return results

    def _scrape_page(self, city_slug: str, city: str, page: int, bhk, max_price, listing_type: str) -> list[dict]:
        bedroom_str = f"&bedroom={'%2C'.join(str(b) for b in bhk)}" if bhk else ""
        budget_str = f"&budget_max={max_price}" if max_price else ""
        offset = (page - 1) * 30
        mode = "buy" if listing_type == "buy" else "rent"

        url = (
            f"{BASE_URL}/search/property/{mode}/{city_slug}-ffid"
            f"?preference=S{bedroom_str}{budget_str}&offset={offset}&postedSince=-1"
        )

        if self.has_proxy:
            # ScraperAPI with ultra_premium — 99acres uses Akamai which blocks even premium tiers.
            # ultra_premium uses the highest-grade residential IPs; last viable option.
            resp = self._get_proxied(url, render=True, ultra=True)
            html = resp.text
        else:
            # Without a proxy, Akamai blocks at network level before browser loads.
            # Return empty so caller logs it as "blocked" rather than an error.
            logger.warning("[99acres] Akamai CDN block — SCRAPER_API_KEY required")
            return []

        soup = BeautifulSoup(html, "lxml")
        props = self._extract_from_json(html, city) or self._parse_html_cards(soup, city)
        for p in props:
            p["listing_type"] = listing_type
        return props

    def _extract_from_json(self, html: str, city: str) -> list[dict]:
        """99acres embeds property data in a __INITIAL_STATE__ or window.__data JSON blob."""
        results = []
        patterns = [
            r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});",
            r"window\.__data\s*=\s*(\{.*?\});",
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.DOTALL)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
                listings = (
                    data.get("srp", {}).get("listingData", {}).get("data", [])
                    or data.get("listings", [])
                    or data.get("data", {}).get("listings", [])
                )
                for item in listings:
                    p = self._map_listing(item, city)
                    if p:
                        results.append(p)
                if results:
                    return results
            except Exception:
                continue
        return []

    def _map_listing(self, item: dict, city: str) -> dict | None:
        try:
            prop_id = str(item.get("propertyId") or item.get("id", ""))
            if not prop_id:
                return None
            price_raw = item.get("priceDetails", {}).get("price") or item.get("price", 0)
            area_raw = item.get("areaDetails", {}).get("area") or item.get("builtUpArea", 0)
            bhk_raw = item.get("bedroom") or item.get("bhk") or 0
            locality = item.get("localityDetails", {}).get("localityName") or item.get("locality", "")
            title = item.get("projectName") or item.get("title") or f"{bhk_raw} BHK in {locality}"
            price_text = item.get("priceDetails", {}).get("priceLabel") or str(price_raw)
            url = item.get("url") or f"{BASE_URL}/property/{prop_id}"
            image_url = (item.get("photos") or [{}])[0].get("url", "")

            return self._normalize(
                {
                    "source": self.source_name,
                    "property_id": prop_id,
                    "title": title,
                    "price": self._parse_price(str(price_raw)) if isinstance(price_raw, str) else int(price_raw or 0),
                    "price_text": price_text,
                    "area_sqft": float(area_raw or 0),
                    "bhk": int(bhk_raw or 0),
                    "city": city,
                    "locality": locality,
                    "url": url if url.startswith("http") else BASE_URL + url,
                    "image_url": image_url,
                    "furnishing": item.get("furnishing", ""),
                    "is_new_project": 1 if item.get("isNewProject") else 0,
                    "builder_name": item.get("developerName", ""),
                    "rera_id": item.get("reraRegId", ""),
                }
            )
        except Exception as e:
            logger.debug(f"[99acres] map error: {e}")
            return None

    def _parse_html_cards(self, soup: BeautifulSoup, city: str) -> list[dict]:
        results = []
        cards = soup.select(".tuple__mainContent, .srp_tuple, [data-propid]")
        for card in cards:
            try:
                prop_id = card.get("data-propid", "")
                title_el = card.select_one(".proj_name, .tuple__propTitle, h2")
                price_el = card.select_one(".rupees, .tuple__price, .price")
                loc_el = card.select_one(".localityName, .tuple__locationName, .location")
                area_el = card.select_one(".area, .tuple__area")
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

                if not prop_id and url:
                    m = re.search(r"/(\d+)", url)
                    prop_id = m.group(1) if m else url[-10:]

                results.append(
                    self._normalize(
                        {
                            "source": self.source_name,
                            "property_id": prop_id,
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
                logger.debug(f"[99acres] card parse error: {e}")
        return results
