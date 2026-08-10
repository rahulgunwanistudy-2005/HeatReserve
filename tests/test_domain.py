from datetime import datetime

import pytest
from pydantic import ValidationError

from heatreserve.domain import CommitmentDecision, EvidenceClass, TimeWindow, Zone


def test_evidence_class_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        EvidenceClass("OBSERVED_MAYBE")


def test_money_minor_units_reject_float() -> None:
    with pytest.raises(ValidationError):
        CommitmentDecision(
            status="QUALIFIED",
            amount_minor=200.5,
            reason_codes=("RESERVE_AVAILABLE",),
            idempotency_key="abc",
            reserve_before_minor=1000,
            reserve_after_minor=800,
        )


def test_time_window_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=datetime(2026, 5, 1, 8), end=datetime(2026, 5, 1, 9))


def test_invalid_timezone_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Zone(zone_id="bad", name="Bad", timezone="Mars/Olympus")


def test_reserve_balance_cannot_exceed_initial() -> None:
    from heatreserve.domain import Reserve

    with pytest.raises(ValidationError):
        Reserve(
            reserve_id="r", tenant_id="t", currency="INR",
            initial_minor=100, current_minor=101, version=0,
        )


def test_missing_humidity_is_rejected() -> None:
    from heatreserve.domain import HourlyCondition

    with pytest.raises(ValidationError):
        HourlyCondition.model_validate({
            "fact_id": "x", "at": "2026-05-28T06:00:00+05:30",
            "temperature_c": 30, "apparent_temperature_c": 32,
            "solar_proxy": 0.1, "warning_flag": False, "source_snapshot_id": "s",
        })


def test_live_mode_is_rejected_by_prototype(monkeypatch) -> None:
    from heatreserve.config import Settings

    monkeypatch.setenv("HEATRESERVE_MODE", "live")
    import pytest
    with pytest.raises(ValueError, match="Unsupported HEATRESERVE_MODE"):
        Settings.from_env()
