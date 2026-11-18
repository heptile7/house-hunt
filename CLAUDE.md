# House Hunt India

Aggregates residential buy/rent listings for Indian cities from MagicBricks, 99acres, NoBroker and Housing.com into a local SQLite DB, with a Flask web UI (filters, map, analytics, EMI calculator) and an MCP server.

## Commands (Windows, run from project root)
- Web app: `run.bat` or `.venv\Scripts\python.exe app.py` → http://localhost:5000
- MCP server: `.venv\Scripts\python.exe mcp_server.py` (stdio; for Claude Desktop)
- One-off scrape: `.venv\Scripts\python.exe -m scheduler.update_scheduler Chennai`
- Tests: `.venv\Scripts\python.exe -m pytest -q`
- First-time Playwright setup: `.venv\Scripts\python.exe -m playwright install chromium`

## Layout
- `app.py`: Flask JSON API plus `templates/index.html` and `static/app.js` (vanilla JS, Chart.js, Leaflet). `/api/fetch` runs scrapers in a background thread, and the UI polls `/api/fetch/status`.
- `config.py`: cities, `CITY_SLUGS` (per-site URL slugs: `mb`/`99a`/`nb`/`hc`), `CITY_STATE` (used for stamp duty), and scraper settings.
- `database/db.py`: SQLite `house_hunting.db`. The unique key is `(source, property_id, listing_type)`. Schema migrations live in `init_db()`. Upsert never overwrites known values with blanks or zeros.
- `scrapers/`:
  - `BaseScraper` (requests + tenacity retry, `_normalize`, `_parse_price`, `_parse_area`) → `MagicBricksScraper` (plain HTTP).
  - `PlaywrightScraper` → `Acres99Scraper`, `HousingScraper`, `NoBrokerScraper`.
- `scheduler/update_scheduler.py`: `run_scrapers()` is the single scrape+save+log path used by the web app.
- `mcp_server.py`: MCP tools. It has its own Playwright network-interception path for Housing and NoBroker (`_intercept_and_parse`).
- `utils/emi_calculator.py`: EMI, stamp duty by state, GST (only for under-construction homes: 1% under ₹45L, otherwise 5%).

## Conventions
- **Prices are stored as whole rupees.** For API and UI price inputs, `buy` values are in **lakhs** (×100000) and `rent` values are in **plain ₹** (×1). This includes the misleadingly named `max_price_lac` field. Use `_price_multiplier()` in `app.py` and `_max_price()` in `mcp_server.py`.
- Every scraper returns dicts built through `BaseScraper._normalize()` and sets `listing_type`.
- `.env` (`SCRAPER_API_KEY`) is loaded at the top of `app.py` and `mcp_server.py`, before other imports, because `base_scraper` reads it at import time.
- `app.json.sort_keys = False`: response dict order matters (for example, price buckets are sorted numerically).
- Tests redirect `database.db.DB_PATH` to a temp file in `tests/conftest.py`, so they never touch the real DB. Use the `tmp_db` / `client` fixtures and the `make_prop()` helper.

## Source reality
Only **MagicBricks** works reliably. 99acres (Akamai), Housing.com (WAF + SPA) and NoBroker (SPA + auth) are usually blocked even with ScraperAPI, and the scrapers return `[]` quickly when no key is set (see `/api/proxy-status`). A scrape that returns 0 is logged as `blocked`, not `error`.

## Gotchas
- `_fetch_status` in `app.py` is in-process global state, and only one fetch runs at a time. The debug reloader is disabled (`use_reloader=False`) so the background thread isn't duplicated.
- `scheduler.start_scheduler` / `update_city` (APScheduler periodic refresh) exist but are not wired into the app.
