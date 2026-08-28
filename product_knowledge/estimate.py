"""Price estimation: narrow exact + broad family range.

Narrow estimate is authoritative only when backed by enough sellers.
Broad range is a labelled fallback (family).
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timedelta

from product_knowledge.models import FamilyPriceRange, PriceEstimate

def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)

def _seller_landed_prices(conn: sqlite3.Connection, variant_id: str, condition: str, fresh_hours: int, now: datetime) -> list[float]:
    since = (now - timedelta(hours=fresh_hours)).isoformat()
    rows = conn.execute(
        """
        SELECT l.seller, o.price, o.shipping
          FROM price_observations o
          JOIN source_listings l ON l.id = o.listing_id
         WHERE l.variant_id = ? AND l.condition_bucket = ? AND l.active = 1
           AND o.observed_at >= ? AND o.availability = "available"
         ORDER BY o.observed_at DESC
        """, (variant_id, condition, since)).fetchall()
    latest: dict[str, float] = {}
    for seller, price, shipping in rows:
        if seller in latest:
            continue
        landed = float(price) + (float(shipping) if shipping is not None else 0.0)
        latest[seller] = landed
    return list(latest.values())

def estimate_variant(conn: sqlite3.Connection, variant_id: str, condition: str = "new",
                     fresh_hours: int = 72, now: datetime | None = None) -> PriceEstimate:
    now = now or datetime.now()
    values = _seller_landed_prices(conn, variant_id, condition, fresh_hours, now)
    n = len(values)
    if n == 0:
        return PriceEstimate(variant_id=variant_id, condition=condition, computed_at=now, confidence="low", evidence_sellers=0, evidence_listings=0, is_family_fallback=False)
    values_sorted = sorted(values)
    typical = statistics.median(values_sorted)
    low = _percentile(values_sorted, 0.25)
    high = _percentile(values_sorted, 0.75)
    # floor = second-lowest when enough sellers, else lowest
    floor = values_sorted[1] if n >= 3 else values_sorted[0]
    # quick_sale ~ 10th percentile for used
    quick = _percentile(values_sorted, 0.10) if condition == "used" else None
    if n >= 3:
        conf = "high"
    elif n == 2:
        conf = "medium"
    else:
        conf = "low"
    return PriceEstimate(variant_id=variant_id, condition=condition, computed_at=now,
                         market_floor=floor, typical_price=typical, low=low, high=high, quick_sale=quick,
                         confidence=conf, evidence_sellers=n, evidence_listings=n, is_family_fallback=False)

def estimate_family(conn: sqlite3.Connection, family_id: str, condition: str = "new",
                    fresh_hours: int = 72, now: datetime | None = None) -> FamilyPriceRange:
    now = now or datetime.now()
    # collect seller landed prices across all variants in family
    since = (now - timedelta(hours=fresh_hours)).isoformat()
    rows = conn.execute(
        """
        SELECT l.seller, o.price, o.shipping, l.variant_id
          FROM price_observations o
          JOIN source_listings l ON l.id = o.listing_id
         WHERE l.family_id = ? AND l.condition_bucket = ? AND l.active = 1
           AND o.observed_at >= ? AND o.availability = "available"
         ORDER BY o.observed_at DESC
        """, (family_id, condition, since)).fetchall()
    latest: dict[str, float] = {}
    variants: set[str] = set()
    for seller, price, shipping, vid in rows:
        if seller in latest:
            continue
        landed = float(price) + (float(shipping) if shipping is not None else 0.0)
        latest[seller] = landed
        if vid:
            variants.add(vid)
    values = sorted(latest.values())
    n = len(values)
    if n == 0:
        return FamilyPriceRange(family_id=family_id, condition=condition, computed_at=now, confidence="low", variants_count=len(variants), evidence_sellers=0)
    typical = statistics.median(values)
    low = _percentile(values, 0.25)
    high = _percentile(values, 0.75)
    floor = values[1] if n >= 3 else values[0]
    conf = "high" if n >= 4 else ("medium" if n >= 2 else "low")
    return FamilyPriceRange(family_id=family_id, condition=condition, computed_at=now,
                            low=low, high=high, typical=typical, floor=floor,
                            variants_count=len(variants) or 1, evidence_sellers=n, confidence=conf)

def value_score(resale_price: float, buy_price: float, shipping_buy: float = 0, commission: float = 0.12, shipping_sell: float = 25) -> tuple[float, float]:
    """Return (margin_pln, roi)."""
    landed_buy = buy_price + shipping_buy
    net_sell = resale_price * (1 - commission) - shipping_sell
    margin = net_sell - landed_buy
    roi = margin / landed_buy if landed_buy else 0.0
    return margin, roi
