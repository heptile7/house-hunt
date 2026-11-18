import logging
import re
import json
from bs4 import BeautifulSoup
from scrapers.playwright_base import PlaywrightScraper
from config import CITY_SLUGS

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nobroker.in"
API_URL  = "https://www.nobroker.in/api/v1/search/property/list"


class NoBrokerScraper(PlaywrightScraper):
    source_name = "nobroker"

    def scrape(self, city: str, bhk: list[int] = None, max_price: int = None, listing_type: str = "buy") -> list[dict]:
        # NoBroker is a full React SPA. Their JSON API requires auth cookies only set by
        # a real browser session. ScraperAPI rendering gets only a 11KB shell.
        # Try the JSON API (fast, no browser) — if it returns 0, fail immediately.
        city_slug = CITY_SLUGS.get(city, {}).get("nb", city.lower())
        results = []
        for page in range(1, self.max_pages + 1):
            try:
                props = self._scrape_api(city_slug, city, page, bhk, max_price, listing_type)
                if not props:
                    break
                results.extend(props)
                self._sleep()
            except Exception as e:
                logger.warning(f"[NoBroker] API page {page} error: {e}")
                break
        return results

    def _scrape_api(self, city_slug: str, city: str, page: int, bhk, max_price, listing_type: str) -> list[dict]:
        """Attempt NoBroker's internal search API."""
        bedroom_filter = [str(b) for b in bhk] if bhk else []
        payload = {
            "city": city_slug,
            "listingType": listing_type,
            "filter": {
                "bedrooms": bedroom_filter,
                "propertyType": ["flat", "independent_house", "villa"],
                **({"maxPrice": max_price} if max_price else {}),
            },
            "page": page,
            "size": 30,
        }
        headers = {
            "Content-Type": "application/json",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/property/residential/{city_slug}/buy",
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = self._post(API_URL, json=payload, headers=headers)
            data = resp.json()
            listings = (
                data.get("data", {}).get("searchResult", []) or
                data.get("result", []) or
                data.get("properties", [])
            )
            props = [p for item in listings if (p := self._map_api(item, city))]
            for p in props:
                p["listing_type"] = listing_type
            return props
        except Exception as e:
            logger.debug(f"[NoBroker] API failed: {e}")
            return []

    def _map_api(self, item: dict, city: str) -> dict | None:
        try:
            prop_id = str(item.get("id") or item.get("propertyId", ""))
            if not prop_id:
                return None
            price = item.get("price") or item.get("expectedPrice") or 0
            area  = item.get("builtArea") or item.get("carpetArea") or item.get("area") or 0
            bhk   = item.get("bhk") or item.get("bedroom") or 0
            loc   = item.get("locality") or item.get("location", "")
            title = f"{bhk} BHK {item.get('propertyType', 'Apartment')} in {loc}"
            url   = item.get("url") or f"{BASE_URL}/property/residential/{city.lower()}/buy/{prop_id}"
            images = item.get("images") or []
            image_url = images[0].get("url", "") if images else ""

            return self._normalize({
                "source": self.source_name,
                "property_id": prop_id,
                "title": title,
                "price": int(price),
                "price_text": self._format_price(int(price)),
                "area_sqft": float(area),
                "bhk": int(bhk),
                "city": city,
                "locality": loc,
                "url": url if url.startswith("http") else BASE_URL + url,
                "image_url": image_url,
                "furnishing": item.get("furnishing", ""),
                "floor": str(item.get("floorNumber", "")),
                "total_floors": int(item.get("totalFloors") or 0),
                "facing": item.get("facingDirection", ""),
                "parking": int(item.get("parking") or 0),
            })
        except Exception as e:
            logger.debug(f"[NoBroker] map error: {e}")
            return None

    def _scrape_html(self, city_slug: str, city: str, page: int, bhk, max_price, listing_type: str) -> list[dict]:
        """Playwright-rendered NoBroker listing page, with homepage warm-up cookies."""
        bedroom_str = "-".join(str(b) for b in bhk) + "bhk-" if bhk else ""
        mode = listing_type
        url = f"{BASE_URL}/property/residential/{city_slug}/{mode}/{bedroom_str}?page={page}"
        pw_page = self._context.new_page()
        try:
            pw_page.goto(url, wait_until="networkidle", timeout=45_000)
            # Wait for listing cards or data attributes to appear
            try:
                pw_page.wait_for_selector(
                    ".search-result-card, [data-id], .nb-card, .listingCard",
                    timeout=10_000,
                )
            except Exception:
                pass
            pw_page.wait_for_timeout(2_000)
            html = pw_page.content()
            soup = BeautifulSoup(html, "lxml")
            props = self._parse_cards(soup, city)
            for p in props:
                p["listing_type"] = listing_type
            return props
        except Exception as e:
            logger.debug(f"[NoBroker] HTML scrape failed: {e}")
            return []
        finally:
            pw_page.close()

    def _parse_cards(self, soup: BeautifulSoup, city: str) -> list[dict]:
        results = []
        cards = soup.select(".search-result-card, .property-card, [data-id]")
        for card in cards:
            try:
                prop_id = card.get("data-id", "")
                title_el = card.select_one("h3, .title, .property-title")
                price_el = card.select_one(".price, .property-price")
                loc_el   = card.select_one(".locality, .property-locality, .location")
                area_el  = card.select_one(".area, .property-area")
                link_el  = card.select_one("a[href]")
                img_el   = card.select_one("img")

                title     = title_el.get_text(strip=True) if title_el else ""
                price_text = price_el.get_text(strip=True) if price_el else ""
                locality  = loc_el.get_text(strip=True) if loc_el else ""
                area_text = area_el.get_text(strip=True) if area_el else ""
                url       = link_el["href"] if link_el else ""
                if url and not url.startswith("http"):
                    url = BASE_URL + url
                image_url = img_el.get("data-src") or img_el.get("src", "") if img_el else ""

                bhk_match = re.search(r"(\d)\s*BHK", title, re.I)
                bhk = int(bhk_match.group(1)) if bhk_match else 0

                results.append(self._normalize({
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
                }))
            except Exception as e:
                logger.debug(f"[NoBroker] card parse error: {e}")
        return results

    @staticmethod
    def _format_price(price: int) -> str:
        if price >= 1_00_00_000:
            return f"₹{price / 1_00_00_000:.2f} Cr"
        elif price >= 1_00_000:
            return f"₹{price / 1_00_000:.1f} Lac"
        return f"₹{price:,}"
