from pathlib import Path

import pytest

from heatreserve.config import Settings
from heatreserve.service import HeatReserveService


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "judge_mode"


@pytest.fixture
def settings(tmp_path: Path, fixture_dir: Path) -> Settings:
    return Settings(
        mode="judge",
        database_path=tmp_path / "heatreserve-test.db",
        database_url=None,
        fixture_dir=fixture_dir,
        planner_provider="deterministic",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen3:4b",
        planner_timeout_seconds=4.0,
        log_level="WARNING",
        allowed_origins=("http://localhost:8000",),
        source_provider="fixture",
        source_timeout_seconds=10.0,
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


@pytest.fixture
def service(settings: Settings) -> HeatReserveService:
    return HeatReserveService(settings)
