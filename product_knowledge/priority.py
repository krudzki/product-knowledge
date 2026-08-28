"""Resale priority scoring — value estimate drives scan priority.

Priority is derived from computed price estimates, not from a static
category rank.  Category P1/P2/P3 remains a bootstrap until a variant
has estimates; once estimates exist, the value score wins.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from product_knowledge.estimate import estimate_variant, estimate_family, value_score

@dataclass(frozen=True)
class PriorityInput:
    variant_id: str
    family_id: str
    buy_price: float
    shipping_buy: float = 0.0
    commission: float = 0.12
    shipping_sell: float = 25.0

def _liquidity_score(sellers: int, listings: int) -> float:
    # 0..1, saturated at 8 sellers
    return min(1.0, (sellers * 0.12 + listings * 0.04))

def _volatility_score(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return min(1.0, math.sqrt(var) / mean)

def _seller_prices(conn: sqlite3.Connection, variant_id: str, hours: int = 72) -> list[float]:
    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        """SELECT l.seller, o.price, o.shipping FROM price_observations o
           JOIN source_listings l ON l.id=o.listing_id
           WHERE l.variant_id=? AND o.observed_at>=? ORDER BY o.observed_at DESC""",
        (variant_id, since),
    ).fetchall()
    latest: dict[str,float] = {}
    for seller, price, shipping in rows:
        if seller in latest:
            continue
        latest[seller] = float(price) + (float(shipping) if shipping else 0)
    return list(latest.values())

def priority_for_variant(conn: sqlite3.Connection, inp: PriorityInput) -> dict:
    est = estimate_variant(conn, inp.variant_id, fresh_hours=72)
    # fallback to family when narrow is thin
    if est.evidence_sellers < 2 and inp.family_id:
        fam = estimate_family(conn, inp.family_id, fresh_hours=72)
        # use family typical as resale reference with lower confidence
        resale_ref = fam.typical or est.typical_price or 0
        sellers = fam.evidence_sellers
        variants = fam.variants_count
        is_fallback = True
        typical = fam.typical
        floor = fam.floor
        conf = fam.confidence
    else:
        resale_ref = est.typical_price or 0
        sellers = est.evidence_sellers
        variants = 1
        is_fallback = est.is_family_fallback
        typical = est.typical_price
        floor = est.market_floor
        conf = est.confidence

    margin, roi = value_score(resale_ref or 0, inp.buy_price, inp.shipping_buy, inp.commission, inp.shipping_sell)
    prices = _seller_prices(conn, inp.variant_id)
    liq = _liquidity_score(sellers, len(prices))
    vol = _volatility_score(prices)

    # priority_score: margin-driven, dampened by volatility, boosted by liquidity
    # keep in 0..100
    raw = 0.0
    if resale_ref and inp.buy_price:
        # margin is primary, roi secondary
        raw = margin * 0.7 + (roi * inp.buy_price) * 0.3
        raw = raw * (0.6 + 0.4 * liq) * (1 - 0.3 * vol)
    # confidence penalty
    if conf == "low":
        raw *= 0.5
    elif conf == "medium":
        raw *= 0.8
    priority = max(0.0, min(100.0, raw / 10.0))

    return {
        "variant_id": inp.variant_id,
        "family_id": inp.family_id,
        "resale_reference": resale_ref,
        "typical": typical,
        "floor": floor,
        "buy_price": inp.buy_price,
        "margin_pln": round(margin, 2),
        "roi": round(roi, 4),
        "liquidity": round(liq, 3),
        "volatility": round(vol, 3),
        "confidence": conf,
        "is_family_fallback": is_fallback,
        "evidence_sellers": sellers,
        "variants_in_family": variants,
        "priority_score": round(priority, 2),
    }
