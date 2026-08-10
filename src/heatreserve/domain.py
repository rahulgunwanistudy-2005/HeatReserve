from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


class EvidenceClass(StrEnum):
    RESEARCH = "RESEARCH"
    MEASURED = "MEASURED"
    SIMULATED = "SIMULATED"
    TARGET = "TARGET"


MinorUnits = Annotated[StrictInt, Field(ge=0)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeWindow(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "TimeWindow":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time windows require timezone-aware timestamps")
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        return self


class SourceSnapshot(StrictModel):
    snapshot_id: str
    source_type: str
    source_uri: str
    issued_at: datetime
    fetched_at: datetime
    valid_from: datetime
    valid_to: datetime
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser_version: str
    verified: bool
    evidence_class: EvidenceClass = EvidenceClass.RESEARCH

    @model_validator(mode="after")
    def validate_times(self) -> "SourceSnapshot":
        values = (self.issued_at, self.fetched_at, self.valid_from, self.valid_to)
        if any(value.tzinfo is None for value in values):
            raise ValueError("snapshot timestamps must be timezone-aware")
        if self.valid_to <= self.valid_from:
            raise ValueError("snapshot valid_to must be after valid_from")
        return self


class HeatEpisode(StrictModel):
    episode_id: str
    zone_id: str
    builder_version: str
    start_at: datetime
    end_at: datetime
    warning_snapshot_ids: tuple[str, ...]
    canonical_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_times(self) -> "HeatEpisode":
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("episode timestamps must be timezone-aware")
        if self.end_at <= self.start_at:
            raise ValueError("episode end_at must be after start_at")
        if not self.warning_snapshot_ids:
            raise ValueError("episode requires at least one warning snapshot")
        return self


class WorkerConstraints(StrictModel):
    available_windows: tuple[TimeWindow, ...]
    preferred_windows: tuple[TimeWindow, ...]
    required_work_minutes: int = Field(gt=0, le=24 * 60)
    workload_class: Literal["light", "moderate", "heavy"] = "moderate"


class Worker(StrictModel):
    worker_id: str
    tenant_id: str
    worker_type: str
    zone_id: str
    language: Literal["en", "hi"] = "en"
    constraints: WorkerConstraints


class Policy(StrictModel):
    policy_id: str
    tenant_id: str
    version: str
    status: Literal["draft", "published", "retired"]
    source_type: str
    min_consecutive_warning_days: int = Field(ge=1, le=14)
    episode_block_days: int = Field(ge=1, le=14)
    allowed_worker_types: tuple[str, ...]
    allowed_zones: tuple[str, ...]
    currency: Literal["INR"] = "INR"
    amount_minor: MinorUnits
    per_episode_cap_minor: MinorUnits
    reserve_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Reserve(StrictModel):
    reserve_id: str
    tenant_id: str
    currency: Literal["INR"]
    initial_minor: MinorUnits
    current_minor: MinorUnits
    version: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_balance(self) -> "Reserve":
        if self.current_minor > self.initial_minor:
            raise ValueError("reserve current balance cannot exceed initial balance")
        return self


class CommitmentDecision(StrictModel):
    status: Literal["QUALIFIED", "NOT_QUALIFIED", "MANUAL_REVIEW"]
    amount_minor: MinorUnits
    reason_codes: tuple[str, ...]
    idempotency_key: str
    reserve_before_minor: MinorUnits
    reserve_after_minor: MinorUnits
    evidence_class: EvidenceClass = EvidenceClass.SIMULATED


class HourlyCondition(StrictModel):
    fact_id: str
    at: datetime
    temperature_c: float
    relative_humidity_pct: float = Field(ge=0, le=100)
    apparent_temperature_c: float
    solar_proxy: float = Field(ge=0, le=1)
    warning_flag: bool
    source_snapshot_id: str

    @field_validator("at")
    @classmethod
    def validate_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("hourly condition timestamp must be timezone-aware")
        return value


class CoolingPoint(StrictModel):
    cooling_point_id: str
    zone_id: str
    name: str
    opens_at: str
    closes_at: str
    verification_status: Literal["VERIFIED", "UNVERIFIED", "STALE"]
    source_snapshot_id: str
    fact_id: str


class PlanBlock(StrictModel):
    kind: Literal["work", "cooling_break"]
    start: datetime
    end: datetime
    cooling_point_id: str | None = None
    rationale: str
    fact_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_block(self) -> "PlanBlock":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("plan block timestamps must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("plan block end must be after start")
        if self.kind == "cooling_break" and not self.cooling_point_id:
            raise ValueError("cooling break requires cooling_point_id")
        return self


class AdaptationPlan(StrictModel):
    plan_id: str
    worker_id: str
    episode_id: str
    planner_mode: Literal["deterministic", "ollama", "fallback"]
    provider: str
    model: str
    prompt_version: str
    verifier_version: str
    verifier_status: Literal["VERIFIED", "FALLBACK"]
    blocks: tuple[PlanBlock, ...]
    baseline_burden: float = Field(ge=0)
    recommended_burden: float = Field(ge=0)
    modeled_burden_delta: float
    high_heat_minutes_shifted: int
    caveat: str
    evidence_class: EvidenceClass = EvidenceClass.SIMULATED
    tool_fact_ids: tuple[str, ...]


class ReceiptDigest(StrictModel):
    algorithm: Literal["SHA-256"] = "SHA-256"
    value: str = Field(pattern=r"^[a-f0-9]{64}$")


class DecisionReceipt(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str
    tenant_id: str
    worker_id: str
    episode_id: str
    commitment_id: str
    plan_id: str
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_id: str
    policy_version: str
    decision_status: Literal["QUALIFIED", "NOT_QUALIFIED", "MANUAL_REVIEW"]
    decision_reason_codes: tuple[str, ...]
    decision_idempotency_key: str
    amount_minor: MinorUnits
    source_snapshot_ids: tuple[str, ...]
    planner_mode: str
    provider: str
    model: str
    prompt_version: str
    verifier_version: str
    tool_fact_ids: tuple[str, ...]
    evidence_class: EvidenceClass
    created_at: datetime
    digest: ReceiptDigest | None = None


class Metric(StrictModel):
    key: str
    value: float | int | str
    unit: str
    evidence_class: EvidenceClass
    source: str


def validate_timezone_name(name: str) -> str:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {name}") from exc
    return name


class Zone(StrictModel):
    zone_id: str
    name: str
    timezone: str

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return validate_timezone_name(value)
