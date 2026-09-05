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
import random
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Iterable

DEFAULT_DB = pathlib.Path.home() / "dane/product-verification.sqlite3"
_PRIORITIES = {"P1": 1, "P2": 2, "P3": 3}
# An item now at or below 1/1.5 of a price it was previously observed at is
# worth an AI estimate before anything else in the queue.
MISPRICE_RATIO = 1.5


# Product types whose best-case saving is tens of PLN, so they can never justify
# an AI estimate no matter how wrong the listed price is. Matched against the
# START of the title: Polish titles here lead with the product type ("Etui Bizon
# ...", "Kabel HDMI ..."), whereas a substring match wrongly caught real deals
# such as "Sluchawki ... z mikrofonem" or a DualSense pad via an incidental
# "kabel"/"pasek" in the description.
ACCESSORY_TYPES = (
    "etui", "folia", "szklo", "szkło", "kabel", "przewod", "przewód",
    "ladowarka", "ładowarka", "uchwyt", "adapter", "pokrowiec", "podkladka",
    "podkładka", "torba", "worek", "filtr", "organizer", "sciereczka",
    "ściereczka", "sciereczki", "ściereczki", "wtyk", "zlaczka", "złączka",
    "lacznik", "łącznik", "figurka", "naklejka", "smycz", "tabletki",
    "kapsulki", "kapsułki", "plyn", "płyn", "bity", "wkret", "wkręt",
)
# Above this price an accessory can still hide a saving worth looking at, so the
# filter only applies below it.
ACCESSORY_PRICE_CAP = 150.0

# Refused accessories are appended here rather than dropped. The filter is a
# budget decision, not a judgement that these items are uninteresting: a steep
# enough anomaly may still be worth a look, and the log keeps that option open
# and lets the threshold be re-tuned against real data instead of guesswork.
DEFAULT_REJECTED_LOG = pathlib.Path.home() / "dane/verification-rejected-accessories.jsonl"


def _rejected_log_path() -> pathlib.Path:
    configured = os.environ.get("VERIFICATION_REJECTED_LOG", "")
    return pathlib.Path(configured) if configured else DEFAULT_REJECTED_LOG


def log_rejected_accessory(candidate: "VerificationCandidate") -> None:
    """Append one refused candidate as JSON; never raise into the caller."""
    try:
        path = _rejected_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "store": candidate.store,
            "title": candidate.title,
            "url": candidate.url,
            "current_price": candidate.current_price,
            "category_slug": candidate.category_slug,
            "priority": candidate.priority,
            "gtin": candidate.gtin,
            "mpn": candidate.mpn,
            "reason": "low_value_accessory",
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def is_low_value_accessory(title: str, price: float) -> bool:
    """True when an item is a cheap accessory not worth an AI estimate."""
    if price <= 0 or price >= ACCESSORY_PRICE_CAP:
        return False
    lowered = (title or "").strip().lower()
    return any(lowered.startswith(f"{word} ") for word in ACCESSORY_TYPES)


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


#: Retry for transient `database is locked`: this DB shares the disk with the
#: fleet's multi-GB SQLite files, and in `delete` journal mode a committing
#: writer holds EXCLUSIVE, blocking even readers. `busy_timeout` covers short
#: collisions; a short back-off covers the rest instead of killing the whole
#: scan cycle (Failed = silent day). Kept local: deal-pipeline depends on
#: product-knowledge, so importing its retry helper would be circular.
_STATEMENT_ATTEMPTS = 5
_STATEMENT_BASE_DELAY_S = 0.2

#: Objects created by `_init_schema` (tables, indexes, trigger, including past
#: migrations). When all are present the schema is current and init returns
#: after two read-only probes instead of taking write locks (DDL + backfill
#: UPDATE over the whole table) on every construction.
_SCHEMA_OBJECTS = frozenset({
    "verification_candidates",
    "notification_deliveries",
    "idx_verification_pending",
    "idx_delivery_candidate",
    "idx_verification_pending_fresh",
    "trg_verification_pending_since_insert",
})


def _is_locked(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc)


def _retry_locked(fn, *args, **kwargs):
    for attempt in range(_STATEMENT_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if not _is_locked(exc) or attempt == _STATEMENT_ATTEMPTS - 1:
                raise
            time.sleep(_STATEMENT_BASE_DELAY_S * (2**attempt) + random.uniform(0, 0.05))


class _RetryingConnection(sqlite3.Connection):
    """Connection whose statements survive a transient lock instead of failing."""

    def execute(self, *args, **kwargs):
        return _retry_locked(super().execute, *args, **kwargs)

    def executemany(self, *args, **kwargs):
        return _retry_locked(super().executemany, *args, **kwargs)

    def executescript(self, *args, **kwargs):
        return _retry_locked(super().executescript, *args, **kwargs)

    def commit(self):
        return _retry_locked(super().commit)


class VerificationStore:
    """SQLite-backed candidate queue and notification-delivery audit."""

    def __init__(self, path: pathlib.Path | str | None = None) -> None:
        configured = os.environ.get("PRODUCT_VERIFICATION_DB", "")
        self.path = pathlib.Path(path or configured or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30, factory=_RetryingConnection)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> VerificationStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _schema_ready(self) -> bool:
        """True when the schema (including past migrations) already exists.

        Read-only: two SELECTs, no write lock. Lets every per-cycle
        `VerificationStore()` skip the DDL + backfill UPDATE that otherwise
        contend for EXCLUSIVE on the shared disk.
        """
        try:
            names = {
                row[0]
                for row in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE name IN "
                    "('verification_candidates','notification_deliveries',"
                    "'idx_verification_pending','idx_delivery_candidate',"
                    "'idx_verification_pending_fresh',"
                    "'trg_verification_pending_since_insert')"
                )
            }
        except sqlite3.OperationalError:
            return False
        if len(names) < len(_SCHEMA_OBJECTS):
            return False
        columns = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(verification_candidates)")
        }
        return "pending_since_at" in columns

    def _backfill_pending_since(self) -> None:
        """Fill NULL pending timestamps left by older writers.

        Runs only when such rows exist (a read-only probe first), so a
        steady-state construction takes no write lock while a store that
        still has unmigrated rows gets the exact same UPDATE as before.
        """
        row = self.conn.execute(
            "SELECT EXISTS(SELECT 1 FROM verification_candidates"
            " WHERE pending_since_at IS NULL)"
        ).fetchone()
        if row is None or not row[0]:
            return
        self.conn.execute(
            """UPDATE verification_candidates
               SET pending_since_at=CASE
                   WHEN status='pending' AND estimated_at IS NOT NULL
                   THEN last_seen_at ELSE first_seen_at END
               WHERE pending_since_at IS NULL"""
        )
        self.conn.commit()

    def _init_schema(self) -> None:
        if self._schema_ready():
            self._backfill_pending_since()
            return
        if self._schema_ready():
            return
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
                pending_since_at TEXT NOT NULL,
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
        columns = {
            row[1] for row in self.conn.execute(
                "PRAGMA table_info(verification_candidates)"
            )
        }
        if "pending_since_at" not in columns:
            self.conn.execute(
                "ALTER TABLE verification_candidates ADD COLUMN pending_since_at TEXT"
            )
        self._backfill_pending_since()
        self.conn.execute(
            """CREATE TRIGGER IF NOT EXISTS trg_verification_pending_since_insert
               AFTER INSERT ON verification_candidates
               WHEN NEW.pending_since_at IS NULL
               BEGIN
                   UPDATE verification_candidates
                   SET pending_since_at=NEW.first_seen_at
                   WHERE candidate_key=NEW.candidate_key;
               END"""
        )
        self.conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_verification_pending_fresh
               ON verification_candidates(status, priority, pending_since_at)"""
        )
        self.conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def enqueue(self, candidate: VerificationCandidate) -> str:
        # Single intake gate for every scanner path. Cheap accessories are the
        # bulk of the queue (measured: 27% of pending) and can never produce an
        # alert worth the AI budget they consume, so they are refused here
        # rather than filtered per-caller.
        if is_low_value_accessory(candidate.title, candidate.current_price):
            log_rejected_accessory(candidate)
            return ""
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
                brand, image_url, reason, first_seen_at, last_seen_at,
                pending_since_at
            ) VALUES (
                :candidate_key, :source, :store, :title, :url, :current_price,
                :reference_price, :category_slug, :priority, :gtin, :mpn, :asin,
                :brand, :image_url, :reason, :now, :now, :now
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
                pending_since_at=CASE
                    WHEN verification_candidates.current_price != excluded.current_price
                    THEN excluded.pending_since_at
                    ELSE verification_candidates.pending_since_at
                END,
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
        """Order the queue so suspected mispricings are estimated first.

        The goal is catching price errors -- a 4000 PLN item listed at 20 PLN --
        not surveying expensive products, so the previous ``current_price DESC``
        ordering worked directly against it.

        The ranking signal is an item's own observed price history in the shared
        knowledge DB: an item now far below a price it was seen at before is a
        genuine candidate. A category median is deliberately NOT used -- measured
        on the live queue it surfaced cheap accessories miscategorised into
        expensive slugs (a 2 PLN antenna plug against a 600 PLN tv-audio median),
        which are correctly priced and worthless as alerts.

        Items without usable history keep the old priority/price ordering, so the
        queue degrades gracefully while history accumulates.
        """
        ranked: list[sqlite3.Row] = []
        drops = self._history_drops(limit)
        if drops:
            placeholders = ",".join("?" * len(drops))
            found = self.conn.execute(
                f"""SELECT * FROM verification_candidates
                    WHERE status='pending' AND candidate_key IN ({placeholders})""",
                tuple(drops),
            ).fetchall()
            order = {key: index for index, key in enumerate(drops)}
            ranked = sorted(found, key=lambda row: order[row["candidate_key"]])
        if len(ranked) >= limit:
            return ranked[:limit]
        rest = self.conn.execute(
            """
            SELECT * FROM verification_candidates
            WHERE status='pending'
            ORDER BY CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                     CASE WHEN priority='P1' THEN pending_since_at END DESC,
                     CASE WHEN priority!='P1' THEN first_seen_at END ASC,
                     current_price DESC
            LIMIT ?
            """,
            (limit + len(ranked),),
        ).fetchall()
        seen = {row["candidate_key"] for row in ranked}
        for row in rest:
            if row["candidate_key"] in seen:
                continue
            ranked.append(row)
            if len(ranked) >= limit:
                break
        return ranked[:limit]

    def _history_drops(self, limit: int) -> list[str]:
        """Candidate keys whose own price history shows a steep drop, worst first.

        Best-effort by design: the knowledge DB is a separate file that scanner
        timers write to constantly, so it may be missing or briefly locked. Any
        failure falls back to the plain ordering rather than breaking a triage
        run that would otherwise have produced estimates.
        """
        configured = os.environ.get("PRODUCT_KNOWLEDGE_DB", "")
        knowledge = pathlib.Path(
            configured or pathlib.Path.home() / "dane/product-knowledge.db"
        )
        if not knowledge.exists():
            return []
        attached = False
        try:
            self.conn.execute(
                "ATTACH DATABASE ? AS knowledge", (f"file:{knowledge}?mode=ro",)
            )
            attached = True
            rows = self.conn.execute(
                """
                SELECT v.candidate_key
                FROM verification_candidates v
                JOIN knowledge.source_listings l ON l.url = v.url
                JOIN knowledge.price_observations o ON o.listing_id = l.id
                WHERE v.status='pending' AND v.current_price > 0
                GROUP BY v.candidate_key
                HAVING COUNT(o.id) >= 2
                   AND MAX(o.price) >= v.current_price * ?
                ORDER BY (MAX(o.price) / v.current_price) DESC
                LIMIT ?
                """,
                (MISPRICE_RATIO, limit),
            ).fetchall()
            return [row["candidate_key"] for row in rows]
        except sqlite3.Error:
            return []
        finally:
            if attached:
                try:
                    self.conn.execute("DETACH DATABASE knowledge")
                except sqlite3.Error:
                    pass

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
