from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StrategyName = Literal["equal", "impact_first", "fairness_constrained"]


@dataclass(frozen=True, slots=True)
class AllocationCandidate:
    worker_id: str
    zone_id: str
    cost_minor: int
    modeled_high_heat_minutes: int
    burden_score: float


@dataclass(frozen=True, slots=True)
class AllocationResult:
    strategy: StrategyName
    selected_worker_ids: tuple[str, ...]
    unselected_worker_ids: tuple[str, ...]
    spend_minor: int
    budget_minor: int
    projected_high_heat_minutes_addressed: int
    zone_coverage: tuple[str, ...]
    explanations: dict[str, str]


def _finalize(
    strategy: StrategyName,
    selected: list[AllocationCandidate],
    all_candidates: tuple[AllocationCandidate, ...],
    budget_minor: int,
    rationale: str,
) -> AllocationResult:
    selected_ids = {item.worker_id for item in selected}
    explanations = {
        item.worker_id: (
            rationale
            if item.worker_id in selected_ids
            else "Not selected within the fixed scenario budget."
        )
        for item in all_candidates
    }
    return AllocationResult(
        strategy=strategy,
        selected_worker_ids=tuple(item.worker_id for item in selected),
        unselected_worker_ids=tuple(
            item.worker_id for item in all_candidates if item.worker_id not in selected_ids
        ),
        spend_minor=sum(item.cost_minor for item in selected),
        budget_minor=budget_minor,
        projected_high_heat_minutes_addressed=sum(
            item.modeled_high_heat_minutes for item in selected
        ),
        zone_coverage=tuple(sorted({item.zone_id for item in selected})),
        explanations=explanations,
    )


def allocate_equal(
    candidates: tuple[AllocationCandidate, ...], budget_minor: int
) -> AllocationResult:
    selected: list[AllocationCandidate] = []
    spent = 0
    for item in sorted(candidates, key=lambda candidate: candidate.worker_id):
        if spent + item.cost_minor <= budget_minor:
            selected.append(item)
            spent += item.cost_minor
    return _finalize(
        "equal",
        selected,
        candidates,
        budget_minor,
        "Selected by stable first-qualified ordering under the same fixed budget.",
    )


def allocate_impact_first(
    candidates: tuple[AllocationCandidate, ...], budget_minor: int
) -> AllocationResult:
    ranked = sorted(
        candidates,
        key=lambda item: (
            -(item.modeled_high_heat_minutes / max(item.cost_minor, 1)),
            -item.burden_score,
            item.worker_id,
        ),
    )
    selected = _fit_ranked(ranked, budget_minor)
    return _finalize(
        "impact_first",
        selected,
        candidates,
        budget_minor,
        "Selected for higher modeled high-heat minutes addressed per minor currency unit.",
    )


def allocate_fairness_constrained(
    candidates: tuple[AllocationCandidate, ...], budget_minor: int
) -> AllocationResult:
    by_zone: dict[str, list[AllocationCandidate]] = {}
    for item in candidates:
        by_zone.setdefault(item.zone_id, []).append(item)
    selected: list[AllocationCandidate] = []
    spent = 0
    for zone_id in sorted(by_zone):
        best = max(
            by_zone[zone_id],
            key=lambda item: (item.modeled_high_heat_minutes, item.burden_score, item.worker_id),
        )
        if spent + best.cost_minor <= budget_minor:
            selected.append(best)
            spent += best.cost_minor
    remaining = [item for item in candidates if item not in selected]
    ranked = sorted(
        remaining,
        key=lambda item: (-item.modeled_high_heat_minutes, -item.burden_score, item.worker_id),
    )
    selected.extend(_fit_ranked(ranked, budget_minor - spent))
    return _finalize(
        "fairness_constrained",
        selected,
        candidates,
        budget_minor,
        "Selected with a one-per-zone coverage pass before impact-ranked allocation.",
    )


def _fit_ranked(ranked: list[AllocationCandidate], budget_minor: int) -> list[AllocationCandidate]:
    selected: list[AllocationCandidate] = []
    spent = 0
    for item in ranked:
        if spent + item.cost_minor <= budget_minor:
            selected.append(item)
            spent += item.cost_minor
    return selected


def compare_strategies(
    candidates: tuple[AllocationCandidate, ...], budget_minor: int
) -> tuple[AllocationResult, ...]:
    if budget_minor < 0:
        raise ValueError("budget must be non-negative")
    return (
        allocate_equal(candidates, budget_minor),
        allocate_impact_first(candidates, budget_minor),
        allocate_fairness_constrained(candidates, budget_minor),
    )
