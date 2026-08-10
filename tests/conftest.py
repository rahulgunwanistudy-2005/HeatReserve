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
        fixture_dir=fixture_dir,
        planner_provider="deterministic",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen3:4b",
        log_level="WARNING",
        allowed_origins=("http://localhost:8000",),
    )


@pytest.fixture
def service(settings: Settings) -> HeatReserveService:
    return HeatReserveService(settings)
