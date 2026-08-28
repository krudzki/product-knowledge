"""Query API for scanners: narrow first, broad as labelled fallback.

Usage from a scanner:
    from product_knowledge.query import price_for_observation
    result = price_for_observation(conn, gtin=..., mpn=..., brand=..., family_id=..., attrs={...})
    # result.kind == "exact_variant"  -> authoritative
    # result.kind in ("family","similar_spec") -> fallback range, show as widełki
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from product_knowledge.estimate import estimate_variant, estimate_family
from product_knowledge.matching import resolve

@dataclass(frozen=True)
class PriceAnswer:
    kind: str  # exact_variant | family | similar_spec | none
    basis: str
    confidence: str
    variant_id: str
    family_id: str
    market_floor: float | None
    typical: float | None
    low: float | None
    high: float | None
    evidence_sellers: int
    is_fallback: bool
    computed_at: datetime

def price_for_observation(conn: sqlite3.Connection, *, gtin: str = "", mpn: str = "", brand: str = "",
                          asin: str = "", catalog_code: str = "", family_id: str = "", attrs: dict | None = None,
                          condition: str = "new") -> PriceAnswer:
    m = resolve(conn, gtin=gtin, mpn=mpn, brand=brand, asin=asin, catalog_code=catalog_code, family_id=family_id, attrs=attrs or {})
    now = datetime.now()
    if m.kind == "exact_variant" and m.variant_id:
        est = estimate_variant(conn, m.variant_id, condition=condition, now=now)
        return PriceAnswer(kind=m.kind, basis=m.basis, confidence=est.confidence, variant_id=m.variant_id, family_id=m.family_id,
                           market_floor=est.market_floor, typical=est.typical_price, low=est.low, high=est.high,
                           evidence_sellers=est.evidence_sellers, is_fallback=False, computed_at=now)
    if m.kind in ("family", "similar_spec") and m.family_id:
        fam = estimate_family(conn, m.family_id, condition=condition, now=now)
        # similar_spec: also try the specific variant if we have one
        if m.variant_id:
            est = estimate_variant(conn, m.variant_id, condition=condition, now=now)
            if est.evidence_sellers >= 2:
                return PriceAnswer(kind=m.kind, basis=m.basis, confidence=est.confidence, variant_id=m.variant_id, family_id=m.family_id,
                                   market_floor=est.market_floor, typical=est.typical_price, low=est.low, high=est.high,
                                   evidence_sellers=est.evidence_sellers, is_fallback=True, computed_at=now)
        return PriceAnswer(kind="family", basis=m.basis, confidence=fam.confidence, variant_id=m.variant_id, family_id=m.family_id,
                           market_floor=fam.floor, typical=fam.typical, low=fam.low, high=fam.high,
                           evidence_sellers=fam.evidence_sellers, is_fallback=True, computed_at=now)
    return PriceAnswer(kind="none", basis=m.basis, confidence="low", variant_id="", family_id=m.family_id or family_id,
                       market_floor=None, typical=None, low=None, high=None, evidence_sellers=0, is_fallback=True, computed_at=now)
