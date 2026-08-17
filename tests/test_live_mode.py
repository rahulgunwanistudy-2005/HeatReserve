"""
Tests for live mode invariants.

INVARIANT: live mode never silently falls back to fixture data.
           Source failures are transparent, not hidden.

These tests use mocking to simulate live source behavior without
making real network calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from heatreserve.config import Settings
from heatreserve.sources import SourceFetchError


def _live_settings(tmp_path: Path, fixture_dir: Path) -> Settings:
    return Settings(
        mode="live",
        database_path=tmp_path / "live-test.db",
        database_url=None,
        fixture_dir=fixture_dir,
        planner_provider="deterministic",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen3:4b",
        planner_timeout_seconds=4.0,
        log_level="WARNING",
        allowed_origins=("http://localhost:8000",),
        source_provider="open-meteo",
        source_timeout_seconds=5.0,
        source_max_age_seconds=3600,
        open_meteo_lat=28.6139,
        open_meteo_lon=77.2090,
        open_meteo_zone_id="DELHI_DEMO_ZONE_A",
        auth_mode="none",
        api_keys=frozenset(),
        receipt_signing_key_path=None,
        receipt_signing_key_id="key-1",
        max_consecutive_work_hours=3,
    )


def _fake_open_meteo_payload() -> bytes:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Asia/Kolkata")
    times = [(datetime(2024, 5, 25, h, 0, tzinfo=tz)).strftime("%Y-%m-%dT%H:%M")
             for h in range(24)]
    return json.dumps({
        "latitude": 28.6139,
        "longitude": 77.209,
        "generationtime_ms": 0.4,
        "hourly": {
            "time": times,
            "temperature_2m": [32.0 + h * 0.3 for h in range(24)],
            "relative_humidity_2m": [55.0 for _ in range(24)],
            "apparent_temperature": [35.0 + h * 0.3 for h in range(24)],
            "shortwave_radiation": [max(0.0, 600.0 * (1 - abs(h - 12) / 12)) for h in range(24)],
            "weathercode": [1 for _ in range(24)],
        },
    }).encode()


class TestLiveModeSourceInvariant:
    def test_live_mode_fetch_returns_real_conditions(self, tmp_path, fixture_dir):
        """Live source fetch must return real conditions, not fixture data."""
        settings = _live_settings(tmp_path, fixture_dir)
        raw = _fake_open_meteo_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        from heatreserve.service import HeatReserveService
        with patch("urllib.request.urlopen", return_value=mock_resp):
            service = HeatReserveService(settings)
            conditions = service.get_live_conditions()

        assert len(conditions) == 24
        for cond in conditions:
            assert cond.source_snapshot_id.startswith("snap-")
            assert cond.at.tzinfo is not None

    def test_live_mode_never_substitutes_fixture_on_failure(self, tmp_path, fixture_dir):
        """When live fetch fails, must raise SourceFetchError — not return fixture data."""
        import urllib.error
        settings = _live_settings(tmp_path, fixture_dir)

        from heatreserve.service import HeatReserveService
        service = HeatReserveService(settings)

        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.URLError(reason="connection refused")
            with pytest.raises(SourceFetchError):
                service.get_live_conditions()

    def test_live_mode_fixture_conditions_not_returned(self, tmp_path, fixture_dir):
        """get_live_conditions must not return fixture conditions."""
        import urllib.error
        settings = _live_settings(tmp_path, fixture_dir)
        from heatreserve.service import HeatReserveService
        service = HeatReserveService(settings)

        fixture_condition_ids = {c.fact_id for c in service.fixtures.conditions}

        raw = _fake_open_meteo_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            live_conditions = service.get_live_conditions()

        live_ids = {c.fact_id for c in live_conditions}
        # Live conditions should have different fact IDs from fixture conditions
        # (since they come from a different source with different timestamps)
        assert not (live_ids & fixture_condition_ids), (
            "Live conditions must not share fact IDs with fixture conditions"
        )

    def test_get_live_conditions_raises_outside_live_mode(self, service):
        """get_live_conditions must only work in live mode."""
        assert service.settings.mode == "judge"
        with pytest.raises(RuntimeError, match="live mode"):
            service.get_live_conditions()

    def test_live_source_status_shows_unavailable_initially(self, tmp_path, fixture_dir):
        """Before any fetch, live source status must show UNAVAILABLE."""
        settings = _live_settings(tmp_path, fixture_dir)
        from heatreserve.service import HeatReserveService
        service = HeatReserveService(settings)
        status = service.live_source_status()
        assert status["status"] == "UNAVAILABLE"

    def test_live_source_status_shows_fresh_after_successful_fetch(
        self, tmp_path, fixture_dir
    ):
        """After successful fetch, status must show FRESH with provider info."""
        settings = _live_settings(tmp_path, fixture_dir)
        raw = _fake_open_meteo_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        from heatreserve.service import HeatReserveService
        service = HeatReserveService(settings)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            service.get_live_conditions()

        status = service.live_source_status()
        assert status["status"] == "FRESH"
        assert status["provider"] == "open-meteo"
        assert "raw_sha256" in status
        assert "evidence_class" in status


class TestLiveModeEvidence:
    def test_live_conditions_have_observed_evidence_class(self, tmp_path, fixture_dir):
        """Live conditions must use OBSERVED (not SIMULATED) evidence class."""
        settings = _live_settings(tmp_path, fixture_dir)
        raw = _fake_open_meteo_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        from heatreserve.domain import EvidenceClass
        from heatreserve.service import HeatReserveService
        service = HeatReserveService(settings)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            service.get_live_conditions()

        status = service.live_source_status()
        assert status["evidence_class"] == EvidenceClass.OBSERVED

    def test_fixture_snapshot_sha256_differs_from_live_sha256(self, tmp_path, fixture_dir):
        """Live artifact sha256 must differ from fixture snapshots (different data)."""
        settings = _live_settings(tmp_path, fixture_dir)
        raw = _fake_open_meteo_payload()
        mock_resp = MagicMock()
        mock_resp.read.return_value = raw
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        from heatreserve.service import HeatReserveService
        service = HeatReserveService(settings)
        fixture_hashes = {s.raw_sha256 for s in service.fixtures.snapshots}
        with patch("urllib.request.urlopen", return_value=mock_resp):
            service.get_live_conditions()

        live_status = service.live_source_status()
        assert live_status["raw_sha256"] not in fixture_hashes
