"""Ingest observations from scanners / products.db into product-knowledge.

Usage:
  python -m product_knowledge.ingest --products-db ~/dane/products.db --pk-db /tmp/pk.db --limit 500

Maps ceny_biezace rows to source_listings + price_observations.
Does NOT auto-merge name-only keys into canonical variants — those stay
as family-level or provisional listings for review.

Ledger key parsing:
  code:<value>  -> try GTIN else MPN/manufacturer_code identifier
  name:<...>    -> family-level provisional listing
  page:<...>    -> provisional listing
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime

from product_knowledge.catalog import add_observation, upsert_listing
from product_knowledge.storage import init_db

GTIN_RE = re.compile(r"^\d{8}$|^\d{12}$|^\d{13}$|^\d{14}$")

def _classify_code(value: str) -> tuple[str, str]:
    s = value.strip()
    digits = re.sub(r"\D", "", s)
    if GTIN_RE.match(digits) and len(digits) in (8,12,13,14):
        # validate check digit
        total = 0
        for i, ch in enumerate(reversed(digits)):
            d = int(ch)
            if i == 0:
                continue
            total += d * 3 if i % 2 == 1 else d
        if (10 - (total % 10)) % 10 == int(digits[-1]):
            return "gtin", digits
    return "mpn", s.upper()

def ingest(products_db: str, pk_db: str, limit: int = 1000) -> dict:
    src = sqlite3.connect(f"file:{products_db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(pk_db)
    init_db(dst)
    rows = src.execute(
        "SELECT klucz, nazwa, sprzedawca, zrodlo, cena, url, ostatnio_widziana FROM ceny_biezace ORDER BY ostatnio_widziana DESC LIMIT ?",
        (limit,),
    ).fetchall()
    ingested = 0
    for r in rows:
        key, name, seller, source, price, url, seen = r["klucz"], r["nazwa"], r["sprzedawca"], r["zrodlo"], r["cena"], r["url"], r["ostatnio_widziana"]
        if price is None or price <= 0:
            continue
        # listing id stable per ledger row
        lid = f"{source}:{seller}:{key}"
        # try to resolve variant via identifier table
        variant_id = ""
        family_id = ""
        if key.startswith("code:"):
            val = key[5:].strip()
            scheme, norm = _classify_code(val)
            hit = dst.execute("SELECT variant_id FROM product_identifiers WHERE scheme=? AND normalized=?", (scheme, norm)).fetchone()
            if not hit and scheme == "mpn":
                hit = dst.execute("SELECT variant_id FROM product_identifiers WHERE normalized=?", (norm,)).fetchone()
            if hit:
                variant_id = hit[0]
                fam = dst.execute("SELECT family_id FROM product_variants WHERE id=?", (variant_id,)).fetchone()
                family_id = fam[0] if fam else ""
        # title fallback
        title = name or key
        upsert_listing(dst, lid, source, seller, url or "", title, family_id=family_id, variant_id=variant_id, condition_bucket="new")
        try:
            when = datetime.fromisoformat(seen) if seen else datetime.now()
        except Exception:
            when = datetime.now()
        add_observation(dst, lid, float(price), observed_at=when)
        ingested += 1
    dst.commit()
    return {"ingested": ingested, "limit": limit}
