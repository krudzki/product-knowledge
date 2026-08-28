import sqlite3
from product_knowledge.storage import init_db
from product_knowledge.catalog import upsert_family, upsert_variant
from product_knowledge.matching import resolve, similar_spec_search

def test_family_fallback_and_similar_spec():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    upsert_family(conn, "fam-legion", "Lenovo Legion Pro 7", "electronics:computers", "Lenovo", {"line": "legion pro 7"})
    upsert_variant(conn, "var-a", "fam-legion", "Legion RTX 5080 32GB 1TB", "electronics:computers",
                   {"cpu": "ryzen 9 9955hx3d", "ram_gb": 32, "gpu": "rtx 5080", "storage_gb": 1000})
    upsert_variant(conn, "var-b", "fam-legion", "Legion RTX 5080 64GB 2TB", "electronics:computers",
                   {"cpu": "ryzen 9 9955hx3d", "ram_gb": 64, "gpu": "rtx 5080", "storage_gb": 2000})
    # similar-spec should find the closer RAM variant
    sims = similar_spec_search(conn, "fam-legion", {"cpu": "ryzen 9 9955hx3d", "ram_gb": 32, "gpu": "rtx 5080", "storage_gb": 1000})
    assert sims and sims[0].variant_id == "var-a"
    # unknown spec still falls back to family
    r = resolve(conn, family_id="fam-legion", attrs={"cpu": "intel i7", "ram_gb": 16})
    assert r.kind in ("family", "similar_spec")

def test_xbox_family_vs_exact():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    upsert_family(conn, "fam-xbox", "Microsoft Xbox Series X", "electronics:gaming", "Microsoft")
    upsert_variant(conn, "var-disc", "fam-xbox", "Xbox 1TB disc", "electronics:gaming", {"storage_gb": 1024, "optical_drive": True})
    upsert_variant(conn, "var-digital", "fam-xbox", "Xbox 1TB digital", "electronics:gaming", {"storage_gb": 1024, "optical_drive": False})
    r = resolve(conn, family_id="fam-xbox", attrs={"storage_gb": 1024, "optical_drive": True})
    assert r.kind in ("family", "similar_spec")
