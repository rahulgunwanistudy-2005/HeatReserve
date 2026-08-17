"""Tests for source adapter framework."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from heatreserve.sources import (
    OpenMeteoWeatherAdapter,
    SourceFetchError,
    SourceParseError,
    LiveSourceStatus,
)


class TestOpenMeteoAdapter:
    def _make_payload(self, n_hours: int = 24) -> bytes:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Kolkata")
        base = datetime(2024, 5, 25, 0, 0, tzinfo=tz)
        times = [(base.replace(hour=h)).strftime("%Y-%m-%dT%H:%M") for h in range(n_hours)]
        return json.dumps({
            "latitude": 28.6139,
            "longitude": 77.209,
            "generationtime_ms": 0.5,
            "hourly": {
                "time": times,
                "temperature_2m": [35.0 + i * 0.1 for i in range(n_hours)],
                "relative_humidity_2m": [50.0 for _ in range(n_hours)],
                "apparent_temperature": [38.0 + i * 0.1 for i in range(n_hours)],
                "shortwave_radiation": [600.0 for _ in range(n_hours)],
                "weathercode": [1 for _ in range(n_hours)],
            },
        }).encode()

    def test_fetch_raises_on_http_error(self):
        import urllib.error
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="", code=429, msg="rate limited", hdrs=None, fp=None
            )
            with pytest.raises(SourceFetchError, match="429"):
                adapter.fetch("ZONE_A")

    def test_fetch_raises_on_network_error(self):
        import urllib.error
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.URLError(reason="connection refused")
            with pytest.raises(SourceFetchError, match="network error"):
                adapter.fetch("ZONE_A")

    def test_parse_error_on_invalid_json(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json {"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(SourceParseError, match="non-JSON"):
                adapter.fetch("ZONE_A")

    def test_artifact_has_sha256_bound_content(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        raw = self._make_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            artifact = adapter.fetch("ZONE_A")
        from heatreserve.evidence import sha256_bytes
        assert artifact.raw_sha256 == sha256_bytes(raw)
        assert artifact.provider == "open-meteo"
        assert artifact.source_type == "hourly_weather"

    def test_normalize_from_bytes_produces_correct_row_count(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        raw = self._make_payload(n_hours=24)
        from heatreserve.evidence import sha256_bytes
        sha = sha256_bytes(raw)

        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            artifact = adapter.fetch("ZONE_A")

        conditions = adapter.normalize_from_bytes(raw, artifact)
        assert len(conditions) == 24
        assert all(c.source_snapshot_id.startswith("snap-") for c in conditions)

    def test_normalize_rejects_hash_mismatch(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        raw = self._make_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            artifact = adapter.fetch("ZONE_A")

        tampered = raw + b" extra"
        with pytest.raises(SourceParseError, match="hash mismatch"):
            adapter.normalize_from_bytes(tampered, artifact)

    def test_conditions_are_timezone_aware(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        raw = self._make_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            artifact = adapter.fetch("ZONE_A")
        conditions = adapter.normalize_from_bytes(raw, artifact)
        for cond in conditions:
            assert cond.at.tzinfo is not None

    def test_warning_flag_set_for_extreme_apparent_temp(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        raw = json.dumps({
            "hourly": {
                "time": ["2024-05-25T14:00"],
                "temperature_2m": [42.0],
                "relative_humidity_2m": [55.0],
                "apparent_temperature": [45.0],  # > 40 → warning
                "shortwave_radiation": [900.0],
                "weathercode": [1],
            }
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            artifact = adapter.fetch("ZONE_A")
        conditions = adapter.normalize_from_bytes(raw, artifact)
        assert len(conditions) == 1
        assert conditions[0].warning_flag is True

    def test_solar_proxy_normalized_to_0_1(self):
        adapter = OpenMeteoWeatherAdapter(lat=28.6, lon=77.2)
        raw = json.dumps({
            "hourly": {
                "time": ["2024-05-25T12:00"],
                "temperature_2m": [35.0],
                "relative_humidity_2m": [50.0],
                "apparent_temperature": [38.0],
                "shortwave_radiation": [1200.0],  # max value
                "weathercode": [0],
            }
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            artifact = adapter.fetch("ZONE_A")
        conditions = adapter.normalize_from_bytes(raw, artifact)
        assert 0.0 <= conditions[0].solar_proxy <= 1.0


class TestLiveSourceStatus:
    def test_not_fresh_before_update(self):
        status = LiveSourceStatus()
        assert not status.is_fresh(3600)
        d = status.to_dict(3600)
        assert d["status"] == "UNAVAILABLE"

    def test_fresh_after_update(self):
        from datetime import datetime, UTC
        from heatreserve.domain import EvidenceClass, SourceFreshness, RawSourceArtifact
        from heatreserve.domain import SourceSnapshot
        from heatreserve.evidence import sha256_bytes

        raw = b"fake-raw"
        sha = sha256_bytes(raw)
        from datetime import timedelta
        now = datetime.now(UTC)
        artifact = RawSourceArtifact(
            artifact_id=sha[:16],
            source_type="hourly_weather",
            provider="open-meteo",
            source_uri="https://example.com",
            retrieved_at=now,
            issued_at=now,
            valid_from=now,
            valid_to=now + timedelta(hours=24),
            raw_sha256=sha,
            media_type="application/json",
            adapter_version="v1",
            parser_version="v1",
            freshness=SourceFreshness.FRESH,
            evidence_class=EvidenceClass.OBSERVED,
        )
        snapshot = SourceSnapshot(
            snapshot_id=f"snap-{sha[:16]}",
            source_type="hourly_weather",
            source_uri="https://example.com",
            issued_at=now,
            fetched_at=now,
            valid_from=now,
            valid_to=now + timedelta(hours=24),
            raw_sha256=sha,
            parser_version="v1",
            verified=True,
            evidence_class=EvidenceClass.OBSERVED,
        )
        status = LiveSourceStatus()
        status.update(artifact, snapshot, ())
        assert status.is_fresh(3600)
        d = status.to_dict(3600)
        assert d["status"] == "FRESH"
        assert d["provider"] == "open-meteo"
        assert d["raw_sha256"] == sha
