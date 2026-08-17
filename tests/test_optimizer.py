"""Tests for the DP constraint optimization planner."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from heatreserve.burden import ScoredHour
from heatreserve.domain import HourlyCondition
from heatreserve.optimizer import _baseline_burden, _dp_optimize, optimize_work_hours


TZ = ZoneInfo("Asia/Kolkata")


def _make_hour(hour: int, score: float, snap_id: str = "snap-1") -> ScoredHour:
    at = datetime(2024, 5, 25, hour, 0, tzinfo=TZ)
    solar = min(1.0, max(0.0, score))
    condition = HourlyCondition(
        fact_id=f"fact-h{hour:02d}",
        at=at,
        temperature_c=35.0 + score * 5,
        relative_humidity_pct=60.0,
        apparent_temperature_c=38.0 + score * 5,
        solar_proxy=solar,
        warning_flag=score > 0.7,
        source_snapshot_id=snap_id,
    )
    return ScoredHour(condition=condition, score=score)


def _hours(specs: list[tuple[int, float]]) -> list[ScoredHour]:
    return [_make_hour(h, s) for h, s in specs]


class TestDPOptimize:
    def test_selects_minimum_burden_hours(self):
        """With no consecutive constraint, should pick the globally cheapest hours."""
        available = _hours([(6, 0.2), (7, 0.3), (8, 0.8), (9, 0.9), (10, 0.1), (11, 0.4)])
        selected, feasible, status = _dp_optimize(available, required=3, max_consecutive=6)
        assert feasible
        assert status == "OPTIMAL"
        assert len(selected) == 3
        scores = {h.score for h in selected}
        # Cheapest 3: 0.1, 0.2, 0.3
        assert scores == {0.1, 0.2, 0.3}

    def test_consecutive_constraint_breaks_greedy_optimum(self):
        """When the 3 cheapest hours are all adjacent and max_consecutive=2, DP must find alt."""
        # hours 8,9,10 have lowest burden but are 3 consecutive → violates max_consecutive=2
        available = _hours([
            (6, 0.9), (7, 0.9), (8, 0.1), (9, 0.1), (10, 0.1), (11, 0.8), (14, 0.2)
        ])
        selected, feasible, status = _dp_optimize(available, required=3, max_consecutive=2)
        assert feasible
        hours_selected = sorted(h.condition.at.hour for h in selected)
        # Should not select 8, 9, 10 all three (that would be 3 consecutive)
        run_of_3 = [8, 9, 10] == hours_selected
        assert not run_of_3, "DP should respect max_consecutive=2"
        # Verify no 3-consecutive selected hours
        consecutive_count = 1
        for i in range(1, len(hours_selected)):
            if hours_selected[i] == hours_selected[i - 1] + 1:
                consecutive_count += 1
                assert consecutive_count <= 2
            else:
                consecutive_count = 1

    def test_exactly_required_hours_selected(self):
        available = _hours([(h, 0.5) for h in range(6, 18)])
        for required in (2, 4, 6):
            selected, feasible, _ = _dp_optimize(available, required, max_consecutive=4)
            assert feasible
            assert len(selected) == required

    def test_infeasible_when_insufficient_hours(self):
        available = _hours([(6, 0.3), (7, 0.2)])
        selected, feasible, status = _dp_optimize(available, required=5, max_consecutive=4)
        assert not feasible
        assert "INFEASIBLE" in status

    def test_trivially_feasible_single_hour(self):
        available = _hours([(8, 0.5)])
        selected, feasible, status = _dp_optimize(available, required=1, max_consecutive=1)
        assert feasible
        assert len(selected) == 1

    def test_reconstruction_is_sorted_by_time(self):
        available = _hours([(10, 0.9), (6, 0.1), (8, 0.5), (14, 0.3)])
        selected, feasible, _ = _dp_optimize(available, required=3, max_consecutive=4)
        assert feasible
        times = [h.condition.at for h in selected]
        assert times == sorted(times)

    def test_non_adjacent_hours_do_not_count_as_consecutive(self):
        """Hours 6 and 8 are not adjacent (gap of 2h), so they don't form a consecutive run."""
        # Only hours 6, 8, 10 available (non-adjacent)
        available = _hours([(6, 0.3), (8, 0.2), (10, 0.1)])
        selected, feasible, status = _dp_optimize(available, required=3, max_consecutive=1)
        # max_consecutive=1 means at most 1 adjacent hour in a row
        # Since none of the hours are adjacent to each other, all 3 can be selected
        assert feasible
        assert len(selected) == 3


class TestOptimizeWorkHours:
    def test_greedy_and_dp_agree_without_constraint(self):
        """Without a binding consecutive constraint, DP picks minimum burden hours."""
        # scores 0.0..0.6 (capped at 1.0 for solar proxy)
        available = _hours([(h, 0.1 * (h - 6)) for h in range(6, 13)])
        result = optimize_work_hours(available, required=4, max_consecutive=12)
        assert result.feasible
        assert result.solver_status == "OPTIMAL"
        # Should pick the 4 lowest burden hours (h=6,7,8,9) with scores 0.0,0.1,0.2,0.3
        assert abs(result.total_burden - (0.0 + 0.1 + 0.2 + 0.3)) < 1e-6

    def test_burden_delta_is_positive_when_optimizer_beats_baseline(self):
        """Optimizer should reduce burden relative to the time-order baseline."""
        # High burden in morning, low in evening (unusual for heat but tests direction)
        available = _hours([
            (6, 0.9), (7, 0.8), (8, 0.7),  # worker's default (first 3 in time order)
            (14, 0.1), (15, 0.2), (16, 0.3),  # lower burden hours later
        ])
        result = optimize_work_hours(available, required=3, max_consecutive=3)
        assert result.feasible
        # Optimizer should pick 14, 15, 16 (lower burden) over 6, 7, 8
        assert result.total_burden < result.baseline_burden
        assert result.burden_delta > 0

    def test_falls_back_to_greedy_when_infeasible(self):
        """With a very tight consecutive constraint, DP may be infeasible → greedy fallback."""
        # All hours are adjacent, max_consecutive=1 means no 2 consecutive hours ever
        # required=5, only 5 adjacent hours → impossible with max_consecutive=1
        available = _hours([(h, 0.5) for h in range(6, 11)])  # 5 adjacent hours
        result = optimize_work_hours(available, required=5, max_consecutive=1)
        # 5 adjacent hours, need all 5, but max_consecutive=1 → infeasible
        assert not result.feasible
        assert "GREEDY_FALLBACK" in result.solver_status
        assert len(result.selected) == 5  # greedy still picks all 5

    def test_budget_conservation_all_hours_within_available(self):
        """All selected hours must come from the available list."""
        available = _hours([(h, float(h) / 20) for h in range(6, 14)])
        result = optimize_work_hours(available, required=3, max_consecutive=4)
        avail_ids = {h.condition.fact_id for h in available}
        for h in result.selected:
            assert h.condition.fact_id in avail_ids

    def test_empty_available_returns_trivial(self):
        result = optimize_work_hours([], required=0, max_consecutive=3)
        assert result.selected == ()

    def test_optimizer_version_is_reported(self):
        available = _hours([(h, 0.5) for h in range(6, 10)])
        result = optimize_work_hours(available, required=2, max_consecutive=3)
        assert result.solver_version.startswith("dp-optimizer")


class TestBaselineBurden:
    def test_uses_time_order_not_burden_order(self):
        """Baseline is the FIRST required hours in time order, not lowest burden."""
        available = _hours([(6, 0.9), (7, 0.1), (8, 0.5)])
        # Baseline for required=2 is hours 6 and 7 (time order)
        baseline = _baseline_burden(available, 2)
        assert abs(baseline - (0.9 + 0.1)) < 1e-6
