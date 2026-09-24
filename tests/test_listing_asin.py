"""Amazon history lookups must use an index, and must match what LIKE matched.

Measured 2026-09-24: `url LIKE '%/dp/' || asin` cost 322 ms per lookup on the
live 944k-row table (leading wildcard = full scan), twice per product per
Amazon scan. The generated `asin` column replaces it; these tests pin that the
replacement is both indexed and equivalent, including the legacy slug URLs.
"""

from __future__ import annotations

import sqlite3

from product_knowledge.catalog import upsert_listing
from product_knowledge.storage import DDL, init_db

LIKE_LOOKUP = "SELECT id FROM source_listings WHERE source = ? AND url LIKE ?"
ASIN_LOOKUP = "SELECT id FROM source_listings WHERE source = ? AND asin = ?"

URLS = {
    "canonical-pl": "https://www.amazon.pl/dp/B0CURRENCY",
    "canonical-de-host": "https://www.amazon.de/dp/B0CURRENCY",
    "legacy-slug": "https://www.amazon.pl/Some-Product-Name/dp/B0CURRENCY",
    "lowercase": "https://www.amazon.pl/dp/b0currency",
    "session-suffix": "https://www.amazon.pl/x/dp/B0CURRENCY/ref=zg/605-2498562?psc=1",
    "other-asin": "https://www.amazon.pl/dp/B0OTHER001",
    "not-amazon": "https://www.x-kom.pl/p/1234567890",
    "short-tail": "https://shop.example/dp/SHORT",
}


def _store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    for name, url in URLS.items():
        upsert_listing(conn, name, "amazon-nowosci", "amazon-nowosci", url, "t")
    return conn


def test_asin_lookup_matches_exactly_what_like_matched():
    conn = _store()
    for asin in ("B0CURRENCY", "B0OTHER001", "B0UNKNOWN1"):
        like = {r[0] for r in conn.execute(LIKE_LOOKUP, ("amazon-nowosci", "%/dp/" + asin))}
        exact = {r[0] for r in conn.execute(ASIN_LOOKUP, ("amazon-nowosci", asin))}
        assert exact == like, asin


def test_legacy_slug_url_keeps_its_history():
    """A host-list lookup on the canonical URL dropped these rows."""
    conn = _store()
    found = {r[0] for r in conn.execute(ASIN_LOOKUP, ("amazon-nowosci", "B0CURRENCY"))}
    assert "legacy-slug" in found


def test_asin_lookup_uses_the_index():
    conn = _store()
    plan = " ".join(str(r) for r in conn.execute(
        "EXPLAIN QUERY PLAN " + ASIN_LOOKUP, ("amazon-nowosci", "B0CURRENCY")))
    assert "idx_listings_asin" in plan, plan
    assert "SCAN" not in plan, plan


def test_existing_store_is_migrated_in_place_and_idempotently():
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)  # the pre-migration schema, already holding data
    upsert_listing(conn, "old", "amazon-nowosci", "amazon-nowosci", URLS["legacy-slug"], "t")

    init_db(conn)
    init_db(conn)  # every drain calls it; the second pass must be a no-op

    assert [r[0] for r in conn.execute(ASIN_LOOKUP, ("amazon-nowosci", "B0CURRENCY"))] == ["old"]


def test_plain_insert_without_column_list_still_works():
    """Generated columns are not writable; positional inserts must not shift."""
    conn = _store()
    conn.execute(
        "INSERT INTO source_listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("pos", "s", "s", "https://www.amazon.pl/dp/B0POSITION", "t", "", "", "new", "", 0,
         "x", "x", 1),
    )
    assert conn.execute("SELECT asin FROM source_listings WHERE id='pos'").fetchone() == ("B0POSITION",)
