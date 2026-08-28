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

    # --- Xbox accessories / additional Xbox variants ---
    dict(kind="variant", id="var-xbox-series-s-512", family="fam-xbox-series-x",
         name="Microsoft Xbox Series S 512GB biały", category="electronics:gaming",
         attrs={"storage_gb": 512, "optical_drive": False, "color": "white", "edition": "series s"}, mpn="RRS-00009"),
    dict(kind="variant", id="var-xbox-controller-black", family="fam-xbox-series-x",
         name="Microsoft Xbox Wireless Controller Carbon Black", category="electronics:gaming",
         attrs={"accessory": "controller", "color": "black"}, mpn="QAT-00002"),
    # --- PS5 additional ---
    dict(kind="variant", id="var-ps5-slim-digital", family="fam-ps5",
         name="Sony PlayStation 5 Slim Digital (CFI-2016 Digital)", category="electronics:gaming",
         attrs={"storage_gb": 1000, "optical_drive": False, "revision": "slim-digital"}, mpn="CFI-2016-DIGITAL"),
    dict(kind="variant", id="var-ps5-dualsense-white", family="fam-ps5",
         name="Sony DualSense Wireless Controller White", category="electronics:gaming",
         attrs={"accessory": "controller", "color": "white"}, mpn="CFI-ZCT1W"),
    # --- RTX 5080 family: more partners/editions ---
    dict(kind="variant", id="var-msi-rtx5080-gaming-x", family="fam-rtx-5080",
         name="MSI GeForce RTX 5080 Gaming X Trio 16GB", category="electronics:components",
         attrs={"chip": "rtx 5080", "vram_gb": 16, "partner": "msi", "edition": "gaming x trio"}, mpn="G5080-16G-GAMING-X-TRIO"),
    dict(kind="variant", id="var-asus-rtx5080-tuf", family="fam-rtx-5080",
         name="ASUS GeForce RTX 5080 TUF Gaming 16GB", category="electronics:components",
         attrs={"chip": "rtx 5080", "vram_gb": 16, "partner": "asus", "edition": "tuf"}, mpn="TUF-RTX5080-16G-GAMING"),
    dict(kind="variant", id="var-gigabyte-rtx5080-aorus", family="fam-rtx-5080",
         name="Gigabyte GeForce RTX 5080 AORUS Master 16GB", category="electronics:components",
         attrs={"chip": "rtx 5080", "vram_gb": 16, "partner": "gigabyte", "edition": "aorus master"}, mpn="GV-N5080AORUS-M-16GD"),
    # RTX 5070 / 5090 siblings (same family for broad range demo)
    dict(kind="family", id="fam-rtx-5070", name="NVIDIA GeForce RTX 5070", category="electronics:components", brand="NVIDIA",
         attrs={"chip": "rtx 5070", "vram_gb": 12}),
    dict(kind="variant", id="var-gainward-rtx5070-phoenix", family="fam-rtx-5070",
         name="Gainward GeForce RTX 5070 Phoenix 12GB", category="electronics:components",
         attrs={"chip": "rtx 5070", "vram_gb": 12, "partner": "gainward", "edition": "phoenix"}, mpn="NE75070T19T9-1042P"),
    dict(kind="family", id="fam-rtx-5090", name="NVIDIA GeForce RTX 5090", category="electronics:components", brand="NVIDIA",
         attrs={"chip": "rtx 5090", "vram_gb": 32}),
    dict(kind="variant", id="var-msi-rtx5090-suprim", family="fam-rtx-5090",
         name="MSI GeForce RTX 5090 Suprim 32GB", category="electronics:components",
         attrs={"chip": "rtx 5090", "vram_gb": 32, "partner": "msi", "edition": "suprim"}, mpn="G5090-32S-SUPRIM"),
    # --- iPhone: more storage/color variants ---
    dict(kind="variant", id="var-iphone16-256-black", family="fam-iphone-16",
         name="Apple iPhone 16 256GB czarny", category="electronics:phones",
         attrs={"storage_gb": 256, "color": "black", "model": "iphone 16"}, mpn="MYE83QN/A"),
    dict(kind="variant", id="var-iphone16-pro-128-black", family="fam-iphone-16",
         name="Apple iPhone 16 Pro 128GB Black Titanium", category="electronics:phones",
         attrs={"storage_gb": 128, "color": "black titanium", "model": "iphone 16 pro"}, mpn="MYND3QN/A"),
    dict(kind="variant", id="var-iphone16-pro-max-512-black", family="fam-iphone-16",
         name="Apple iPhone 16 Pro Max 512GB Black Titanium", category="electronics:phones",
         attrs={"storage_gb": 512, "color": "black titanium", "model": "iphone 16 pro max"}, mpn="MYX33QN/A"),
    dict(kind="variant", id="var-iphone15-128-black", family="fam-iphone-16",
         name="Apple iPhone 15 128GB czarny", category="electronics:phones",
         attrs={"storage_gb": 128, "color": "black", "model": "iphone 15"}, mpn="MTP03QN/A"),
    # Samsung flagships
    dict(kind="family", id="fam-galaxy-s24", name="Samsung Galaxy S24", category="electronics:phones", brand="Samsung",
         attrs={"model": "galaxy s24"}),
    dict(kind="variant", id="var-galaxy-s24-256-black", family="fam-galaxy-s24",
         name="Samsung Galaxy S24 256GB czarny", category="electronics:phones",
         attrs={"storage_gb": 256, "color": "black", "model": "galaxy s24"}, mpn="SM-S921BZKDEUB"),
    dict(kind="variant", id="var-galaxy-s24-ultra-512-black", family="fam-galaxy-s24",
         name="Samsung Galaxy S24 Ultra 512GB czarny", category="electronics:phones",
         attrs={"storage_gb": 512, "color": "black", "model": "galaxy s24 ultra"}, mpn="SM-S928BZKDEUB"),
    dict(kind="variant", id="var-galaxy-s23-256-black", family="fam-galaxy-s24",
         name="Samsung Galaxy S23 256GB czarny", category="electronics:phones",
         attrs={"storage_gb": 256, "color": "black", "model": "galaxy s23"}, mpn="SM-S911BZKDEUB"),
    # --- MacBook ---
    dict(kind="family", id="fam-macbook-air-m3", name="Apple MacBook Air M3", category="electronics:computers", brand="Apple",
         attrs={"line": "macbook air", "chip": "m3"}),
    dict(kind="variant", id="var-macbook-air-m3-13-256", family="fam-macbook-air-m3",
         name="Apple MacBook Air 13 M3 256GB gwiezdna szarość", category="electronics:computers",
         attrs={"display_inch": 13, "chip": "m3", "ram_gb": 8, "storage_gb": 256}, mpn="MRXN3ZE/A"),
    dict(kind="variant", id="var-macbook-air-m3-15-512", family="fam-macbook-air-m3",
         name="Apple MacBook Air 15 M3 512GB gwiezdna szarość", category="electronics:computers",
         attrs={"display_inch": 15, "chip": "m3", "ram_gb": 8, "storage_gb": 512}, mpn="MRYU3ZE/A"),
    dict(kind="variant", id="var-macbook-pro-m3-14-512", family="fam-macbook-air-m3",
         name="Apple MacBook Pro 14 M3 512GB gwiezdna szarość", category="electronics:computers",
         attrs={"display_inch": 14, "chip": "m3", "ram_gb": 8, "storage_gb": 512}, mpn="MRX33ZE/A"),
    # --- Laptops: more Legion variants for similar-spec demo ---
    dict(kind="variant", id="var-legion-pro-7-5070-32-1tb", family="fam-legion-pro-7",
         name="Lenovo Legion Pro 7 RTX 5070 32GB 1TB", category="electronics:computers",
         attrs={"cpu": "ryzen 9 9955hx3d", "ram_gb": 32, "gpu": "rtx 5070", "storage_gb": 1000, "display_inch": 16}),
    dict(kind="variant", id="var-legion-pro-7-5080-32-512", family="fam-legion-pro-7",
         name="Lenovo Legion Pro 7 RTX 5080 32GB 512GB", category="electronics:computers",
         attrs={"cpu": "ryzen 9 9955hx3d", "ram_gb": 32, "gpu": "rtx 5080", "storage_gb": 512, "display_inch": 16}),
    dict(kind="variant", id="var-legion-5-4060-16-512", family="fam-legion-pro-7",
         name="Lenovo Legion 5 RTX 4060 16GB 512GB", category="electronics:computers",
         attrs={"cpu": "ryzen 7 7840hs", "ram_gb": 16, "gpu": "rtx 4060", "storage_gb": 512, "display_inch": 16}),
    # --- Nintendo Switch ---
    dict(kind="family", id="fam-switch", name="Nintendo Switch", category="electronics:gaming", brand="Nintendo",
         attrs={"platform": "switch"}),
    dict(kind="variant", id="var-switch-oled-white", family="fam-switch",
         name="Nintendo Switch OLED biały", category="electronics:gaming",
         attrs={"revision": "oled", "color": "white"}, mpn="HEG-001"),
    dict(kind="variant", id="var-switch-oled-neon", family="fam-switch",
         name="Nintendo Switch OLED neon", category="electronics:gaming",
         attrs={"revision": "oled", "color": "neon"}, mpn="HEG-001-NEON"),
    dict(kind="variant", id="var-switch-lite-yellow", family="fam-switch",
         name="Nintendo Switch Lite żółty", category="electronics:gaming",
         attrs={"revision": "lite", "color": "yellow"}, mpn="HDH-001"),
    # --- iPad / Watch / AirPods ---
    dict(kind="family", id="fam-ipad-air-m2", name="Apple iPad Air M2", category="electronics:tablets", brand="Apple",
         attrs={"line": "ipad air", "chip": "m2"}),
    dict(kind="variant", id="var-ipad-air-m2-11-128", family="fam-ipad-air-m2",
         name="Apple iPad Air 11 M2 128GB WiFi gwiezdna szarość", category="electronics:tablets",
         attrs={"display_inch": 11, "storage_gb": 128, "connectivity": "wifi"}, mpn="MUWD3ZE/A"),
    dict(kind="variant", id="var-ipad-pro-m4-11-256", family="fam-ipad-air-m2",
         name="Apple iPad Pro 11 M4 256GB WiFi gwiezdna szarość", category="electronics:tablets",
         attrs={"display_inch": 11, "storage_gb": 256, "connectivity": "wifi"}, mpn="MVVC3ZE/A"),
    dict(kind="family", id="fam-apple-watch", name="Apple Watch", category="electronics:wearables", brand="Apple",
         attrs={"line": "apple watch"}),
    dict(kind="variant", id="var-watch-series10-45-gps", family="fam-apple-watch",
         name="Apple Watch Series 10 45mm GPS północ", category="electronics:wearables",
         attrs={"size_mm": 45, "connectivity": "gps"}, mpn="MWWE3ZE/A"),
    dict(kind="variant", id="var-watch-ultra2-black", family="fam-apple-watch",
         name="Apple Watch Ultra 2 49mm tytan czarny", category="electronics:wearables",
         attrs={"size_mm": 49, "connectivity": "gps+cellular"}, mpn="MRE93ZE/A"),
    dict(kind="family", id="fam-airpods", name="Apple AirPods", category="electronics:audio-portable", brand="Apple",
         attrs={"line": "airpods"}),
    dict(kind="variant", id="var-airpods-pro-2", family="fam-airpods",
         name="Apple AirPods Pro 2 generacji", category="electronics:audio-portable",
         attrs={"generation": 2, "anc": True}, mpn="MTJV3ZE/A"),
    dict(kind="variant", id="var-airpods-4", family="fam-airpods",
         name="Apple AirPods 4", category="electronics:audio-portable",
         attrs={"generation": 4, "anc": False}, mpn="MXP63ZE/A"),
    # --- Pixel ---
    dict(kind="family", id="fam-pixel", name="Google Pixel", category="electronics:phones", brand="Google",
         attrs={"line": "pixel"}),
    dict(kind="variant", id="var-pixel-8-128-black", family="fam-pixel",
         name="Google Pixel 8 128GB czarny", category="electronics:phones",
         attrs={"storage_gb": 128, "color": "black", "model": "pixel 8"}, mpn="GA04851-GB"),
    dict(kind="variant", id="var-pixel-8-pro-256-black", family="fam-pixel",
         name="Google Pixel 8 Pro 256GB czarny", category="electronics:phones",
         attrs={"storage_gb": 256, "color": "black", "model": "pixel 8 pro"}, mpn="GA04890-GB"),
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
