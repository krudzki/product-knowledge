"""Regression: ready schema skips DDL/backfill instead of taking write locks."""

from __future__ import annotations

from unittest import mock

from product_knowledge import verification
from product_knowledge.verification import VerificationStore


def test_init_skips_writes_when_schema_ready(tmp_path):
    path = tmp_path / "v.sqlite3"
    first = VerificationStore(path)
    first.close()
    with mock.patch.object(
        verification._RetryingConnection,
        "executescript",
        side_effect=AssertionError("DDL must not run on a ready schema"),
    ):
        second = VerificationStore(path)
    try:
        assert second._schema_ready()
    finally:
        second.close()


def test_init_builds_schema_on_empty_db(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    assert not path.exists()
    store = VerificationStore(path)
    try:
        import sqlite3

        probe = sqlite3.connect(path)
        try:
            names = {
                row[0]
                for row in probe.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','index','trigger')"
                )
            }
        finally:
            probe.close()
        assert {
            "verification_candidates",
            "notification_deliveries",
            "idx_verification_pending",
            "idx_delivery_candidate",
            "idx_verification_pending_fresh",
            "trg_verification_pending_since_insert",
        } <= names
    finally:
        store.close()
