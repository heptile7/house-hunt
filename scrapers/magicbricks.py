import logging
import re
import json
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from config import CITY_SLUGS

logger = logging.getLogger(__name__)

BASE_URL = "https://www.magicbricks.com"

PROP_TYPE_MAP = {
    "Apartment": "Multistorey-Apartment,Builder-Floor-Apartment,Studio-Apartment",
    "Villa":     "Villa",
    "Plot":      "Residential-Plot",
    "Penthouse": "Penthouse",
}


class MagicBricksScraper(BaseScraper):
    source_name = "magicbricks"

    def scrape(self, city: str, bhk: list[int] = None, max_price: int = None, listing_type: str = "buy") -> list[dict]:
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

        props = self._parse_json_ld(soup, city) or self._parse_cards(soup, city)
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
        return self._normalize({
            "source": self.source_name,
            "property_id": prop_id.group(1),
            "title": item.get("name", ""),
            "price": self._parse_price(str(price_raw)),
            "price_text": str(price_raw),
            "city": city,
            "url": url,
            "image_url": (item.get("image") or [""])[0] if isinstance(item.get("image"), list) else item.get("image", ""),
        })

    def _parse_cards(self, soup: BeautifulSoup, city: str) -> list[dict]:
        results = []
        cards = soup.select("div.mb-srp__card")
        if not cards:
            cards = soup.select("[data-id]")

        for card in cards:
            try:
                prop_id = card.get("data-id", "") or card.get("id", "")
                title_el = card.select_one(".mb-srp__card__title, h2.title, .listing-title")
                price_el = card.select_one(".mb-srp__card__price--amount, .price, .rupees")
                loc_el   = card.select_one(".mb-srp__card__addr, .locality, .address")
                area_el  = card.select_one(".mb-srp__card__summary--area, .area")
                link_el  = card.select_one("a[href]")
                img_el   = card.select_one("img")

                title = title_el.get_text(strip=True) if title_el else ""
                price_text = price_el.get_text(strip=True) if price_el else ""
                locality = loc_el.get_text(strip=True) if loc_el else ""
                area_text = area_el.get_text(strip=True) if area_el else ""
                url = (BASE_URL + link_el["href"]) if link_el else ""
                image_url = img_el.get("data-src") or img_el.get("src", "") if img_el else ""

                bhk_match = re.search(r"(\d)\s*BHK", title, re.I)
                bhk = int(bhk_match.group(1)) if bhk_match else 0

                if not prop_id and url:
                    m = re.search(r"-(\d+)\.html", url)
                    prop_id = m.group(1) if m else url[-12:]

                results.append(self._normalize({
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
                }))
            except Exception as e:
                logger.debug(f"[MagicBricks] card parse error: {e}")
        return results
