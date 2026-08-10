from __future__ import annotations

import tempfile
import urllib.request
from pathlib import Path

from heatreserve.config import Settings
from heatreserve.evidence import require_verified_manifest
from heatreserve.service import HeatReserveService

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "judge_mode"


def blocked_network(*args, **kwargs):
    raise RuntimeError("network access is disabled during judge-check")


with tempfile.TemporaryDirectory(prefix="heatreserve-judge-") as tmp:
    require_verified_manifest(FIXTURE_DIR)
    urllib.request.urlopen = blocked_network
    settings = Settings(
        mode="judge",
        database_path=Path(tmp) / "judge.db",
        fixture_dir=FIXTURE_DIR,
        planner_provider="deterministic",
        ollama_url="http://127.0.0.1:11434",
        ollama_model="qwen3:4b",
        log_level="WARNING",
        allowed_origins=("http://localhost:8000",),
    )
    service = HeatReserveService(settings)
    result = service.run_judge_demo()
    assert result["commitment"]["decision"].status == "QUALIFIED"
    assert result["receipt_verification"]["valid"] is True
    assert result["tamper_verification"]["valid"] is False
    assert result["reconciliation"]["ledger_reconciles"] is True
print("judge-check: PASS")
