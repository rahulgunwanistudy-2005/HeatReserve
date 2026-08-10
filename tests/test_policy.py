from heatreserve.domain import Reserve, SourceSnapshot
from heatreserve.policy import EvaluationContext, evaluate_policy


def test_policy_decision_is_deterministic(service) -> None:
    f = service.fixtures
    worker = f.workers[0]
    snapshots = tuple(s for s in f.snapshots if s.snapshot_id in f.episode.warning_snapshot_ids)
    outputs = [
        evaluate_policy(
            f.policy,
            f.episode,
            worker,
            f.reserve,
            snapshots,
            EvaluationContext(worker.tenant_id),
        ).model_dump(mode="json")
        for _ in range(50)
    ]
    assert all(item == outputs[0] for item in outputs)


def test_unpublished_policy_fails_closed(service) -> None:
    f = service.fixtures
    policy = f.policy.model_copy(update={"status": "draft"})
    decision = evaluate_policy(
        policy,
        f.episode,
        f.workers[0],
        f.reserve,
        (f.snapshots[0],),
        EvaluationContext("demo-tenant"),
    )
    assert decision.status == "NOT_QUALIFIED"
    assert "POLICY_NOT_PUBLISHED" in decision.reason_codes


def test_unverified_warning_fails_closed(service) -> None:
    f = service.fixtures
    bad = SourceSnapshot.model_validate({**f.snapshots[0].model_dump(), "verified": False})
    decision = evaluate_policy(
        f.policy,
        f.episode,
        f.workers[0],
        f.reserve,
        (bad,),
        EvaluationContext("demo-tenant"),
    )
    assert decision.status == "NOT_QUALIFIED"
    assert "SOURCE_UNVERIFIED" in decision.reason_codes


def test_insufficient_reserve_does_not_go_negative(service) -> None:
    f = service.fixtures
    reserve = Reserve(
        reserve_id=f.reserve.reserve_id,
        tenant_id=f.reserve.tenant_id,
        currency="INR",
        initial_minor=19999,
        current_minor=19999,
        version=0,
    )
    decision = evaluate_policy(
        f.policy,
        f.episode,
        f.workers[0],
        reserve,
        (f.snapshots[0],),
        EvaluationContext("demo-tenant"),
    )
    assert decision.amount_minor == 0
    assert decision.reserve_after_minor == 19999


def test_warning_source_type_must_match_policy(service) -> None:
    f = service.fixtures
    bad = f.snapshots[0].model_copy(update={"source_type": "social_media_warning"})
    decision = evaluate_policy(
        f.policy, f.episode, f.workers[0], f.reserve, (bad,),
        EvaluationContext("demo-tenant"),
    )
    assert decision.status == "NOT_QUALIFIED"
    assert "SOURCE_UNVERIFIED" in decision.reason_codes


def test_cross_tenant_policy_cannot_spend_reserve(service) -> None:
    f = service.fixtures
    foreign_worker = f.workers[0].model_copy(update={"tenant_id": "other-tenant"})
    decision = evaluate_policy(
        f.policy, f.episode, foreign_worker, f.reserve, (f.snapshots[0],),
        EvaluationContext("other-tenant"),
    )
    assert decision.status == "NOT_QUALIFIED"
    assert decision.reason_codes == ("TENANT_MISMATCH",)


def test_policy_respects_per_episode_cap(service) -> None:
    f = service.fixtures
    capped = f.policy.model_copy(update={"per_episode_cap_minor": 12500})
    decision = evaluate_policy(
        capped, f.episode, f.workers[0], f.reserve, (f.snapshots[0],),
        EvaluationContext("demo-tenant"),
    )
    assert decision.status == "QUALIFIED"
    assert decision.amount_minor == 12500
    assert decision.reserve_after_minor == f.reserve.current_minor - 12500
