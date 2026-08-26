"""
Local SQLite database — single source of truth for all Copart data.

Tables:
  lots         1 row per vehicle (stable identity/attributes)
  snapshots    1 row per lot per visit    (what Copart said at that moment)
  pricings     1 row per lot per pricing  (our valuation, over time)
  market_cache 1 row per make|model|year  (Auto.dev comps cache)

Data flows in through the Chrome extension -> server (no automated scraping).
"""
import sqlite3
import json
import datetime
from contextlib import contextmanager
from pathlib import Path

DB_FILE = Path(__file__).parent / "copart.db"

# ---- field groups ----
# Static vehicle identity (one row per lot, upserted on each visit).
LOT_FIELDS = [
    "lot_number", "item_number", "vin", "year", "make", "model", "trim",
    "title", "body_style", "color", "engine", "cylinders", "transmission",
    "drivetrain", "fuel", "odometer_brand", "keys", "drive_status",
    "title_group", "title_code", "title_desc", "primary_damage",
    "secondary_damage", "lot_condition", "seller", "lot_url", "image", "timezone",
]

# Dynamic fields captured per visit (this is what builds history over time).
SNAPSHOT_FIELDS = [
    "snapshot_date", "lot_number", "odometer", "condition_code", "yard",
    "buy_now_price", "est_retail_value", "acv", "repair_cost",
    "sale_date", "sale_time",
]

# Valuation fields produced by pricing.price_lot().
PRICING_FIELDS = [
    "run_id", "lot_number", "price_source", "market_price", "market_avg",
    "market_n_listings", "market_scope", "market_min", "market_max",
    "market_miles_matched", "market_mileage_adjusted", "condition_code",
    "condition_discount_pct", "max_bid",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
  lot_number       TEXT PRIMARY KEY,
  item_number      TEXT,
  vin              TEXT,
  year             INTEGER,
  make             TEXT,
  model            TEXT,
  trim             TEXT,
  title            TEXT,
  body_style       TEXT,
  color            TEXT,
  engine           TEXT,
  cylinders        TEXT,
  transmission     TEXT,
  drivetrain       TEXT,
  fuel             TEXT,
  odometer_brand   TEXT,
  keys             TEXT,
  drive_status     TEXT,
  title_group      TEXT,
  title_code       TEXT,
  title_desc       TEXT,
  primary_damage   TEXT,
  secondary_damage TEXT,
  lot_condition    TEXT,
  seller           TEXT,
  lot_url          TEXT,
  image            TEXT,
  timezone         TEXT,
  first_seen       TEXT NOT NULL,
  last_seen        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_date    TEXT NOT NULL,
  lot_number       TEXT NOT NULL REFERENCES lots(lot_number),
  odometer         REAL,
  condition_code   TEXT,
  yard             TEXT,
  buy_now_price    REAL,
  est_retail_value REAL,
  acv              REAL,
  repair_cost      REAL,
  sale_date        TEXT,
  sale_time        TEXT,
  PRIMARY KEY (snapshot_date, lot_number)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_lot ON snapshots(lot_number, snapshot_date);

CREATE TABLE IF NOT EXISTS pricings (
  run_id                  TEXT NOT NULL,
  lot_number              TEXT NOT NULL REFERENCES lots(lot_number),
  price_source            TEXT,
  market_price            REAL,
  market_avg              REAL,
  market_n_listings       INTEGER,
  market_scope            TEXT,
  market_min              REAL,
  market_max              REAL,
  market_miles_matched    INTEGER,
  market_mileage_adjusted INTEGER,
  condition_code          TEXT,
  condition_discount_pct  INTEGER,
  max_bid                 REAL,
  PRIMARY KEY (run_id, lot_number)
);
CREATE INDEX IF NOT EXISTS idx_pricings_lot ON pricings(lot_number, run_id);

CREATE TABLE IF NOT EXISTS market_cache (
  make       TEXT NOT NULL,
  model      TEXT NOT NULL,
  year       INTEGER NOT NULL,
  scope      TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  listings   TEXT NOT NULL,   -- JSON array of {"price":.., "miles":..}
  PRIMARY KEY (make, model, year)
);
"""


def get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def tx():
    """Connection context manager: commits on success, always closes."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with tx() as conn:
        conn.executescript(SCHEMA)


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_db(v):
    if isinstance(v, bool):
        return int(v)
    return v


def upsert_lots(conn, rows):
    update_cols = [c for c in LOT_FIELDS if c != "lot_number"]
    sql = (
        "INSERT INTO lots (" + ", ".join(LOT_FIELDS + ["first_seen", "last_seen"]) + ") "
        "VALUES (" + ", ".join(":" + c for c in LOT_FIELDS) + ", :first_seen, :last_seen) "
        "ON CONFLICT(lot_number) DO UPDATE SET " +
        ", ".join("%s = excluded.%s" % (c, c) for c in update_cols) +
        ", last_seen = CASE WHEN excluded.last_seen > lots.last_seen "
        "THEN excluded.last_seen ELSE lots.last_seen END"
    )
    for r in rows:
        if not r.get("lot_number"):
            continue
        d = {c: _to_db(r.get(c)) for c in LOT_FIELDS}
        d["first_seen"] = d["last_seen"] = r.get("snapshot_date") or now()
        conn.execute(sql, d)


def insert_snapshots(conn, rows):
    sql = (
        "INSERT OR REPLACE INTO snapshots (" + ", ".join(SNAPSHOT_FIELDS) + ") "
        "VALUES (" + ", ".join(":" + c for c in SNAPSHOT_FIELDS) + ")"
    )
    for r in rows:
        if not r.get("lot_number"):
            continue
        conn.execute(sql, {c: _to_db(r.get(c)) for c in SNAPSHOT_FIELDS})


def insert_pricings(conn, rows, run_id):
    sql = (
        "INSERT OR REPLACE INTO pricings (" + ", ".join(PRICING_FIELDS) + ") "
        "VALUES (" + ", ".join(":" + c for c in PRICING_FIELDS) + ")"
    )
    for r in rows:
        if not r.get("lot_number"):
            continue
        d = {c: _to_db(r.get(c)) for c in PRICING_FIELDS}
        d["run_id"] = run_id
        conn.execute(sql, d)


# ---- convenience wrappers used by the server ----

def save_lot(row):
    """Upsert one lot + append one snapshot (called when a lot page opens)."""
    with tx() as conn:
        upsert_lots(conn, [row])
        insert_snapshots(conn, [row])
    return row.get("lot_number")


def save_pricings(rows, run_id):
    with tx() as conn:
        insert_pricings(conn, rows, run_id)
    return len(rows)


def has_pricing(lot_number):
    with tx() as conn:
        r = conn.execute("SELECT 1 FROM pricings WHERE lot_number = ? LIMIT 1", (lot_number,)).fetchone()
    return r is not None


def _merge(lot, snap, pr):
    """Merge a lot row with optional snapshot + pricing into one flat dict."""
    rec = {}
    rec.update(dict(lot))
    snap = dict(snap) if snap else {}
    snap_cc = snap.get("condition_code")
    rec.update(snap)
    pr = dict(pr) if pr else {}
    rec.update(pr)
    if snap_cc is not None:          # snapshot condition is authoritative
        rec["condition_code"] = snap_cc
    if rec.get("market_mileage_adjusted") is not None:
        rec["market_mileage_adjusted"] = bool(rec["market_mileage_adjusted"])
    return rec


def get_lot_record(lot_number):
    """Merged lot + latest snapshot + latest pricing for a single lot."""
    with tx() as conn:
        lot = conn.execute("SELECT * FROM lots WHERE lot_number = ?", (lot_number,)).fetchone()
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE lot_number = ? ORDER BY snapshot_date DESC LIMIT 1",
            (lot_number,)).fetchone()
        pr = conn.execute(
            "SELECT * FROM pricings WHERE lot_number = ? ORDER BY run_id DESC LIMIT 1",
            (lot_number,)).fetchone()
    if not lot:
        return None
    return _merge(lot, snap, pr)


def all_lots():
    """Every lot, each merged with its latest snapshot + latest pricing.
    Served to the extension at /copart_listings_priced.json."""
    with tx() as conn:
        lots = conn.execute("SELECT * FROM lots").fetchall()
        snaps = conn.execute(
            "SELECT s.* FROM snapshots s "
            "JOIN (SELECT lot_number, MAX(snapshot_date) AS m FROM snapshots GROUP BY lot_number) x "
            "ON s.lot_number = x.lot_number AND s.snapshot_date = x.m"
        ).fetchall()
        prices = conn.execute(
            "SELECT p.* FROM pricings p "
            "JOIN (SELECT lot_number, MAX(run_id) AS m FROM pricings GROUP BY lot_number) x "
            "ON p.lot_number = x.lot_number AND p.run_id = x.m"
        ).fetchall()
    snap_by = {r["lot_number"]: r for r in snaps}
    price_by = {r["lot_number"]: r for r in prices}
    return [_merge(lot, snap_by.get(lot["lot_number"]), price_by.get(lot["lot_number"])) for lot in lots]


def cache_get(make, model, year):
    with tx() as conn:
        r = conn.execute(
            "SELECT scope, listings FROM market_cache WHERE make = ? AND model = ? AND year = ?",
            (make, model, year),
        ).fetchone()
    if not r:
        return None
    return {"scope": r["scope"], "listings": json.loads(r["listings"])}


def cache_put(make, model, year, scope, listings):
    with tx() as conn:
        conn.execute(
            "INSERT INTO market_cache (make, model, year, scope, fetched_at, listings) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(make, model, year) DO UPDATE SET "
            "scope = excluded.scope, fetched_at = excluded.fetched_at, listings = excluded.listings",
            (make, model, year, scope, now(), json.dumps(listings)),
        )


def cache_clear():
    with tx() as conn:
        conn.execute("DELETE FROM market_cache")


def stats():
    with tx() as conn:
        n_lots = conn.execute("SELECT COUNT(*) AS n FROM lots").fetchone()["n"]
        n_snaps = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        n_priced = conn.execute("SELECT COUNT(DISTINCT lot_number) AS n FROM pricings").fetchone()["n"]
        n_maxbid = conn.execute(
            "SELECT COUNT(DISTINCT lot_number) AS n FROM pricings WHERE max_bid IS NOT NULL"
        ).fetchone()["n"]
        n_cache = conn.execute("SELECT COUNT(*) AS n FROM market_cache").fetchone()["n"]
        last_scrape = conn.execute("SELECT MAX(snapshot_date) AS m FROM snapshots").fetchone()["m"]
        last_price = conn.execute("SELECT MAX(run_id) AS m FROM pricings").fetchone()["m"]
    return {
        "lots": n_lots,
        "snapshots": n_snaps,
        "priced_lots": n_priced,
        "max_bid_lots": n_maxbid,
        "cache": n_cache,
        "last_scrape": last_scrape,
        "last_pricing": last_price,
    }
