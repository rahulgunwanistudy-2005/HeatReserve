from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StrategyName = Literal["equal", "impact_first", "fairness_constrained", "optimized"]


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


def allocate_optimized(
    candidates: tuple[AllocationCandidate, ...], budget_minor: int
) -> AllocationResult:
    """
    0/1 knapsack optimizer: maximize sum of modeled_high_heat_minutes_addressed
    subject to sum(cost_minor) <= budget_minor.

    Uses exact DP in O(n * budget_in_units).
    Budget is scaled to ₹100 units to keep table size tractable.
    Falls back to impact_first if budget is very large.

    INVARIANT: this is scenario analysis only — calling this endpoint never
    debits the reserve or creates commitments.
    """
    if not candidates or budget_minor == 0:
        return AllocationResult(
            strategy="optimized",
            selected_worker_ids=(),
            unselected_worker_ids=tuple(c.worker_id for c in candidates),
            spend_minor=0,
            budget_minor=budget_minor,
            projected_high_heat_minutes_addressed=0,
            zone_coverage=(),
            explanations={c.worker_id: "Budget insufficient for any candidate." for c in candidates},
        )

    # Scale to ₹100 units so DP table stays manageable (max ~10k cells for 1M budget)
    scale = 100
    cap = budget_minor // scale
    n = len(candidates)
    costs = [max(1, c.cost_minor // scale) for c in candidates]
    values = [c.modeled_high_heat_minutes for c in candidates]

    # Guard against pathologically large budgets
    if cap > 20_000:
        return allocate_impact_first(candidates, budget_minor)

    # Standard 0/1 knapsack DP with 2D table for exact reconstruction
    # dp[i][j] = max value using items 0..i-1 with capacity j
    dp = [[0] * (cap + 1) for _ in range(n + 1)]
    for i in range(n):
        w, v = costs[i], values[i]
        for j in range(cap + 1):
            dp[i + 1][j] = dp[i][j]
            if j >= w and dp[i][j - w] + v > dp[i + 1][j]:
                dp[i + 1][j] = dp[i][j - w] + v

    # Reconstruct selected set by tracing back through 2D table
    selected_set: list[AllocationCandidate] = []
    remaining_cap = cap
    for i in range(n - 1, -1, -1):
        if dp[i + 1][remaining_cap] != dp[i][remaining_cap]:
            selected_set.append(candidates[i])
            remaining_cap -= costs[i]

    # Verify budget in original units (scaled rounding may permit slight overspend)
    actual_spend = sum(c.cost_minor for c in selected_set)
    if actual_spend > budget_minor:
        # Remove the most expensive selection until feasible
        selected_set.sort(key=lambda c: -c.cost_minor)
        while selected_set and sum(c.cost_minor for c in selected_set) > budget_minor:
            selected_set.pop(0)

    return _finalize(
        "optimized",
        selected_set,
        candidates,
        budget_minor,
        (
            "Selected by exact 0/1 knapsack DP to maximize total modeled "
            "high-heat minutes addressed within budget. "
            "Scenario analysis only — does not commit reserve funds."
        ),
    )


def compare_strategies(
    candidates: tuple[AllocationCandidate, ...], budget_minor: int
) -> tuple[AllocationResult, ...]:
    if budget_minor < 0:
        raise ValueError("budget must be non-negative")
    return (
        allocate_equal(candidates, budget_minor),
        allocate_impact_first(candidates, budget_minor),
        allocate_fairness_constrained(candidates, budget_minor),
        allocate_optimized(candidates, budget_minor),
    )
