"""A triage refusal must stick - and must not outlive the price it judged.

pending() ranks by price drop and returns the same head every run, so a
consumer that refuses a row has nowhere to record it: measured 2026-09-19, 464
of 600 rows served had already been refused, and the queue re-served them
forever while fresh candidates starved behind them.

Marking fixes that, but a mark must not become a permanent blindfold. The
enqueue contract already says a changed price is a new deal; these tests pin
both halves.
"""

from __future__ import annotations

import pytest

from product_knowledge.verification import VerificationCandidate, VerificationStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_VERIFICATION_DB", str(tmp_path / "verify.sqlite3"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", "/nonexistent/knowledge.db")
    monkeypatch.setenv("VERIFICATION_REJECTED_LOG", str(tmp_path / "rejected.jsonl"))
    with VerificationStore() as verification:
        yield verification


def _candidate(price: float = 899.0, title: str = "Tablet HUION Kamvas 16") -> VerificationCandidate:
    """A product expensive enough to pass the intake accessory gate."""
    return VerificationCandidate(
        source="scanner", store="rtv-euro-agd", title=title,
        url="https://euro.pl/tablet.bhtml", current_price=price,
        category_slug="electronics:tablets", gtin="5905562793999",
    )


def test_a_marked_row_leaves_the_queue(store):
    key = store.enqueue(_candidate())
    assert [row["candidate_key"] for row in store.pending(10)] == [key]

    assert store.mark_skipped(key, reason="accessory") is True

    assert store.pending(10) == []
    assert store.counts().get("skipped") == 1


def test_marking_is_idempotent_and_reports_real_work(store):
    key = store.enqueue(_candidate())
    assert store.mark_skipped(key) is True
    # Second call changes nothing and says so, so callers can count honestly.
    assert store.mark_skipped(key) is False
    assert store.mark_skipped("no-such-key") is False


def test_a_new_price_overrides_an_old_refusal(store):
    """A refusal judges a price, not a product - re-listing revives the row."""
    key = store.enqueue(_candidate(price=899.0))
    store.mark_skipped(key)
    assert store.pending(10) == []

    store.enqueue(_candidate(price=39.0))  # same item, crashed price

    assert [row["candidate_key"] for row in store.pending(10)] == [key]
    assert store.counts().get("pending") == 1


def test_re_seeing_the_same_price_does_not_revive(store):
    """Otherwise every scan cycle would undo the refusal it just recorded."""
    key = store.enqueue(_candidate(price=899.0))
    store.mark_skipped(key)

    store.enqueue(_candidate(price=899.0))

    assert store.pending(10) == []
    assert store.counts().get("skipped") == 1


def test_batch_marking_counts_only_rows_it_changed(store):
    # Distinct GTINs: the candidate key is derived from the identifier, so
    # varying only the title would collapse these into a single row.
    keys = [
        store.enqueue(
            VerificationCandidate(
                source="scanner", store="rtv-euro-agd", title=f"Tablet HUION {index}",
                url=f"https://euro.pl/t{index}.bhtml", current_price=500.0 + index,
                category_slug="electronics:tablets", gtin=f"590556279399{index}",
            )
        )
        for index in range(3)
    ]
    assert len(set(keys)) == 3
    store.mark_skipped(keys[0])

    changed = store.mark_skipped_many(keys + ["", "missing"], reason="accessory")

    assert changed == 2  # the already-marked one is not counted twice
    assert store.pending(10) == []


def test_an_estimated_row_is_never_downgraded(store):
    """An estimate is a result; a refusal must not overwrite it."""
    key = store.enqueue(_candidate())
    store.save_estimate(
        key, low=800.0, high=1000.0, confidence="high", identified=True,
        pricing_error_likelihood="low", rationale="market price",
    )

    assert store.mark_skipped(key) is False
    assert store.counts().get("estimated") == 1
