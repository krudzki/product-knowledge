from __future__ import annotations

from product_knowledge.verification import VerificationCandidate, VerificationStore


def candidate(**overrides) -> VerificationCandidate:
    data = {
        "source": "scanner",
        "store": "example",
        "title": "Example Laptop 16 GB",
        "url": "https://example.test/p/1",
        "current_price": 999.0,
        "category_slug": "electronics:computers",
        "priority": "P1",
    }
    data.update(overrides)
    return VerificationCandidate(**data)


def test_queue_is_idempotent_and_reopens_when_price_changes(tmp_path):
    db = VerificationStore(tmp_path / "verification.sqlite3")
    key = db.enqueue(candidate())
    db.save_estimate(
        key,
        low=2000,
        high=2400,
        confidence="high",
        identified=True,
        pricing_error_likelihood="high",
    )

    db.enqueue(candidate())
    row = db.export_candidate(key)
    assert row is not None
    assert row["status"] == "estimated"
    assert row["seen_count"] == 2

    db.enqueue(candidate(current_price=899.0))
    row = db.export_candidate(key)
    assert row is not None
    assert row["status"] == "pending"
    assert row["seen_count"] == 3


def test_pending_orders_priority_then_value(tmp_path):
    db = VerificationStore(tmp_path / "verification.sqlite3")
    p3 = db.enqueue(candidate(url="https://example.test/p3", priority="P3", current_price=9000))
    p1_low = db.enqueue(candidate(url="https://example.test/p1-low", priority="P1", current_price=1000))
    p1_high = db.enqueue(candidate(url="https://example.test/p1-high", priority="P1", current_price=2000))

    assert [row["candidate_key"] for row in db.pending()] == [p1_high, p1_low, p3]


def test_invalid_enums_fall_back_safely(tmp_path):
    db = VerificationStore(tmp_path / "verification.sqlite3")
    key = db.enqueue(candidate(priority="urgent"))
    db.save_estimate(
        key,
        low=None,
        high=None,
        confidence="certain",
        identified=False,
        pricing_error_likelihood="yes",
    )

    row = db.export_candidate(key)
    assert row is not None
    assert row["priority"] == "P3"
    assert row["estimate_confidence"] == "unknown"
    assert row["pricing_error_likelihood"] == "unknown"


def test_delivery_audit_keeps_success_and_failure(tmp_path):
    db = VerificationStore(tmp_path / "verification.sqlite3")
    key = db.enqueue(candidate())
    db.record_delivery(key, channel="electronics", delivered=False, error="timeout")
    db.record_delivery(key, channel="electronics", delivered=True, message_id="123")

    history = db.delivery_history(key)
    assert len(history) == 2
    assert history[0]["delivered"] == 1
    assert history[0]["message_id"] == "123"
    assert history[1]["delivered"] == 0
    assert history[1]["error"] == "timeout"
