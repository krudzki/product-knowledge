"""Tests for logging refused accessories.

The intake filter is a budget decision, not a claim that these items are
worthless -- so a refusal must leave a durable record that can be mined later
and used to re-tune the threshold against real data.
"""

from __future__ import annotations

import json

import pytest

from product_knowledge.verification import (
    VerificationCandidate,
    VerificationStore,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_VERIFICATION_DB", str(tmp_path / "verify.sqlite3"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", "/nonexistent/knowledge.db")
    monkeypatch.setenv("VERIFICATION_REJECTED_LOG", str(tmp_path / "rejected.jsonl"))
    with VerificationStore() as verification:
        yield verification


def _accessory(price: float = 45.0) -> VerificationCandidate:
    return VerificationCandidate(
        source="scanner", store="rtv-euro-agd", title="Etui Bizon do iPhone",
        url="https://euro.pl/etui.bhtml", current_price=price,
        category_slug="electronics:accessories", gtin="5905562793405",
    )


def test_a_refused_accessory_is_logged(store, tmp_path):
    store.enqueue(_accessory())

    lines = (tmp_path / "rejected.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["title"] == "Etui Bizon do iPhone"
    assert record["current_price"] == 45.0
    assert record["url"] == "https://euro.pl/etui.bhtml"
    assert record["reason"] == "low_value_accessory"
    assert record["gtin"] == "5905562793405"
    assert record["ts"]


def test_an_accepted_item_is_not_logged(store, tmp_path):
    store.enqueue(VerificationCandidate(
        source="scanner", store="rtv-euro-agd", title="Lodowka Samsung RM90F",
        url="https://euro.pl/lodowka.bhtml", current_price=20.0))

    assert not (tmp_path / "rejected.jsonl").exists()


def test_refusals_accumulate_one_line_each(store, tmp_path):
    for index in range(3):
        store.enqueue(VerificationCandidate(
            source="scanner", store="rtv-euro-agd", title=f"Kabel HDMI {index}",
            url=f"https://euro.pl/k{index}.bhtml", current_price=30.0))

    lines = (tmp_path / "rejected.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["title"] for line in lines] == [
        "Kabel HDMI 0", "Kabel HDMI 1", "Kabel HDMI 2"]


def test_an_unwritable_log_never_breaks_intake(store, monkeypatch, tmp_path):
    """Losing the audit trail must not cost a scan cycle."""
    monkeypatch.setenv("VERIFICATION_REJECTED_LOG", "/proc/nonexistent/rejected.jsonl")

    assert store.enqueue(_accessory()) == ""
