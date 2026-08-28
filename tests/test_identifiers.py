import sqlite3
from product_knowledge.identifiers import normalize_gtin, normalize_mpn, normalize_code
from product_knowledge.storage import init_db
from product_knowledge.catalog import upsert_family, upsert_variant, add_identifier
from product_knowledge.matching import narrow_lookup

def test_gtin_valid():
    assert normalize_gtin("5901234123457") == "5901234123457"

def test_gtin_invalid_length():
    assert normalize_gtin("123") is None

def test_mpn_normalized():
    assert normalize_mpn(" rrt-00010 ") == "RRT-00010"

def test_narrow_gtin_hit():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    upsert_family(conn, "fam-x", "Xbox X", "electronics:gaming", "Microsoft")
    upsert_variant(conn, "var-x", "fam-x", "Xbox X 1TB", "electronics:gaming", {"storage_gb": 1024})
    add_identifier(conn, "var-x", "gtin", "5901234123457", "5901234123457")
    hit = narrow_lookup(conn, gtin="5901234123457")
    assert hit and hit.variant_id == "var-x" and hit.kind == "exact_variant"

def test_narrow_mpn_hit():
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    upsert_family(conn, "fam-x", "Xbox X", "electronics:gaming", "Microsoft")
    upsert_variant(conn, "var-x", "fam-x", "Xbox X 1TB", "electronics:gaming", {"storage_gb": 1024})
    add_identifier(conn, "var-x", "mpn", "RRT-00010", "RRT-00010")
    hit = narrow_lookup(conn, mpn="rrt-00010", brand="Microsoft")
    assert hit and hit.variant_id == "var-x"

def test_code_length_guard():
    assert len(normalize_code("AB")) == 2
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    upsert_family(conn, "fam-x", "Xbox", "electronics:gaming", "Microsoft")
    upsert_variant(conn, "var-x", "fam-x", "Xbox", "electronics:gaming", {})
    add_identifier(conn, "var-x", "mpn", "RRT-00010", "RRT00010")
    hit = narrow_lookup(conn, catalog_code="AB")
    assert hit is None
