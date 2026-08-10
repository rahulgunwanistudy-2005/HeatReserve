from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .domain import CommitmentDecision, HeatEpisode, Policy, Reserve, SourceSnapshot, Worker


REASON_OFFICIAL_WARNING = "OFFICIAL_WARNING_EPISODE"
REASON_WORKER_ALLOWED = "WORKER_TYPE_ALLOWED"
REASON_WORKER_NOT_ALLOWED = "WORKER_TYPE_NOT_ALLOWED"
REASON_ZONE_ALLOWED = "ZONE_ALLOWED"
REASON_ZONE_NOT_ALLOWED = "ZONE_NOT_ALLOWED"
REASON_ALREADY_COMMITTED = "ALREADY_COMMITTED"
REASON_RESERVE_AVAILABLE = "RESERVE_AVAILABLE"
REASON_INSUFFICIENT_RESERVE = "INSUFFICIENT_RESERVE"
REASON_SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"
REASON_POLICY_NOT_PUBLISHED = "POLICY_NOT_PUBLISHED"
REASON_TENANT_MISMATCH = "TENANT_MISMATCH"


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    tenant_id: str
    existing_commitment: bool = False


def make_idempotency_key(
    tenant_id: str,
    worker_id: str,
    episode_id: str,
    policy_id: str,
    policy_version: str,
) -> str:
    canonical = "|".join((tenant_id, worker_id, episode_id, policy_id, policy_version))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _not_qualified(
    key: str,
    reserve: Reserve,
    reasons: list[str],
) -> CommitmentDecision:
    return CommitmentDecision(
        status="NOT_QUALIFIED",
        amount_minor=0,
        reason_codes=tuple(reasons),
        idempotency_key=key,
        reserve_before_minor=reserve.current_minor,
        reserve_after_minor=reserve.current_minor,
    )


def evaluate_policy(
    policy: Policy,
    episode: HeatEpisode,
    worker: Worker,
    reserve: Reserve,
    snapshots: tuple[SourceSnapshot, ...],
    context: EvaluationContext,
) -> CommitmentDecision:
    key = make_idempotency_key(
        context.tenant_id, worker.worker_id, episode.episode_id, policy.policy_id, policy.version
    )
    reasons: list[str] = []
    if not (context.tenant_id == worker.tenant_id == policy.tenant_id == reserve.tenant_id):
        return _not_qualified(key, reserve, [REASON_TENANT_MISMATCH])
    if context.existing_commitment:
        return _not_qualified(key, reserve, [REASON_ALREADY_COMMITTED])
    if policy.status != "published":
        return _not_qualified(key, reserve, [REASON_POLICY_NOT_PUBLISHED])
    if not snapshots or any(not snapshot.verified for snapshot in snapshots):
        return _not_qualified(key, reserve, [REASON_SOURCE_UNVERIFIED])
    if any(snapshot.source_type != policy.source_type for snapshot in snapshots):
        return _not_qualified(key, reserve, [REASON_SOURCE_UNVERIFIED])
    reasons.append(REASON_OFFICIAL_WARNING)
    if worker.worker_type not in policy.allowed_worker_types:
        reasons.append(REASON_WORKER_NOT_ALLOWED)
        return _not_qualified(key, reserve, reasons)
    reasons.append(REASON_WORKER_ALLOWED)
    if worker.zone_id not in policy.allowed_zones or worker.zone_id != episode.zone_id:
        reasons.append(REASON_ZONE_NOT_ALLOWED)
        return _not_qualified(key, reserve, reasons)
    reasons.append(REASON_ZONE_ALLOWED)
    amount = min(policy.amount_minor, policy.per_episode_cap_minor)
    if reserve.current_minor < amount:
        reasons.append(REASON_INSUFFICIENT_RESERVE)
        return _not_qualified(key, reserve, reasons)
    reasons.append(REASON_RESERVE_AVAILABLE)
    return CommitmentDecision(
        status="QUALIFIED",
        amount_minor=amount,
        reason_codes=tuple(reasons),
        idempotency_key=key,
        reserve_before_minor=reserve.current_minor,
        reserve_after_minor=reserve.current_minor - amount,
    )
