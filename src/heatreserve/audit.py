"""
Immutable audit event journal.

Audit events are append-only records that explain what happened, who did it,
and what evidence was used. They do not replace domain tables — they are an
explainability/operations layer alongside them.

Events are small, structured, and never contain sensitive payloads.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

LOGGER = logging.getLogger("heatreserve.audit")

# Canonical event types
SOURCE_FETCH_STARTED = "SOURCE_FETCH_STARTED"
SOURCE_SNAPSHOT_VERIFIED = "SOURCE_SNAPSHOT_VERIFIED"
SOURCE_FETCH_FAILED = "SOURCE_FETCH_FAILED"
SOURCE_STALE = "SOURCE_STALE"
EPISODE_CREATED = "EPISODE_CREATED"
POLICY_EVALUATED = "POLICY_EVALUATED"
COMMITMENT_CREATED = "COMMITMENT_CREATED"
COMMITMENT_REUSED = "COMMITMENT_REUSED"
COMMITMENT_DENIED = "COMMITMENT_DENIED"
PLAN_CREATED = "PLAN_CREATED"
PLAN_FALLBACK_USED = "PLAN_FALLBACK_USED"
RECEIPT_CREATED = "RECEIPT_CREATED"
RECEIPT_VERIFIED = "RECEIPT_VERIFIED"
RECEIPT_TAMPER_DETECTED = "RECEIPT_TAMPER_DETECTED"
AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
DEMO_RESET = "DEMO_RESET"
RECONCILIATION_RUN = "RECONCILIATION_RUN"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    request_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_type
    ON audit_events(tenant_id, event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_request
    ON audit_events(request_id);
"""


class AuditJournal:
    """
    SQLite-backed append-only audit journal.

    In production PostgreSQL mode, the same interface is used with a
    psycopg2 connection. Events are never deleted or modified.
    """

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLE)

    def record(
        self,
        *,
        event_type: str,
        tenant_id: str,
        actor: str,
        request_id: str = "",
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, str] | None = None,
    ) -> str:
        event_id = f"evt-{uuid4().hex[:16]}"
        occurred_at = datetime.now(UTC).isoformat()
        meta_json = json.dumps(metadata or {}, separators=(",", ":"))
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO audit_events("
                    "event_id,tenant_id,actor,request_id,event_type,"
                    "target_type,target_id,occurred_at,metadata_json"
                    ") VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        event_id,
                        tenant_id,
                        actor,
                        request_id or "",
                        event_type,
                        target_type or "",
                        target_id or "",
                        occurred_at,
                        meta_json,
                    ),
                )
        except sqlite3.Error as exc:
            # Audit failure must never block the primary operation
            LOGGER.error("audit.write_failed event_type=%s error=%s", event_type, exc)
        return event_id

    def recent(self, tenant_id: str, limit: int = 50) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_id,event_type,actor,target_type,target_id,"
                "occurred_at,metadata_json "
                "FROM audit_events WHERE tenant_id = ? "
                "ORDER BY occurred_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "occurred_at": row["occurred_at"],
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]

    def count(self, event_type: str, tenant_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM audit_events "
                "WHERE tenant_id = ? AND event_type = ?",
                (tenant_id, event_type),
            ).fetchone()
        return int(row["n"]) if row else 0


class NullAuditJournal:
    """No-op journal for contexts that don't need persistence (e.g. unit tests)."""

    def record(self, **_kwargs: object) -> str:
        return ""

    def recent(self, tenant_id: str, limit: int = 50) -> list[dict[str, object]]:
        return []

    def count(self, event_type: str, tenant_id: str) -> int:
        return 0
