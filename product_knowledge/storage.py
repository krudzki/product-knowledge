"""SQLite dev mirror of the PostgreSQL schema.

Production DDL lives in migrations/*.sql.  This module creates the same
tables in SQLite so tests and local scanners work without Postgres.
"""

from __future__ import annotations

import pathlib
import sqlite3

BUSY_TIMEOUT_MS = 30_000


def connect_db(
    path: str | pathlib.Path,
    *,
    read_only: bool = False,
) -> sqlite3.Connection:
    """Open the knowledge store with the fleet's SQLite concurrency policy.

    The canonical store is read continuously while several collectors drain
    observations into it. WAL keeps those readers from blocking a writer;
    the busy timeout covers the remaining short writer/writer collisions.
    All databases are on local ext4, where WAL is safe.
    """
    if read_only:
        conn = sqlite3.connect(
            f"file:{pathlib.Path(path)}?mode=ro",
            uri=True,
            timeout=BUSY_TIMEOUT_MS / 1_000,
        )
    else:
        conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1_000)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    if not read_only:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn

DDL = """
CREATE TABLE IF NOT EXISTS product_families (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    category_slug TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT "",
    attributes_json TEXT NOT NULL DEFAULT "{}",
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS product_variants (
    id TEXT PRIMARY KEY,
    family_id TEXT NOT NULL REFERENCES product_families(id),
    canonical_name TEXT NOT NULL,
    category_slug TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT "{}",
    kind TEXT NOT NULL DEFAULT "single",
    fingerprint TEXT NOT NULL DEFAULT "",
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS product_identifiers (
    variant_id TEXT NOT NULL,
    scheme TEXT NOT NULL,
    raw TEXT NOT NULL,
    normalized TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT "global",
    verified INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (variant_id, scheme, normalized)
);
CREATE INDEX IF NOT EXISTS idx_identifiers_normalized ON product_identifiers(scheme, normalized);
CREATE TABLE IF NOT EXISTS source_listings (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    seller TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    family_id TEXT NOT NULL DEFAULT "",
    variant_id TEXT NOT NULL DEFAULT "",
    condition_bucket TEXT NOT NULL DEFAULT "new",
    condition_grade TEXT NOT NULL DEFAULT "",
    is_bundle INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_listings_variant ON source_listings(variant_id, active);
CREATE INDEX IF NOT EXISTS idx_listings_family ON source_listings(family_id, active);
-- URL is how scanners and the verification queue address a listing, so the
-- mispricing ranking joins on it; without this the lookup is a full scan.
CREATE INDEX IF NOT EXISTS idx_listings_url ON source_listings(url);
CREATE TABLE IF NOT EXISTS price_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL REFERENCES source_listings(id),
    observed_at TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT "PLN",
    shipping REAL,
    availability TEXT NOT NULL DEFAULT "available",
    payload_hash TEXT NOT NULL DEFAULT ""
);
CREATE INDEX IF NOT EXISTS idx_obs_listing_time ON price_observations(listing_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS match_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    basis TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    resolver_version TEXT NOT NULL DEFAULT "v1",
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_estimates (
    variant_id TEXT NOT NULL,
    condition_bucket TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    market_floor REAL,
    typical_price REAL,
    low REAL,
    high REAL,
    quick_sale REAL,
    confidence TEXT NOT NULL,
    evidence_sellers INTEGER NOT NULL DEFAULT 0,
    evidence_listings INTEGER NOT NULL DEFAULT 0,
    is_family_fallback INTEGER NOT NULL DEFAULT 0,
    method_version TEXT NOT NULL DEFAULT "v1",
    PRIMARY KEY (variant_id, condition_bucket)
);
CREATE TABLE IF NOT EXISTS family_price_ranges (
    family_id TEXT NOT NULL,
    condition_bucket TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    low REAL,
    high REAL,
    typical REAL,
    floor REAL,
    variants_count INTEGER NOT NULL DEFAULT 0,
    evidence_sellers INTEGER NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL,
    method_version TEXT NOT NULL DEFAULT "v1",
    PRIMARY KEY (family_id, condition_bucket)
);
CREATE TABLE IF NOT EXISTS value_scores (
    variant_id TEXT PRIMARY KEY,
    resale_margin_pln REAL NOT NULL,
    roi REAL NOT NULL,
    liquidity REAL NOT NULL,
    price_volatility REAL NOT NULL,
    priority_score REAL NOT NULL,
    computed_at TEXT NOT NULL
);
"""

# Amazon listings are keyed by URL, but every consumer asks by ASIN. The only
# way to express that without a column was `url LIKE '%/dp/' || asin`, whose
# leading wildcard cannot use any index: measured 2026-09-24 on the live
# 944k-row table, 322 ms per lookup (median of 300), issued twice per product
# by the Amazon scanners - most of the sweep's 90-minute CPU budget.
#
# The column is GENERATED from the URL, so it can never drift from it and no
# writer has to learn about it. It holds the last ten characters when the URL
# ends in `/dp/<10 chars>` (case-insensitive), which is exactly the set the
# old LIKE matched: canonical `https://www.amazon.pl/dp/ASIN` rows AND the
# 71 legacy `.../slug/dp/ASIN` rows written before URL canonicalisation. A
# host-list lookup on the canonical URL would silently drop the latter and
# changed the price verdict for 2 of them.
#
# VIRTUAL, not STORED: SQLite cannot ADD a stored column to an existing
# table, and the partial index materialises the value anyway. The ALTER only
# rewrites the schema; building the index is the one full pass.
LISTING_ASIN_COLUMN = (
    "asin TEXT GENERATED ALWAYS AS ("
    "CASE WHEN lower(substr(url, -14, 4)) = '/dp/' "
    "THEN upper(substr(url, -10)) END) VIRTUAL"
)


def _ensure_listing_asin(conn: sqlite3.Connection) -> None:
    """Add the generated ASIN column and its index to an existing store."""
    columns = {row[1] for row in conn.execute("PRAGMA table_xinfo(source_listings)")}
    if "asin" not in columns:
        try:
            conn.execute(f"ALTER TABLE source_listings ADD COLUMN {LISTING_ASIN_COLUMN}")
        except sqlite3.OperationalError as error:
            # Several drains and scanners call init_db; losing the race to
            # add the column is success, anything else is not.
            if "duplicate column" not in str(error):
                raise
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_listings_asin "
        "ON source_listings(asin, source) WHERE asin IS NOT NULL"
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    _ensure_listing_asin(conn)
    conn.commit()
