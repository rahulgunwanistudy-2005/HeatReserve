from heatreserve.allocator import compare_strategies


def test_allocator_never_exceeds_budget(service) -> None:
    candidates = service.fixtures.allocation_candidates
    for budget in (0, 20000, 40000, 80000, 120000, 500000):
        for result in compare_strategies(candidates, budget):
            assert result.spend_minor <= budget
            assert len(result.selected_worker_ids) == len(set(result.selected_worker_ids))


def test_allocator_is_deterministic(service) -> None:
    candidates = service.fixtures.allocation_candidates
    first = compare_strategies(candidates, 120000)
    for _ in range(20):
        assert compare_strategies(candidates, 120000) == first


def test_fairness_strategy_covers_each_zone_when_feasible(service) -> None:
    result = compare_strategies(service.fixtures.allocation_candidates, 120000)[2]
    assert set(result.zone_coverage) == {
        "DELHI_DEMO_ZONE_A",
        "DELHI_DEMO_ZONE_B",
        "DELHI_DEMO_ZONE_C",
    }
