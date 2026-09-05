"""Regression: VerificationStore survives transient SQLite locks.

Overnight the fleet's concurrent writers hold EXCLUSIVE on the shared disk,
so even a reader's `_init_schema` can hit `database is locked`. The store
must wait it out instead of killing the whole scan cycle.
"""

from __future__ import annotations

import sqlite3

import pytest

from product_knowledge import verification
from product_knowledge.verification import VerificationStore


def test_retry_waits_out_transient_locks():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert verification._retry_locked(flaky) == "ok"
    assert calls["n"] == 3


def test_genuine_db_errors_still_raise_immediately():
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise sqlite3.OperationalError("no such table: missing")

    with pytest.raises(sqlite3.OperationalError):
        verification._retry_locked(broken)
    assert calls["n"] == 1


def test_store_statements_use_the_retrying_connection(tmp_path):
    store = VerificationStore(tmp_path / "v.sqlite3")
    try:
        assert isinstance(store.conn, verification._RetryingConnection)
    finally:
        store.close()
