"""WAL on the verification queue: a writer must not block readers.

### Why this exists
`_RetryingConnection` and `busy_timeout=30000` both turn a lock into a wait;
neither shortens the lock. This module's own comment already names the reason:
in `delete` journal mode a committing writer holds EXCLUSIVE over the whole
file, so even a plain SELECT waits.

Measured on the minipc after products.db went WAL on 2026-09-05 21:21 UTC:
fleet-wide `database is locked` fell 1227 -> 5 over the following 8.5 hours,
and **all five survivors** were `verification_queue_failed` from this store -
02:46:08, 02:46:41, 02:47:15, 02:47:51 and 03:17:42 UTC. products.db was
converted; product-verification.sqlite3 (80 MB, shared disk, ~60 timers) was
not, because VerificationStore opens sqlite3.connect directly instead of going
through the shared helper.

The property under test is therefore not the pragma but the contention: a
writer must commit while a reader holds a transaction open.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import time

from product_knowledge.verification import VerificationCandidate, VerificationStore

# Holds a READ transaction. In delete mode the SHARED lock blocks a writer's
# COMMIT (which needs EXCLUSIVE); in WAL both proceed.
HOLD_READ = """
import sqlite3, sys, time
c = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=30)
c.execute("BEGIN")
c.execute("SELECT count(*) FROM verification_candidates").fetchone()
print("holding", flush=True)
time.sleep(float(sys.argv[2]))
c.execute("COMMIT")
"""


def _start_reader(path, seconds):
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLD_READ, str(path), str(seconds)],
        stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "holding"
    return proc


def test_store_enables_wal(tmp_path):
    db = tmp_path / "v.sqlite3"
    with VerificationStore(db) as store:
        mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_wal_sticks_to_the_file(tmp_path):
    """journal_mode is a property of the FILE - it must survive reopening."""
    db = tmp_path / "v.sqlite3"
    with VerificationStore(db):
        pass
    plain = sqlite3.connect(db)
    try:
        assert plain.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        plain.close()


def test_writer_commits_while_a_reader_holds_a_transaction(tmp_path):
    """The five surviving lock errors, reproduced as a property.

    Goes through `enqueue` rather than a hand-written INSERT, so the test
    exercises the path the scanners actually use.
    """
    db = tmp_path / "v.sqlite3"
    with VerificationStore(db):
        pass  # create the schema

    candidate = VerificationCandidate(
        source="scanner", store="s", title="RTX 4090 graphics card",
        url="https://example.test/p/1", current_price=4000.0,
        category_slug="electronics:components", priority="P1",
        reason="missing_reference", external_key="k1",
    )

    reader = _start_reader(db, 5)
    try:
        with VerificationStore(db) as store:
            started = time.monotonic()
            store.enqueue(candidate)
            elapsed = time.monotonic() - started
        assert elapsed < 1.0, (
            "writer waited %.2fs for a reader - still serialised" % elapsed)
    finally:
        reader.wait(timeout=30)
