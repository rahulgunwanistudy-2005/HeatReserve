from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
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
from .schema import UP_SQL

@dataclass(frozen=True, slots=True)
class CommitmentRecord:
    commitment_id: str
    decision: CommitmentDecision
    created: bool


class Repository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(UP_SQL)

    def reset_demo(self, workers: tuple[Worker, ...], policy: Policy, reserve: Reserve) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in (
                    "DELETE FROM receipts", "DELETE FROM plans", "DELETE FROM ledger_entries",
                    "DELETE FROM commitments", "DELETE FROM workers", "DELETE FROM policies",
                    "DELETE FROM reserves",
                ):
                    connection.execute(statement)
                self._insert_workers(connection, workers)
                self._insert_policy(connection, policy)
                self._insert_reserve(connection, reserve)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _insert_workers(self, connection: sqlite3.Connection, workers: tuple[Worker, ...]) -> None:
        rows = [
            (
                worker.worker_id,
                worker.tenant_id,
                worker.worker_type,
                worker.zone_id,
                worker.language,
                worker.model_dump_json(),
            )
            for worker in workers
        ]
        connection.executemany(
            "INSERT INTO workers(id,tenant_id,worker_type,zone_id,language,payload_json) "
            "VALUES(?,?,?,?,?,?)",
            rows,
        )

    def _insert_policy(self, connection: sqlite3.Connection, policy: Policy) -> None:
        connection.execute(
            "INSERT INTO policies(policy_id,version,tenant_id,status,sha256,payload_json) "
            "VALUES(?,?,?,?,?,?)",
            (
                policy.policy_id,
                policy.version,
                policy.tenant_id,
                policy.status,
                policy.sha256,
                policy.model_dump_json(),
            ),
        )

    def _insert_reserve(self, connection: sqlite3.Connection, reserve: Reserve) -> None:
        connection.execute(
            "INSERT INTO reserves(id,tenant_id,currency,initial_minor,current_minor,version) "
            "VALUES(?,?,?,?,?,?)",
            (
                reserve.reserve_id,
                reserve.tenant_id,
                reserve.currency,
                reserve.initial_minor,
                reserve.current_minor,
                reserve.version,
            ),
        )

    def get_worker(self, worker_id: str) -> Worker | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workers WHERE id = ?", (worker_id,)
            ).fetchone()
        return Worker.model_validate_json(row["payload_json"]) if row else None

    def list_workers(self) -> tuple[Worker, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload_json FROM workers ORDER BY id").fetchall()
        return tuple(Worker.model_validate_json(row["payload_json"]) for row in rows)

    def save_policy(self, policy: Policy) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status,payload_json FROM policies WHERE policy_id = ? AND version = ?",
                (policy.policy_id, policy.version),
            ).fetchone()
            if (
                row
                and row["status"] == "published"
                and row["payload_json"] != policy.model_dump_json()
            ):
                raise ValueError("published policy versions are immutable; publish a new version")
            connection.execute(
                "INSERT INTO policies(policy_id,version,tenant_id,status,sha256,payload_json) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(policy_id,version) DO UPDATE SET "
                "tenant_id=excluded.tenant_id,status=excluded.status,sha256=excluded.sha256,"
                "payload_json=excluded.payload_json",
                (
                    policy.policy_id,
                    policy.version,
                    policy.tenant_id,
                    policy.status,
                    policy.sha256,
                    policy.model_dump_json(),
                ),
            )

    def get_policy(self, policy_id: str, version: str) -> Policy | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM policies WHERE policy_id = ? AND version = ?",
                (policy_id, version),
            ).fetchone()
        return Policy.model_validate_json(row["payload_json"]) if row else None

    def get_reserve(self, reserve_id: str) -> Reserve | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reserves WHERE id = ?", (reserve_id,)
            ).fetchone()
        return _row_to_reserve(row) if row else None

    def create_or_reuse_commitment(
        self,
        *,
        worker: Worker,
        episode: HeatEpisode,
        policy: Policy,
        snapshots: tuple[SourceSnapshot, ...],
    ) -> CommitmentRecord:
        key = make_idempotency_key(
            worker.tenant_id, worker.worker_id, episode.episode_id, policy.policy_id, policy.version
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = _find_commitment(connection, key)
                if existing:
                    connection.commit()
                    return CommitmentRecord(existing[0], existing[1], False)
                reserve_row = connection.execute(
                    "SELECT * FROM reserves WHERE id = ?", (policy.reserve_id,)
                ).fetchone()
                if reserve_row is None:
                    raise ValueError(f"Reserve not found: {policy.reserve_id}")
                reserve = _row_to_reserve(reserve_row)
                decision = evaluate_policy(
                    policy,
                    episode,
                    worker,
                    reserve,
                    snapshots,
                    EvaluationContext(tenant_id=worker.tenant_id),
                )
                if decision.status != "QUALIFIED":
                    connection.commit()
                    return CommitmentRecord("", decision, False)
                record = _persist_commitment(connection, worker, episode, policy, decision)
                connection.commit()
                return record
            except Exception:
                connection.rollback()
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
        with self._connect() as connection:
            existing = _find_commitment(connection, key)
        if existing is None:
            return None
        return CommitmentRecord(existing[0], existing[1], False)

    def save_plan(self, plan: AdaptationPlan) -> None:
        created_at = datetime.now(UTC).isoformat()
        payload = plan.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO plans(id,worker_id,episode_id,payload_json,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (plan.plan_id, plan.worker_id, plan.episode_id, payload, created_at),
            )
            row = connection.execute(
                "SELECT payload_json FROM plans WHERE id = ?", (plan.plan_id,)
            ).fetchone()
            if row is None or row["payload_json"] != payload:
                raise ValueError("plan IDs are immutable and content-bound")

    def save_receipt(self, receipt: DecisionReceipt) -> None:
        if receipt.digest is None:
            raise ValueError("receipt must include digest before storage")
        payload = receipt.model_dump_json()
        created_at = receipt.created_at.isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO receipts("
                "id,commitment_id,plan_id,digest_sha256,payload_json,created_at"
                ") VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                (
                    receipt.receipt_id,
                    receipt.commitment_id,
                    receipt.plan_id,
                    receipt.digest.value,
                    payload,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT payload_json FROM receipts WHERE id = ?", (receipt.receipt_id,)
            ).fetchone()
            if row is None or row["payload_json"] != payload:
                raise ValueError("receipt IDs are immutable and content-bound")

    def get_receipt(self, receipt_id: str) -> DecisionReceipt | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM receipts WHERE id = ?", (receipt_id,)
            ).fetchone()
        return DecisionReceipt.model_validate_json(row["payload_json"]) if row else None

    def commitment_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM commitments").fetchone()
        return int(row["n"])

    def reserve_reconciles(self, reserve_id: str) -> bool:
        with self._connect() as connection:
            reserve = connection.execute(
                "SELECT * FROM reserves WHERE id = ?", (reserve_id,)
            ).fetchone()
            spent = connection.execute(
                "SELECT COALESCE(SUM(amount_minor),0) AS total "
                "FROM ledger_entries WHERE reserve_id = ?",
                (reserve_id,),
            ).fetchone()
        if reserve is None:
            return False
        return int(reserve["initial_minor"]) - int(spent["total"]) == int(reserve["current_minor"])


def _row_to_reserve(row: sqlite3.Row) -> Reserve:
    return Reserve(
        reserve_id=row["id"],
        tenant_id=row["tenant_id"],
        currency=row["currency"],
        initial_minor=row["initial_minor"],
        current_minor=row["current_minor"],
        version=row["version"],
    )


def _find_commitment(
    connection: sqlite3.Connection, idempotency_key: str
) -> tuple[str, CommitmentDecision] | None:
    row = connection.execute(
        "SELECT id,decision_json FROM commitments WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    if row is None:
        return None
    return row["id"], CommitmentDecision.model_validate_json(row["decision_json"])


def _persist_commitment(
    connection: sqlite3.Connection,
    worker: Worker,
    episode: HeatEpisode,
    policy: Policy,
    decision: CommitmentDecision,
) -> CommitmentRecord:
    commitment_id = f"commit-{decision.idempotency_key[:12]}"
    created_at = datetime.now(UTC).isoformat()
    connection.execute(
        "UPDATE reserves SET current_minor = ?, version = version + 1 WHERE id = ?",
        (decision.reserve_after_minor, policy.reserve_id),
    )
    connection.execute(
        "INSERT INTO commitments(id,worker_id,episode_id,policy_id,policy_version,idempotency_key,"
        "amount_minor,status,decision_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            commitment_id,
            worker.worker_id,
            episode.episode_id,
            policy.policy_id,
            policy.version,
            decision.idempotency_key,
            decision.amount_minor,
            decision.status,
            decision.model_dump_json(),
            created_at,
        ),
    )
    connection.execute(
        "INSERT INTO ledger_entries(id,reserve_id,commitment_id,entry_type,amount_minor,"
        "balance_after_minor,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            f"ledger-{uuid4().hex[:12]}",
            policy.reserve_id,
            commitment_id,
            "COMMITMENT",
            decision.amount_minor,
            decision.reserve_after_minor,
            created_at,
        ),
    )
    return CommitmentRecord(commitment_id, decision, True)
