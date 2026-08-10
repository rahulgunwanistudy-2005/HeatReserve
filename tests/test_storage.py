from concurrent.futures import ThreadPoolExecutor

from heatreserve.domain import Reserve
from heatreserve.storage import Repository


def test_duplicate_commitment_returns_existing_without_double_spend(service) -> None:
    f = service.fixtures
    args = (f.workers[0].worker_id, f.episode.episode_id, f.policy.policy_id, f.policy.version)
    first = service.create_commitment(*args)
    second = service.create_commitment(*args)
    assert first.created is True
    assert second.created is False
    assert first.commitment_id == second.commitment_id
    assert service.repository.commitment_count() == 1
    assert service.repository.get_reserve(f.reserve.reserve_id).current_minor == 100000


def test_concurrent_same_key_creates_one_commitment(service) -> None:
    f = service.fixtures
    args = (f.workers[0].worker_id, f.episode.episode_id, f.policy.policy_id, f.policy.version)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: service.create_commitment(*args), range(20)))
    ids = {result.commitment_id for result in results}
    assert ids == {"commit-269a91cc954b"}
    assert service.repository.commitment_count() == 1
    assert service.repository.reserve_reconciles(f.reserve.reserve_id)


def test_concurrent_different_workers_cannot_overspend(service) -> None:
    f = service.fixtures
    tiny = Reserve(
        reserve_id=f.reserve.reserve_id,
        tenant_id=f.reserve.tenant_id,
        currency="INR",
        initial_minor=40000,
        current_minor=40000,
        version=0,
    )
    service.repository.reset_demo(f.workers, f.policy, tiny)
    worker_ids = [worker.worker_id for worker in f.workers if worker.zone_id == f.episode.zone_id]

    def commit(worker_id: str):
        return service.create_commitment(
            worker_id, f.episode.episode_id, f.policy.policy_id, f.policy.version
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(commit, worker_ids))
    qualified = [item for item in results if item.decision.status == "QUALIFIED"]
    assert len(qualified) == 2
    reserve = service.repository.get_reserve(f.reserve.reserve_id)
    assert reserve.current_minor == 0
    assert service.repository.commitment_count() == 2
    assert service.repository.reserve_reconciles(f.reserve.reserve_id)


def test_published_policy_version_is_immutable(service) -> None:
    policy = service.fixtures.policy
    modified = policy.model_copy(
        update={"amount_minor": policy.amount_minor + 100, "sha256": "0" * 64}
    )
    try:
        service.repository.save_policy(modified)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("published policy mutation should fail")


def test_published_policy_cannot_change_status_with_same_hash(service) -> None:
    policy = service.fixtures.policy
    modified = policy.model_copy(update={"status": "retired"})
    try:
        service.repository.save_policy(modified)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("published policy payload mutation should fail")


def test_resaving_plan_after_receipt_preserves_foreign_key(service) -> None:
    f = service.fixtures
    service.create_commitment(
        f.workers[0].worker_id, f.episode.episode_id, f.policy.policy_id, f.policy.version
    )
    plan = service.create_plan(f.workers[0].worker_id, f.episode.episode_id)
    receipt = service.create_receipt(f.workers[0].worker_id, f.episode.episode_id, plan)
    service.repository.save_plan(plan)
    assert service.repository.get_receipt(receipt.receipt_id) == receipt


def test_plan_id_cannot_be_reused_for_different_payload(service) -> None:
    f = service.fixtures
    plan = service.create_plan(f.workers[0].worker_id, f.episode.episode_id)
    changed = plan.model_copy(update={"caveat": plan.caveat + " Altered."})
    try:
        service.repository.save_plan(changed)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("same plan ID must not accept different payload")


def test_receipt_id_cannot_be_reused_for_different_payload(service) -> None:
    from heatreserve.receipts import attach_digest

    data = service.run_judge_demo()
    receipt = data["receipt"]
    changed = attach_digest(
        receipt.model_copy(update={"amount_minor": receipt.amount_minor + 100})
    )
    try:
        service.repository.save_receipt(changed)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("same receipt ID must not accept different payload")
