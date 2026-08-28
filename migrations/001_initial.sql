-- PostgreSQL initial schema — product-knowledge v1
-- SQLite dev mirror is in product_knowledge/storage.py (DDL constant).

CREATE TABLE IF NOT EXISTS product_families (
    id              TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    category_slug   TEXT NOT NULL,
    brand           TEXT NOT NULL DEFAULT "",
    attributes_json JSONB NOT NULL DEFAULT "{}"::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS product_variants (
    id              TEXT PRIMARY KEY,
    family_id       TEXT NOT NULL REFERENCES product_families(id),
    canonical_name  TEXT NOT NULL,
    category_slug   TEXT NOT NULL,
    attributes_json JSONB NOT NULL DEFAULT "{}"::jsonb,
    kind            TEXT NOT NULL DEFAULT "single",
    fingerprint     TEXT NOT NULL DEFAULT "",
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_variants_family ON product_variants(family_id);

CREATE TABLE IF NOT EXISTS product_identifiers (
    variant_id  TEXT NOT NULL REFERENCES product_variants(id),
    scheme      TEXT NOT NULL,
    raw         TEXT NOT NULL,
    normalized  TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT "global",
    verified    BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (variant_id, scheme, normalized)
);
CREATE INDEX IF NOT EXISTS idx_identifiers_normalized ON product_identifiers(scheme, normalized);

CREATE TABLE IF NOT EXISTS source_listings (
    id               TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    seller           TEXT NOT NULL,
    url              TEXT NOT NULL,
    title            TEXT NOT NULL,
    family_id        TEXT NOT NULL DEFAULT "",
    variant_id       TEXT NOT NULL DEFAULT "",
    condition_bucket TEXT NOT NULL DEFAULT "new",
    condition_grade  TEXT NOT NULL DEFAULT "",
    is_bundle        BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT now(),
    active           BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_listings_variant ON source_listings(variant_id, active);
CREATE INDEX IF NOT EXISTS idx_listings_family ON source_listings(family_id, active);

CREATE TABLE IF NOT EXISTS price_observations (
    id              BIGSERIAL PRIMARY KEY,
    listing_id      TEXT NOT NULL REFERENCES source_listings(id),
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    price           DOUBLE PRECISION NOT NULL,
    currency        TEXT NOT NULL DEFAULT "PLN",
    shipping        DOUBLE PRECISION,
    availability    TEXT NOT NULL DEFAULT "available",
    payload_hash    TEXT NOT NULL DEFAULT ""
);
CREATE INDEX IF NOT EXISTS idx_obs_listing_time ON price_observations(listing_id, observed_at DESC);
-- Partition by month in production when volume grows:
-- CREATE TABLE price_observations_y2026m08 PARTITION OF price_observations FOR VALUES FROM ("2026-08-01") TO ("2026-09-01");

CREATE TABLE IF NOT EXISTS match_decisions (
    id               BIGSERIAL PRIMARY KEY,
    listing_id       TEXT NOT NULL,
    variant_id       TEXT NOT NULL,
    decision         TEXT NOT NULL,
    basis            TEXT NOT NULL,
    score            DOUBLE PRECISION NOT NULL DEFAULT 0,
    resolver_version TEXT NOT NULL DEFAULT "v1",
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS price_estimates (
    variant_id          TEXT NOT NULL,
    condition_bucket    TEXT NOT NULL,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_floor        DOUBLE PRECISION,
    typical_price       DOUBLE PRECISION,
    low                 DOUBLE PRECISION,
    high                DOUBLE PRECISION,
    quick_sale          DOUBLE PRECISION,
    confidence          TEXT NOT NULL,
    evidence_sellers    INTEGER NOT NULL DEFAULT 0,
    evidence_listings   INTEGER NOT NULL DEFAULT 0,
    is_family_fallback  BOOLEAN NOT NULL DEFAULT FALSE,
    method_version      TEXT NOT NULL DEFAULT "v1",
    PRIMARY KEY (variant_id, condition_bucket)
);

CREATE TABLE IF NOT EXISTS family_price_ranges (
    family_id        TEXT NOT NULL,
    condition_bucket TEXT NOT NULL,
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    low              DOUBLE PRECISION,
    high             DOUBLE PRECISION,
    typical          DOUBLE PRECISION,
    floor            DOUBLE PRECISION,
    variants_count   INTEGER NOT NULL DEFAULT 0,
    evidence_sellers INTEGER NOT NULL DEFAULT 0,
    confidence       TEXT NOT NULL,
    method_version   TEXT NOT NULL DEFAULT "v1",
    PRIMARY KEY (family_id, condition_bucket)
);

CREATE TABLE IF NOT EXISTS value_scores (
    variant_id        TEXT PRIMARY KEY,
    resale_margin_pln DOUBLE PRECISION NOT NULL,
    roi               DOUBLE PRECISION NOT NULL,
    liquidity         DOUBLE PRECISION NOT NULL,
    price_volatility  DOUBLE PRECISION NOT NULL,
    priority_score    DOUBLE PRECISION NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
