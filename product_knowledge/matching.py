"""Narrow + broad matching.

Narrow: exact GTIN/MPN/ASIN/catalog — precision-first auto-link.
Broad:  family or similar-spec range — labelled fallback, used for
        laptops with close specs and console family ranges.

Both layers live here so scanners have one call site:
    result = resolve(listing, ctx)  -> MatchResult(variant_id, kind, basis)

Narrow kinds: exact_variant
Broad kinds:  family, similar_spec
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from product_knowledge.identifiers import normalize_asin, normalize_code, normalize_gtin, normalize_mpn

@dataclass(frozen=True)
class MatchResult:
    variant_id: str
    family_id: str
    kind: str  # exact_variant | family | similar_spec | none
    basis: str
    score: float
    confidence: str  # high | medium | low

# ---------- narrow: exact identifier lookup ----------

def narrow_lookup(conn: sqlite3.Connection, *, gtin: str = "", mpn: str = "", brand: str = "",
                  asin: str = "", catalog_code: str = "") -> MatchResult | None:
    # GTIN
    g = normalize_gtin(gtin) if gtin else None
    if g:
        for scheme in ("gtin","ean","upc"):
            row = conn.execute("SELECT variant_id FROM product_identifiers WHERE scheme=? AND normalized=?", (scheme, g)).fetchone()
            if row:
                fam = conn.execute("SELECT family_id FROM product_variants WHERE id=?", (row[0],)).fetchone()
                return MatchResult(row[0], fam[0] if fam else "", "exact_variant", "exact_gtin", 1.0, "high")
    # brand+MPN
    if mpn:
        m = normalize_mpn(mpn)
        # MPN is scoped to brand — try normalized MPN with brand in attributes or with any variant that has this MPN
        row = conn.execute("SELECT variant_id FROM product_identifiers WHERE scheme IN ('mpn','manufacturer_code') AND normalized=?", (m,)).fetchone()
        if row:
            # verify brand when possible
            fam = conn.execute("SELECT family_id, category_slug FROM product_variants WHERE id=?", (row[0],)).fetchone()
            fam_brand = ""
            if fam:
                fam_row = conn.execute("SELECT brand FROM product_families WHERE id=?", (fam[0],)).fetchone()
                fam_brand = (fam_row[0] if fam_row else "").lower()
            if not brand or not fam_brand or brand.lower() in fam_brand or fam_brand in brand.lower():
                return MatchResult(row[0], fam[0] if fam else "", "exact_variant", "brand_mpn", 0.98, "high")
    # ASIN
    if asin:
        a = normalize_asin(asin)
        if a:
            row = conn.execute("SELECT variant_id FROM product_identifiers WHERE scheme='asin' AND normalized=?", (a,)).fetchone()
            if row:
                fam = conn.execute("SELECT family_id FROM product_variants WHERE id=?", (row[0],)).fetchone()
                return MatchResult(row[0], fam[0] if fam else "", "exact_variant", "verified_asin", 0.97, "high")
    # literal catalog code
    if catalog_code:
        c = normalize_code(catalog_code)
        if len(c) >= 6:
            row = conn.execute("SELECT variant_id FROM product_identifiers WHERE normalized=?", (c,)).fetchone()
            if row:
                fam = conn.execute("SELECT family_id FROM product_variants WHERE id=?", (row[0],)).fetchone()
                return MatchResult(row[0], fam[0] if fam else "", "exact_variant", "literal_code", 0.95, "high")
    return None

# ---------- broad: family / similar-spec ----------

# Laptop spec keys that define a similar-spec bucket
LAPTOP_SPEC_KEYS = ("cpu", "ram_gb", "gpu", "storage_gb", "display_inch")

def _spec_bucket(variant_attrs: dict) -> tuple:
    return tuple(str(variant_attrs.get(k, "")).lower() for k in LAPTOP_SPEC_KEYS)

def family_fallback(conn: sqlite3.Connection, family_id: str) -> MatchResult | None:
    if not family_id:
        return None
    row = conn.execute("SELECT id FROM product_families WHERE id=?", (family_id,)).fetchone()
    if not row:
        return None
    return MatchResult("", family_id, "family", "family", 0.6, "low")

def similar_spec_search(conn: sqlite3.Connection, family_id: str, attrs: dict, max_results: int = 8) -> list[MatchResult]:
    """Find variants in the same family with close specs (laptops etc)."""
    if not family_id or not attrs:
        return []
    rows = conn.execute("SELECT id, attributes_json FROM product_variants WHERE family_id=?", (family_id,)).fetchall()
    scored: list[tuple[float, str]] = []
    target = _spec_bucket(attrs)
    for vid, j in rows:
        try:
            va = json.loads(j or "{}")
        except Exception:
            va = {}
        bucket = _spec_bucket(va)
        # score: exact field matches weighted
        score = 0.0
        weights = {"cpu": 0.3, "gpu": 0.3, "ram_gb": 0.2, "storage_gb": 0.1, "display_inch": 0.1}
        for k, w in weights.items():
            a = str(attrs.get(k, "")).lower().strip()
            b = str(va.get(k, "")).lower().strip()
            if not a or not b:
                continue
            if a == b:
                score += w
            elif k in ("ram_gb","storage_gb"):
                try:
                    if abs(int(a) - int(b)) <= 8:  # close RAM/storage
                        score += w * 0.5
                except Exception:
                    pass
        if score >= 0.45:
            scored.append((score, vid))
    scored.sort(reverse=True)
    out: list[MatchResult] = []
    for s, vid in scored[:max_results]:
        conf = "medium" if s >= 0.7 else "low"
        out.append(MatchResult(vid, family_id, "similar_spec", "attribute", s, conf))
    return out

def resolve(conn: sqlite3.Connection, *, gtin: str = "", mpn: str = "", brand: str = "",
            asin: str = "", catalog_code: str = "", family_id: str = "", attrs: dict | None = None) -> MatchResult:
    """Narrow first, then broad. Never invents an identity."""
    hit = narrow_lookup(conn, gtin=gtin, mpn=mpn, brand=brand, asin=asin, catalog_code=catalog_code)
    if hit:
        return hit
    if family_id:
        sims = similar_spec_search(conn, family_id, attrs or {})
        if sims:
            return sims[0]
        fam = family_fallback(conn, family_id)
        if fam:
            return fam
    return MatchResult("", family_id or "", "none", "none", 0.0, "low")
