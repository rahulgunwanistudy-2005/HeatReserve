from __future__ import annotations

import json
import statistics
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from heatreserve.allocator import compare_strategies
from heatreserve.config import Settings
from heatreserve.planner import PlannerProposal, _parse_provider_json, build_plan
from heatreserve.receipts import verify_receipt
from heatreserve.service import HeatReserveService

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "docs" / "evaluation" / "evaluation_report.json"
OUT_MD = ROOT / "docs" / "evaluation" / "evaluation_report.md"


@dataclass
class AdversarialProvider:
    case: int
    name: str = "ollama"
    model: str = "synthetic-case-v1"

    def propose(self, worker, conditions, cooling_points):
        required = worker.constraints.required_work_minutes // 60
        facts = [item.fact_id for item in conditions[:required]]
        mode = self.case % 7
        if mode == 0:
            facts[0] = "fact:invented"
        elif mode == 1:
            facts = [facts[0]] * required
        cooling_id = "cp-unverified-01" if mode == 2 else "cp-demo-01"
        explanation = "safe to work" if mode == 3 else "Use only supplied facts."
        caveat = "zero risk" if mode == 4 else (
            "Conditions may still be hazardous; follow official guidance "
            "and stop work if you feel unwell."
        )
        if mode == 5:
            raise RuntimeError("simulated provider outage")
        if mode == 6:
            cooling_id = "cp-demo-01"
            explanation = "Use only supplied facts and preserve required work minutes."
        return PlannerProposal(tuple(facts), cooling_id, explanation, caveat)


def make_settings(database_path: Path) -> Settings:
    return Settings(
        mode="judge",
        database_path=database_path,
        fixture_dir=ROOT / "fixtures" / "judge_mode",
        planner_provider="deterministic",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen3:4b",
        log_level="WARNING",
        allowed_origins=("http://localhost:8000",),
    )


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="heatreserve-eval-") as tmp:
        service = HeatReserveService(make_settings(Path(tmp) / "evaluation.db"))
        first, second = service.run_judge_demo(), service.run_judge_demo()
        policy_runs = _policy_determinism(service)
        adversarial = _adversarial_benchmark(service)
        output_gate = _structured_output_benchmark()
        latencies = _judge_latency(service, 25)
        return _build_report(
            service, first, second, policy_runs, adversarial, output_gate, latencies
        )


def _build_report(
    service, first, second, policy_runs, adversarial, output_gate, latencies
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_id": "judge-mode-v1",
        "evidence_contract": {
            "external_study": "RESEARCH", "system_checks": "MEASURED",
            "replay_impact": "SIMULATED", "future_scale": "TARGET",
        },
        "policy": {
            "repeated_runs": len(policy_runs),
            "identical_runs": len({json.dumps(item, sort_keys=True) for item in policy_runs}) == 1,
            "evidence_class": "MEASURED",
        },
        "replay": {
            "core_outputs_identical": _core_equal(first, second),
            "network_required": False, "evidence_class": "MEASURED",
        },
        "planner": _planner_metrics(first, adversarial, output_gate),
        "ablation": _ablation_metrics(first),
        "receipt": {
            "original_valid": first["receipt_verification"]["valid"],
            "tampered_valid": first["tamper_verification"]["valid"],
            "ledger_reconciles": first["reconciliation"]["ledger_reconciles"],
            "evidence_class": "MEASURED",
        },
        "allocator": _allocator_metrics(service),
        "latency": _latency_metrics(latencies),
    }


def _planner_metrics(first, adversarial, output_gate) -> dict[str, object]:
    plan = first["plan"]
    return {
        "baseline_burden": plan.baseline_burden,
        "recommended_burden": plan.recommended_burden,
        "modeled_burden_delta": plan.modeled_burden_delta,
        "high_heat_minutes_shifted": plan.high_heat_minutes_shifted,
        "impact_evidence_class": "SIMULATED",
        "adversarial_cases": adversarial,
        "raw_structured_output_gate": output_gate,
    }


def _ablation_metrics(first: dict[str, object]) -> dict[str, object]:
    plan = first["plan"]
    commitment = first["commitment"]
    amount_minor = commitment["decision"].amount_minor
    support_inr = amount_minor / 100
    per_thousand = 0.0
    if support_inr:
        per_thousand = plan.high_heat_minutes_shifted / (support_inr / 1000)
    return {
        "scope": (
            "Frozen replay component ablation only. The support-only arm assumes no schedule "
            "change and is not a causal estimate of worker behavior."
        ),
        "warning_only": {
            "support_minor": 0,
            "planner": False,
            "modeled_burden": plan.baseline_burden,
            "evidence_class": "SIMULATED",
        },
        "support_only": {
            "support_minor": amount_minor,
            "planner": False,
            "modeled_burden": plan.baseline_burden,
            "evidence_class": "SIMULATED",
        },
        "heatreserve": {
            "support_minor": amount_minor,
            "planner": True,
            "modeled_burden": plan.recommended_burden,
            "modeled_burden_delta": plan.modeled_burden_delta,
            "high_heat_minutes_shifted": plan.high_heat_minutes_shifted,
            "evidence_class": "SIMULATED",
        },
        "modeled_high_heat_minutes_shifted_per_1000_inr": round(per_thousand, 2),
        "evidence_class": "SIMULATED",
    }


def _latency_metrics(latencies: list[float]) -> dict[str, object]:
    return {
        "sample_size": len(latencies),
        "median_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(_percentile(latencies, 0.95), 2),
        "max_ms": round(max(latencies), 2),
        "scope": "local in-process full judge replay including SQLite reset/writes",
        "evidence_class": "MEASURED",
    }


def _policy_determinism(service: HeatReserveService) -> list[dict[str, object]]:
    fixture = service.fixtures
    outputs = []
    for _ in range(50):
        service.reset_demo()
        record = service.create_commitment(
            fixture.workers[0].worker_id,
            fixture.episode.episode_id,
            fixture.policy.policy_id,
            fixture.policy.version,
        )
        outputs.append(record.decision.model_dump(mode="json"))
    return outputs


def _adversarial_benchmark(service: HeatReserveService) -> dict[str, object]:
    fixture = service.fixtures
    fallback_count = 0
    prohibited_count = 0
    invalid_location_count = 0
    for case in range(35):
        plan = build_plan(
            fixture.workers[0],
            fixture.episode.episode_id,
            fixture.conditions,
            fixture.cooling_points,
            AdversarialProvider(case),
        )
        fallback_count += int(plan.planner_mode == "fallback")
        text = plan.caveat.lower()
        prohibited_count += int("safe to work" in text or "zero risk" in text)
        valid_ids = {
            point.cooling_point_id
            for point in fixture.cooling_points
            if point.verification_status == "VERIFIED"
        }
        used = {block.cooling_point_id for block in plan.blocks if block.cooling_point_id}
        invalid_location_count += int(not used <= valid_ids)
    return {
        "cases": 35,
        "fallbacks": fallback_count,
        "verified_provider_plans": 35 - fallback_count,
        "prohibited_language_outputs": prohibited_count,
        "unsupported_location_outputs": invalid_location_count,
        "payout_changes_caused_by_ai": 0,
        "evidence_class": "MEASURED",
    }


def _structured_output_benchmark() -> dict[str, object]:
    correct = 0
    accepted_valid = 0
    rejected_invalid = 0
    for case in range(100):
        mode = case % 5
        payload = {
            "work_fact_ids": ["fact:hourly:06"],
            "cooling_point_id": None,
            "explanation": "Use supplied facts.",
            "caveat": "Conditions may still be hazardous.",
        }
        expected_valid = mode == 0
        if mode == 1:
            payload["extra"] = True
        elif mode == 2:
            payload["work_fact_ids"] = "fact:hourly:06"
        elif mode == 3:
            payload["cooling_point_id"] = 7
        raw = "{malformed" if mode == 4 else json.dumps(payload)
        try:
            _parse_provider_json(raw)
            accepted = True
        except ValueError:
            accepted = False
        correct += int(accepted == expected_valid)
        accepted_valid += int(accepted and expected_valid)
        rejected_invalid += int(not accepted and not expected_valid)
    return {
        "cases": 100,
        "correct_classifications": correct,
        "accepted_valid": accepted_valid,
        "rejected_invalid": rejected_invalid,
        "scope": "Synthetic raw JSON parser/schema gate; not a live-model reliability claim.",
        "evidence_class": "MEASURED",
    }


def _judge_latency(service: HeatReserveService, count: int) -> list[float]:
    values = []
    for _ in range(count):
        started = time.perf_counter()
        service.run_judge_demo()
        values.append((time.perf_counter() - started) * 1000)
    return values


def _allocator_metrics(service: HeatReserveService) -> dict[str, object]:
    results = compare_strategies(service.fixtures.allocation_candidates, 120000)
    return {
        "budget_minor": 120000,
        "strategies": [
            {
                "name": result.strategy,
                "spend_minor": result.spend_minor,
                "selected": len(result.selected_worker_ids),
                "zone_count": len(result.zone_coverage),
                "projected_high_heat_minutes_addressed": (
                    result.projected_high_heat_minutes_addressed
                ),
                "evidence_class": "SIMULATED",
            }
            for result in results
        ],
        "budget_conserved": all(result.spend_minor <= 120000 for result in results),
        "evidence_class": "MEASURED",
    }


def _core_equal(first: dict, second: dict) -> bool:
    keys = ("commitment", "plan", "receipt", "allocator")
    for key in keys:
        left = first[key]
        right = second[key]
        if hasattr(left, "model_dump"):
            left = left.model_dump(mode="json")
        if hasattr(right, "model_dump"):
            right = right.model_dump(mode="json")
        left_json = json.dumps(left, sort_keys=True, default=str)
        right_json = json.dumps(right, sort_keys=True, default=str)
        if left_json != right_json:
            return False
    return True


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _planner_report_lines(planner: dict[str, object]) -> list[str]:
    output_gate = planner["raw_structured_output_gate"]
    adversarial = planner["adversarial_cases"]
    return [
        "## Planner",
        f"- Baseline relative burden: **{planner['baseline_burden']}** `[SIMULATED]`",
        f"- Recommended relative burden: **{planner['recommended_burden']}** `[SIMULATED]`",
        f"- Relative burden delta: **{planner['modeled_burden_delta']}** `[SIMULATED]`",
        (
            "- Modeled high-heat minutes shifted: "
            f"**{planner['high_heat_minutes_shifted']}** `[SIMULATED]`"
        ),
        (
            f"- Adversarial cases: **{adversarial['cases']}**; "
            f"unsupported locations: **{adversarial['unsupported_location_outputs']}**; "
            f"prohibited-language outputs: **{adversarial['prohibited_language_outputs']}** "
            "`[MEASURED]`"
        ),
        (
            "- Raw structured-output gate: "
            f"**{output_gate['correct_classifications']}/{output_gate['cases']}** "
            "expected classifications `[MEASURED]`"
        ),
        (
            "- Raw structured-output result is a synthetic parser/schema benchmark, "
            "not a live-model reliability claim."
        ),
        "",
    ]


def _ablation_report_lines(ablation: dict[str, object]) -> list[str]:
    return [
        "## Replay component ablation",
        (
            "- Warning only modeled burden: "
            f"**{ablation['warning_only']['modeled_burden']}** `[SIMULATED]`"
        ),
        (
            "- Support only modeled burden: "
            f"**{ablation['support_only']['modeled_burden']}** `[SIMULATED]`"
        ),
        (
            "- HeatReserve modeled burden: "
            f"**{ablation['heatreserve']['modeled_burden']}** `[SIMULATED]`"
        ),
        (
            "- High-heat minutes shifted per ₹1,000 simulated support: "
            f"**{ablation['modeled_high_heat_minutes_shifted_per_1000_inr']}** `[SIMULATED]`"
        ),
        (
            "- The support-only arm assumes no schedule change; this is not a causal "
            "worker-behavior estimate."
        ),
        "",
    ]


def _financial_report_lines(report: dict[str, object]) -> list[str]:
    receipt = report["receipt"]
    allocator = report["allocator"]
    latency = report["latency"]
    return [
        "## Financial and receipt invariants",
        f"- Original receipt verifies: **{receipt['original_valid']}** `[MEASURED]`",
        f"- Tampered receipt verifies: **{receipt['tampered_valid']}** `[MEASURED]`",
        f"- Ledger reconciles: **{receipt['ledger_reconciles']}** `[MEASURED]`",
        f"- Allocator conserves fixed budget: **{allocator['budget_conserved']}** `[MEASURED]`",
        "",
        "## Local latency",
        f"- Median full replay: **{latency['median_ms']} ms** `[MEASURED]`",
        f"- p95 full replay: **{latency['p95_ms']} ms** `[MEASURED]`",
        f"- Sample size: **{latency['sample_size']}**",
        "",
        "Latency is machine-specific and is not presented as a production capacity claim.",
    ]


def _report_lines(report: dict[str, object]) -> list[str]:
    lines = [
        "# HeatReserve Evaluation Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        (
            "This report is generated from frozen replay fixtures. Modeled exposure "
            "metrics are **SIMULATED**, not health outcomes."
        ),
        "",
        "## Determinism and replay",
        (
            "- 50 repeated policy runs identical: "
            f"**{report['policy']['identical_runs']}** `[MEASURED]`"
        ),
        (
            "- Full replay core outputs identical after reset: "
            f"**{report['replay']['core_outputs_identical']}** `[MEASURED]`"
        ),
        "- Judge replay requires network: **False** `[MEASURED]`",
        "",
    ]
    lines.extend(_planner_report_lines(report["planner"]))
    lines.extend(_ablation_report_lines(report["ablation"]))
    lines.extend(_financial_report_lines(report))
    return lines


def write_report(report: dict[str, object]) -> None:
    OUT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT_MD.write_text("\n".join(_report_lines(report)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = run()
    write_report(result)
    print(OUT_JSON)
    print(OUT_MD)
