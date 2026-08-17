"""
Source adapter framework.

Live adapters fetch real evidence from external providers.
Fixture adapters serve frozen replay evidence for Judge Mode.

INVARIANT: live mode never silently substitutes fixture data.
If a live fetch fails, the result is UNAVAILABLE — never synthetic.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from .domain import (
    EvidenceClass,
    HourlyCondition,
    RawSourceArtifact,
    SourceFreshness,
    SourceSnapshot,
)
from .evidence import canonical_sha256, sha256_bytes

LOGGER = logging.getLogger("heatreserve.sources")

_ADAPTER_VERSION = "source-adapter-v1"
_OPEN_METEO_PARSER_VERSION = "open-meteo-parser-v1"
_OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


class SourceAdapter(Protocol):
    source_type: str
    provider: str
    adapter_version: str

    def fetch(self, zone_id: str) -> RawSourceArtifact: ...
    def normalize(self, artifact: RawSourceArtifact) -> tuple[HourlyCondition, ...]: ...


class SourceFetchError(RuntimeError):
    """Raised when a live fetch fails — never silently suppressed."""


class SourceParseError(ValueError):
    """Raised when raw artifact cannot be normalized."""


class SourceStaleError(ValueError):
    """Raised when the fetched artifact falls outside the freshness window."""


def _build_snapshot(artifact: RawSourceArtifact) -> SourceSnapshot:
    return SourceSnapshot(
        snapshot_id=f"snap-{artifact.artifact_id}",
        source_type=artifact.source_type,
        source_uri=artifact.source_uri,
        issued_at=artifact.issued_at or artifact.retrieved_at,
        fetched_at=artifact.retrieved_at,
        valid_from=artifact.valid_from,
        valid_to=artifact.valid_to,
        raw_sha256=artifact.raw_sha256,
        parser_version=artifact.parser_version,
        verified=True,
        evidence_class=artifact.evidence_class,
    )


class OpenMeteoWeatherAdapter:
    """
    Fetches real hourly weather from Open-Meteo (https://open-meteo.com).
    No API key required. Free, non-commercial use.
    Source: Open-Meteo.com (CC BY 4.0 for forecast data).
    """

    source_type = "hourly_weather"
    provider = "open-meteo"
    adapter_version = _ADAPTER_VERSION

    def __init__(
        self,
        lat: float,
        lon: float,
        timezone: str = "Asia/Kolkata",
        timeout_seconds: float = 10.0,
        max_age_seconds: int = 3600,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.timezone = timezone
        self.timeout_seconds = timeout_seconds
        self.max_age_seconds = max_age_seconds

    def _build_url(self) -> str:
        params = (
            f"latitude={self.lat}&longitude={self.lon}"
            f"&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"shortwave_radiation,weathercode"
            f"&timezone={self.timezone}"
            f"&forecast_days=2"
        )
        return f"{_OPEN_METEO_BASE}?{params}"

    def fetch(self, zone_id: str) -> RawSourceArtifact:
        url = self._build_url()
        now = datetime.now(UTC)
        LOGGER.info("source.fetch provider=open-meteo zone=%s url=%s", zone_id, url)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "HeatReserve/0.3.0 (climate-adaptation-research)"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw_bytes = resp.read()
        except urllib.error.HTTPError as exc:
            raise SourceFetchError(
                f"Open-Meteo HTTP {exc.code} fetching weather for zone {zone_id}"
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise SourceFetchError(
                f"Open-Meteo network error fetching weather for zone {zone_id}: {exc}"
            ) from exc

        try:
            payload = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            raise SourceParseError(
                f"Open-Meteo returned non-JSON for zone {zone_id}: {exc}"
            ) from exc

        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            raise SourceParseError(f"Open-Meteo returned no hourly data for zone {zone_id}")

        tz = ZoneInfo(self.timezone)
        first_time = datetime.fromisoformat(times[0]).replace(tzinfo=tz)
        last_time = datetime.fromisoformat(times[-1]).replace(tzinfo=tz)

        raw_hash = sha256_bytes(raw_bytes)
        artifact_id = raw_hash[:16]

        age_seconds = (now - now.replace(
            hour=first_time.hour, minute=0, second=0, microsecond=0
        )).total_seconds()
        freshness = (
            SourceFreshness.FRESH
            if abs(age_seconds) < self.max_age_seconds
            else SourceFreshness.STALE
        )

        artifact = RawSourceArtifact(
            artifact_id=artifact_id,
            source_type=self.source_type,
            provider=self.provider,
            source_uri=url,
            retrieved_at=now,
            issued_at=first_time,
            valid_from=first_time,
            valid_to=last_time + timedelta(hours=1),
            raw_sha256=raw_hash,
            media_type="application/json",
            adapter_version=self.adapter_version,
            parser_version=_OPEN_METEO_PARSER_VERSION,
            freshness=freshness,
            evidence_class=EvidenceClass.OBSERVED,
        )
        LOGGER.info(
            "source.fetched provider=open-meteo zone=%s sha256=%s freshness=%s",
            zone_id, raw_hash[:12], freshness,
        )
        return artifact

    def normalize(self, artifact: RawSourceArtifact) -> tuple[HourlyCondition, ...]:
        if artifact.provider != self.provider:
            raise SourceParseError(f"Artifact provider mismatch: {artifact.provider}")
        # Re-fetch is not ideal; in production, store raw bytes alongside artifact.
        # For this implementation, we re-derive conditions from the artifact's source_uri.
        # The sha256 binds the content — re-fetching re-verifies.
        try:
            req = urllib.request.Request(
                artifact.source_uri,
                headers={"User-Agent": "HeatReserve/0.3.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw_bytes = resp.read()
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise SourceFetchError(f"Re-fetch for normalization failed: {exc}") from exc

        actual_hash = sha256_bytes(raw_bytes)
        if actual_hash != artifact.raw_sha256:
            raise SourceParseError(
                f"Re-fetched data hash mismatch: expected {artifact.raw_sha256[:12]} "
                f"got {actual_hash[:12]} — source changed between fetch and normalize"
            )
        return self._parse_conditions(raw_bytes, artifact)

    def normalize_from_bytes(
        self, raw_bytes: bytes, artifact: RawSourceArtifact
    ) -> tuple[HourlyCondition, ...]:
        actual_hash = sha256_bytes(raw_bytes)
        if actual_hash != artifact.raw_sha256:
            raise SourceParseError("Byte hash mismatch during normalization")
        return self._parse_conditions(raw_bytes, artifact)

    def _parse_conditions(
        self, raw_bytes: bytes, artifact: RawSourceArtifact
    ) -> tuple[HourlyCondition, ...]:
        payload = json.loads(raw_bytes)
        hourly = payload.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        humidity = hourly.get("relative_humidity_2m", [])
        apparent = hourly.get("apparent_temperature", [])
        solar = hourly.get("shortwave_radiation", [])
        weather_codes = hourly.get("weathercode", [])

        if not (len(times) == len(temps) == len(humidity) == len(apparent)):
            raise SourceParseError("Open-Meteo hourly arrays have inconsistent lengths")

        tz = ZoneInfo(self.timezone)
        snapshot_id = f"snap-{artifact.artifact_id}"
        conditions: list[HourlyCondition] = []

        for i, time_str in enumerate(times):
            at = datetime.fromisoformat(time_str).replace(tzinfo=tz)
            t_c = float(temps[i]) if i < len(temps) else 0.0
            rh = float(humidity[i]) if i < len(humidity) else 50.0
            app_c = float(apparent[i]) if i < len(apparent) else t_c
            solar_w = float(solar[i]) if i < len(solar) else 0.0
            wcode = int(weather_codes[i]) if i < len(weather_codes) else 0
            # solar proxy: normalize shortwave radiation (0-1200 W/m²) to 0-1
            solar_proxy = min(1.0, max(0.0, solar_w / 1200.0))
            # Approximate heat warning heuristic (apparent > 40°C or extreme weather)
            warning_flag = app_c >= 40.0 or wcode >= 95

            fact_id = canonical_sha256({
                "snapshot_id": snapshot_id,
                "at": at.isoformat(),
                "source": self.provider,
            })
            conditions.append(
                HourlyCondition(
                    fact_id=f"fact-{fact_id[:12]}",
                    at=at,
                    temperature_c=round(t_c, 2),
                    relative_humidity_pct=round(max(0.0, min(100.0, rh)), 2),
                    apparent_temperature_c=round(app_c, 2),
                    solar_proxy=round(solar_proxy, 4),
                    warning_flag=warning_flag,
                    source_snapshot_id=snapshot_id,
                )
            )

        LOGGER.info(
            "source.normalized provider=open-meteo rows=%d snapshot=%s",
            len(conditions), snapshot_id,
        )
        return tuple(conditions)


def fetch_and_normalize_live(
    lat: float,
    lon: float,
    zone_id: str,
    timeout_seconds: float = 10.0,
    max_age_seconds: int = 3600,
    timezone: str = "Asia/Kolkata",
) -> tuple[RawSourceArtifact, SourceSnapshot, tuple[HourlyCondition, ...]]:
    """
    Fetch real weather from Open-Meteo, verify hash, normalize into domain facts.
    Returns the raw artifact, a domain snapshot, and hourly conditions.

    INVARIANT: on any failure, raises — never returns synthetic data.
    """
    adapter = OpenMeteoWeatherAdapter(
        lat=lat,
        lon=lon,
        timezone=timezone,
        timeout_seconds=timeout_seconds,
        max_age_seconds=max_age_seconds,
    )
    # Fetch + keep raw bytes in one pass (avoid re-fetching for normalize)
    url = adapter._build_url()
    now = datetime.now(UTC)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "HeatReserve/0.3.0 (climate-adaptation-research)"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        raise SourceFetchError(
            f"Open-Meteo HTTP {exc.code} for zone {zone_id}"
        ) from exc
    except (OSError, urllib.error.URLError) as exc:
        raise SourceFetchError(f"Open-Meteo network error for zone {zone_id}: {exc}") from exc

    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise SourceParseError(f"Non-JSON from Open-Meteo: {exc}") from exc

    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        raise SourceParseError("Open-Meteo returned empty hourly data")

    tz = ZoneInfo(timezone)
    first_time = datetime.fromisoformat(times[0]).replace(tzinfo=tz)
    last_time = datetime.fromisoformat(times[-1]).replace(tzinfo=tz)

    raw_hash = sha256_bytes(raw_bytes)
    artifact_id = raw_hash[:16]

    freshness = SourceFreshness.FRESH  # just fetched

    artifact = RawSourceArtifact(
        artifact_id=artifact_id,
        source_type="hourly_weather",
        provider="open-meteo",
        source_uri=url,
        retrieved_at=now,
        issued_at=first_time,
        valid_from=first_time,
        valid_to=last_time + timedelta(hours=1),
        raw_sha256=raw_hash,
        media_type="application/json",
        adapter_version=_ADAPTER_VERSION,
        parser_version=_OPEN_METEO_PARSER_VERSION,
        freshness=freshness,
        evidence_class=EvidenceClass.OBSERVED,
    )

    snapshot = _build_snapshot(artifact)

    # Parse conditions from the bytes we already have
    temp_adapter = OpenMeteoWeatherAdapter(lat=lat, lon=lon, timezone=timezone)
    conditions = temp_adapter.normalize_from_bytes(raw_bytes, artifact)

    return artifact, snapshot, conditions


class LiveSourceStatus:
    """Tracks freshness of the last successful live fetch."""

    def __init__(self) -> None:
        self._artifact: RawSourceArtifact | None = None
        self._snapshot: SourceSnapshot | None = None
        self._conditions: tuple[HourlyCondition, ...] = ()
        self._fetched_at: datetime | None = None

    def update(
        self,
        artifact: RawSourceArtifact,
        snapshot: SourceSnapshot,
        conditions: tuple[HourlyCondition, ...],
    ) -> None:
        self._artifact = artifact
        self._snapshot = snapshot
        self._conditions = conditions
        self._fetched_at = datetime.now(UTC)

    def is_fresh(self, max_age_seconds: int) -> bool:
        if self._fetched_at is None:
            return False
        age = (datetime.now(UTC) - self._fetched_at).total_seconds()
        return age < max_age_seconds

    def to_dict(self, max_age_seconds: int) -> dict[str, object]:
        if self._artifact is None:
            return {"status": "UNAVAILABLE", "fetched_at": None, "freshness": "UNAVAILABLE"}
        age = (datetime.now(UTC) - self._fetched_at).total_seconds() if self._fetched_at else None
        return {
            "status": "FRESH" if self.is_fresh(max_age_seconds) else "STALE",
            "provider": self._artifact.provider,
            "fetched_at": self._fetched_at.isoformat() if self._fetched_at else None,
            "artifact_id": self._artifact.artifact_id,
            "raw_sha256": self._artifact.raw_sha256,
            "evidence_class": self._artifact.evidence_class,
            "condition_count": len(self._conditions),
            "age_seconds": round(age, 1) if age is not None else None,
            "max_age_seconds": max_age_seconds,
        }

    @property
    def artifact(self) -> RawSourceArtifact | None:
        return self._artifact

    @property
    def snapshot(self) -> SourceSnapshot | None:
        return self._snapshot

    @property
    def conditions(self) -> tuple[HourlyCondition, ...]:
        return self._conditions
