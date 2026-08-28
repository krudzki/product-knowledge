# product-knowledge

Canonical product knowledge base for the scanner fleet.

## Purpose

Collect observations once, estimate value once, reuse everywhere.
Scanners remain simple producers; this package owns identity and pricing.

## Two matching layers

- **Narrow (exact variant):** GTIN/EAN, brand+MPN, verified ASIN/Ceneo/Allegro mapping, literal catalog code. Precision-first. False merge is a blocker.
- **Broad (family / similar-spec range):** same family with compatible specs — e.g. laptops with similar CPU/RAM/GPU/storage, Xbox Series X family range (disc vs digital, 1TB). Labelled fallback with wide requests, never presented as the narrow value.

Query order: narrow -> similar-spec -> family. See product_knowledge/query.py:price_for_observation.

## Modules

- storage.py — SQLite dev mirror of PostgreSQL DDL
- migrations/001_initial.sql — PostgreSQL schema (source of truth)
- catalog.py — families/variants/identifiers/listings/observations
- identifiers.py — GTIN/EAN/MPN/ASIN normalization
- matching.py — narrow_lookup / resolve
- estimate.py — estimate_variant (exact) and estimate_family (range)
- query.py — price_for_observation (narrow-first API for scanners)
- priority.py — priority_for_variant (value score drives scan priority)
- ingest.py — import from ceny_biezace / historia_cen (migrates products.db)
- seed.py — Tier A seed (Xbox, PS5, RTX 5080, iPhone 16, Legion Pro 7)
