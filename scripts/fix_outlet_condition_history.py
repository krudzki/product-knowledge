"""Correct outlet listings historically recorded as new stock.

`PriceLedger` hard-coded condition="new" for every observation, so outlet rows
that reached the knowledge DB through it were filed as sealed stock. The write
path is fixed (deal-pipeline 7875f8f); this repairs what it already wrote.

Scope is deliberately narrow: only `source_listings` rows whose SOURCE label
says outlet/refurb and whose bucket is not already `used`. Nothing else is
touched, and the source label is the scanner's own declaration — not a guess.

Default is a dry run. Pass --apply to write inside a single transaction.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

PKDB = Path.home() / "dane" / "product-knowledge.db"
SELECT = """
    SELECT id, source, seller, condition_bucket, title
      FROM source_listings
     WHERE (lower(source) LIKE '%outlet%'
            OR lower(source) LIKE '%refurb%'
            OR lower(source) LIKE '%poleasing%')
       AND COALESCE(condition_bucket, '') != 'used'
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the correction (default: dry run)")
    args = parser.parse_args()

    mode = "" if args.apply else "?mode=ro"
    conn = sqlite3.connect(f"file:{PKDB}{mode}", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(SELECT).fetchall()
    print(f"mode: {'APPLY' if args.apply else 'dry-run'}")
    print(f"kandydatow do korekty: {len(rows)}")

    by_source: dict[str, int] = {}
    for row in rows:
        by_source[row["source"]] = by_source.get(row["source"], 0) + 1
    for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {source:24s} {count}")

    print("\nprzyklady:")
    for row in rows[:5]:
        print(f"  [{row['id']}] {row['source']:18s} {(row['title'] or '')[:52]}")

    if not args.apply:
        print("\n(dry run - nic nie zapisano)")
        return 0

    with conn:  # single transaction
        cursor = conn.execute("""
            UPDATE source_listings SET condition_bucket = 'used'
             WHERE (lower(source) LIKE '%outlet%'
                    OR lower(source) LIKE '%refurb%'
                    OR lower(source) LIKE '%poleasing%')
               AND COALESCE(condition_bucket, '') != 'used'
        """)
        changed = cursor.rowcount
    print(f"\nzaktualizowano: {changed}")

    left = conn.execute(SELECT).fetchall()
    print(f"pozostalo zle oznaczonych: {len(left)}")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"integrity_check: {integrity}")
    return 0 if (not left and integrity == "ok") else 1


if __name__ == "__main__":
    sys.exit(main())
