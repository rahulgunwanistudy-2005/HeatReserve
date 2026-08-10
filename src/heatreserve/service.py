from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .allocator import AllocationCandidate, compare_strategies
from .config import Settings
from .domain import (
    AdaptationPlan,
    CoolingPoint,
    HeatEpisode,
    HourlyCondition,
    Policy,
    Reserve,
    SourceSnapshot,
    Worker,
)
from .episodes import build_episode_from_warning
from .evidence import (
    load_json,
    require_verified_manifest,
    verify_manifest,
    verify_snapshot_bindings,
)
from .planner import DeterministicProvider, OllamaProvider, PlannerProvider, build_plan
from .receipts import build_receipt, verify_receipt
from .storage import CommitmentRecord, Repository


@dataclass(frozen=True, slots=True)
class FixtureBundle:
    episode: HeatEpisode
    workers: tuple[Worker, ...]
    policy: Policy
    reserve: Reserve
    snapshots: tuple[SourceSnapshot, ...]
    conditions: tuple[HourlyCondition, ...]
    cooling_points: tuple[CoolingPoint, ...]
    allocation_candidates: tuple[AllocationCandidate, ...]
    sources: tuple[dict[str, Any], ...]


class HeatReserveService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._judge_lock = threading.RLock()
        require_verified_manifest(settings.fixture_dir)
        self.fixtures = load_fixture_bundle(settings.fixture_dir)
        self.repository = Repository(settings.database_path)
        self.provider = _make_provider(settings)
        self.reset_demo()

    def readiness(self) -> dict[str, Any]:
        errors = self._integrity_errors()
        reserve = self.repository.get_reserve(self.fixtures.reserve.reserve_id)
        if reserve is None:
            errors.append("reserve_missing")
        return {
            "ready": not errors,
            "mode": self.settings.mode,
            "planner_provider": self.provider.name,
            "fixture_manifest": (
                "VERIFIED" if not verify_manifest(self.settings.fixture_dir) else "INVALID"
            ),
            "errors": errors,
        }

    def reset_demo(self) -> dict[str, Any]:
        with self._judge_lock:
            self.repository.reset_demo(
                self.fixtures.workers, self.fixtures.policy, self.fixtures.reserve
            )
        return {
            "status": "RESET",
            "fixture_id": "judge-mode-v1",
            "network_required": False,
            "reserve_minor": self.fixtures.reserve.initial_minor,
        }

    def get_episode(self, episode_id: str) -> HeatEpisode:
        if episode_id != self.fixtures.episode.episode_id:
            raise KeyError(f"Unknown episode: {episode_id}")
        return self.fixtures.episode

    def create_commitment(
        self, worker_id: str, episode_id: str, policy_id: str, policy_version: str
    ) -> CommitmentRecord:
        worker = self._worker(worker_id)
        episode = self.get_episode(episode_id)
        policy = self.repository.get_policy(policy_id, policy_version)
        if policy is None:
            raise KeyError(f"Unknown policy {policy_id}@{policy_version}")
        snapshots = tuple(
            snapshot for snapshot in self.fixtures.snapshots
            if snapshot.snapshot_id in episode.warning_snapshot_ids
        )
        return self.repository.create_or_reuse_commitment(
            worker=worker, episode=episode, policy=policy, snapshots=snapshots
        )

    def create_plan(self, worker_id: str, episode_id: str) -> AdaptationPlan:
        worker = self._worker(worker_id)
        episode = self.get_episode(episode_id)
        if worker.zone_id != episode.zone_id:
            raise ValueError("No verified hourly replay facts are available for the worker zone")
        points = tuple(
            point for point in self.fixtures.cooling_points if point.zone_id == worker.zone_id
        )
        plan = build_plan(
            worker, episode.episode_id, self.fixtures.conditions, points, self.provider
        )
        self.repository.save_plan(plan)
        return plan

    def create_receipt(
        self, worker_id: str, episode_id: str, plan: AdaptationPlan | None = None
    ):
        worker = self._worker(worker_id)
        policy = self.fixtures.policy
        record = self.repository.get_commitment_for(
            tenant_id=worker.tenant_id,
            worker_id=worker.worker_id,
            episode_id=episode_id,
            policy_id=policy.policy_id,
            policy_version=policy.version,
        )
        if record is None:
            raise ValueError("A qualified commitment is required before creating a receipt")
        resolved_plan = plan or self.create_plan(worker_id, episode_id)
        receipt = build_receipt(
            receipt_id=f"receipt-{record.commitment_id.removeprefix('commit-')}",
            tenant_id=worker.tenant_id,
            worker_id=worker.worker_id,
            episode_id=episode_id,
            commitment_id=record.commitment_id,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            decision=record.decision,
            plan=resolved_plan,
            source_snapshot_ids=tuple(
                snapshot.snapshot_id for snapshot in self.fixtures.snapshots if snapshot.verified
            ),
            created_at=self.fixtures.episode.start_at,
        )
        self.repository.save_receipt(receipt)
        return receipt

    def allocator_scenarios(self, budget_minor: int | None = None) -> tuple[dict[str, Any], ...]:
        budget = budget_minor if budget_minor is not None else self.fixtures.reserve.initial_minor
        return tuple(_allocation_payload(result) for result in compare_strategies(
            self.fixtures.allocation_candidates, budget
        ))

    def run_judge_demo(self) -> dict[str, Any]:
        with self._judge_lock:
            self.reset_demo()
            worker, policy = self.fixtures.workers[0], self.fixtures.policy
            record = self.create_commitment(
                worker.worker_id, self.fixtures.episode.episode_id,
                policy.policy_id, policy.version,
            )
            if record.decision.status != "QUALIFIED":
                raise RuntimeError("Judge fixture no longer produces a qualified commitment")
            plan = self.create_plan(worker.worker_id, self.fixtures.episode.episode_id)
            receipt = self.create_receipt(worker.worker_id, self.fixtures.episode.episode_id, plan)
            return self._judge_payload(worker, policy, record, plan, receipt)

    def evidence_sources(self) -> tuple[dict[str, Any], ...]:
        return self.fixtures.sources

    def receipt(self, receipt_id: str):
        receipt = self.repository.get_receipt(receipt_id)
        if receipt is None:
            raise KeyError(f"Unknown receipt: {receipt_id}")
        return receipt

    def _worker(self, worker_id: str) -> Worker:
        worker = self.repository.get_worker(worker_id)
        if worker is None:
            raise KeyError(f"Unknown worker: {worker_id}")
        return worker

    def _integrity_errors(self) -> list[str]:
        errors = verify_manifest(self.settings.fixture_dir)
        errors.extend(verify_snapshot_bindings(self.settings.fixture_dir, self.fixtures.snapshots))
        try:
            warning = load_json(self.settings.fixture_dir / "warning.json")
            rebuilt = build_episode_from_warning(
                warning, self.fixtures.policy,
                snapshot_id=self.fixtures.episode.warning_snapshot_ids[0],
            )
            if rebuilt != self.fixtures.episode:
                errors.append("episode_rebuild_mismatch")
        except (ValueError, KeyError, IndexError) as exc:
            errors.append(f"episode_rebuild_error:{exc}")
        return errors

    def _judge_payload(self, worker, policy, record, plan, receipt) -> dict[str, Any]:
        tampered = copy.deepcopy(receipt.model_dump(mode="json"))
        tampered["amount_minor"] += 100
        return {
            "scenario": _scenario_summary(worker),
            "episode": self.fixtures.episode,
            "commitment": {
                "commitment_id": record.commitment_id,
                "created": record.created,
                "authority": "DETERMINISTIC_POLICY_ENGINE",
                "simulated": True,
                "decision": record.decision,
            },
            "plan": plan,
            "receipt": receipt,
            "receipt_verification": verify_receipt(receipt),
            "tamper_verification": verify_receipt(tampered),
            "allocator": self.allocator_scenarios(),
            "reserve": self.repository.get_reserve(policy.reserve_id),
            "evidence": self.fixtures.sources,
            "reconciliation": {
                "ledger_reconciles": self.repository.reserve_reconciles(policy.reserve_id),
                "commitment_count": self.repository.commitment_count(),
                "evidence_class": "MEASURED",
            },
        }


def _allocation_payload(result) -> dict[str, Any]:
    return {
        "strategy": result.strategy,
        "selected_worker_ids": result.selected_worker_ids,
        "unselected_worker_ids": result.unselected_worker_ids,
        "spend_minor": result.spend_minor,
        "budget_minor": result.budget_minor,
        "projected_high_heat_minutes_addressed": result.projected_high_heat_minutes_addressed,
        "zone_coverage": result.zone_coverage,
        "explanations": result.explanations,
        "evidence_class": "SIMULATED",
    }


def _scenario_summary(worker: Worker) -> dict[str, Any]:
    preferred = worker.constraints.preferred_windows[0]
    return {
        "title": "Illustrative Delhi NCR heat replay",
        "worker_id": worker.worker_id,
        "worker_type": worker.worker_type,
        "zone_id": worker.zone_id,
        "preferred_window": {
            "start": preferred.start,
            "end": preferred.end,
            "required_work_minutes": worker.constraints.required_work_minutes,
        },
        "claim": (
            "A warning can create an income-versus-exposure trade-off "
            "for output-paid workers."
        ),
        "evidence_class": "SIMULATED",
    }


def load_fixture_bundle(fixture_dir: Path) -> FixtureBundle:
    episode = HeatEpisode.model_validate(load_json(fixture_dir / "episode.json"))
    policy = Policy.model_validate(load_json(fixture_dir / "policy.json"))
    reserve_payload = load_json(fixture_dir / "reserve.json")
    reserve_payload.pop("fixture_class", None)
    reserve = Reserve.model_validate(reserve_payload)
    workers = tuple(
        Worker.model_validate(item)
        for item in load_json(fixture_dir / "workers.json")["workers"]
    )
    snapshots = tuple(
        SourceSnapshot.model_validate(item)
        for item in load_json(fixture_dir / "source_snapshots.json")["snapshots"]
    )
    conditions = tuple(
        HourlyCondition.model_validate(item)
        for item in load_json(fixture_dir / "weather.json")["rows"]
    )
    cooling_points = tuple(
        CoolingPoint.model_validate(item)
        for item in load_json(fixture_dir / "cooling_points.json")["points"]
    )
    bindings = verify_snapshot_bindings(fixture_dir, snapshots)
    if bindings:
        raise ValueError("Snapshot binding verification failed: " + "; ".join(bindings))
    _validate_fact_sources(snapshots, conditions, cooling_points)
    warning = load_json(fixture_dir / "warning.json")
    rebuilt = build_episode_from_warning(
        warning, policy, snapshot_id=episode.warning_snapshot_ids[0]
    )
    if rebuilt != episode:
        raise ValueError("Frozen episode does not match deterministic episode builder output")
    return FixtureBundle(
        episode=episode, workers=workers, policy=policy, reserve=reserve,
        snapshots=snapshots, conditions=conditions, cooling_points=cooling_points,
        allocation_candidates=_load_candidates(fixture_dir),
        sources=tuple(load_json(fixture_dir / "sources.json")["sources"]),
    )



def _validate_fact_sources(
    snapshots: tuple[SourceSnapshot, ...],
    conditions: tuple[HourlyCondition, ...],
    cooling_points: tuple[CoolingPoint, ...],
) -> None:
    by_id = {snapshot.snapshot_id: snapshot for snapshot in snapshots}
    for condition in conditions:
        snapshot = by_id.get(condition.source_snapshot_id)
        if snapshot is None or not snapshot.verified or snapshot.source_type != "hourly_weather":
            raise ValueError(
                f"Hourly fact {condition.fact_id} is not bound to a verified "
                "hourly_weather snapshot"
            )
    for point in cooling_points:
        snapshot = by_id.get(point.source_snapshot_id)
        if snapshot is None or not snapshot.verified or snapshot.source_type != "cooling_points":
            raise ValueError(
                f"Cooling fact {point.fact_id} is not bound to a verified cooling_points snapshot"
            )

def _load_candidates(fixture_dir: Path) -> tuple[AllocationCandidate, ...]:
    return tuple(
        AllocationCandidate(
            worker_id=item["worker_id"], zone_id=item["zone_id"],
            cost_minor=int(item["cost_minor"]),
            modeled_high_heat_minutes=int(item["modeled_high_heat_minutes"]),
            burden_score=float(item["burden_score"]),
        )
        for item in load_json(fixture_dir / "allocation_candidates.json")["candidates"]
    )


def _make_provider(settings: Settings) -> PlannerProvider:
    if settings.mode == "safe_fallback":
        return DeterministicProvider()
    if settings.planner_provider == "ollama":
        return OllamaProvider(settings.ollama_url, settings.ollama_model)
    return DeterministicProvider()
