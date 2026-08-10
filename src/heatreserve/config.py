from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    mode: str
    database_path: Path
    fixture_dir: Path
    planner_provider: str
    ollama_url: str
    ollama_model: str
    log_level: str
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        root = _repo_root()
        database_path = Path(
            os.getenv("HEATRESERVE_DATABASE_PATH", str(root / "data" / "heatreserve.db"))
        ).expanduser()
        fixture_dir = Path(
            os.getenv("HEATRESERVE_FIXTURE_DIR", str(root / "fixtures" / "judge_mode"))
        ).expanduser()
        mode = os.getenv("HEATRESERVE_MODE", "judge").lower().strip()
        provider = os.getenv("HEATRESERVE_PLANNER_PROVIDER", "deterministic").lower().strip()
        if mode not in {"judge", "replay", "safe_fallback"}:
            raise ValueError(f"Unsupported HEATRESERVE_MODE={mode!r}")
        if provider not in {"deterministic", "ollama"}:
            raise ValueError(f"Unsupported planner provider={provider!r}")
        return cls(
            mode=mode,
            database_path=database_path,
            fixture_dir=fixture_dir,
            planner_provider=provider,
            ollama_url=os.getenv("HEATRESERVE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("HEATRESERVE_OLLAMA_MODEL", "qwen3:4b"),
            log_level=os.getenv("HEATRESERVE_LOG_LEVEL", "INFO").upper(),
            allowed_origins=_split_csv(
                os.getenv(
                    "HEATRESERVE_ALLOWED_ORIGINS",
                    "http://localhost:8000,http://127.0.0.1:8000",
                )
            ),
        )
