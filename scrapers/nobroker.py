"""
NoBroker scraper — plain HTTP, no browser or proxy needed.

NoBroker's list pages are server-rendered and embed the full listing objects:
  * rent pages (Next.js):  inside the `self.__next_f.push([1, "..."])` flight payload
  * sale pages (legacy):   inside `nb.appState = {...}` → listPage.listPageProperties
Every listing object has a `propertyCode` key, which is how we find them.

URL pattern: /flats-for-{rent|sale}-in-{place}_{city}?pageNo=N where {place} is the
city slug for a city-wide search or a locality slug (e.g. "velachery", "anna_nagar").
"""

import html
import json
import logging
import re
from urllib.parse import unquote, urljoin

from config import CITY_SLUGS
from scrapers.base_scraper import BaseScraper
from scrapers.details import ms_to_date, yes_no

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nobroker.in"
_KEY = '"propertyCode"'
_BS = "\\"
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"' + _BS * 2 + r"]|" + _BS * 2 + r'.)*")\]\)')


def _text(value) -> str:
    """Owner-typed text: decode HTML entities (&#40; → '(') and collapse whitespace."""
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _image_url(o: dict) -> str:
    """First photo, medium size. `originalImageUrl` (assets.nobroker.in/<file>) returns 403
    to everyone; the public path is images.nobroker.in/images/<listing id>/<file>."""
    for photo in o.get("photos") or []:
        sizes = (photo or {}).get("imagesMap") or {}
        name = sizes.get("medium") or sizes.get("large") or sizes.get("original")
        if name:
            return f"https://images.nobroker.in/images/{o.get('id')}/{name}"
    return ""


def _furnishing(value) -> str:
    v = str(value or "").upper()
    if "SEMI" in v:
        return "Semi-Furnished"
    if "FULL" in v:
        return "Furnished"
    if "NOT" in v or "UN" in v or "NONE" in v:
        return "Unfurnished"
    return "Unknown"


# amenitiesMap codes → labels
_AMENITY_LABELS = {
    "LIFT": "Lift",
    "GYM": "Gym",
    "POOL": "Swimming Pool",
    "CLUB": "Club House",
    "PARK": "Park",
    "CPA": "Children's Play Area",
    "SECURITY": "Security",
    "INTERCOM": "Intercom",
    "PB": "Power Backup",
    "GP": "Gas Pipeline",
    "FS": "Fire Safety",
    "RWH": "Rain Water Harvesting",
    "STP": "Sewage Treatment Plant",
    "VP": "Visitor Parking",
    "HK": "Housekeeping",
    "AC": "Air Conditioner",
    "INTERNET": "Internet",
    "SERVANT": "Servant Room",
    "SC": "Shopping Centre",
}
_TENANTS = {
    "FAMILY": "Family",
    "BACHELOR": "Bachelors",
    "BACHELOR_MALE": "Bachelor (male)",
    "BACHELOR_FEMALE": "Bachelor (female)",
    "COMPANY": "Company",
    "ANYONE": "Anyone",
}


_FACING = {
    "N": "North", "S": "South", "E": "East", "W": "West",
    "NE": "North-East", "NW": "North-West", "SE": "South-East", "SW": "South-West",
}  # fmt: skip


def _unquote(value) -> str:
    """Some owner descriptions arrive percent-encoded, sometimes twice (%25E2%2580%2599 → ’)."""
    s = str(value or "")
    for _ in range(2):
        if not re.search(r"%[0-9A-Fa-f]{2}", s):
            break
        s = unquote(s)
    return s


def _attr(o: dict, key: str, display: bool = False) -> str:
    """Owner-entered attributes in `aea__`, e.g. PET, NON_VEG_ALLOWED, CURRENT_SITUATION."""
    a = (o.get("aea__") or {}).get(key) or {}
    return (a.get("display_value") if display else a.get("value")) or ""


def _amenities(o: dict) -> list[str]:
    amap = o.get("amenitiesMap")
    if not isinstance(amap, dict):
        try:
            amap = json.loads(o.get("amenities") or "{}")
        except (TypeError, ValueError):
            amap = {}
    out = [_AMENITY_LABELS.get(k, k.title()) for k, v in amap.items() if v is True]
    if _attr(o, "GATED_SECURITY") == "YES" and "Gated Security" not in out:
        out.append("Gated Security")
    if o.get("parkingDesc") and o.get("parking") not in (None, "", "NONE"):
        out.append(f"Parking ({o['parkingDesc']})")
    if str(o.get("powerBackup") or "").upper() in ("FULL", "PARTIAL") and "Power Backup" not in out:
        out.append(f"Power Backup ({str(o['powerBackup']).title()})")
    return sorted(set(out))


def _tenants(o: dict) -> str:
    codes = o.get("leaseTypeNew") or ([o["leaseType"]] if o.get("leaseType") else [])
    return ", ".join(_TENANTS.get(str(c).upper(), str(c).replace("_", " ").title()) for c in codes)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def listing_objects(html: str) -> list[dict]:
    """Extract raw NoBroker listing dicts from a list page (either embedding format)."""
    objs = _from_app_state(html)
    if objs:
        return objs
    flight = "".join(json.loads(m.group(1)) for m in _PUSH_RE.finditer(html))
    return _objects_with_key(flight) if flight else []


def _from_app_state(html: str) -> list[dict]:
    i = html.find("nb.appState = ")
    if i < 0:
        return []
    try:
        state, _ = json.JSONDecoder().raw_decode(html, i + len("nb.appState = "))
    except ValueError:
        return []

    def walk(o):
        if isinstance(o, list) and o and isinstance(o[0], dict) and "propertyCode" in o[0]:
            return o
        children = o.values() if isinstance(o, dict) else o if isinstance(o, list) else []
        for c in children:
            found = walk(c)
            if found:
                return found
        return None

    return walk(state) or []


def _objects_with_key(text: str) -> list[dict]:
    """Find every JSON object in `text` that directly contains the propertyCode key."""
    dec = json.JSONDecoder()
    out, seen = [], set()
    for m in re.finditer(re.escape(_KEY), text):
        depth, i = 0, m.start()
        while i > 0:
            i -= 1
            ch = text[i]
            if ch == "}":
                depth += 1
            elif ch == "{":
                if depth == 0:
                    try:
                        obj, _ = dec.raw_decode(text, i)
                    except ValueError:
                        break
                    if "propertyCode" in obj and obj.get("id") not in seen:
                        seen.add(obj.get("id"))
                        out.append(obj)
                    break
                depth -= 1
    return out


class NoBrokerScraper(BaseScraper):
    source_name = "nobroker"
    supports_localities = True

    def scrape(
        self,
        city: str,
        bhk: list[int] = None,
        max_price: int = None,
        listing_type: str = "buy",
        localities: list[str] = None,
    ) -> list[dict]:
        city_slug = CITY_SLUGS.get(city, {}).get("nb") or slugify(city)
        places = [slugify(loc) for loc in localities] if localities else [city_slug]
        pages = self.locality_pages if localities else self.max_pages
        results, seen = [], set()
        for place in places:
            for page in range(1, pages + 1):
                try:
                    props = self._scrape_page(place, city_slug, city, page, listing_type)
                except Exception as e:
                    logger.warning(f"[NoBroker] {place} page {page} error: {e}")
                    break
                new = [p for p in props if p["property_id"] not in seen]
                if not new:
                    break
                seen.update(p["property_id"] for p in new)
                results.extend(new)
                self._sleep()
        return self._filter(results, bhk, max_price)

    def _scrape_page(self, place: str, city_slug: str, city: str, page: int, listing_type: str) -> list[dict]:
        mode = "rent" if listing_type == "rent" else "sale"
        url = f"{BASE_URL}/flats-for-{mode}-in-{place}_{city_slug}"
        if page > 1:
            url += f"?pageNo={page}"
        objs = []
        for attempt in range(2):
            resp = self._get(url, headers={"Referer": BASE_URL + "/"})
            objs = listing_objects(resp.text)
            if objs:
                break
            # NoBroker intermittently serves a page without listing data after a burst of
            # requests; one slower retry usually gets the real page.
            logger.warning(
                f"[NoBroker] no listing data in {url} ({len(resp.text)} bytes)" + ("; retrying" if attempt == 0 else "")
            )
            if attempt == 0:
                self._sleep(extra=self.delay * 2)
        return [p for o in objs if (p := self.map_listing(o, city, listing_type))]

    def map_listing(self, o: dict, city: str, listing_type: str) -> dict | None:
        prop_id = o.get("id")
        if not prop_id:
            return None
        bhk_m = re.search(r"(\d+)", str(o.get("type") or ""))
        price = o.get("rent") if listing_type == "rent" else o.get("price")
        price = int(price or o.get("price") or o.get("rent") or 0)
        image = _image_url(o)
        floor, total = o.get("floor"), o.get("totalFloor")
        lat, lng = o.get("latitude"), o.get("longitude")
        return self._normalize(
            {
                "source": self.source_name,
                "property_id": str(prop_id),
                "listing_type": listing_type,
                "title": _text(o.get("propertyTitle")),
                "price": price,
                "price_text": "",
                "area_sqft": float(o.get("propertySize") or o.get("carpetArea") or 0),
                "bhk": int(bhk_m.group(1)) if bhk_m else 0,
                "city": city,
                "locality": _text(o.get("locality")).rstrip(","),
                "address": _text(o.get("society") or o.get("secondaryTitle")),
                "latitude": float(lat) if lat else None,
                "longitude": float(lng) if lng else None,
                "url": urljoin(BASE_URL, o.get("detailUrl") or ""),
                "image_url": image,
                "furnishing": _furnishing(o.get("furnishing") or o.get("furnishingDesc")),
                "floor": f"{floor} out of {total}" if floor is not None and total else str(floor or ""),
                "total_floors": int(total or 0),
                "facing": o.get("facingDesc") or _FACING.get(str(o.get("facing") or "").upper(), o.get("facing") or ""),
                # Details
                "posted_date": ms_to_date(
                    o.get("lastActivationDate") or o.get("activationDate") or o.get("creationDate")
                ),
                "updated_date": ms_to_date(o.get("lastUpdateDate")),
                "available_from": ms_to_date(o.get("availableFrom")),
                "tenant_preference": _tenants(o),
                "pets_allowed": yes_no(_attr(o, "PET")),
                "non_veg_allowed": yes_no(_attr(o, "NON_VEG_ALLOWED")),
                "amenities": _amenities(o),
                "deposit": int(o.get("deposit") or 0),
                "maintenance": int(o.get("maintenanceAmount") or o.get("maintenanceCost") or 0),
                "occupancy": _attr(o, "CURRENT_SITUATION", display=True),
                "description": _text(_unquote(o.get("ownerDescription"))),
            }
        )
