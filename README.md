# House Hunt India

Search flats and houses to **buy or rent** across Indian cities from one place. House Hunt India pulls listings from NoBroker, SquareYards, MagicBricks and CommonFloor into a local database and lets you filter them by locality, BHK, price, area and source. You can also see them on a map, look at price analytics, and work out the EMI and move-in cost of a purchase.

## Features
- **Four sources in one search:** NoBroker, SquareYards, MagicBricks and CommonFloor, fetched over plain HTTP. No browser automation or paid proxy is needed.
- **Locality search:** add one or more localities (e.g. *Velachery*, *Adyar*). Suggestions come from the listings already fetched. The localities filter what you see, and **Fetch Now** also searches those localities directly on the sources that support it (NoBroker and SquareYards).
- **Listing details:** each card shows when the listing was **posted** (or last updated) and when you can **move in** (a date, "Immediately" or "Ready to move"). Badges show whether **pets** and **non-veg** food are allowed and the **tenant preference** (family / bachelors / anyone). Open **Details** for deposit, maintenance, vacancy status, floor, facing, **amenities** and the owner's description.
- **Filters:** buy/rent, city, BHK, property type, price range (lakhs for buy, ₹/month for rent), area, source, **pets allowed**, **non-veg allowed**, **posted within** (3 days to 1 month) and **move in by** (date). Sort by price, area, BHK, **newest posted** or **earliest move-in**.
- **Map:** listings with coordinates are shown as pins, and the map zooms to the area you've filtered to.
- **Analytics:** BHK mix, price distribution, average price by locality, and listings per source.
- **EMI calculator:** monthly EMI, total interest, stamp duty and registration for the city's state, GST (under-construction homes only), and total move-in cost.
- **MCP server:** the same search is available as tools for Claude Desktop or any MCP client.

## Setup (Windows)
```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Optional: copy `.env.example` to `.env` and set `SCRAPER_API_KEY`. None of the active sources need it.

## Run
```bat
run.bat
```
Then open http://localhost:5000:
1. Choose **Buy** or **Rent** and a city, and optionally add localities.
2. Click **↓ Fetch Now**. This takes about 30–60 seconds; progress shows per source.
3. Filter, sort, open the **Map** or **Analytics** tabs, and click **View →** to open a listing on its site.

Listings are saved in `house_hunting.db`, so they're still there next time without fetching again.

### Command line / MCP
- Refresh one city without the UI: `.venv\Scripts\python.exe -m scheduler.update_scheduler Chennai`
- MCP server for Claude Desktop: add it to `claude_desktop_config.json`.
  ```json
  { "mcpServers": { "house-hunt": {
      "command": "D:/GPT/house_hunting/.venv/Scripts/python.exe",
      "args": ["D:/GPT/house_hunting/mcp_server.py"] } } }
  ```
  Tools: `fetch_source`, `fetch_all_sources`, `query_saved_listings`, `list_localities`, `get_source_health`.
  `query_saved_listings` supports `pets_allowed`, `non_veg_allowed`, `posted_within_days`, `available_by` and `sort_by="posted"`.

## Sources and limits
| Source | Buy | Rent | Locality search | Notes |
|---|---|---|---|---|
| NoBroker | ✅ | ✅ | ✅ | City-wide buy search returns at most 25. Add localities for more. |
| SquareYards | ✅ | ✅ | ✅ | Commercial listings are skipped. |
| MagicBricks | ⚠️ | ✅ | — | Its sale pages are often "down for maintenance". |
| CommonFloor | ✅ | few | — | Mostly sale listings. |
| 99acres, Housing.com | ❌ | ❌ | — | They block automated access, so they are disabled. |

**Which details each source provides:**
- **NoBroker:** everything (structured pets, non-veg, move-in date, deposit, amenities).
- **MagicBricks:** posted date, availability, tenant preference and description.
- **SquareYards:** posted date (rentals), possession status, parking and description.
- **CommonFloor:** posted date, availability or possession date, amenities and description.

For sources without structured pets or non-veg data, these are read only from explicit phrases in the description ("no pets", "vegetarian only", …). Otherwise they show as unknown, and the pets / non-veg filters leave those listings out.

Sites change their pages from time to time. If a source suddenly returns 0 listings, its parser probably needs updating (see `CLAUDE.md`).

## Development
```bat
.venv\Scripts\python.exe -m pytest -q          :: tests (parsers run against saved real pages)
.venv\Scripts\python.exe -m ruff check --fix . :: lint
.venv\Scripts\python.exe -m ruff format .      :: format
```
- `CLAUDE.md` covers architecture, conventions and how each source is scraped.
- Claude Code project hooks (`.claude/settings.json`):
  - After Claude edits a `.py` file, ruff fixes and formats it.
  - Before Claude finishes a turn with code changes, it is asked to update `README.md`/`CLAUDE.md`.
- The `/commit-push` skill (`.claude/skills/commit-push`) runs the checks, then commits and pushes to GitHub.

Listings belong to their respective sites. This tool is for personal house hunting, and it keeps request rates low.
