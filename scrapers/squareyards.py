"""
SquareYards scraper — plain HTTP.

Each search-result card is an <article class="listing-card" propertyid="..."> whose
descendant element carries every field as data-* attributes (data-price in rupees,
data-unittype "2 BHK", data-area "1043 Sq.Ft.", data-sublocalityname, data-lat/long, ...).

URLs:  /sale/property-for-sale-in-{place}-{city}?page=N   (place omitted for city-wide)
       /rent/property-for-rent-in-{place}-{city}?page=N
"""

import html
import logging
import re

from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper
from scrapers.details import parse_availability, parse_date_text

logger = logging.getLogger(__name__)

BASE_URL = "https://www.squareyards.com"
# Rent/sale searches also return commercial stock; this app is for homes.
_COMMERCIAL = re.compile(r"office|warehouse|shop|showroom|commercial|industrial|godown|co-?working", re.I)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


class SquareYardsScraper(BaseScraper):
    source_name = "squareyards"
    supports_localities = True

    def scrape(
        self,
        city: str,
        bhk: list[int] = None,
        max_price: int = None,
        listing_type: str = "buy",
        localities: list[str] = None,
    ) -> list[dict]:
        places = [f"{slugify(loc)}-{slugify(city)}" for loc in localities] if localities else [slugify(city)]
        pages = self.locality_pages if localities else self.max_pages
        results, seen = [], set()
        for place in places:
            for page in range(1, pages + 1):
                try:
                    props = self._scrape_page(place, city, page, listing_type)
                except Exception as e:
                    logger.warning(f"[SquareYards] {place} page {page} error: {e}")
                    break
                new = [p for p in props if p["property_id"] not in seen]
                if not new:
                    break
                seen.update(p["property_id"] for p in new)
                results.extend(new)
                self._sleep()
        return self._filter(results, bhk, max_price)

    def _scrape_page(self, place: str, city: str, page: int, listing_type: str) -> list[dict]:
        kind = "rent/property-for-rent" if listing_type == "rent" else "sale/property-for-sale"
        url = f"{BASE_URL}/{kind}-in-{place}"
        if page > 1:
            url += f"?page={page}"
        resp = self._get(url, headers={"Referer": BASE_URL + "/"})
        return self.parse_page(resp.text, city, listing_type)

    def parse_page(self, html: str, city: str, listing_type: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        # JSON-LD carries the description (Apartment/House items) and, for rentals, the
        # posting time (RentAction.startTime). Index both by listing URL.
        ld_by_url: dict[str, dict] = {}
        for item in self._ld_items(soup):
            url = item.get("url")
            if url:
                ld_by_url.setdefault(url, {}).update(
                    {k: v for k, v in item.items() if k in ("description", "startTime") and v}
                )
        out = []
        for card in soup.select("article.listing-card[propertyid]"):
            try:
                p = self._parse_card(card, city, listing_type, ld_by_url)
                if p:
                    out.append(p)
            except Exception as e:
                logger.debug(f"[SquareYards] card parse error: {e}")
        return out

    def _parse_card(self, card, city: str, listing_type: str, ld_by_url: dict | None = None) -> dict | None:
        # Fields are spread over several descendants (price on one, lat/long on another):
        # merge every data-* attribute in the card, first occurrence wins.
        a: dict[str, str] = {}
        for el in card.find_all(True):
            for k, v in el.attrs.items():
                if k.startswith("data-") and isinstance(v, str) and v and k not in a:
                    a[k] = v
        if "data-price" not in a:
            return None
        ptype = a.get("data-propertytype", "")
        if _COMMERCIAL.search(ptype):
            return None
        bhk_m = re.search(r"(\d+)\s*BHK", a.get("data-unittype", "") + " " + a.get("data-desc", ""), re.I)
        lat, lng = a.get("data-lat"), a.get("data-long")
        status = a.get("data-propstatus", "")
        price = a.get("data-price", "")
        url = a.get("data-url") or a.get("data-propertylink", "")
        ld = (ld_by_url or {}).get(url, {})
        # Visible attribute rows: <div class="attribute-item"><dt>Parking</dt><dd>1 Covered</dd></div>
        attrs = {}
        for item in card.select(".attribute-item"):
            dt, dd = item.find("dt"), item.find("dd")
            if dt and dd:
                attrs[dt.get_text(" ", strip=True).lower()] = re.sub(r"\s+", " ", dd.get_text(" ", strip=True))
        amenities = []
        if attrs.get("parking"):
            amenities.append(f"Parking ({attrs['parking']})")
        if attrs.get("additional spaces"):
            amenities.append(attrs["additional spaces"])
        return self._normalize(
            {
                "source": self.source_name,
                "property_id": a.get("data-propertyid") or card.get("propertyid"),
                "listing_type": listing_type,
                "title": a.get("data-desc") or a.get("data-propname", ""),
                "price": int(float(price))
                if re.fullmatch(r"\d+(\.\d+)?", price)
                else self._parse_price(a.get("data-totalprice")),
                "price_text": a.get("data-totalprice", ""),
                "area_sqft": self._parse_area(re.sub(r"(?i)sq\.?\s*ft\.?", "", a.get("data-area", ""))),
                "bhk": int(bhk_m.group(1)) if bhk_m else 0,
                "property_type": "Plot" if ptype in ("Plot", "Land") else ptype or "Apartment",
                "city": city,
                "locality": a.get("data-sublocalityname", ""),
                "address": a.get("data-projectname", ""),
                "latitude": _float(lat),
                "longitude": _float(lng),
                "url": url,
                "image_url": a.get("data-image", ""),
                # For rent cards data-propstatus is the furnishing; for sale it's possession status.
                "furnishing": status if "furnish" in status.lower() else "Unknown",
                "floor": attrs.get("floor", ""),
                "facing": attrs.get("facing", "").replace(" Facing", ""),
                # Details
                "posted_date": parse_date_text(ld.get("startTime", "")),
                "available_from": parse_availability(attrs.get("possession status") or attrs.get("availability")),
                "amenities": amenities,
                "description": html.unescape(re.sub(r"<[^>]+>", " ", ld.get("description", ""))).strip(),
            }
        )


def _float(v):
    try:
        f = float(v)
        return f if f else None
    except (TypeError, ValueError):
        return None
