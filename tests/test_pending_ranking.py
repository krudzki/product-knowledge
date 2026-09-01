"""Tests for mispricing-first ordering in the verification queue.

The queue exists to catch price errors (a 4000 PLN item listed at 20 PLN). The
previous ordering was current_price DESC, which surfaced expensive products --
the opposite of the goal. These tests pin the new ranking and, just as
importantly, that it degrades safely when no history exists yet: on the live
queue 82% of pending rows still have a single observation.
"""

from __future__ import annotations

import sqlite3

import pytest

from product_knowledge.verification import (
    VerificationCandidate,
    VerificationStore,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_VERIFICATION_DB", str(tmp_path / "verify.sqlite3"))
    with VerificationStore() as verification:
        yield verification


def _candidate(key: str, price: float, priority: str = "P3") -> VerificationCandidate:
    return VerificationCandidate(
        source="scanner", store="rtv-euro-agd", title=f"Item {key}",
        url=f"https://euro.pl/{key}.bhtml", current_price=price,
        priority=priority, external_key=key,
    )


def _knowledge_db(path, rows) -> str:
    """Build a minimal knowledge DB: (url, [prices])."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE source_listings (
            id TEXT PRIMARY KEY, source TEXT, seller TEXT, url TEXT,
            title TEXT, first_seen TEXT, last_seen TEXT, active INTEGER);
        CREATE TABLE price_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id TEXT,
            observed_at TEXT, price REAL);
    """)
    for index, (url, prices) in enumerate(rows):
        listing = f"L{index}"
        conn.execute(
            "INSERT INTO source_listings VALUES (?,?,?,?,?,?,?,1)",
            (listing, "euro-outlet", "rtv-euro-agd", url, "t", "x", "x"))
        for price in prices:
            conn.execute(
                "INSERT INTO price_observations (listing_id, observed_at, price)"
                " VALUES (?,?,?)", (listing, "2026-08-30T00:00:00", price))
    conn.commit()
    conn.close()
    return str(path)


def test_a_steep_drop_outranks_a_more_expensive_item(store, tmp_path, monkeypatch):
    store.enqueue(_candidate("cheap-drop", 20.0))
    store.enqueue(_candidate("expensive", 4000.0, priority="P1"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", _knowledge_db(
        tmp_path / "k.db",
        [("https://euro.pl/cheap-drop.bhtml", [4000.0, 3900.0])]))

    order = [row["candidate_key"] for row in store.pending(10)]

    assert order[0] == "cheap-drop", "a 4000 -> 20 PLN drop must be estimated first"
    assert "expensive" in order


def test_items_without_history_still_appear(store, tmp_path, monkeypatch):
    """82% of the live queue has a single observation; it must not vanish."""
    store.enqueue(_candidate("no-history", 500.0))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", _knowledge_db(tmp_path / "k.db", []))

    assert [r["candidate_key"] for r in store.pending(10)] == ["no-history"]


def test_a_single_observation_is_not_a_drop(store, tmp_path, monkeypatch):
    """One observation is just today's backfill, not evidence of a fall."""
    store.enqueue(_candidate("one-obs", 20.0))
    store.enqueue(_candidate("richer", 900.0, priority="P1"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", _knowledge_db(
        tmp_path / "k.db", [("https://euro.pl/one-obs.bhtml", [4000.0])]))

    assert [r["candidate_key"] for r in store.pending(10)][0] == "richer"


def test_a_shallow_drop_is_not_promoted(store, tmp_path, monkeypatch):
    """A normal sale is not a price error; ratio must clear MISPRICE_RATIO."""
    store.enqueue(_candidate("mild", 90.0))
    store.enqueue(_candidate("richer", 900.0, priority="P1"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", _knowledge_db(
        tmp_path / "k.db", [("https://euro.pl/mild.bhtml", [100.0, 99.0])]))

    assert [r["candidate_key"] for r in store.pending(10)][0] == "richer"


def test_missing_knowledge_db_falls_back_instead_of_failing(store, monkeypatch):
    """A triage run must not die because the shared DB is absent."""
    store.enqueue(_candidate("a", 10.0))
    store.enqueue(_candidate("b", 999.0, priority="P1"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", "/nonexistent/knowledge.db")

    assert [r["candidate_key"] for r in store.pending(10)] == ["b", "a"]


def test_limit_is_respected_with_ranked_and_plain_rows(store, tmp_path, monkeypatch):
    for index in range(5):
        store.enqueue(_candidate(f"k{index}", 100.0 + index))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", _knowledge_db(
        tmp_path / "k.db", [("https://euro.pl/k0.bhtml", [4000.0, 3900.0])]))

    rows = store.pending(3)
    keys = [row["candidate_key"] for row in rows]
    assert len(rows) == 3 and len(set(keys)) == 3
    assert keys[0] == "k0"


def test_fresh_p1_outranks_old_expensive_p1_without_history(store, monkeypatch):
    store.enqueue(_candidate("old-expensive", 4000.0, priority="P1"))
    store.enqueue(_candidate("fresh", 100.0, priority="P1"))
    store.conn.execute(
        "UPDATE verification_candidates SET pending_since_at=? WHERE candidate_key=?",
        ("2026-09-01T06:00:00+00:00", "old-expensive"),
    )
    store.conn.execute(
        "UPDATE verification_candidates SET pending_since_at=? WHERE candidate_key=?",
        ("2026-09-01T08:00:00+00:00", "fresh"),
    )
    store.conn.commit()
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", "/nonexistent/knowledge.db")

    assert [row["candidate_key"] for row in store.pending(2)] == [
        "fresh", "old-expensive",
    ]


def test_only_a_price_change_refreshes_pending_since(store):
    candidate = _candidate("changed", 100.0, priority="P1")
    store.enqueue(candidate)
    store.save_estimate(
        candidate.key, low=200.0, high=250.0, confidence="high",
        identified=True,
    )
    old = "2026-09-01T06:00:00+00:00"
    store.conn.execute(
        "UPDATE verification_candidates SET pending_since_at=? WHERE candidate_key=?",
        (old, candidate.key),
    )
    store.conn.commit()

    store.enqueue(candidate)
    unchanged = store.export_candidate(candidate.key)
    assert unchanged is not None
    assert unchanged["status"] == "estimated"
    assert unchanged["pending_since_at"] == old

    store.enqueue(_candidate("changed", 90.0, priority="P1"))
    changed = store.export_candidate(candidate.key)
    assert changed is not None
    assert changed["status"] == "pending"
    assert changed["pending_since_at"] != old
