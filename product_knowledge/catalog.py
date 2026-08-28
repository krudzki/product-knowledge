"""Catalog helpers: families, variants, identifiers, listings, observations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

def upsert_family(conn: sqlite3.Connection, fid: str, name: str, category_slug: str, brand: str = "", attrs: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO product_families (id, canonical_name, category_slug, brand, attributes_json, created_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name, category_slug=excluded.category_slug, brand=excluded.brand, attributes_json=excluded.attributes_json",
        (fid, name, category_slug, brand, json.dumps(attrs or {}, ensure_ascii=False), datetime.now().isoformat()),
    )

def upsert_variant(conn: sqlite3.Connection, vid: str, family_id: str, name: str, category_slug: str, attrs: dict | None = None, kind: str = "single") -> None:
    # fingerprint = sorted attrs
    fp = json.dumps(attrs or {}, sort_keys=True, ensure_ascii=False)
    conn.execute(
        "INSERT INTO product_variants (id, family_id, canonical_name, category_slug, attributes_json, kind, fingerprint, created_at) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name, category_slug=excluded.category_slug, attributes_json=excluded.attributes_json, kind=excluded.kind, fingerprint=excluded.fingerprint",
        (vid, family_id, name, category_slug, json.dumps(attrs or {}, ensure_ascii=False), kind, fp, datetime.now().isoformat()),
    )

def add_identifier(conn: sqlite3.Connection, variant_id: str, scheme: str, raw: str, normalized: str, scope: str = "global", verified: int = 1) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO product_identifiers (variant_id, scheme, normalized, raw, scope, verified) VALUES (?,?,?,?,?,?)",
        (variant_id, scheme, normalized, raw, scope, verified),
    )

def upsert_listing(conn: sqlite3.Connection, lid: str, source: str, seller: str, url: str, title: str, family_id: str = "", variant_id: str = "", condition_bucket: str = "new", condition_grade: str = "", is_bundle: bool = False) -> None:
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO source_listings (id, source, seller, url, title, family_id, variant_id, condition_bucket, condition_grade, is_bundle, first_seen, last_seen, active) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, family_id=excluded.family_id, variant_id=excluded.variant_id, condition_bucket=excluded.condition_bucket, condition_grade=excluded.condition_grade, is_bundle=excluded.is_bundle, last_seen=excluded.last_seen, active=1",
        (lid, source, seller, url, title, family_id, variant_id, condition_bucket, condition_grade, int(is_bundle), now, now),
    )

def add_observation(conn: sqlite3.Connection, listing_id: str, price: float, currency: str = "PLN", shipping: float | None = None, availability: str = "available", payload_hash: str = "", observed_at: datetime | None = None) -> None:
    conn.execute(
        "INSERT INTO price_observations (listing_id, observed_at, price, currency, shipping, availability, payload_hash) VALUES (?,?,?,?,?,?,?)",
        (listing_id, (observed_at or datetime.now()).isoformat(), float(price), currency, shipping, availability, payload_hash),
    )

def record_match(conn: sqlite3.Connection, listing_id: str, variant_id: str, decision: str, basis: str, score: float, version: str = "v1") -> None:
    conn.execute(
        "INSERT INTO match_decisions (listing_id, variant_id, decision, basis, score, resolver_version, created_at) VALUES (?,?,?,?,?,?,?)",
        (listing_id, variant_id, decision, basis, float(score), version, datetime.now().isoformat()),
    )
