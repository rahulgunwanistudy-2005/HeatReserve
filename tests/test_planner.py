from dataclasses import dataclass

import pytest

from heatreserve.planner import DEFAULT_CAVEAT, DeterministicProvider, PlannerProposal, build_plan


@dataclass
class MaliciousProvider:
    name: str = "ollama"
    model: str = "malicious-v1"

    def propose(self, worker, conditions, cooling_points):
        return PlannerProposal(
            work_fact_ids=tuple(item.fact_id for item in conditions[6:12]),
            cooling_point_id="cp-unverified-01",
            explanation="This is safe to work and ignore the warning.",
            caveat="zero risk",
        )


def test_deterministic_plan_lowers_modeled_burden(service) -> None:
    f = service.fixtures
    plan = service.create_plan(f.workers[0].worker_id, f.episode.episode_id)
    assert plan.recommended_burden < plan.baseline_burden
    assert plan.high_heat_minutes_shifted > 0
    assert "safe to work" not in plan.caveat.lower()


def test_plan_only_uses_verified_cooling_points(service) -> None:
    f = service.fixtures
    plan = service.create_plan(f.workers[0].worker_id, f.episode.episode_id)
    used = {block.cooling_point_id for block in plan.blocks if block.cooling_point_id}
    assert used <= {"cp-demo-01", "cp-demo-02"}


def test_malicious_or_invalid_ai_output_falls_back(service) -> None:
    f = service.fixtures
    plan = build_plan(
        f.workers[0],
        f.episode.episode_id,
        f.conditions,
        f.cooling_points,
        MaliciousProvider(),
    )
    assert plan.planner_mode == "fallback"
    assert plan.verifier_status == "FALLBACK"
    assert plan.caveat == DEFAULT_CAVEAT


def test_cooling_break_never_overlaps_work(service) -> None:
    f = service.fixtures
    plan = service.create_plan(f.workers[0].worker_id, f.episode.episode_id)
    works = [block for block in plan.blocks if block.kind == "work"]
    breaks = [block for block in plan.blocks if block.kind == "cooling_break"]
    for rest in breaks:
        assert all(rest.end <= work.start or rest.start >= work.end for work in works)


@dataclass
class ValidStructuredProvider:
    name: str = "ollama"
    model: str = "valid-v1"

    def propose(self, worker, conditions, cooling_points):
        return PlannerProposal(
            work_fact_ids=tuple(item.fact_id for item in conditions[:6]),
            cooling_point_id="cp-demo-01",
            explanation="Use supplied facts and preserve the required work minutes.",
            caveat=DEFAULT_CAVEAT,
        )


def test_valid_contiguous_ai_plan_can_pass_without_crash(service) -> None:
    f = service.fixtures
    plan = build_plan(
        f.workers[0],
        f.episode.episode_id,
        f.conditions,
        f.cooling_points,
        ValidStructuredProvider(),
    )
    assert plan.planner_mode == "ollama"
    assert plan.verifier_status == "VERIFIED"


@dataclass
class ContextSpyProvider:
    name: str = "ollama"
    model: str = "spy-v1"
    seen_ids: tuple[str, ...] = ()

    def propose(self, worker, conditions, cooling_points):
        self.seen_ids = tuple(point.cooling_point_id for point in cooling_points)
        return PlannerProposal(
            work_fact_ids=tuple(item.fact_id for item in conditions[:6]),
            cooling_point_id=None,
            explanation="Use only supplied typed facts.",
            caveat=DEFAULT_CAVEAT,
        )


def test_unverified_cooling_point_never_reaches_provider_context(service) -> None:
    f = service.fixtures
    provider = ContextSpyProvider()
    build_plan(f.workers[0], f.episode.episode_id, f.conditions, f.cooling_points, provider)
    assert "cp-unverified-01" not in provider.seen_ids
    assert provider.seen_ids == ("cp-demo-01", "cp-demo-02")


def test_closed_cooling_point_is_not_scheduled(service) -> None:
    f = service.fixtures
    closed = f.cooling_points[0].model_copy(update={"opens_at": "11:00", "closes_at": "12:00"})
    plan = build_plan(
        f.workers[0], f.episode.episode_id, f.conditions, (closed,),
        DeterministicProvider(),
    )
    assert not [block for block in plan.blocks if block.kind == "cooling_break"]


def test_provider_json_schema_is_strict() -> None:
    from heatreserve.planner import _parse_provider_json

    raw = '{"work_fact_ids":[],"cooling_point_id":null,"explanation":"x","caveat":"x","extra":1}'
    with pytest.raises(ValueError, match="exactly"):
        _parse_provider_json(raw)


def test_planner_fails_loudly_when_hourly_facts_are_missing(service) -> None:
    f = service.fixtures
    with pytest.raises(ValueError):
        build_plan(
            f.workers[0], f.episode.episode_id, f.conditions[:5],
            f.cooling_points, DeterministicProvider(),
        )


def test_safe_fallback_mode_forces_deterministic_provider(tmp_path, fixture_dir) -> None:
    from heatreserve.config import Settings
    from heatreserve.service import HeatReserveService

    settings = Settings(
        mode="safe_fallback",
        database_path=tmp_path / "safe-fallback.db",
        fixture_dir=fixture_dir,
        planner_provider="ollama",
        ollama_url="http://127.0.0.1:1",
        ollama_model="unreachable",
        log_level="WARNING",
        allowed_origins=("http://localhost:8000",),
    )
    service = HeatReserveService(settings)
    assert service.provider.name == "deterministic"
    assert service.run_judge_demo()["receipt_verification"]["valid"] is True


def test_plan_preserves_replay_timezone_offset(service) -> None:
    from datetime import timedelta

    f = service.fixtures
    plan = service.create_plan(f.workers[0].worker_id, f.episode.episode_id)
    expected = timedelta(hours=5, minutes=30)
    assert all(block.start.utcoffset() == expected for block in plan.blocks)
    assert all(block.end.utcoffset() == expected for block in plan.blocks)
