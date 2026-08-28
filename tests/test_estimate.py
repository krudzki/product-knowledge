import sqlite3
from datetime import datetime, timedelta
from product_knowledge.storage import init_db
from product_knowledge.catalog import upsert_family, upsert_variant, upsert_listing, add_observation
from product_knowledge.estimate import estimate_variant, estimate_family

def test_estimate_narrow_and_family():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    upsert_family(conn, "fam-x", "Xbox Series X", "electronics:gaming", "Microsoft")
    upsert_variant(conn, "var-disc", "fam-x", "Xbox 1TB disc", "electronics:gaming", {"storage_gb": 1024, "optical_drive": True})
    upsert_variant(conn, "var-digital", "fam-x", "Xbox 1TB digital", "electronics:gaming", {"storage_gb": 1024, "optical_drive": False})
    now = datetime.now()
    # 3 sellers for disc variant
    for seller, price in [("a", 1800), ("b", 1900), ("c", 2100)]:
        lid = f"ceneo:{seller}:var-disc"
        upsert_listing(conn, lid, "ceneo", seller, f"https://ceneo.pl/{seller}", "Xbox disc", family_id="fam-x", variant_id="var-disc")
        add_observation(conn, lid, price, observed_at=now)
    # 1 seller for digital
    upsert_listing(conn, "ceneo:d:var-digital", "ceneo", "d", "https://ceneo.pl/d", "Xbox digital", family_id="fam-x", variant_id="var-digital")
    add_observation(conn, "ceneo:d:var-digital", 1700, observed_at=now)

    est = estimate_variant(conn, "var-disc", fresh_hours=72, now=now)
    assert est.market_floor == 1900  # second-lowest
    assert est.typical_price == 1900
    assert est.confidence == "high"
    assert est.evidence_sellers == 3

    fam = estimate_family(conn, "fam-x", fresh_hours=72, now=now)
    assert fam.evidence_sellers == 4
    assert fam.low is not None and fam.high is not None
    assert fam.variants_count == 2
