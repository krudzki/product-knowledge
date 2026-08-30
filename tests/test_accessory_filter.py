"""Tests for the low-value accessory intake filter.

Cheap accessories were 27% of the live pending queue and can never produce an
alert worth the AI budget they consume. The filter must be aggressive about junk
while never touching a potential price error on a real product.
"""

from __future__ import annotations

import pytest

from product_knowledge.verification import (
    VerificationCandidate,
    VerificationStore,
    is_low_value_accessory,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCT_VERIFICATION_DB", str(tmp_path / "verify.sqlite3"))
    monkeypatch.setenv("PRODUCT_KNOWLEDGE_DB", "/nonexistent/knowledge.db")
    with VerificationStore() as verification:
        yield verification


@pytest.mark.parametrize("title,price", [
    ("Etui Anbernic do konsoli RG556", 36.0),
    ("Kabel sieciowy Hama 200670 5m Bezowy", 35.0),
    ("Folia ochronna Bizon matowa do iPhone", 40.0),
    ("Wtyk antenowy TechniSat 0000/3360", 2.0),
    ("Figurka Good Loot Call of Duty", 40.0),
    ("Filtr do okapu Bosch DHZ5275", 99.0),
])
def test_cheap_accessories_are_refused(title, price):
    assert is_low_value_accessory(title, price) is True


@pytest.mark.parametrize("title,price", [
    # Real products whose descriptions contain accessory words -- a substring
    # match caught these, which is why matching is anchored to the title start.
    ("Sluchawki bezprzewodowe z mikrofonem Logitech", 300.0),
    ("Pad Sony DualSense do PS5 Bezprzewodowy", 300.0),
    ("Sluchawki przewodowe z mikrofonem Razer Kraken", 299.0),
    # Expensive items that happen to be accessories by type.
    ("Uchwyt Vogels TVM 7675 Automatyczny od 40 do 77", 3799.0),
    ("Folia grzewcza MISSION AIR ZESTAW IR SILVER", 2822.0),
])
def test_real_or_expensive_items_are_kept(title, price):
    assert is_low_value_accessory(title, price) is False


def test_a_cheap_real_product_is_never_filtered():
    """The whole point of the queue: a 4000 PLN item listed at 20 PLN."""
    assert is_low_value_accessory("Lodowka Samsung RM90F67CECEO", 20.0) is False
    assert is_low_value_accessory("Laptop ASUS ROG Zephyrus", 15.0) is False


def test_enqueue_refuses_a_cheap_accessory(store):
    key = store.enqueue(VerificationCandidate(
        source="scanner", store="rtv-euro-agd", title="Etui Bizon do iPhone",
        url="https://euro.pl/etui.bhtml", current_price=45.0))

    assert key == ""
    assert store.pending(10) == []


def test_enqueue_accepts_a_cheap_real_product(store):
    key = store.enqueue(VerificationCandidate(
        source="scanner", store="rtv-euro-agd", title="Lodowka Samsung RM90F",
        url="https://euro.pl/lodowka.bhtml", current_price=20.0))

    assert key != ""
    assert [row["title"] for row in store.pending(10)] == ["Lodowka Samsung RM90F"]


def test_zero_price_is_not_treated_as_an_accessory():
    """A zero price is a parsing problem, not a cheap accessory."""
    assert is_low_value_accessory("Etui cokolwiek", 0.0) is False
