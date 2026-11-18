# House Hunt India

Aggregates residential buy/rent listings for Indian cities from NoBroker, SquareYards, MagicBricks and CommonFloor into a local SQLite DB. It has a Flask web UI (filters, locality picker, map, analytics, EMI calculator) and an MCP server.

## Commands (Windows, run from project root)
- Web app: `run.bat` or `.venv\Scripts\python.exe app.py` → http://localhost:5000
- MCP server: `.venv\Scripts\python.exe mcp_server.py` (stdio; for Claude Desktop)
- One-off scrape: `.venv\Scripts\python.exe -m scheduler.update_scheduler Chennai`
- Tests: `.venv\Scripts\python.exe -m pytest -q`
- Lint/format: `.venv\Scripts\python.exe -m ruff check --fix .` and `... -m ruff format .` (config: `ruff.toml`, line length 120)

## Claude Code automation (`.claude/`)
- **PostToolUse hook** (`hooks/post_edit_cleanup.py`): after every Edit/Write to a `.py` file, it runs `ruff check --fix` and `ruff format` on that file. It reports issues ruff can't fix back as context.
  - **Files may be reformatted right after an edit, so re-read before editing the same region again.**
  - **Add an import only after the code that uses it.** The auto-fix deletes an import that is unused at that moment. Mid-sequence F821 "undefined name" reports are expected and clear once the import edit lands.
- **Stop hook** (`hooks/docs_check.py`): at the end of a turn with uncommitted code changes where README.md or CLAUDE.md wasn't touched, it asks once (per set of changes) to update the docs. If nothing documented changed, say so and stop.
- **Skill `commit-push`** (`skills/commit-push/SKILL.md`): used when the user asks to commit/push/"ship it". It runs ruff and pytest, checks for secrets and stale docs, commits to `main` and pushes to `heptile7/house-hunt`.

## Layout
- `app.py`: Flask JSON API plus `templates/index.html` and `static/app.js` (vanilla JS, Chart.js, Leaflet). `/api/fetch` runs `run_scrapers` in a background thread, and the UI polls `/api/fetch/status`. `/api/localities` feeds the locality picker.
- `config.py`:
  - `SOURCES` / `SOURCE_LABELS`: the active sources, in fetch order. The UI source list comes from here, via `window.APP_SOURCES`.
  - `DISABLED_SOURCES`: blocked sources that are no longer fetched.
  - Also `CITY_SLUGS`, `CITY_STATE` (for stamp duty) and `SCRAPER_CONFIG`.
- `database/db.py`: SQLite `house_hunting.db`.
  - The unique key is `(source, property_id, listing_type)`. Upsert never overwrites known values with blanks, zeros or NULL coordinates.
  - `query_properties(localities=[...])` matches each locality as a substring of locality, title or address.
  - Detail columns (`DETAIL_COLUMNS`, added by migration 3 in `init_db`): `updated_date`, `available_from`, `tenant_preference`, `pets_allowed`, `non_veg_allowed`, `deposit`, `maintenance`, `occupancy`, `description`. `posted_date` and `amenities` (a JSON list) are original columns.
  - `query_properties` filters on `pets_allowed`, `non_veg_allowed`, `posted_within_days` and `available_by`, and returns `amenities` decoded to a list.
  - A new listing field needs to be added in four places: `BaseScraper._normalize` defaults, `DETAIL_COLUMNS`, the upsert column list, and the ON CONFLICT clause.
- `scrapers/`:
  - All active scrapers use plain HTTP through `BaseScraper._get`.
  - `scrape(city, bhk, max_price, listing_type, localities)` must return dicts built with `_normalize()`.
  - Scrapers with `supports_localities = True` fetch per-locality pages (`max_pages_per_locality`). The others fetch city-wide.
  - `scrapers/details.py` holds the shared text parsing.
    - `parse_date_text` handles "Posted: Nov 06, '26", "4 days ago", "Jun'27", dd/mm/yyyy and ISO, all in IST.
    - `parse_availability` returns an ISO date, or "Immediately" / "Ready to move" / "Under construction".
    - `infer_restrictions` reads pets / non-veg from explicit description phrases only, with "no" patterns checked first.
    - Also `ms_to_date` and `yes_no`.
  - `_normalize()` runs `infer_restrictions` on the description only when the site gave no structured value.
- `scheduler/update_scheduler.py`: `get_scraper_classes()` plus `run_scrapers()`, the single scrape+save+log path used by both the web app and the MCP server.
- `utils/emi_calculator.py`: EMI, stamp duty by state, GST (only for under-construction homes: 1% under ₹45L, otherwise 5%).

## Sources (as of 2026-11)
| Source | How | Notes |
|---|---|---|
| NoBroker | Listing objects embedded in the page | Rent pages: Next.js `self.__next_f.push` payload. Sale pages: `nb.appState`. Both found by the `propertyCode` key. Locality pages: `flats-for-{rent\|sale}-in-{locality}_{city}`. Sale pages ignore `pageNo` (25 max). Occasionally serves a data-less page, so it is retried once. Images: `images.nobroker.in/images/{id}/{file}` (`originalImageUrl` is 403). Details are on the list page, so no per-listing requests are needed. `aea__` has PET / NON_VEG_ALLOWED / GATED_SECURITY / CURRENT_SITUATION as `{value, display_value}`. Other fields: `amenitiesMap` (codes mapped in `_AMENITY_LABELS`), `availableFrom` / `lastActivationDate` / `lastUpdateDate` (epoch ms), `leaseTypeNew`. `ownerDescription` may be percent-encoded twice. "For Lease" listings have rent 0 and a large deposit. |
| SquareYards | `data-*` attributes inside `article.listing-card` | Merge attributes from all card descendants. Commercial listings are skipped. Locality pages: `property-for-{sale\|rent}-in-{locality}-{city}`. Details: `.attribute-item` dt/dd rows (possession, parking, extra rooms); JSON-LD, matched by URL, for the description and `RentAction.startTime` (posted date, rent only). |
| MagicBricks | `div.mb-srp__card` HTML cards | Sale pages often show a "down for maintenance" page (raised as an error, logged as blocked). Details: `.mb-srp__card__photo__fig--post` ("Posted: …" or "Updated …"), `[data-summary]` status / tenant preference, `.mb-srp__card--desc--text`. |
| CommonFloor | JSON-LD `Product`+`Apartment/House/Residence` | City-wide only: locality URLs redirect to another city, which the scraper guards against. Placeholder image and `(0,0)` / India-centroid coordinates are dropped. Details: `div.snb-tile` cards, matched by listing id, give `.infodata` "Available From" / "Possession On", the `.infoline` amenities and the `.infoowner` "Posted : …". |
| 99acres, Housing | disabled | 403/406 on every request. The code is kept in `scrapers/` but they are not in `SOURCES`. |

## Conventions
- **Prices are stored as whole rupees.** For API, UI and MCP price inputs, `buy` values are in **lakhs** (×100000) and `rent` values are in **plain ₹** (×1). This includes the misleadingly named `max_price_lac` field. Use `_price_multiplier()` in `app.py` and `_price()` in `mcp_server.py`.
- `_normalize()` sets coordinates outside India's bounding box to `None`.
- **Never send `Accept-Encoding: br`.** `requests` can't decode Brotli without an extra package, and NoBroker then returns an undecodable body that parses as 0 listings. There is a test for this.
- `.env` (`SCRAPER_API_KEY`, optional) is loaded at the top of `app.py` and `mcp_server.py`, before other imports.
- `app.json.sort_keys = False`: response dict order matters (for example, price buckets are sorted numerically).
- **Tests:**
  - `tests/conftest.py` redirects `database.db.DB_PATH` to a temp file. Use the `tmp_db` / `client` fixtures and `make_prop()`.
  - Parser tests use trimmed real pages in `tests/fixtures/`. When a site changes its markup, save a fresh page and update the fixture and the parser together.

## Gotchas
- `_fetch_status` in `app.py` is in-process global state, and only one fetch runs at a time. The debug reloader is disabled (`use_reloader=False`) so the background thread isn't duplicated.
- A full Fetch Now takes about 30–60 s: 4 sources × up to 5 pages with a ~2.5 s polite delay.
- `scheduler.start_scheduler` / `update_city` (APScheduler periodic refresh) exist but are not wired into the app.
