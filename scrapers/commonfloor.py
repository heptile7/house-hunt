"""
CommonFloor scraper — plain HTTP, parses the JSON-LD ['Product', 'Apartment'|'House'|'Residence']
items on the city search page.

URL: /{city}-property/for-{sale|rent}?page=N
CommonFloor has no per-locality search pages (they redirect to another city), so this
scraper is city-wide only; the DB locality filter narrows results afterwards.
"""

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.details import parse_availability, parse_date_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.commonfloor.com"
_PLACEHOLDER_IMG = "no-image"
# CommonFloor uses the centre of India as a "no location" placeholder.
_PLACEHOLDER_GEO = (20.5937, 78.9629)
_LISTING_TYPES = {"Apartment", "House", "Residence", "SingleFamilyResidence"}


class CommonFloorScraper(BaseScraper):
    source_name = "commonfloor"

    def scrape(
        self,
        city: str,
        bhk: list[int] = None,
        max_price: int = None,
        listing_type: str = "buy",
        localities: list[str] = None,
    ) -> list[dict]:
        city_slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
        results, seen = [], set()
        for page in range(1, self.max_pages + 1):
            try:
                props = self._scrape_page(city_slug, city, page, listing_type)
            except Exception as e:
                logger.warning(f"[CommonFloor] page {page} error: {e}")
                break
            new = [p for p in props if p["property_id"] not in seen]
            if not new:
                break
            seen.update(p["property_id"] for p in new)
            results.extend(new)
            self._sleep()
        return self._filter(results, bhk, max_price)

    def _scrape_page(self, city_slug: str, city: str, page: int, listing_type: str) -> list[dict]:
        mode = "rent" if listing_type == "rent" else "sale"
        url = f"{BASE_URL}/{city_slug}-property/for-{mode}"
        if page > 1:
            url += f"?page={page}"
        resp = self._get(url, headers={"Referer": BASE_URL + "/"})
        # Unknown city/locality URLs redirect to some other city's page — don't save those.
        if city_slug not in urlparse(resp.url).path:
            logger.warning(f"[CommonFloor] {url} redirected to {resp.url}; skipping")
            return []
        return self.parse_page(resp.text, city, listing_type)

    def parse_page(self, html: str, city: str, listing_type: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        cards = self._card_details(soup)
        out = []
        for item in self._ld_items(soup):
            if not (self._ld_types(item) & _LISTING_TYPES) or "URL" not in item and "url" not in item:
                continue
            try:
                p = self._map_item(item, city, listing_type, cards)
                if p:
                    out.append(p)
            except Exception as e:
                logger.debug(f"[CommonFloor] item parse error: {e}")
        return out

    @staticmethod
    def _card_details(soup) -> dict[str, dict]:
        """Visible result cards (div.snb-tile) → {listing id: details}. Cards hold what the
        JSON-LD lacks: 'Available From' / 'Possession On', 'Posted : 4 days ago', amenities."""
        out = {}
        for card in soup.select("div.snb-tile"):
            link = card.find("a", href=re.compile(r"/listing/"))
            if not link:
                continue
            prop_id = link["href"].split("?")[0].rstrip("/").rsplit("/", 1)[-1]
            info = {}
            for row in card.select(".infodata"):
                parts = [s for s in row.stripped_strings]
                if len(parts) >= 2:
                    info[parts[0].lower()] = " ".join(parts[1:])
            amen_row = card.select_one(".infoline")
            amenities = (
                [s for s in amen_row.stripped_strings if s.lower() != "amenities" and "more" not in s.lower()]
                if amen_row
                else []
            )
            owner = card.select_one(".infoowner")
            posted = re.search(r"Posted\s*:?\s*(.+)$", owner.get_text(" ", strip=True)) if owner else None
            out[prop_id] = {
                "available": info.get("available from") or info.get("possession on") or "",
                "amenities": amenities,
                "posted": posted.group(1) if posted else "",
            }
        return out

    def _map_item(self, it: dict, city: str, listing_type: str, cards: dict | None = None) -> dict | None:
        url = urljoin(BASE_URL, it.get("URL") or it.get("url") or "")
        prop_id = url.rstrip("/").rsplit("/", 1)[-1]
        if not prop_id or "/listing/" not in url:
            return None
        card = (cards or {}).get(prop_id, {})
        name = it.get("name") or ""
        size = it.get("floorSize") or {}
        area = size.get("value") if isinstance(size, dict) else size
        geo = it.get("geo") or {}
        lat, lng = _float(geo.get("latitude")), _float(geo.get("longitude"))
        if lat is not None and (round(lat, 4), round(lng or 0, 4)) == _PLACEHOLDER_GEO:
            lat = lng = None
        image = it.get("image") or ""
        rooms = it.get("numberOfRooms")
        bhk_m = re.search(r"(\d+)\s*BHK", name, re.I)
        furn_m = re.match(r"(Semi Furnished|Fully Furnished|Furnished|Unfurnished)", name, re.I)
        types = self._ld_types(it)
        return self._normalize(
            {
                "source": self.source_name,
                "property_id": prop_id,
                "listing_type": listing_type,
                # "... in Padur, Chennai at Individual House" → drop the trailing project bit
                "title": re.sub(r"\s+at\s+(Not part of a project|Individual House)$", "", name).strip(),
                "price": int((it.get("offers") or {}).get("price") or 0),
                "area_sqft": float(area or 0),
                "bhk": int(rooms) if str(rooms or "").isdigit() else (int(bhk_m.group(1)) if bhk_m else 0),
                "property_type": (
                    "Plot"
                    if name.lower().startswith("plot")
                    else "Independent House"
                    if "House" in types
                    else "Apartment"
                ),
                "city": city,
                "locality": ((it.get("address") or {}).get("addressLocality") or "").strip(),
                "latitude": lat,
                "longitude": lng,
                "url": url,
                "image_url": "" if _PLACEHOLDER_IMG in image else image,
                "furnishing": _furnishing(furn_m.group(1)) if furn_m else "Unknown",
                # Details
                "posted_date": parse_date_text(card.get("posted")),
                "available_from": parse_availability(card.get("available")),
                "amenities": card.get("amenities", []),
                "description": (it.get("description") or "").strip(),
            }
        )


def _furnishing(text: str) -> str:
    t = text.lower()
    return "Semi-Furnished" if "semi" in t else "Unfurnished" if "unfurnished" in t else "Furnished"


def _float(v):
    try:
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None
