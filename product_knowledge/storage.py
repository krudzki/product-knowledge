"""SQLite dev mirror of the PostgreSQL schema.

Production DDL lives in migrations/*.sql.  This module creates the same
tables in SQLite so tests and local scanners work without Postgres.
"""

from __future__ import annotations

import sqlite3

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

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()
