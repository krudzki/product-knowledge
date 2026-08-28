
"""Category boosts derived from family price ranges.

Produces a JSON-ready map slug -> boost (0.0-1.0) used by scanners
to tilt pages_per_run / budget toward high-value families.

Bootstrap: P1/P2/P3 from category_map.  Once estimates exist, the boost
tracks (typical price * liquidity / volatility).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from product_knowledge.estimate import estimate_family

# Static bootstrap when no estimates yet — keeps current behavior
BOOTSTRAP = {"P1": 1.0, "P2": 0.65, "P3": 0.35}

def _family_slugs(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    # id, name, category_slug
    return list(conn.execute("SELECT id, canonical_name, category_slug FROM product_families").fetchall())

def category_boosts(conn: sqlite3.Connection, fresh_hours: int = 72) -> dict[str, dict]:
    out: dict[str, dict] = {}
    # bucket per category_slug: best family score in that slug
    by_slug: dict[str, float] = {}
    details: dict[str, dict] = {}
    for fid, name, slug in _family_slugs(conn):
        est = estimate_family(conn, fid, fresh_hours=fresh_hours)
        # value signal: typical weighted by confidence & liquidity
        sellers = est.evidence_sellers
        typical = est.typical or 0
        conf_w = {"high": 1.0, "medium": 0.6, "low": 0.3}.get(est.confidence, 0.3)
        # liquidity proxy: sellers
        liq = min(1.0, sellers / 4.0) if sellers else 0.2
        score = typical * conf_w * (0.5 + 0.5 * liq) if typical else 0
        by_slug[slug] = max(by_slug.get(slug, 0), score)
        if score > 0:
            details[slug] = {"family": fid, "typical": typical, "sellers": sellers, "confidence": est.confidence, "score": round(score, 1)}
    # normalize 0..1
    mx = max(by_slug.values()) if by_slug else 0
    for slug, score in by_slug.items():
        boost = round(score / mx, 3) if mx else 0.5
        d = details.get(slug, {})
        d.update({"boost": boost, "category": slug})
        out[slug] = d
    return out

def boosts_as_budget_overlay(boosts: dict[str, dict], base_pages: int = 12) -> dict[str, int]:
    # pages_per_run overlay: base * (0.6 + 0.6*boost), clamped 6..24
    out: dict[str, int] = {}
    for slug, info in boosts.items():
        b = float(info.get("boost", 0.5))
        pages = int(round(base_pages * (0.6 + 0.6 * b)))
        out[slug] = max(6, min(24, pages))
    return out

if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(pathlib.Path.home() / "dane/product-knowledge.db"))
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    from product_knowledge.storage import init_db
    init_db(conn)
    print(json.dumps(category_boosts(conn), indent=2, ensure_ascii=False))
