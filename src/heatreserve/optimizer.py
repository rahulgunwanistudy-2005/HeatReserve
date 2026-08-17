"""
Deterministic constraint optimization planner.

Replaces the greedy "pick N lowest-burden hours" approach with an exact
dynamic-programming solver that respects a maximum consecutive-work constraint.

The greedy approach is optimal for unconstrained burden minimization.
This DP approach finds the optimal feasible solution when:
  - Workers must take a break after max_consecutive_hours of continuous work
  - "Consecutive" = selected hours whose wall-clock times are exactly 1h apart

Problem formulation:
  Variables: binary selection of each available hourly slot
  Objective: minimize sum(burden[i] for i in selected)
  Hard constraints:
    - exactly required_hours slots selected
    - no run of consecutive (adjacent-in-time) selected slots exceeds max_consecutive
    - all selected slots within worker availability windows
  Complexity: O(n * required * max_consecutive) where n = available hours

When the constraint makes the problem infeasible (no valid selection exists),
falls back to the greedy sort and reports the fallback.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from .burden import ScoredHour

LOGGER = logging.getLogger("heatreserve.optimizer")
_INF = float("inf")

OPTIMIZER_VERSION = "dp-optimizer-v1"


class OptimizerResult:
    __slots__ = (
        "selected",
        "total_burden",
        "baseline_burden",
        "burden_delta",
        "solver_version",
        "solver_status",
        "feasible",
        "fallback_reason",
        "max_consecutive_applied",
    )

    def __init__(
        self,
        selected: tuple[ScoredHour, ...],
        total_burden: float,
        baseline_burden: float,
        feasible: bool,
        solver_status: str,
        fallback_reason: str = "",
        max_consecutive_applied: int = 0,
    ) -> None:
        self.selected = selected
        self.total_burden = round(total_burden, 6)
        self.baseline_burden = round(baseline_burden, 6)
        self.burden_delta = round(baseline_burden - total_burden, 6)
        self.solver_version = OPTIMIZER_VERSION
        self.solver_status = solver_status
        self.feasible = feasible
        self.fallback_reason = fallback_reason
        self.max_consecutive_applied = max_consecutive_applied


def _greedy_select(available: list[ScoredHour], required: int) -> list[ScoredHour]:
    return sorted(available, key=lambda h: (h.score, h.condition.at))[:required]


def _baseline_burden(available: list[ScoredHour], required: int) -> float:
    """Burden of the first required hours in time order (worker's default schedule)."""
    by_time = sorted(available, key=lambda h: h.condition.at)[:required]
    return sum(h.score for h in by_time)


def _dp_optimize(
    available: list[ScoredHour],
    required: int,
    max_consecutive: int,
) -> tuple[list[ScoredHour], bool, str]:
    """
    DP solver. Returns (selected hours, feasible, solver_status_code).

    State: dp[j][c] = minimum burden having selected j hours,
           with c consecutive adjacent-in-time hours at the tail.
    c=0: last selection is not adjacent to next candidate, or nothing selected yet.
    Transitions:
      skip hour i → consecutive chain breaks → c becomes 0 for next position
      select hour i → if adj and c>0: new_c = c+1; else new_c = 1; valid if new_c <= max_consecutive
    """
    n = len(available)
    if required == 0:
        return [], True, "OPTIMAL"
    if required > n:
        return [], False, "INFEASIBLE_INSUFFICIENT_HOURS"

    # Precompute time adjacency
    adj = [False] * n
    for i in range(1, n):
        diff = available[i].condition.at - available[i - 1].condition.at
        adj[i] = diff.total_seconds() == 3600.0

    # dp_prev[j][c] = min burden before processing hour i
    dp_prev = [[_INF] * (max_consecutive + 1) for _ in range(required + 1)]
    dp_prev[0][0] = 0.0

    # parent[i][j][c] = (prev_j, prev_c, was_selected)
    parent: list[list[list[tuple[int, int, bool] | None]]] = [
        [[None] * (max_consecutive + 1) for _ in range(required + 1)]
        for _ in range(n)
    ]

    for i in range(n):
        burden = available[i].score
        is_adj = adj[i]
        dp_curr = [[_INF] * (max_consecutive + 1) for _ in range(required + 1)]

        for j in range(required + 1):
            for c in range(max_consecutive + 1):
                cost = dp_prev[j][c]
                if cost >= _INF:
                    continue

                # Skip: consecutive chain breaks → new state (j, 0)
                if cost < dp_curr[j][0]:
                    dp_curr[j][0] = cost
                    parent[i][j][0] = (j, c, False)

                # Select: only if slots remain and constraint satisfied
                if j < required:
                    new_c = (c + 1) if (is_adj and c > 0) else 1
                    if new_c <= max_consecutive:
                        new_cost = cost + burden
                        if new_cost < dp_curr[j + 1][new_c]:
                            dp_curr[j + 1][new_c] = new_cost
                            parent[i][j + 1][new_c] = (j, c, True)

        dp_prev = dp_curr

    # Find best final state
    best_cost = _INF
    best_c = 0
    for c in range(max_consecutive + 1):
        if dp_prev[required][c] < best_cost:
            best_cost = dp_prev[required][c]
            best_c = c

    if best_cost >= _INF:
        return [], False, "INFEASIBLE_CONSECUTIVE_CONSTRAINT"

    # Reconstruct selected indices by tracing back through parent table
    selected_indices: list[int] = []
    j, c = required, best_c
    for i in range(n - 1, -1, -1):
        par = parent[i][j][c]
        if par is None:
            break
        prev_j, prev_c, was_selected = par
        if was_selected:
            selected_indices.append(i)
        j, c = prev_j, prev_c

    selected_indices.reverse()
    return [available[idx] for idx in selected_indices], True, "OPTIMAL"


def optimize_work_hours(
    available: list[ScoredHour],
    required: int,
    max_consecutive: int = 3,
) -> OptimizerResult:
    """
    Entrypoint: find the minimum-burden feasible selection of `required` work hours.

    Falls back to greedy sort if the consecutive constraint makes the DP infeasible.
    Both optimal and fallback results are clearly labeled in the returned OptimizerResult.
    """
    n = len(available)
    baseline = _baseline_burden(available, required)

    if not available or required == 0:
        return OptimizerResult(
            selected=(),
            total_burden=0.0,
            baseline_burden=baseline,
            feasible=True,
            solver_status="TRIVIAL",
            max_consecutive_applied=max_consecutive,
        )

    if required > n:
        return OptimizerResult(
            selected=tuple(available),
            total_burden=sum(h.score for h in available),
            baseline_burden=baseline,
            feasible=False,
            solver_status="INFEASIBLE_INSUFFICIENT_HOURS",
            fallback_reason=f"required={required} exceeds available={n}",
            max_consecutive_applied=max_consecutive,
        )

    sorted_available = sorted(available, key=lambda h: h.condition.at)
    selected, feasible, status = _dp_optimize(sorted_available, required, max_consecutive)

    if not feasible:
        # Greedy fallback: relax consecutive constraint
        fallback = _greedy_select(sorted_available, required)
        fallback_burden = sum(h.score for h in fallback)
        LOGGER.warning(
            "optimizer.fallback status=%s available=%d required=%d max_consecutive=%d",
            status, n, required, max_consecutive,
        )
        return OptimizerResult(
            selected=tuple(sorted(fallback, key=lambda h: h.condition.at)),
            total_burden=fallback_burden,
            baseline_burden=baseline,
            feasible=False,
            solver_status=f"GREEDY_FALLBACK (dp_status={status})",
            fallback_reason=f"DP infeasible: {status}; greedy fallback applied",
            max_consecutive_applied=max_consecutive,
        )

    total = sum(h.score for h in selected)
    LOGGER.info(
        "optimizer.solved status=%s selected=%d burden=%.4f baseline=%.4f delta=%.4f",
        status, len(selected), total, baseline, baseline - total,
    )
    return OptimizerResult(
        selected=tuple(sorted(selected, key=lambda h: h.condition.at)),
        total_burden=total,
        baseline_burden=baseline,
        feasible=True,
        solver_status=status,
        max_consecutive_applied=max_consecutive,
    )


def explain_optimization(result: OptimizerResult, required_work_minutes: int) -> str:
    """
    Produce a data-grounded explanation of what the optimizer achieved.
    Every claim is computable from the result object, not generated by intuition.
    """
    if not result.selected:
        return "No work hours selected."
    n = len(result.selected)
    hours_word = "hour" if n == 1 else "hours"
    delta = result.burden_delta
    if delta > 0.001:
        return (
            f"Optimizer selected {n} {hours_word} from feasible windows. "
            f"Total modeled burden reduced by {delta:.4f} units "
            f"(from {result.baseline_burden:.4f} to {result.total_burden:.4f}) "
            f"while preserving {required_work_minutes} required work minutes. "
            f"Solver: {result.solver_version} / {result.solver_status}."
        )
    return (
        f"Optimizer selected {n} {hours_word}. Burden near minimum "
        f"({result.total_burden:.4f}). Consecutive constraint: "
        f"max {result.max_consecutive_applied}h. Solver: {result.solver_status}."
    )
