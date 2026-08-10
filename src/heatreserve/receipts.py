from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .domain import (
    AdaptationPlan,
    CommitmentDecision,
    DecisionReceipt,
    EvidenceClass,
    ReceiptDigest,
)
from .evidence import canonical_sha256


def _normalize_receipt_payload(receipt: DecisionReceipt | dict[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, DecisionReceipt):
        payload = receipt.model_dump(mode="json")
    else:
        payload = dict(receipt)
    payload.pop("digest", None)
    return payload


def compute_receipt_digest(receipt: DecisionReceipt | dict[str, Any]) -> str:
    return canonical_sha256(_normalize_receipt_payload(receipt))


def attach_digest(receipt: DecisionReceipt) -> DecisionReceipt:
    digest = compute_receipt_digest(receipt)
    return receipt.model_copy(update={"digest": ReceiptDigest(value=digest)})


def verify_receipt(receipt: DecisionReceipt | dict[str, Any]) -> dict[str, Any]:
    stored = None
    if isinstance(receipt, DecisionReceipt):
        stored = receipt.digest.value if receipt.digest else None
        schema_version = receipt.schema_version
    else:
        digest = receipt.get("digest")
        stored = digest.get("value") if isinstance(digest, dict) else None
        schema_version = receipt.get("schema_version", "unknown")
    computed = compute_receipt_digest(receipt)
    return {
        "valid": bool(stored) and stored == computed,
        "computed_sha256": computed,
        "stored_sha256": stored,
        "schema_version": schema_version,
        "verification_scope": "INTEGRITY_ONLY",
        "authenticity_established": False,
    }


def build_receipt(
    *,
    receipt_id: str,
    tenant_id: str,
    worker_id: str,
    episode_id: str,
    commitment_id: str,
    policy_id: str,
    policy_version: str,
    decision: CommitmentDecision,
    plan: AdaptationPlan,
    source_snapshot_ids: tuple[str, ...],
    created_at: datetime | None = None,
) -> DecisionReceipt:
    receipt = DecisionReceipt(
        receipt_id=receipt_id,
        tenant_id=tenant_id,
        worker_id=worker_id,
        episode_id=episode_id,
        commitment_id=commitment_id,
        plan_id=plan.plan_id,
        plan_sha256=canonical_sha256(plan.model_dump(mode="json")),
        policy_id=policy_id,
        policy_version=policy_version,
        decision_status=decision.status,
        decision_reason_codes=decision.reason_codes,
        decision_idempotency_key=decision.idempotency_key,
        amount_minor=decision.amount_minor,
        source_snapshot_ids=source_snapshot_ids,
        planner_mode=plan.planner_mode,
        provider=plan.provider,
        model=plan.model,
        prompt_version=plan.prompt_version,
        verifier_version=plan.verifier_version,
        tool_fact_ids=plan.tool_fact_ids,
        evidence_class=EvidenceClass.SIMULATED,
        created_at=created_at or datetime.now(UTC),
    )
    return attach_digest(receipt)
