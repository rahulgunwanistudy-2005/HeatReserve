from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .domain import HeatEpisode, Policy
from .evidence import canonical_sha256


def build_episode_from_warning(
    warning: dict[str, object],
    policy: Policy,
    *,
    snapshot_id: str,
    timezone: str = "Asia/Kolkata",
) -> HeatEpisode:
    if warning.get("source_type") != policy.source_type:
        raise ValueError("warning source type does not match policy")
    zone_id = str(warning.get("zone_id", ""))
    if zone_id not in policy.allowed_zones:
        raise ValueError("warning zone is not allowed by policy")
    raw_days = warning.get("warning_days")
    if not isinstance(raw_days, list) or not raw_days:
        raise ValueError("warning_days must be a non-empty list")
    days = sorted({_parse_date(value) for value in raw_days})
    sequence = _first_qualifying_sequence(days, policy.min_consecutive_warning_days)
    if sequence is None:
        raise ValueError("warning does not meet minimum consecutive-day criteria")
    block_days = min(len(sequence), policy.episode_block_days)
    tz = ZoneInfo(timezone)
    start = datetime.combine(sequence[0], time.min, tzinfo=tz)
    end = datetime.combine(
        sequence[0] + timedelta(days=block_days), time.min, tzinfo=tz
    ) - timedelta(seconds=1)
    body = {
        "episode_id": (
            "episode:demo-delhi-001"
            if zone_id == "DELHI_DEMO_ZONE_A"
            else f"episode:{zone_id}:{sequence[0].isoformat()}"
        ),
        "zone_id": zone_id,
        "builder_version": "episode-builder-v1",
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "warning_snapshot_ids": [snapshot_id],
    }
    return HeatEpisode.model_validate({**body, "canonical_sha256": canonical_sha256(body)})


def _parse_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("warning day must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid warning day: {value}") from exc


def _first_qualifying_sequence(days: list[date], minimum: int) -> list[date] | None:
    if not days:
        return None
    current = [days[0]]
    for day in days[1:]:
        if day == current[-1] + timedelta(days=1):
            current.append(day)
        else:
            if len(current) >= minimum:
                return current
            current = [day]
    return current if len(current) >= minimum else None
