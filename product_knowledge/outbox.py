
"""Durable outbox for scanner observations.

Scanners never block on product-knowledge DB availability.  They append
a JSONL line to a local outbox file; a periodic consumer drains it into
the canonical SQLite/Postgres store.

File: ~/dane/product-knowledge-outbox.jsonl  (one JSON object per line)
Consumer: python -m product_knowledge.outbox --drain
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import time
from datetime import datetime

DEFAULT_OUTBOX = pathlib.Path.home() / "dane/product-knowledge-outbox.jsonl"

def append(outbox: pathlib.Path | str = DEFAULT_OUTBOX, *, source: str, seller: str, url: str, title: str,
           price: float, currency: str = "PLN", shipping: float | None = None,
           gtin: str = "", mpn: str = "", asin: str = "", family_id: str = "", variant_id: str = "",
           condition: str = "new", availability: str = "available") -> None:
    outbox = pathlib.Path(outbox)
    outbox.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now().isoformat(),
        "source": source, "seller": seller, "url": url, "title": title,
        "price": price, "currency": currency, "shipping": shipping,
        "gtin": gtin, "mpn": mpn, "asin": asin, "family_id": family_id, "variant_id": variant_id,
        "condition": condition, "availability": availability,
    }
    with open(outbox, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def drain(outbox: pathlib.Path | str = DEFAULT_OUTBOX, pk_db: str | pathlib.Path = "") -> dict:
    outbox = pathlib.Path(outbox)
    if not outbox.exists():
        return {"drained": 0, "kept": 0}
    lines = outbox.read_text(encoding="utf-8").splitlines()
    if not lines:
        return {"drained": 0, "kept": 0}
    # lazy import to avoid hard dep
    from product_knowledge.catalog import upsert_listing, add_observation
    from product_knowledge.storage import init_db
    from product_knowledge.matching import narrow_lookup

    pk_db = str(pk_db) or str(pathlib.Path.home() / "dane/product-knowledge.db")
    conn = sqlite3.connect(pk_db)
    init_db(conn)
    drained = 0
    kept: list[str] = []
    for line in lines:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        # try to resolve variant if not already set
        vid = rec.get("variant_id") or ""
        fid = rec.get("family_id") or ""
        if not vid:
            hit = narrow_lookup(conn, gtin=rec.get("gtin",""), mpn=rec.get("mpn",""), brand=rec.get("seller",""), asin=rec.get("asin",""))
            if hit and hit.variant_id:
                vid, fid = hit.variant_id, hit.family_id
        lid = f"{rec.get('source','')}:{rec.get('seller','')}:{rec.get('url','')}"
        upsert_listing(conn, lid, rec.get("source",""), rec.get("seller",""), rec.get("url",""), rec.get("title",""), family_id=fid, variant_id=vid, condition_bucket=rec.get("condition","new"))
        try:
            when = datetime.fromisoformat(rec.get("ts",""))
        except Exception:
            when = datetime.now()
        add_observation(conn, lid, float(rec.get("price",0)), currency=rec.get("currency","PLN"), shipping=rec.get("shipping"), availability=rec.get("availability","available"), observed_at=when)
        drained += 1
    conn.commit()
    # truncate outbox after successful drain
    outbox.write_text("", encoding="utf-8")
    return {"drained": drained, "kept": len(kept)}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--outbox", default=str(DEFAULT_OUTBOX))
    ap.add_argument("--db", default=str(pathlib.Path.home() / "dane/product-knowledge.db"))
    ap.add_argument("--drain", action="store_true", help="drain outbox into DB")
    ap.add_argument("--show", action="store_true", help="show pending count")
    args = ap.parse_args()
    if args.show:
        p = pathlib.Path(args.outbox)
        n = len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0
        print(f"pending={n} path={args.outbox}")
    elif args.drain:
        print(json.dumps(drain(args.outbox, args.db)))
    else:
        ap.print_help()
