"""Seed Tier A families/variants + identifiers.

Run: python -m product_knowledge.seed --db /tmp/pk.db
Idempotent — upserts by id.
"""

from __future__ import annotations

import argparse
import sqlite3

from product_knowledge.catalog import add_identifier, upsert_family, upsert_variant
from product_knowledge.storage import init_db

SEED = [
    # Xbox Series X family
    dict(kind="family", id="fam-xbox-series-x", name="Microsoft Xbox Series X", category="electronics:gaming", brand="Microsoft",
         attrs={"platform": "xbox", "generation": "series x"}),
    dict(kind="variant", id="var-xbox-series-x-1tb-disc", family="fam-xbox-series-x",
         name="Microsoft Xbox Series X 1TB z napędem (disc) czarny", category="electronics:gaming",
         attrs={"storage_gb": 1024, "optical_drive": True, "color": "black", "edition": "standard"}, mpn="RRT-00010", gtin="196313117207"),
    dict(kind="variant", id="var-xbox-series-x-1tb-digital", family="fam-xbox-series-x",
         name="Microsoft Xbox Series X Digital 1TB biały (bez napędu)", category="electronics:gaming",
         attrs={"storage_gb": 1024, "optical_drive": False, "color": "white", "edition": "digital"}, mpn="EP2-00702"),
    # PlayStation 5 family
    dict(kind="family", id="fam-ps5", name="Sony PlayStation 5", category="electronics:gaming", brand="Sony",
         attrs={"platform": "playstation", "generation": "5"}),
    dict(kind="variant", id="var-ps5-slim-disc", family="fam-ps5",
         name="Sony PlayStation 5 Slim z napędem (CFI-2016)", category="electronics:gaming",
         attrs={"storage_gb": 1000, "optical_drive": True, "revision": "slim"}, mpn="CFI-2016"),
    dict(kind="variant", id="var-ps5-pro", family="fam-ps5",
         name="Sony PlayStation 5 Pro (CFI-7121)", category="electronics:gaming",
         attrs={"storage_gb": 2000, "optical_drive": False, "revision": "pro"}, mpn="CFI-7121"),
    # RTX 5080 family (Gainward example)
    dict(kind="family", id="fam-rtx-5080", name="NVIDIA GeForce RTX 5080", category="electronics:components", brand="NVIDIA",
         attrs={"chip": "rtx 5080", "vram_gb": 16}),
    dict(kind="variant", id="var-gainward-rtx5080-phantom", family="fam-rtx-5080",
         name="Gainward GeForce RTX 5080 Phantom 16GB", category="electronics:components",
         attrs={"chip": "rtx 5080", "vram_gb": 16, "partner": "gainward", "edition": "phantom"}, mpn="NE64080T19T9-1040P"),
    dict(kind="variant", id="var-gainward-rtx5080-phoenix", family="fam-rtx-5080",
         name="Gainward GeForce RTX 5080 Phoenix 16GB", category="electronics:components",
         attrs={"chip": "rtx 5080", "vram_gb": 16, "partner": "gainward", "edition": "phoenix"}, mpn="NE64080T19T9-1042P"),
    # Apple iPhone 16 family
    dict(kind="family", id="fam-iphone-16", name="Apple iPhone 16", category="electronics:phones", brand="Apple",
         attrs={"model": "iphone 16"}),
    dict(kind="variant", id="var-iphone16-128-black", family="fam-iphone-16",
         name="Apple iPhone 16 128GB czarny", category="electronics:phones",
         attrs={"storage_gb": 128, "color": "black"}, mpn="MYE73QN/A"),
    dict(kind="variant", id="var-iphone16-pro-max-256-desert", family="fam-iphone-16",
         name="Apple iPhone 16 Pro Max 256GB Desert Titanium", category="electronics:phones",
         attrs={"storage_gb": 256, "color": "desert titanium", "model": "iphone 16 pro max"}, mpn="MYWX3"),
    # Laptop family — similar-spec demo
    dict(kind="family", id="fam-legion-pro-7", name="Lenovo Legion Pro 7", category="electronics:computers", brand="Lenovo",
         attrs={"line": "legion pro 7", "display_inch": 16}),
    dict(kind="variant", id="var-legion-pro-7-5080-32-1tb", family="fam-legion-pro-7",
         name="Lenovo Legion Pro 7 RTX 5080 32GB 1TB", category="electronics:computers",
         attrs={"cpu": "ryzen 9 9955hx3d", "ram_gb": 32, "gpu": "rtx 5080", "storage_gb": 1000, "display_inch": 16}),
    dict(kind="variant", id="var-legion-pro-7-5080-64-2tb", family="fam-legion-pro-7",
         name="Lenovo Legion Pro 7 RTX 5080 64GB 2TB", category="electronics:computers",
         attrs={"cpu": "ryzen 9 9955hx3d", "ram_gb": 64, "gpu": "rtx 5080", "storage_gb": 2000, "display_inch": 16}),
]

def seed(conn: sqlite3.Connection) -> None:
    for item in SEED:
        if item["kind"] == "family":
            upsert_family(conn, item["id"], item["name"], item["category"], item.get("brand",""), item.get("attrs"))
        else:
            upsert_variant(conn, item["id"], item["family"], item["name"], item["category"], item.get("attrs"))
            if item.get("mpn"):
                from product_knowledge.identifiers import normalize_mpn
                add_identifier(conn, item["id"], "mpn", item["mpn"], normalize_mpn(item["mpn"]))
            if item.get("gtin"):
                from product_knowledge.identifiers import normalize_gtin
                g = normalize_gtin(item["gtin"])
                if g:
                    add_identifier(conn, item["id"], "gtin", item["gtin"], g)
            # also store manufacturer_code alias
            if item.get("mpn"):
                from product_knowledge.identifiers import normalize_code
                add_identifier(conn, item["id"], "manufacturer_code", item["mpn"], normalize_code(item["mpn"]))
    conn.commit()

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="product_knowledge.db")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    init_db(conn)
    seed(conn)
    print(f"seeded {len(SEED)} records into {args.db}")

if __name__ == "__main__":
    main()
