import sqlite3, tempfile, pathlib
from product_knowledge.storage import init_db
from product_knowledge.seed import seed
from product_knowledge.ingest import ingest

def test_ingest_maps_code_keys(tmp_path=None):
    # use in-memory products.db stub
    import sqlite3 as s3
    products_db = "/tmp/test_products_pk.db"
    import os as _os
    try:
        _os.remove(products_db)
    except FileNotFoundError:
        pass
    conn = s3.connect(products_db)
    conn.execute("CREATE TABLE ceny_biezace (klucz TEXT, nazwa TEXT, sprzedawca TEXT, zrodlo TEXT, cena REAL, url TEXT, ostatnio_widziana TEXT)")
    conn.execute("INSERT INTO ceny_biezace VALUES (?,?,?,?,?,?,?)",
                 ("code:RRT-00010", "Microsoft Xbox Series X 1TB czarny (RRT-00010)", "morele", "morele-katalog", 1899.0, "https://morele.net/xbox", "2026-08-28T10:00:00"))
    conn.execute("INSERT INTO ceny_biezace VALUES (?,?,?,?,?,?,?)",
                 ("name:microsoft xbox series x", "Xbox Series X bundle", "allegro", "allegro", 2100.0, "https://allegro.pl/xbox", "2026-08-28T10:00:00"))
    conn.commit()
    conn.close()

    pk_db = "/tmp/test_pk.db"
    import os
    try:
        os.remove(pk_db)
    except FileNotFoundError:
        pass
    c2 = s3.connect(pk_db)
    init_db(c2)
    seed(c2)
    c2.close()

    res = ingest(products_db, pk_db, limit=10)
    assert res["ingested"] == 2
    c3 = s3.connect(pk_db)
    rows = c3.execute("SELECT variant_id, family_id FROM source_listings").fetchall()
    # first listing should have resolved to the seeded RRT-00010 variant
    assert any(r[0] == "var-xbox-series-x-1tb-disc" for r in rows)
    c3.close()
