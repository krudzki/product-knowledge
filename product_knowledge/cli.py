import argparse, sqlite3, json
from product_knowledge.storage import init_db
from product_knowledge.seed import seed
from product_knowledge.ingest import ingest
from product_knowledge.query import price_for_observation
from product_knowledge.priority import priority_for_variant, PriorityInput

def main():
    ap = argparse.ArgumentParser(prog="product-knowledge")
    sub = ap.add_subparsers(dest="cmd")
    p1 = sub.add_parser("seed")
    p1.add_argument("--db", default="product_knowledge.db")
    p2 = sub.add_parser("ingest")
    p2.add_argument("--products-db", default="/home/krzysztof/dane/products.db")
    p2.add_argument("--db", default="product_knowledge.db")
    p2.add_argument("--limit", type=int, default=1000)
    p3 = sub.add_parser("query")
    p3.add_argument("--db", default="product_knowledge.db")
    p3.add_argument("--gtin", default="")
    p3.add_argument("--mpn", default="")
    p3.add_argument("--brand", default="")
    p3.add_argument("--family", default="")
    p3.add_argument("--condition", default="new")
    p4 = sub.add_parser("priority")
    p4.add_argument("--db", default="product_knowledge.db")
    p4.add_argument("--variant", required=True)
    p4.add_argument("--family", default="")
    p4.add_argument("--buy-price", type=float, required=True)
    args = ap.parse_args()

    if args.cmd == "seed":
        conn = sqlite3.connect(args.db)
        init_db(conn)
        seed(conn)
        print(f"seeded {args.db}")
    elif args.cmd == "ingest":
        res = ingest(args.products_db, args.db, limit=args.limit)
        print(json.dumps(res, ensure_ascii=False))
    elif args.cmd == "query":
        conn = sqlite3.connect(args.db)
        init_db(conn)
        ans = price_for_observation(conn, gtin=args.gtin, mpn=args.mpn, brand=args.brand, family_id=args.family, condition=args.condition)
        print(json.dumps(ans.__dict__, ensure_ascii=False, default=str))
    elif args.cmd == "priority":
        conn = sqlite3.connect(args.db)
        init_db(conn)
        res = priority_for_variant(conn, PriorityInput(variant_id=args.variant, family_id=args.family, buy_price=args.buy_price))
        print(json.dumps(res, ensure_ascii=False))
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
