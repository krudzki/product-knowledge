"""Durable, store-neutral queue for secondary product verification.

Observed market prices remain authoritative.  Records in this queue describe
items that need another look because a reference price is missing or because a
high-value notification should be audited.  AI estimates are stored as labelled
secondary evidence and never become price observations.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterable

DEFAULT_DB = pathlib.Path.home() / "dane/product-verification.sqlite3"
_PRIORITIES = {"P1": 1, "P2": 2, "P3": 3}


@dataclass(frozen=True)
class VerificationCandidate:
    source: str
    store: str
    title: str
    url: str
    current_price: float
    reference_price: float | None = None
    category_slug: str = "other:unclassified"
    priority: str = "P3"
    gtin: str = ""
    mpn: str = ""
    asin: str = ""
    brand: str = ""
    image_url: str = ""
    reason: str = "missing_reference"
    external_key: str = ""

    @property
    def key(self) -> str:
        if self.external_key:
            return self.external_key
        identity = self.url or "|".join((self.store, self.title, self.mpn, self.gtin, self.asin))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


class VerificationStore:
    """SQLite-backed candidate queue and notification-delivery audit."""

    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        configured = os.environ.get("PRODUCT_VERIFICATION_DB", "")
        self.path = pathlib.Path(path or configured or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> VerificationStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS verification_candidates (
                candidate_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                store TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                current_price REAL NOT NULL,
                reference_price REAL,
                category_slug TEXT NOT NULL,
                priority TEXT NOT NULL,
                gtin TEXT NOT NULL DEFAULT '',
                mpn TEXT NOT NULL DEFAULT '',
                asin TEXT NOT NULL DEFAULT '',
                brand TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                estimate_low REAL,
                estimate_high REAL,
                estimate_confidence TEXT NOT NULL DEFAULT 'unknown',
                identified INTEGER NOT NULL DEFAULT 0,
                pricing_error_likelihood TEXT NOT NULL DEFAULT 'unknown',
                estimate_rationale TEXT NOT NULL DEFAULT '',
                estimated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_verification_pending
                ON verification_candidates(status, priority, last_seen_at);
            CREATE TABLE IF NOT EXISTS notification_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_key TEXT NOT NULL,
                channel TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                delivered INTEGER NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(candidate_key) REFERENCES verification_candidates(candidate_key)
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_candidate
                ON notification_deliveries(candidate_key, attempted_at DESC);
            """
        )
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def enqueue(self, candidate: VerificationCandidate) -> str:
        priority = candidate.priority.upper()
        if priority not in _PRIORITIES:
            priority = "P3"
        now = self._now()
        row = asdict(candidate)
        row.update(candidate_key=candidate.key, priority=priority, now=now)
        self.conn.execute(
            """
            INSERT INTO verification_candidates (
                candidate_key, source, store, title, url, current_price,
                reference_price, category_slug, priority, gtin, mpn, asin,
                brand, image_url, reason, first_seen_at, last_seen_at
            ) VALUES (
                :candidate_key, :source, :store, :title, :url, :current_price,
                :reference_price, :category_slug, :priority, :gtin, :mpn, :asin,
                :brand, :image_url, :reason, :now, :now
            )
            ON CONFLICT(candidate_key) DO UPDATE SET
                source=excluded.source,
                store=excluded.store,
                title=excluded.title,
                url=excluded.url,
                current_price=excluded.current_price,
                reference_price=excluded.reference_price,
                category_slug=excluded.category_slug,
                priority=excluded.priority,
                gtin=excluded.gtin,
                mpn=excluded.mpn,
                asin=excluded.asin,
                brand=excluded.brand,
                image_url=excluded.image_url,
                reason=excluded.reason,
                last_seen_at=excluded.last_seen_at,
                seen_count=verification_candidates.seen_count + 1,
                status=CASE
                    WHEN verification_candidates.current_price != excluded.current_price
                    THEN 'pending'
                    ELSE verification_candidates.status
                END
            """,
            row,
        )
        self.conn.commit()
        return candidate.key

    def enqueue_many(self, candidates: Iterable[VerificationCandidate]) -> list[str]:
        return [self.enqueue(candidate) for candidate in candidates]

    def pending(self, limit: int = 100) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM verification_candidates
            WHERE status='pending'
            ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                     current_price DESC, first_seen_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def save_estimate(
        self,
        candidate_key: str,
        *,
        low: float | None,
        high: float | None,
        confidence: str,
        identified: bool,
        pricing_error_likelihood: str = "unknown",
        rationale: str = "",
    ) -> None:
        confidence = confidence if confidence in {"low", "medium", "high", "unknown"} else "unknown"
        likelihood = (
            pricing_error_likelihood
            if pricing_error_likelihood in {"low", "medium", "high", "unknown"}
            else "unknown"
        )
        self.conn.execute(
            """
            UPDATE verification_candidates SET
                estimate_low=?, estimate_high=?, estimate_confidence=?, identified=?,
                pricing_error_likelihood=?, estimate_rationale=?, estimated_at=?, status='estimated'
            WHERE candidate_key=?
            """,
            (low, high, confidence, int(identified), likelihood, rationale[:1000], self._now(), candidate_key),
        )
        self.conn.commit()

    def record_delivery(
        self,
        candidate_key: str,
        *,
        channel: str,
        delivered: bool,
        message_id: str = "",
        error: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO notification_deliveries
                (candidate_key, channel, attempted_at, delivered, message_id, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (candidate_key, channel, self._now(), int(delivered), message_id, error[:500]),
        )
        self.conn.commit()

    def delivery_history(self, candidate_key: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT * FROM notification_deliveries
               WHERE candidate_key=? ORDER BY attempted_at DESC, id DESC""",
            (candidate_key,),
        ).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS count FROM verification_candidates GROUP BY status"
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def export_candidate(self, candidate_key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM verification_candidates WHERE candidate_key=?", (candidate_key,)
        ).fetchone()
        return dict(row) if row else None


def candidate_json(candidate: VerificationCandidate) -> str:
    """Stable JSON representation for diagnostics and handoffs."""
    return json.dumps({**asdict(candidate), "candidate_key": candidate.key}, sort_keys=True)
