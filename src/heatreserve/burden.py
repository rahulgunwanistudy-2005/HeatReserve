from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .domain import HourlyCondition


@dataclass(frozen=True, slots=True)
class BurdenWeights:
    apparent: float = 0.40
    temperature: float = 0.20
    humidity: float = 0.15
    solar: float = 0.15
    warning: float = 0.10

    def validate(self) -> None:
        total = self.apparent + self.temperature + self.humidity + self.solar + self.warning
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"burden weights must sum to 1.0, got {total}")


@dataclass(frozen=True, slots=True)
class ScoredHour:
    condition: HourlyCondition
    score: float


def _minmax(values: list[float]) -> list[float]:
    low = min(values)
    high = max(values)
    if high == low:
        return [0.5 for _ in values]
    return [(value - low) / (high - low) for value in values]


def score_hours(
    conditions: tuple[HourlyCondition, ...],
    weights: BurdenWeights | None = None,
) -> tuple[ScoredHour, ...]:
    if not conditions:
        return ()
    weights = weights or BurdenWeights()
    weights.validate()
    apparent = _minmax([item.apparent_temperature_c for item in conditions])
    temperature = _minmax([item.temperature_c for item in conditions])
    humidity = [item.relative_humidity_pct / 100 for item in conditions]
    scores: list[ScoredHour] = []
    for idx, item in enumerate(conditions):
        score = (
            weights.apparent * apparent[idx]
            + weights.temperature * temperature[idx]
            + weights.humidity * humidity[idx]
            + weights.solar * item.solar_proxy
            + weights.warning * float(item.warning_flag)
        )
        scores.append(ScoredHour(condition=item, score=round(score, 6)))
    return tuple(scores)


def score_lookup(scored: tuple[ScoredHour, ...]) -> dict[datetime, ScoredHour]:
    return {item.condition.at: item for item in scored}


def top_band_threshold(scored: tuple[ScoredHour, ...], percentile: float = 0.70) -> float:
    if not scored:
        return 0.0
    ordered = sorted(item.score for item in scored)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile)))
    return ordered[index]
