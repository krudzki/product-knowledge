
"""Ceneo refresh for thin-evidence Tier A variants.

Picks variants with <2 sellers in the last 72h, up to a budget per run,
and prints / queues Ceneo product URLs for collection.

Does not scrape itself — ceneo/collector.py and product-knowledge/ingest
remain the only writers that touch HTML.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

def thin_variants(pk_db: str | pathlib.Path, max_variants: int = 10, fresh_hours: int = 72) -> list[dict]:
    conn = sqlite3.connect(str(pk_db))
    since = (datetime.now() - timedelta(hours=fresh_hours)).isoformat()
    rows = conn.execute(
        "SELECT id, family_id, canonical_name, category_slug FROM product_variants ORDER BY id"
    ).fetchall()
    out = []
    for vid, fid, name, cat in rows:
        sellers = conn.execute(
            "SELECT COUNT(DISTINCT l.seller) FROM price_observations o JOIN source_listings l ON l.id=o.listing_id "
            "WHERE l.variant_id=? AND o.observed_at>=?",
            (vid, since),
        ).fetchone()[0]
        if sellers < 2:
            out.append({"variant_id": vid, "family_id": fid, "name": name, "category": cat, "sellers": sellers})
            if len(out) >= max_variants:
                break
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(pathlib.Path.home() / "dane/product-knowledge.db"))
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args()
    print(json.dumps(thin_variants(args.db, max_variants=args.max), ensure_ascii=False, indent=2))
