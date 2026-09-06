"""Deadline-first pre-notification queue and exactly-once delivery claims.

The fast lane exists because RAM sells within minutes: a SuperTech DDR4/DDR5
deal that cannot be corroborated deterministically must reach a verdict inside
90 seconds or go out explicitly labelled unverified. Two independent workers
(the AI-verified path and the timeout path) race for that single delivery, so
the claim has to be atomic rather than merely checked.
"""
from __future__ import annotations

import sqlite3

import pytest

from product_knowledge.verification import VerificationCandidate, VerificationStore


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "verification.sqlite3"
    monkeypatch.setenv("PRODUCT_VERIFICATION_DB", str(path))
    # The pending ranking attaches the knowledge DB when it exists; keep the
    # fast lane isolated from whatever the developer machine happens to hold.
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", str(tmp_path / "knowledge-absent.db"))
    return path


@pytest.fixture()
def store(db_path):
    store = VerificationStore(db_path)
    yield store
    store.close()


def candidate(key: str, *, reason: str = "pre_notification", store_name: str = "supertech",
              price: float = 723.99) -> VerificationCandidate:
    return VerificationCandidate(
        source="supertech",
        store=store_name,
        title=f"Pamiec DDR4 {key}",
        url=f"https://supertech.pl/{key}",
        current_price=price,
        reference_price=1221.0,
        category_slug="components:ram",
        priority="P1",
        mpn=key,
        reason=reason,
        external_key=key,
    )


def set_pending_since(store: VerificationStore, key: str, when: str) -> None:
    store.conn.execute(
        "UPDATE verification_candidates SET pending_since_at=? WHERE candidate_key=?",
        (when, key),
    )
    store.conn.commit()


# --- deadline-first selection -------------------------------------------------

def test_pre_notifications_come_back_oldest_deadline_first(store):
    """Whoever has least time left is served first, regardless of price.

    The general queue ranks by suspected mispricing depth. Here the only thing
    that matters is the 90-second clock, so a cheaper older candidate must
    outrank an expensive one that just arrived.
    """
    store.enqueue(candidate("newer", price=5000.0))
    store.enqueue(candidate("oldest", price=100.0))
    set_pending_since(store, "newer", "2026-09-06T10:00:30+00:00")
    set_pending_since(store, "oldest", "2026-09-06T10:00:00+00:00")

    rows = store.pending_pre_notifications(store="supertech", limit=5)

    assert [row["candidate_key"] for row in rows] == ["oldest", "newer"]


def test_the_fast_lane_ignores_the_general_backlog(store):
    """A shared queue would let 3,000 ordinary candidates starve the clock."""
    store.enqueue(candidate("fast"))
    store.enqueue(candidate("ordinary", reason="missing_reference"))
    store.enqueue(candidate("audit", reason="notification_audit"))
    store.enqueue(candidate("other-shop", store_name="proshop"))

    rows = store.pending_pre_notifications(store="supertech", limit=10)

    assert [row["candidate_key"] for row in rows] == ["fast"]


def test_a_decided_candidate_leaves_the_fast_lane(store):
    """Once estimated the row belongs to the audit trail, not the clock."""
    store.enqueue(candidate("done"))
    store.save_estimate(
        "done", low=1200.0, high=1400.0, confidence="high", identified=True,
        pricing_error_likelihood="high",
    )

    assert store.pending_pre_notifications(store="supertech", limit=10) == []


# --- exactly-once delivery ----------------------------------------------------

def test_only_one_worker_can_claim_a_delivery(db_path):
    """The verified path and the timeout path race for the same alert.

    Both may legitimately decide to send at nearly the same instant, from
    separate connections. Exactly one must win, or the user gets the same RAM
    deal twice -- once verified and once labelled unverified.
    """
    first = VerificationStore(db_path)
    second = VerificationStore(db_path)
    try:
        first.enqueue(candidate("contested"))

        results = [
            first.claim_delivery("contested", "verified"),
            second.claim_delivery("contested", "timeout"),
        ]

        assert results.count(True) == 1
        assert results.count(False) == 1
    finally:
        first.close()
        second.close()


def test_the_winning_claim_is_recorded_with_its_kind(store):
    store.enqueue(candidate("claimed"))

    assert store.claim_delivery("claimed", "timeout") is True

    row = store.export_candidate("claimed")
    assert row["delivery_kind"] == "timeout"
    assert row["delivery_claimed_at"]


def test_releasing_a_claim_lets_the_same_path_retry(store):
    """A failed send must not burn the alert; the transport can be retried."""
    store.enqueue(candidate("retry"))
    store.claim_delivery("retry", "verified")

    assert store.release_delivery_claim("retry", "verified") is True
    assert store.claim_delivery("retry", "verified") is True


def test_a_foreign_owner_cannot_release_someone_elses_claim(store):
    """Otherwise the loser of the race could free the winner's alert to double-send."""
    store.enqueue(candidate("owned"))
    store.claim_delivery("owned", "verified")

    assert store.release_delivery_claim("owned", "timeout") is False
    assert store.claim_delivery("owned", "timeout") is False


def test_an_unchanged_re_enqueue_keeps_the_claim(store):
    """Re-seeing the same offer is not a new deal and must not re-alert."""
    store.enqueue(candidate("stable"))
    store.claim_delivery("stable", "verified")

    store.enqueue(candidate("stable"))

    assert store.claim_delivery("stable", "verified") is False


def test_a_changed_price_is_a_new_deal_and_clears_the_claim(store):
    """A genuinely new price deserves a fresh verdict and a fresh alert.

    Both claim fields must be released together. Leaving a stale
    `delivery_kind` behind would make the audit trail describe the previous
    alert's route while the row is genuinely unclaimed.
    """
    store.enqueue(candidate("moving", price=723.99))
    store.claim_delivery("moving", "verified")

    store.enqueue(candidate("moving", price=499.0))

    released = store.export_candidate("moving")
    assert released["delivery_claimed_at"] is None
    assert released["delivery_kind"] is None
    assert store.claim_delivery("moving", "timeout") is True


def test_claiming_an_unknown_candidate_is_refused(store):
    assert store.claim_delivery("ghost", "verified") is False


# --- migration ----------------------------------------------------------------

def test_a_pre_claim_database_is_migrated_in_place(tmp_path, monkeypatch):
    """Production already holds candidates; the upgrade cannot start empty."""
    path = tmp_path / "legacy.sqlite3"
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", str(tmp_path / "absent.db"))
    legacy = VerificationStore(path)
    legacy.enqueue(candidate("legacy"))
    legacy.conn.execute("ALTER TABLE verification_candidates DROP COLUMN delivery_claimed_at")
    legacy.conn.execute("ALTER TABLE verification_candidates DROP COLUMN delivery_kind")
    legacy.conn.commit()
    legacy.close()

    upgraded = VerificationStore(path)
    try:
        assert upgraded.claim_delivery("legacy", "verified") is True
        assert upgraded.export_candidate("legacy")["delivery_kind"] == "verified"
    finally:
        upgraded.close()
