"""Tests for the knapsack allocator and compare_strategies with 4 strategies."""
from __future__ import annotations

import pytest

from heatreserve.allocator import (
    AllocationCandidate,
    allocate_optimized,
    compare_strategies,
)


def _c(wid: str, zone: str, cost: int, minutes: int, score: float = 0.5) -> AllocationCandidate:
    return AllocationCandidate(
        worker_id=wid,
        zone_id=zone,
        cost_minor=cost,
        modeled_high_heat_minutes=minutes,
        burden_score=score,
    )


CANDIDATES = (
    _c("w1", "zone-a", 50_00, 120),  # ₹500, 120 min
    _c("w2", "zone-b", 50_00, 300),  # ₹500, 300 min — high impact
    _c("w3", "zone-a", 30_00, 60),   # ₹300, 60 min
    _c("w4", "zone-c", 80_00, 180),  # ₹800, 180 min
    _c("w5", "zone-b", 20_00, 45),   # ₹200, 45 min
)


class TestKnapsackAllocator:
    def test_never_exceeds_budget(self):
        for budget in (0, 10_00, 50_00, 100_00, 500_00, 10_000_00):
            result = allocate_optimized(CANDIDATES, budget)
            assert result.spend_minor <= budget, (
                f"budget={budget} but spend={result.spend_minor}"
            )

    def test_optimizes_impact_versus_equal(self):
        """Knapsack should reach at least as much impact as equal strategy."""
        from heatreserve.allocator import allocate_equal
        budget = 120_00  # ₹1200
        opt = allocate_optimized(CANDIDATES, budget)
        eq = allocate_equal(CANDIDATES, budget)
        # Knapsack maximizes projected minutes — should be >= equal strategy
        assert (
            opt.projected_high_heat_minutes_addressed
            >= eq.projected_high_heat_minutes_addressed
        ), (
            f"knapsack={opt.projected_high_heat_minutes_addressed} "
            f"< equal={eq.projected_high_heat_minutes_addressed}"
        )

    def test_zero_budget_selects_nothing(self):
        result = allocate_optimized(CANDIDATES, 0)
        assert result.selected_worker_ids == ()
        assert result.spend_minor == 0

    def test_no_duplicate_workers(self):
        result = allocate_optimized(CANDIDATES, 1_000_00)
        assert len(result.selected_worker_ids) == len(set(result.selected_worker_ids))

    def test_all_candidates_covered_in_output(self):
        result = allocate_optimized(CANDIDATES, 100_00)
        all_ids = set(result.selected_worker_ids) | set(result.unselected_worker_ids)
        assert all_ids == {c.worker_id for c in CANDIDATES}

    def test_empty_candidates(self):
        result = allocate_optimized((), 100_00)
        assert result.selected_worker_ids == ()


class TestCompareStrategies:
    def test_returns_four_strategies(self):
        results = compare_strategies(CANDIDATES, 100_00)
        assert len(results) == 4
        strategies = {r.strategy for r in results}
        assert "equal" in strategies
        assert "impact_first" in strategies
        assert "fairness_constrained" in strategies
        assert "optimized" in strategies

    def test_all_strategies_respect_budget(self):
        budget = 75_00
        for result in compare_strategies(CANDIDATES, budget):
            assert result.spend_minor <= budget, (
                f"strategy={result.strategy} spend={result.spend_minor} > budget={budget}"
            )

    def test_negative_budget_raises(self):
        with pytest.raises(ValueError, match="budget"):
            compare_strategies(CANDIDATES, -1)

    def test_deterministic_across_calls(self):
        r1 = compare_strategies(CANDIDATES, 100_00)
        r2 = compare_strategies(CANDIDATES, 100_00)
        for a, b in zip(r1, r2):
            assert a.selected_worker_ids == b.selected_worker_ids
            assert a.spend_minor == b.spend_minor
