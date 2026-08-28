"""Canonical product-knowledge contracts.

Narrow = exact variant.  Broad = family / similar-spec range.
Scanners query narrow first; broad is a labelled fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class IdentifierScheme(str, Enum):
    GTIN = "gtin"
    EAN = "ean"
    UPC = "upc"
    MPN = "mpn"
    ASIN = "asin"
    ALLEGRO_PRODUCT = "allegro_product"
    CENEO_PRODUCT = "ceneo_product"
    MANUFACTURER_CODE = "manufacturer_code"
    STORE_SKU = "store_sku"
    OTHER = "other"

class ConditionBucket(str, Enum):
    NEW = "new"
    USED = "used"

class MatchBasis(str, Enum):
    EXACT_GTIN = "exact_gtin"
    BRAND_MPN = "brand_mpn"
    VERIFIED_ASIN = "verified_asin"
    VERIFIED_CATALOG = "verified_catalog"
    LITERAL_CODE = "literal_code"
    ATTRIBUTE = "attribute"
    NAME = "name"
    AI_SUGGESTION = "ai_suggestion"

@dataclass(frozen=True)
class ProductFamily:
    id: str
    canonical_name: str
    category_slug: str
    brand: str = ""
    attributes: dict = field(default_factory=dict)

@dataclass(frozen=True)
class ProductVariant:
    id: str
    family_id: str
    canonical_name: str
    category_slug: str
    attributes: dict = field(default_factory=dict)
    kind: str = "single"  # single | bundle

@dataclass(frozen=True)
class ProductIdentifier:
    variant_id: str
    scheme: str
    raw: str
    normalized: str
    scope: str = "global"

@dataclass(frozen=True)
class SourceListing:
    id: str
    source: str
    seller: str
    url: str
    title: str
    family_id: str = ""
    variant_id: str = ""
    condition_bucket: str = ConditionBucket.NEW.value
    condition_grade: str = ""
    is_bundle: bool = False

@dataclass(frozen=True)
class PriceObservation:
    listing_id: str
    observed_at: datetime
    price: float
    currency: str = "PLN"
    shipping: float | None = None
    availability: str = "available"
    source_payload_hash: str = ""

@dataclass(frozen=True)
class PriceEstimate:
    """Narrow exact-variant estimate (versioned)."""
    variant_id: str
    condition: str
    computed_at: datetime
    market_floor: float | None = None
    typical_price: float | None = None
    low: float | None = None
    high: float | None = None
    quick_sale: float | None = None
    confidence: str = "low"  # high | medium | low
    evidence_sellers: int = 0
    evidence_listings: int = 0
    method_version: str = "v1"
    is_family_fallback: bool = False

@dataclass(frozen=True)
class FamilyPriceRange:
    """Broad family / similar-spec range (labelled fallback)."""
    family_id: str
    condition: str
    computed_at: datetime
    low: float | None = None
    high: float | None = None
    typical: float | None = None
    floor: float | None = None
    variants_count: int = 0
    evidence_sellers: int = 0
    confidence: str = "low"
    method_version: str = "v1"

@dataclass(frozen=True)
class ValueScore:
    """Value / resale prior that drives scan priority."""
    variant_id: str
    resale_margin_pln: float
    roi: float
    liquidity: float
    price_volatility: float
    priority_score: float
    computed_at: datetime = field(default_factory=datetime.now)
