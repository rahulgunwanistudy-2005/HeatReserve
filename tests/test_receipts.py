import copy

from heatreserve.receipts import compute_receipt_digest, verify_receipt


def test_receipt_digest_is_deterministic(service) -> None:
    data = service.run_judge_demo()
    receipt = data["receipt"]
    assert compute_receipt_digest(receipt) == receipt.digest.value
    assert compute_receipt_digest(receipt) == compute_receipt_digest(receipt)


def test_tamper_detection_fails_for_protected_field(service) -> None:
    data = service.run_judge_demo()
    receipt = data["receipt"].model_dump(mode="json")
    tampered = copy.deepcopy(receipt)
    tampered["policy_version"] = "999.0.0"
    assert verify_receipt(receipt)["valid"] is True
    assert verify_receipt(tampered)["valid"] is False


def test_receipt_binds_full_plan_payload(service) -> None:
    from heatreserve.evidence import canonical_sha256

    data = service.run_judge_demo()
    receipt = data["receipt"]
    plan = data["plan"]
    assert receipt.plan_sha256 == canonical_sha256(plan.model_dump(mode="json"))


def test_receipt_binds_financial_decision_rationale(service) -> None:
    data = service.run_judge_demo()
    receipt = data["receipt"]
    decision = data["commitment"]["decision"]
    assert receipt.decision_status == decision.status
    assert receipt.decision_reason_codes == decision.reason_codes
    assert receipt.decision_idempotency_key == decision.idempotency_key

    payload = receipt.model_dump(mode="json")
    tampered = copy.deepcopy(payload)
    tampered["decision_reason_codes"] = ["FORGED_REASON"]
    assert verify_receipt(payload)["valid"] is True
    assert verify_receipt(tampered)["valid"] is False
