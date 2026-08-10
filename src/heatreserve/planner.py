from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Protocol

from .burden import ScoredHour, score_hours, top_band_threshold
from .domain import AdaptationPlan, CoolingPoint, HourlyCondition, PlanBlock, Worker
from .evidence import canonical_sha256
from .prompts import PLANNER_PROMPT_VERSION, PLANNER_SYSTEM_PROMPT

PROHIBITED_PATTERNS = (
    re.compile(r"\bsafe to work\b", re.I),
    re.compile(r"\bzero risk\b", re.I),
    re.compile(r"\bcannot get heatstroke\b", re.I),
    re.compile(r"\bmedically (safe|cleared|approved)\b", re.I),
)
DEFAULT_CAVEAT = (
    "This plan lowers modeled heat burden relative to the original window. Conditions may still "
    "be hazardous; follow official guidance and stop work if you feel unwell."
)
_PROVIDER_KEYS = {"work_fact_ids", "cooling_point_id", "explanation", "caveat"}


@dataclass(frozen=True, slots=True)
class PlannerProposal:
    work_fact_ids: tuple[str, ...]
    cooling_point_id: str | None
    explanation: str
    caveat: str


class PlannerProvider(Protocol):
    name: str
    model: str

    def propose(
        self,
        worker: Worker,
        conditions: tuple[HourlyCondition, ...],
        cooling_points: tuple[CoolingPoint, ...],
    ) -> PlannerProposal: ...


class DeterministicProvider:
    name = "deterministic"
    model = "fallback-v1"

    def propose(
        self,
        worker: Worker,
        conditions: tuple[HourlyCondition, ...],
        cooling_points: tuple[CoolingPoint, ...],
    ) -> PlannerProposal:
        scored = _available_scored_hours(worker, score_hours(conditions))
        selected = tuple(
            sorted(scored, key=lambda item: (item.score, item.condition.at))[
                : _required_slots(worker)
            ]
        )
        selected = tuple(sorted(selected, key=lambda item: item.condition.at))
        cooling_id = cooling_points[0].cooling_point_id if cooling_points else None
        return PlannerProposal(
            work_fact_ids=tuple(item.condition.fact_id for item in selected),
            cooling_point_id=cooling_id,
            explanation="Shift feasible work hours toward lower modeled heat-burden periods.",
            caveat=DEFAULT_CAVEAT,
        )


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 4.0) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds

    def propose(
        self,
        worker: Worker,
        conditions: tuple[HourlyCondition, ...],
        cooling_points: tuple[CoolingPoint, ...],
    ) -> PlannerProposal:
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=json.dumps(
                _ollama_payload(self.model, worker, conditions, cooling_points)
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama planner unavailable: {exc}") from exc
        return _parse_provider_json(payload.get("response", ""))


def _ollama_payload(
    model: str,
    worker: Worker,
    conditions: tuple[HourlyCondition, ...],
    cooling_points: tuple[CoolingPoint, ...],
) -> dict[str, object]:
    facts = {
        "worker": worker.model_dump(mode="json"),
        "hourly_conditions": [item.model_dump(mode="json") for item in conditions],
        "cooling_points": [item.model_dump(mode="json") for item in cooling_points],
    }
    return {
        "model": model,
        "system": PLANNER_SYSTEM_PROMPT,
        "prompt": json.dumps(facts, separators=(",", ":")),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": 320},
    }


def _parse_provider_json(raw: str) -> PlannerProposal:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Planner returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != _PROVIDER_KEYS:
        raise ValueError("Planner output must contain exactly the documented keys")
    work_ids = payload["work_fact_ids"]
    cooling_id = payload["cooling_point_id"]
    if not isinstance(work_ids, list) or not all(isinstance(item, str) for item in work_ids):
        raise ValueError("work_fact_ids must be a list of strings")
    if cooling_id is not None and not isinstance(cooling_id, str):
        raise ValueError("cooling_point_id must be a string or null")
    if not isinstance(payload["explanation"], str) or not isinstance(payload["caveat"], str):
        raise ValueError("explanation and caveat must be strings")
    return PlannerProposal(tuple(work_ids), cooling_id, payload["explanation"], payload["caveat"])


def _required_slots(worker: Worker) -> int:
    minutes = worker.constraints.required_work_minutes
    if minutes % 60 != 0:
        raise ValueError("demo planner requires required_work_minutes divisible by 60")
    return minutes // 60


def _is_within_windows(at: datetime, worker: Worker) -> bool:
    end = at + timedelta(hours=1)
    return any(
        window.start <= at and end <= window.end
        for window in worker.constraints.available_windows
    )


def _available_scored_hours(
    worker: Worker, scored: tuple[ScoredHour, ...]
) -> tuple[ScoredHour, ...]:
    return tuple(item for item in scored if _is_within_windows(item.condition.at, worker))


def _preferred_fact_ids(worker: Worker, conditions: tuple[HourlyCondition, ...]) -> tuple[str, ...]:
    preferred = []
    for item in conditions:
        end = item.at + timedelta(hours=1)
        if any(
            window.start <= item.at and end <= window.end
            for window in worker.constraints.preferred_windows
        ):
            preferred.append(item.fact_id)
    return tuple(preferred[: _required_slots(worker)])


def _validate_proposal(
    proposal: PlannerProposal,
    worker: Worker,
    conditions: tuple[HourlyCondition, ...],
    cooling_points: tuple[CoolingPoint, ...],
) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    facts = {item.fact_id: item for item in conditions}
    verified_points = {
        point.cooling_point_id
        for point in cooling_points
        if point.verification_status == "VERIFIED"
    }
    if len(proposal.work_fact_ids) != _required_slots(worker):
        errors.append("work slot count does not preserve required work minutes")
    if len(set(proposal.work_fact_ids)) != len(proposal.work_fact_ids):
        errors.append("duplicate work fact id")
    for fact_id in proposal.work_fact_ids:
        condition = facts.get(fact_id)
        if condition is None or not _is_within_windows(condition.at, worker):
            errors.append(f"unsupported or unavailable work fact: {fact_id}")
    if proposal.cooling_point_id and proposal.cooling_point_id not in verified_points:
        errors.append("cooling point is not verified")
    combined_text = f"{proposal.explanation} {proposal.caveat}"
    if any(pattern.search(combined_text) for pattern in PROHIBITED_PATTERNS):
        errors.append("prohibited safety language")
    if "conditions may still be hazardous" not in proposal.caveat.lower():
        errors.append("required hazard caveat missing")
    return not errors, tuple(errors)


def _consolidate_work_blocks(selected: tuple[HourlyCondition, ...]) -> tuple[PlanBlock, ...]:
    if not selected:
        return ()
    ordered = sorted(selected, key=lambda item: item.at)
    blocks: list[PlanBlock] = []
    start, fact_ids, previous = ordered[0].at, [ordered[0].fact_id], ordered[0].at
    for condition in ordered[1:]:
        if condition.at == previous + timedelta(hours=1):
            fact_ids.append(condition.fact_id)
        else:
            blocks.append(_work_block(start, previous + timedelta(hours=1), fact_ids))
            start, fact_ids = condition.at, [condition.fact_id]
        previous = condition.at
    blocks.append(_work_block(start, previous + timedelta(hours=1), fact_ids))
    return tuple(blocks)


def _work_block(start: datetime, end: datetime, fact_ids: list[str]) -> PlanBlock:
    return PlanBlock(
        kind="work",
        start=start,
        end=end,
        rationale="Selected from feasible hours with lower relative modeled burden.",
        fact_ids=tuple(fact_ids),
    )


def _parse_clock(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid cooling point opening time: {value}") from exc


def _point_open_for(point: CoolingPoint, start: datetime, end: datetime) -> bool:
    opens, closes = _parse_clock(point.opens_at), _parse_clock(point.closes_at)
    start_local, end_local = start.timetz().replace(tzinfo=None), end.timetz().replace(tzinfo=None)
    if closes >= opens:
        return opens <= start_local and end_local <= closes
    return start_local >= opens or end_local <= closes


def _cooling_block(
    point: CoolingPoint | None, selected: tuple[HourlyCondition, ...]
) -> PlanBlock | None:
    if point is None or len(selected) < 2:
        return None
    ordered = sorted(selected, key=lambda item: item.at)
    for previous, current in zip(ordered, ordered[1:]):
        gap_start = previous.at + timedelta(hours=1)
        gap_end = gap_start + timedelta(minutes=30)
        if current.at >= gap_end and _point_open_for(point, gap_start, gap_end):
            return PlanBlock(
                kind="cooling_break",
                start=gap_start,
                end=gap_end,
                cooling_point_id=point.cooling_point_id,
                rationale="Optional cooled recovery stop at a verified demo cooling point.",
                fact_ids=(point.fact_id,),
            )
    return None


def build_plan(
    worker: Worker,
    episode_id: str,
    conditions: tuple[HourlyCondition, ...],
    cooling_points: tuple[CoolingPoint, ...],
    provider: PlannerProvider,
) -> AdaptationPlan:
    verified_points = tuple(p for p in cooling_points if p.verification_status == "VERIFIED")
    effective: PlannerProvider = provider
    verifier_status = "VERIFIED"
    try:
        proposal = provider.propose(worker, conditions, verified_points)
        valid, _ = _validate_proposal(proposal, worker, conditions, verified_points)
        if not valid:
            raise ValueError("provider proposal failed deterministic verification")
    except (RuntimeError, ValueError, KeyError, TypeError):
        effective = DeterministicProvider()
        proposal = effective.propose(worker, conditions, verified_points)
        verifier_status = "FALLBACK"
    valid, errors = _validate_proposal(proposal, worker, conditions, verified_points)
    if not valid:
        raise ValueError(f"deterministic fallback failed verification: {errors}")
    return _materialize_plan(
        worker, episode_id, conditions, verified_points, proposal, effective, verifier_status
    )


def _burden_metrics(
    worker: Worker, conditions: tuple[HourlyCondition, ...], proposal: PlannerProposal
) -> tuple[float, float, int]:
    scored = score_hours(conditions)
    score_by_id = {item.condition.fact_id: item.score for item in scored}
    baseline_ids = _preferred_fact_ids(worker, conditions)
    baseline = sum(score_by_id[item] for item in baseline_ids)
    recommended = sum(score_by_id[item] for item in proposal.work_fact_ids)
    threshold = top_band_threshold(scored)
    baseline_high = sum(60 for item in baseline_ids if score_by_id[item] >= threshold)
    recommended_high = sum(60 for item in proposal.work_fact_ids if score_by_id[item] >= threshold)
    return baseline, recommended, baseline_high - recommended_high


def _materialize_plan(
    worker: Worker,
    episode_id: str,
    conditions: tuple[HourlyCondition, ...],
    cooling_points: tuple[CoolingPoint, ...],
    proposal: PlannerProposal,
    provider: PlannerProvider,
    verifier_status: str,
) -> AdaptationPlan:
    facts = {item.fact_id: item for item in conditions}
    selected = tuple(facts[fact_id] for fact_id in proposal.work_fact_ids)
    point = next(
        (p for p in cooling_points if p.cooling_point_id == proposal.cooling_point_id),
        None,
    )
    blocks = list(_consolidate_work_blocks(selected))
    if cooling := _cooling_block(point, selected):
        blocks.append(cooling)
        blocks.sort(key=lambda block: block.start)
    baseline, recommended, shifted = _burden_metrics(worker, conditions, proposal)
    tool_ids = set(proposal.work_fact_ids) | ({point.fact_id} if point else set())
    identity = canonical_sha256({
        "worker_id": worker.worker_id,
        "episode_id": episode_id,
        "provider": provider.name,
        "model": provider.model,
        "work_fact_ids": list(proposal.work_fact_ids),
        "cooling_point_id": proposal.cooling_point_id,
    })
    return AdaptationPlan(
        plan_id=f"plan-{identity[:12]}", worker_id=worker.worker_id, episode_id=episode_id,
        planner_mode="fallback" if verifier_status == "FALLBACK" else provider.name,
        provider=provider.name, model=provider.model, prompt_version=PLANNER_PROMPT_VERSION,
        verifier_version="verifier-v1", verifier_status=verifier_status, blocks=tuple(blocks),
        baseline_burden=round(baseline, 4), recommended_burden=round(recommended, 4),
        modeled_burden_delta=round(baseline - recommended, 4), high_heat_minutes_shifted=shifted,
        caveat=proposal.caveat, tool_fact_ids=tuple(sorted(tool_ids)),
    )
