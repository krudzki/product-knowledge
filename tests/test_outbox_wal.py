"""The knowledge outbox drain must open the store in WAL.

`~/dane/product-knowledge.db` is 12 GB and was still in
`journal_mode=delete` on 2026-09-16. `drain()` is the main write path for
price observations and opened the file with a bare
`sqlite3.connect(pk_db)`: no `busy_timeout`, no journal mode. The one
place that does set WAL (`VerificationStore`) opens a different file,
which is why the fleet looked converted and was not.

In `delete` mode a commit takes EXCLUSIVE over the whole file. Measured
with a live write probe: 10 of 162 attempts blocked (6.2%) with four
concurrent python writers, and a read-only query from outside the fleet
took over 15 minutes to start.

`journal_mode` is a property of the FILE, so this converts the database
once and every later connection inherits WAL.
"""

from __future__ import annotations

import sqlite3

from product_knowledge import outbox


def test_drain_opens_the_store_in_wal(tmp_path):
    """A drain must leave the knowledge DB in WAL, not delete."""
    pk_db = tmp_path / "knowledge.db"
    outbox_path = tmp_path / "outbox.jsonl"
    # A real record: an EMPTY outbox returns before opening the database at
    # all, so an empty-file version of this test would pass vacuously.
    outbox.append(outbox_path, source="test", seller="test",
                  url="https://example.com/p/1", title="Probe", price=10.0)

    outbox.drain(outbox_path, pk_db=pk_db)

    con = sqlite3.connect(pk_db, timeout=5)
    try:
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        con.close()
    assert mode.lower() == "wal", (
        "knowledge store left in journal_mode=%s; in delete mode every "
        "commit locks the whole 12 GB file and readers are shut out" % mode)


def test_drain_succeeds_while_a_reader_holds_a_transaction(tmp_path):
    """A held read transaction must not block the drain.

    Production shape: the fleet queries this store continuously while
    scanners emit observations into it.

    Proved red by reverting `drain` to a bare `sqlite3.connect`.
    """
    pk_db = tmp_path / "knowledge.db"
    outbox_path = tmp_path / "outbox.jsonl"
    outbox.append(outbox_path, source="test", seller="test",
                  url="https://example.com/p/1", title="Probe", price=10.0)
    # First drain creates the schema and converts the file.
    outbox.drain(outbox_path, pk_db=pk_db)

    reader = sqlite3.connect(pk_db, timeout=5)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM sqlite_master").fetchone()
    try:
        outbox.append(outbox_path, source="test", seller="test",
                      url="https://example.com/p/2", title="Probe 2",
                      price=20.0)
        result = outbox.drain(outbox_path, pk_db=pk_db)
        assert result["drained"] >= 1
    finally:
        reader.rollback()
        reader.close()
