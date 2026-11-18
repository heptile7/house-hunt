import sqlite3
import json
import logging
from datetime import datetime, timezone
from config import DB_PATH

logger = logging.getLogger(__name__)


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS properties (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source       TEXT NOT NULL,
            property_id  TEXT NOT NULL,
            listing_type TEXT NOT NULL DEFAULT 'buy',
            title        TEXT,
            price        INTEGER,
            price_text   TEXT,
            area_sqft    REAL,
            bhk          INTEGER,
            property_type TEXT,
            city         TEXT,
            locality     TEXT,
            address      TEXT,
            latitude     REAL,
            longitude    REAL,
            amenities    TEXT,
            image_url    TEXT,
            url          TEXT,
            furnishing   TEXT,
            posted_date  TEXT,
            is_new_project INTEGER DEFAULT 0,
            builder_name TEXT,
            rera_id      TEXT,
            floor        TEXT,
            total_floors INTEGER,
            facing       TEXT,
            parking      INTEGER,
            created_at   TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now')),
            UNIQUE(source, property_id, listing_type)
        );

        CREATE TABLE IF NOT EXISTS scrape_logs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            source              TEXT,
            city                TEXT,
            status              TEXT,
            properties_fetched  INTEGER DEFAULT 0,
            error_message       TEXT,
            scraped_at          TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_city   ON properties(city);
        CREATE INDEX IF NOT EXISTS idx_source ON properties(source);
        CREATE INDEX IF NOT EXISTS idx_price  ON properties(price);
        CREATE INDEX IF NOT EXISTS idx_bhk    ON properties(bhk);
    """)
    # --- Migrations ---
    cols = [r[1] for r in conn.execute("PRAGMA table_info(properties)").fetchall()]

    # Migration 1: add listing_type column if missing
    if "listing_type" not in cols:
        conn.execute("ALTER TABLE properties ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'buy'")

    # Migration 2: rebuild table if old UNIQUE(source, property_id) constraint exists.
    # SQLite can't alter constraints, so we must recreate the table.
    schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='properties'").fetchone()[0]
    if "UNIQUE(source, property_id)" in schema and "listing_type" not in schema.split("UNIQUE")[1]:
        conn.executescript("""
            CREATE TABLE properties_rebuild (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source       TEXT NOT NULL,
                property_id  TEXT NOT NULL,
                listing_type TEXT NOT NULL DEFAULT 'buy',
                title        TEXT, price INTEGER, price_text TEXT,
                area_sqft    REAL, bhk INTEGER, property_type TEXT,
                city TEXT, locality TEXT, address TEXT,
                latitude REAL, longitude REAL, amenities TEXT,
                image_url TEXT, url TEXT, furnishing TEXT,
                posted_date TEXT, is_new_project INTEGER DEFAULT 0,
                builder_name TEXT, rera_id TEXT, floor TEXT,
                total_floors INTEGER, facing TEXT, parking INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(source, property_id, listing_type)
            );
            INSERT INTO properties_rebuild
                SELECT id, source, property_id, listing_type, title, price, price_text,
                       area_sqft, bhk, property_type, city, locality, address,
                       latitude, longitude, amenities, image_url, url, furnishing,
                       posted_date, is_new_project, builder_name, rera_id, floor,
                       total_floors, facing, parking, created_at, updated_at
                FROM properties;
            DROP TABLE properties;
            ALTER TABLE properties_rebuild RENAME TO properties;
            CREATE INDEX IF NOT EXISTS idx_city   ON properties(city);
            CREATE INDEX IF NOT EXISTS idx_source ON properties(source);
            CREATE INDEX IF NOT EXISTS idx_price  ON properties(price);
            CREATE INDEX IF NOT EXISTS idx_bhk    ON properties(bhk);
        """)

    conn.commit()
    conn.close()


def upsert_properties(properties: list[dict]) -> int:
    if not properties:
        return 0
    conn = get_conn()
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    inserted = 0
    for p in properties:
        amenities = json.dumps(p.get("amenities", []))
        try:
            conn.execute("""
                INSERT INTO properties
                    (source, property_id, listing_type, title, price, price_text, area_sqft, bhk,
                     property_type, city, locality, address, latitude, longitude,
                     amenities, image_url, url, furnishing, posted_date,
                     is_new_project, builder_name, rera_id, floor, total_floors,
                     facing, parking, updated_at)
                VALUES
                    (:source, :property_id, :listing_type, :title, :price, :price_text, :area_sqft, :bhk,
                     :property_type, :city, :locality, :address, :latitude, :longitude,
                     :amenities, :image_url, :url, :furnishing, :posted_date,
                     :is_new_project, :builder_name, :rera_id, :floor, :total_floors,
                     :facing, :parking, :updated_at)
                ON CONFLICT(source, property_id, listing_type) DO UPDATE SET
                    -- Refresh fields, but never overwrite a known value with a blank/zero one.
                    title        = COALESCE(NULLIF(excluded.title, ''),      title),
                    price        = COALESCE(NULLIF(excluded.price, 0),       price),
                    price_text   = COALESCE(NULLIF(excluded.price_text, ''), price_text),
                    area_sqft    = COALESCE(NULLIF(excluded.area_sqft, 0),   area_sqft),
                    bhk          = COALESCE(NULLIF(excluded.bhk, 0),         bhk),
                    locality     = COALESCE(NULLIF(excluded.locality, ''),   locality),
                    image_url    = COALESCE(NULLIF(excluded.image_url, ''),  image_url),
                    url          = COALESCE(NULLIF(excluded.url, ''),        url),
                    furnishing   = COALESCE(NULLIF(NULLIF(excluded.furnishing, ''), 'Unknown'), furnishing),
                    updated_at   = excluded.updated_at
            """, {**p, "amenities": amenities, "updated_at": now})
            inserted += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            logger.warning("upsert failed for %s/%s: %s", p.get("source"), p.get("property_id"), e)
    conn.commit()
    conn.close()
    return inserted


def log_scrape(source: str, city: str, status: str, count: int = 0, error: str = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO scrape_logs (source, city, status, properties_fetched, error_message) VALUES (?,?,?,?,?)",
        (source, city, status, count, error),
    )
    conn.commit()
    conn.close()


def query_properties(
    city: str,
    listing_type: str = "buy",
    sources: list[str] = None,
    bhk: list[int] = None,
    prop_types: list[str] = None,
    price_min: int = None,
    price_max: int = None,
    area_min: float = None,
    area_max: float = None,
    limit: int = 500,
) -> list[dict]:
    conn = get_conn()
    conditions = ["city = ?", "listing_type = ?"]
    params: list = [city, listing_type]

    if sources:
        placeholders = ",".join("?" * len(sources))
        conditions.append(f"source IN ({placeholders})")
        params.extend(sources)
    if bhk:
        placeholders = ",".join("?" * len(bhk))
        conditions.append(f"bhk IN ({placeholders})")
        params.extend(bhk)
    if prop_types and "All" not in prop_types:
        placeholders = ",".join("?" * len(prop_types))
        conditions.append(f"property_type IN ({placeholders})")
        params.extend(prop_types)
    if price_min is not None:
        conditions.append("price >= ?")
        params.append(price_min)
    if price_max is not None:
        conditions.append("price <= ?")
        params.append(price_max)
    if area_min is not None:
        conditions.append("area_sqft >= ?")
        params.append(area_min)
    if area_max is not None:
        conditions.append("area_sqft <= ?")
        params.append(area_max)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM properties WHERE {where} ORDER BY updated_at DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_source_status(city: str) -> list[dict]:
    """Latest scrape log per source for the city, plus last-successful-fetch info."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT l.source, l.status, l.properties_fetched, l.error_message, l.scraped_at
        FROM scrape_logs l
        INNER JOIN (
            SELECT source, MAX(scraped_at) AS latest
            FROM scrape_logs WHERE city = ?
            GROUP BY source
        ) m ON l.source = m.source AND l.scraped_at = m.latest
        WHERE l.city = ?
        ORDER BY l.source
    """, (city, city)).fetchall()

    last_good = conn.execute("""
        SELECT source, MAX(scraped_at) AS last_success, MAX(properties_fetched) AS best_count
        FROM scrape_logs
        WHERE city = ? AND status = 'success' AND properties_fetched > 0
        GROUP BY source
    """, (city,)).fetchall()

    conn.close()

    good_map = {r["source"]: dict(r) for r in last_good}
    result = []
    for r in rows:
        d = dict(r)
        g = good_map.get(d["source"], {})
        d["last_success_at"] = g.get("last_success")
        d["best_count"] = g.get("best_count", 0)
        result.append(d)
    return result


def get_last_scrape(city: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scrape_logs WHERE city = ? ORDER BY scraped_at DESC LIMIT 1",
        (city,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_property_count(city: str, listing_type: str = "buy") -> int:
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM properties WHERE city=? AND listing_type=?", (city, listing_type)
    ).fetchone()[0]
    conn.close()
    return count
