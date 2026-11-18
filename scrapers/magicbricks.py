import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import CITY_SLUGS
from scrapers.base_scraper import BaseScraper
from scrapers.details import parse_availability, parse_date_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.magicbricks.com"

PROP_TYPE_MAP = {
    "Apartment": "Multistorey-Apartment,Builder-Floor-Apartment,Studio-Apartment",
    "Villa": "Villa",
    "Plot": "Residential-Plot",
    "Penthouse": "Penthouse",
}


class MagicBricksScraper(BaseScraper):
    source_name = "magicbricks"

    def scrape(
        self,
        city: str,
        bhk: list[int] = None,
        max_price: int = None,
        listing_type: str = "buy",
        localities: list[str] = None,
    ) -> list[dict]:
        city_slug = CITY_SLUGS.get(city, {}).get("mb", city)
        results = []
        for page in range(1, self.max_pages + 1):
            try:
                props = self._scrape_page(city_slug, city, page, bhk, max_price, listing_type)
                if not props:
                    break
                results.extend(props)
                self._sleep()
            except Exception as e:
                logger.warning(f"[MagicBricks] page {page} error: {e}")
                break
        return results

    def _scrape_page(self, city_slug: str, city: str, page: int, bhk, max_price, listing_type: str) -> list[dict]:
        bedroom_param = ",".join(str(b) for b in bhk) if bhk else ""
        budget_param = f"&BudgetMax={max_price}" if max_price else ""
        bedroom_str = f"&bedroom={bedroom_param}" if bedroom_param else ""
        path = "property-for-sale" if listing_type == "buy" else "property-for-rent"

        url = (
            f"{BASE_URL}/{path}/residential-real-estate"
            f"?proptype=Multistorey-Apartment,Builder-Floor-Apartment,Penthouse,Studio-Apartment,Villa"
            f"&cityName={city_slug}{bedroom_str}{budget_param}&page={page}"
        )

        headers = {"Referer": BASE_URL + "/"}
        resp = self._get(url, headers=headers)
        soup = BeautifulSoup(resp.text, "lxml")

        if "down for maintenance" in resp.text[:10_000]:
            raise RuntimeError("MagicBricks returned its maintenance page")
        # Cards carry far more detail than JSON-LD; JSON-LD is only a fallback.
        props = self._parse_cards(soup, city) or self._parse_json_ld(soup, city)
        for p in props:
            p["listing_type"] = listing_type
        return props

    def _parse_json_ld(self, soup: BeautifulSoup, city: str) -> list[dict]:
        results = []
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict) and "@graph" in data:
                    items = data["@graph"]
                else:
                    continue
                for item in items:
                    if item.get("@type") in ("Product", "Offer", "RealEstateListing"):
                        p = self._map_json_ld(item, city)
                        if p:
                            results.append(p)
            except Exception:
                continue
        return results

    def _map_json_ld(self, item: dict, city: str) -> dict | None:
        url = item.get("url", "")
        prop_id = re.search(r"-(\d+)\.html", url)
        if not prop_id:
            return None
        price_raw = item.get("offers", {}).get("price", "0")
        return self._normalize(
            {
                "source": self.source_name,
                "property_id": prop_id.group(1),
                "title": item.get("name", ""),
                "price": self._parse_price(str(price_raw)),
                "price_text": str(price_raw),
                "city": city,
                "url": url,
                "image_url": (item.get("image") or [""])[0]
                if isinstance(item.get("image"), list)
                else item.get("image", ""),
            }
        )

    def _parse_cards(self, soup: BeautifulSoup, city: str) -> list[dict]:
        """Parse search-result cards (markup as of 2026-11: div.mb-srp__card with an
        h2.mb-srp__card--title and [data-summary] key/value items)."""
        results = []
        for card in soup.select("div.mb-srp__card"):
            try:
                p = self._parse_card(card, city)
                if p:
                    results.append(p)
            except Exception as e:
                logger.debug(f"[MagicBricks] card parse error: {e}")
        return results

    def _parse_card(self, card, city: str) -> dict | None:
        def text(sel: str) -> str:
            el = card.select_one(sel)
            return el.get_text(" ", strip=True) if el else ""

        summary = {}
        for item in card.select("[data-summary]"):
            val = item.select_one(".mb-srp__card__summary--value")
            if val and item["data-summary"] not in summary:
                summary[item["data-summary"]] = val.get_text(" ", strip=True)

        # The listing's own page is /propertyDetails/...&id=<hex>; other links point at the
        # project/society page, which many listings share, so they're useless as an ID.
        hrefs = [a["href"] for a in card.select("a[href]")]
        detail = next((h for h in hrefs if "propertyDetails" in h), "")
        m = re.search(r"[?&]id=([0-9a-fA-F]+)", detail)
        if not m:
            return None
        prop_id = m.group(1)
        url = urljoin(BASE_URL + "/", detail)

        title = re.sub(r"\s+", " ", text(".mb-srp__card--title"))
        bhk_m = re.search(r"(\d+)\s*BHK", title, re.I)
        # "2 BHK Flat for Rent in Karapakkam, Chennai" / "...in Neelankarai Chennai" → locality
        loc_m = re.search(r"\bin\s+(.+)$", title)
        locality = loc_m.group(1).strip() if loc_m else ""
        locality = re.sub(rf"[,\s]*\b{re.escape(city)}$", "", locality, flags=re.I).strip(" ,")

        area_text = next((summary[k] for k in ("carpet-area", "super-area", "plot-area") if k in summary), "")
        floor = summary.get("floor", "")
        total_floors_m = re.search(r"out of\s+(\d+)", floor)
        price_text = text(".mb-srp__card__price--amount")
        posted = text(".mb-srp__card__photo__fig--post")
        img = card.select_one("img.mb-srp__card__photo__fig--graphic, img")
        image_url = (img.get("data-src") or img.get("src") or "") if img else ""

        return self._normalize(
            {
                "source": self.source_name,
                "property_id": prop_id,
                "title": title,
                "price": self._parse_price(price_text),
                "price_text": price_text,
                "area_sqft": self._parse_area(area_text),
                "bhk": int(bhk_m.group(1)) if bhk_m else 0,
                "city": city,
                "locality": locality,
                "address": text(".mb-srp__card__society--name"),
                "url": url,
                "image_url": image_url if image_url.startswith("http") else "",
                "furnishing": summary.get("furnishing") or "Unknown",
                "floor": floor,
                "total_floors": int(total_floors_m.group(1)) if total_floors_m else 0,
                "facing": summary.get("facing", ""),
                # Details: "Posted: Nov 06, '26" / "Posted: Yesterday" / "Updated today"
                "posted_date": parse_date_text(posted) if posted.lower().startswith("posted") else "",
                "updated_date": parse_date_text(posted) if posted.lower().startswith("updated") else "",
                # "Immediately" / "From Dec '26" / "Ready to Move" / "Poss. by Jun '27"
                "available_from": parse_availability(summary.get("status", "")),
                "tenant_preference": summary.get("tenent-preffered", ""),
                "amenities": [f"Overlooking {summary['overlooking']}"] if summary.get("overlooking") else [],
                "description": text(".mb-srp__card--desc--text"),
            }
        )
