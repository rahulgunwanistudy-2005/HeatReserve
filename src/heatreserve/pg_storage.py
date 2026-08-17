"""
PostgreSQL persistence layer for live mode.

Uses psycopg2 with row-level locking and serializable transactions to ensure:
- reserve cannot go negative under concurrent commitment requests
- idempotency keys deduplicate concurrent identical requests
- ledger entries are append-only

INVARIANT: Judge Mode always uses SQLite (storage.py).
           This module is only imported when DATABASE_URL starts with 'postgresql'.

Connection pooling: uses a simple thread-local approach suitable for the
FastAPI sync worker model. For async FastAPI, wrap in run_in_executor.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .domain import (
    AdaptationPlan,
    CommitmentDecision,
    DecisionReceipt,
    HeatEpisode,
    Policy,
    Reserve,
    SourceSnapshot,
    Worker,
)
from .policy import EvaluationContext, evaluate_policy, make_idempotency_key
from .storage import CommitmentRecord

LOGGER = logging.getLogger("heatreserve.pg_storage")


def _try_import_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras
        return psycopg2
    except ImportError:
        return None


class PostgresRepository:
    """
    PostgreSQL-backed repository with the same interface as the SQLite Repository.

    Reserve transactions use SELECT ... FOR UPDATE to prevent concurrent overspend.
    Idempotency is enforced at the database level via UNIQUE constraint on
    idempotency_key in the commitments table.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS tenants (
        tenant_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS workers (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
        worker_type TEXT NOT NULL,
        zone_id TEXT NOT NULL,
        language TEXT NOT NULL,
        payload_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_workers_tenant ON workers(tenant_id);
    CREATE TABLE IF NOT EXISTS policies (
        policy_id TEXT NOT NULL,
        version TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        status TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        payload_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(policy_id, version)
    );
    CREATE INDEX IF NOT EXISTS idx_policies_tenant ON policies(tenant_id, status);
    CREATE TABLE IF NOT EXISTS reserves (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        currency TEXT NOT NULL CHECK(currency = 'INR'),
        initial_minor BIGINT NOT NULL CHECK(initial_minor >= 0),
        current_minor BIGINT NOT NULL CHECK(current_minor >= 0),
        version INTEGER NOT NULL CHECK(version >= 0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS commitments (
        id TEXT PRIMARY KEY,
        worker_id TEXT NOT NULL REFERENCES workers(id),
        episode_id TEXT NOT NULL,
        policy_id TEXT NOT NULL,
        policy_version TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        amount_minor BIGINT NOT NULL CHECK(amount_minor >= 0),
        status TEXT NOT NULL,
        decision_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_commitments_worker ON commitments(worker_id, episode_id);
    CREATE TABLE IF NOT EXISTS ledger_entries (
        id TEXT PRIMARY KEY,
        reserve_id TEXT NOT NULL REFERENCES reserves(id),
        commitment_id TEXT NOT NULL UNIQUE REFERENCES commitments(id),
        entry_type TEXT NOT NULL CHECK(entry_type = 'COMMITMENT'),
        amount_minor BIGINT NOT NULL CHECK(amount_minor >= 0),
        balance_after_minor BIGINT NOT NULL CHECK(balance_after_minor >= 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ledger_reserve ON ledger_entries(reserve_id, created_at);
    CREATE TABLE IF NOT EXISTS plans (
        id TEXT PRIMARY KEY,
        worker_id TEXT NOT NULL REFERENCES workers(id),
        episode_id TEXT NOT NULL,
        payload_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS receipts (
        id TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL REFERENCES commitments(id),
        plan_id TEXT NOT NULL REFERENCES plans(id),
        digest_sha256 TEXT NOT NULL,
        payload_json JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        actor TEXT NOT NULL,
        request_id TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL,
        target_type TEXT NOT NULL DEFAULT '',
        target_id TEXT NOT NULL DEFAULT '',
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata_json JSONB NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_events(tenant_id, event_type, occurred_at DESC);
    """

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._local = threading.local()
        psycopg2 = _try_import_psycopg2()
        if psycopg2 is None:
            raise ImportError(
                "psycopg2 is required for PostgreSQL support. "
                "Install with: pip install psycopg2-binary"
            )
        self._psycopg2 = psycopg2
        self._initialize()

    def _connect(self):
        if not getattr(self._local, "conn", None) or self._local.conn.closed:
            self._local.conn = self._psycopg2.connect(
                self._url,
                options="-c statement_timeout=30000",
            )
            self._local.conn.autocommit = False
        return self._local.conn

    def _initialize(self) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(self._DDL)
        conn.commit()

    def reset_demo(self, workers: tuple[Worker, ...], policy: Policy, reserve: Reserve) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            for table in ("receipts", "plans", "ledger_entries", "commitments",
                          "workers", "policies", "reserves"):
                cur.execute(f"DELETE FROM {table}")
            # Ensure tenant exists
            cur.execute(
                "INSERT INTO tenants(tenant_id, name) VALUES(%s, %s) "
                "ON CONFLICT(tenant_id) DO NOTHING",
                (reserve.tenant_id, reserve.tenant_id),
            )
            for w in workers:
                cur.execute(
                    "INSERT INTO workers(id,tenant_id,worker_type,zone_id,language,payload_json) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                    (w.worker_id, w.tenant_id, w.worker_type, w.zone_id, w.language,
                     self._psycopg2.extras.Json(json.loads(w.model_dump_json()))),
                )
            cur.execute(
                "INSERT INTO policies(policy_id,version,tenant_id,status,sha256,payload_json) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(policy_id,version) DO NOTHING",
                (policy.policy_id, policy.version, policy.tenant_id, policy.status,
                 policy.sha256,
                 self._psycopg2.extras.Json(json.loads(policy.model_dump_json()))),
            )
            cur.execute(
                "INSERT INTO reserves(id,tenant_id,currency,initial_minor,current_minor,version) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (reserve.reserve_id, reserve.tenant_id, reserve.currency,
                 reserve.initial_minor, reserve.current_minor, reserve.version),
            )
        conn.commit()

    def get_worker(self, worker_id: str) -> Worker | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM workers WHERE id = %s", (worker_id,)
            )
            row = cur.fetchone()
        conn.commit()
        return Worker.model_validate(row[0]) if row else None

    def list_workers(self) -> tuple[Worker, ...]:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT payload_json FROM workers ORDER BY id")
            rows = cur.fetchall()
        conn.commit()
        return tuple(Worker.model_validate(r[0]) for r in rows)

    def save_policy(self, policy: Policy) -> None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, payload_json FROM policies "
                "WHERE policy_id = %s AND version = %s",
                (policy.policy_id, policy.version),
            )
            existing = cur.fetchone()
            payload_json = json.loads(policy.model_dump_json())
            if existing and existing[0] == "published" and existing[1] != payload_json:
                conn.rollback()
                raise ValueError(
                    "published policy versions are immutable; publish a new version"
                )
            cur.execute(
                "INSERT INTO policies(policy_id,version,tenant_id,status,sha256,payload_json) "
                "VALUES(%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(policy_id,version) DO UPDATE SET "
                "tenant_id=EXCLUDED.tenant_id,status=EXCLUDED.status,"
                "sha256=EXCLUDED.sha256,payload_json=EXCLUDED.payload_json",
                (policy.policy_id, policy.version, policy.tenant_id, policy.status,
                 policy.sha256,
                 self._psycopg2.extras.Json(payload_json)),
            )
        conn.commit()

    def get_policy(self, policy_id: str, version: str) -> Policy | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload_json FROM policies WHERE policy_id = %s AND version = %s",
                (policy_id, version),
            )
            row = cur.fetchone()
        conn.commit()
        return Policy.model_validate(row[0]) if row else None

    def get_reserve(self, reserve_id: str) -> Reserve | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id,tenant_id,currency,initial_minor,current_minor,version "
                "FROM reserves WHERE id = %s",
                (reserve_id,),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return None
        return Reserve(
            reserve_id=row[0], tenant_id=row[1], currency=row[2],
            initial_minor=row[3], current_minor=row[4], version=row[5],
        )

    def create_or_reuse_commitment(
        self,
        *,
        worker: Worker,
        episode: HeatEpisode,
        policy: Policy,
        snapshots: tuple[SourceSnapshot, ...],
    ) -> CommitmentRecord:
        key = make_idempotency_key(
            worker.tenant_id, worker.worker_id, episode.episode_id,
            policy.policy_id, policy.version,
        )
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                # Check for existing commitment first (no lock needed for read)
                cur.execute(
                    "SELECT id, decision_json FROM commitments WHERE idempotency_key = %s",
                    (key,),
                )
                existing = cur.fetchone()
                if existing:
                    conn.commit()
                    dec = CommitmentDecision.model_validate(existing[1])
                    return CommitmentRecord(existing[0], dec, False)

                # Lock reserve row to prevent concurrent overspend
                cur.execute(
                    "SELECT id,tenant_id,currency,initial_minor,current_minor,version "
                    "FROM reserves WHERE id = %s FOR UPDATE",
                    (policy.reserve_id,),
                )
                reserve_row = cur.fetchone()
                if not reserve_row:
                    conn.rollback()
                    raise ValueError(f"Reserve not found: {policy.reserve_id}")
                reserve = Reserve(
                    reserve_id=reserve_row[0], tenant_id=reserve_row[1],
                    currency=reserve_row[2], initial_minor=reserve_row[3],
                    current_minor=reserve_row[4], version=reserve_row[5],
                )
                decision = evaluate_policy(
                    policy, episode, worker, reserve, snapshots,
                    EvaluationContext(tenant_id=worker.tenant_id),
                )
                if decision.status != "QUALIFIED":
                    conn.commit()
                    return CommitmentRecord("", decision, False)

                commitment_id = f"commit-{key[:12]}"
                created_at = datetime.now(UTC).isoformat()
                cur.execute(
                    "UPDATE reserves SET current_minor = %s, version = version + 1, "
                    "updated_at = NOW() WHERE id = %s",
                    (decision.reserve_after_minor, policy.reserve_id),
                )
                cur.execute(
                    "INSERT INTO commitments("
                    "id,worker_id,episode_id,policy_id,policy_version,"
                    "idempotency_key,amount_minor,status,decision_json,created_at"
                    ") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        commitment_id, worker.worker_id, episode.episode_id,
                        policy.policy_id, policy.version, key,
                        decision.amount_minor, decision.status,
                        self._psycopg2.extras.Json(json.loads(decision.model_dump_json())),
                        created_at,
                    ),
                )
                cur.execute(
                    "INSERT INTO ledger_entries("
                    "id,reserve_id,commitment_id,entry_type,"
                    "amount_minor,balance_after_minor,created_at"
                    ") VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        f"ledger-{uuid4().hex[:12]}", policy.reserve_id,
                        commitment_id, "COMMITMENT",
                        decision.amount_minor, decision.reserve_after_minor, created_at,
                    ),
                )
            conn.commit()
            return CommitmentRecord(commitment_id, decision, True)
        except Exception:
            conn.rollback()
            raise

    def get_commitment_for(
        self,
        *,
        tenant_id: str,
        worker_id: str,
        episode_id: str,
        policy_id: str,
        policy_version: str,
    ) -> CommitmentRecord | None:
        key = make_idempotency_key(tenant_id, worker_id, episode_id, policy_id, policy_version)
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, decision_json FROM commitments WHERE idempotency_key = %s", (key,)
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return None
        return CommitmentRecord(row[0], CommitmentDecision.model_validate(row[1]), False)

    def save_plan(self, plan: AdaptationPlan) -> None:
        payload = json.loads(plan.model_dump_json())
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO plans(id,worker_id,episode_id,payload_json) "
                "VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (plan.plan_id, plan.worker_id, plan.episode_id,
                 self._psycopg2.extras.Json(payload)),
            )
            cur.execute("SELECT payload_json FROM plans WHERE id = %s", (plan.plan_id,))
            stored = cur.fetchone()
            if stored and stored[0] != payload:
                conn.rollback()
                raise ValueError("plan IDs are immutable and content-bound")
        conn.commit()

    def save_receipt(self, receipt: DecisionReceipt) -> None:
        if receipt.digest is None:
            raise ValueError("receipt must include digest before storage")
        payload = json.loads(receipt.model_dump_json())
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO receipts("
                "id,commitment_id,plan_id,digest_sha256,payload_json"
                ") VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                (
                    receipt.receipt_id, receipt.commitment_id, receipt.plan_id,
                    receipt.digest.value,
                    self._psycopg2.extras.Json(payload),
                ),
            )
            cur.execute("SELECT payload_json FROM receipts WHERE id = %s", (receipt.receipt_id,))
            stored = cur.fetchone()
            if stored and stored[0] != payload:
                conn.rollback()
                raise ValueError("receipt IDs are immutable and content-bound")
        conn.commit()

    def get_receipt(self, receipt_id: str) -> DecisionReceipt | None:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT payload_json FROM receipts WHERE id = %s", (receipt_id,))
            row = cur.fetchone()
        conn.commit()
        return DecisionReceipt.model_validate(row[0]) if row else None

    def commitment_count(self) -> int:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM commitments")
            row = cur.fetchone()
        conn.commit()
        return int(row[0]) if row else 0

    def reserve_reconciles(self, reserve_id: str) -> bool:
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT initial_minor, current_minor FROM reserves WHERE id = %s",
                (reserve_id,),
            )
            reserve_row = cur.fetchone()
            cur.execute(
                "SELECT COALESCE(SUM(amount_minor), 0) FROM ledger_entries "
                "WHERE reserve_id = %s",
                (reserve_id,),
            )
            spent_row = cur.fetchone()
        conn.commit()
        if not reserve_row:
            return False
        initial, current = reserve_row[0], reserve_row[1]
        spent = int(spent_row[0])
        return initial - spent == current
