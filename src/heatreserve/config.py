from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

VALID_MODES = {"judge", "replay", "safe_fallback", "live"}
VALID_PROVIDERS = {"deterministic", "ollama"}
VALID_AUTH_MODES = {"none", "apikey"}
VALID_DB_SCHEMES = {"sqlite", "postgresql", "postgresql+psycopg2"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    mode: str
    database_path: Path
    database_url: str | None
    fixture_dir: Path
    planner_provider: str
    ollama_url: str
    ollama_model: str
    planner_timeout_seconds: float
    log_level: str
    allowed_origins: tuple[str, ...]
    # Source ingestion
    source_provider: str
    source_timeout_seconds: float
    source_max_age_seconds: int
    open_meteo_lat: float
    open_meteo_lon: float
    open_meteo_zone_id: str
    # Auth
    auth_mode: str
    api_keys: frozenset[str]
    # Receipt signing (Ed25519)
    receipt_signing_key_path: Path | None
    receipt_signing_key_id: str
    # Optimizer
    max_consecutive_work_hours: int

    @classmethod
    def from_env(cls) -> "Settings":
        root = _repo_root()
        mode = os.getenv("HEATRESERVE_MODE", "judge").lower().strip()
        if mode not in VALID_MODES:
            raise ValueError(
                f"Unsupported HEATRESERVE_MODE={mode!r}. Valid: {sorted(VALID_MODES)}"
            )
        database_path = Path(
            os.getenv("HEATRESERVE_DATABASE_PATH", str(root / "data" / "heatreserve.db"))
        ).expanduser()
        database_url = os.getenv("HEATRESERVE_DATABASE_URL") or None
        fixture_dir = Path(
            os.getenv("HEATRESERVE_FIXTURE_DIR", str(root / "fixtures" / "judge_mode"))
        ).expanduser()
        provider = os.getenv("HEATRESERVE_PLANNER_PROVIDER", "deterministic").lower().strip()
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Unsupported planner provider={provider!r}")
        auth_mode = os.getenv("HEATRESERVE_AUTH_MODE", "none").lower().strip()
        if auth_mode not in VALID_AUTH_MODES:
            raise ValueError(f"Unsupported auth mode={auth_mode!r}")
        raw_keys = os.getenv("HEATRESERVE_API_KEYS", "")
        api_keys: frozenset[str] = frozenset(
            k.strip() for k in raw_keys.split(",") if k.strip()
        )
        signing_key_raw = os.getenv("HEATRESERVE_RECEIPT_SIGNING_KEY_PATH", "")
        signing_key_path: Path | None = (
            Path(signing_key_raw).expanduser() if signing_key_raw.strip() else None
        )
        if mode == "live" and auth_mode == "none":
            # Live mode without auth is still allowed but operators should set keys
            pass
        return cls(
            mode=mode,
            database_path=database_path,
            database_url=database_url,
            fixture_dir=fixture_dir,
            planner_provider=provider,
            ollama_url=os.getenv("HEATRESERVE_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("HEATRESERVE_OLLAMA_MODEL", "qwen3:4b"),
            planner_timeout_seconds=float(
                os.getenv("HEATRESERVE_PLANNER_TIMEOUT_SECONDS", "4.0")
            ),
            log_level=os.getenv("HEATRESERVE_LOG_LEVEL", "INFO").upper(),
            allowed_origins=_split_csv(
                os.getenv(
                    "HEATRESERVE_ALLOWED_ORIGINS",
                    "http://localhost:8000,http://127.0.0.1:8000",
                )
            ),
            source_provider=os.getenv("HEATRESERVE_SOURCE_PROVIDER", "fixture"),
            source_timeout_seconds=float(
                os.getenv("HEATRESERVE_SOURCE_TIMEOUT_SECONDS", "10.0")
            ),
            source_max_age_seconds=int(
                os.getenv("HEATRESERVE_SOURCE_MAX_AGE_SECONDS", "3600")
            ),
            open_meteo_lat=float(os.getenv("HEATRESERVE_OPEN_METEO_LAT", "28.6139")),
            open_meteo_lon=float(os.getenv("HEATRESERVE_OPEN_METEO_LON", "77.2090")),
            open_meteo_zone_id=os.getenv(
                "HEATRESERVE_OPEN_METEO_ZONE_ID", "DELHI_DEMO_ZONE_A"
            ),
            auth_mode=auth_mode,
            api_keys=api_keys,
            receipt_signing_key_path=signing_key_path,
            receipt_signing_key_id=os.getenv(
                "HEATRESERVE_RECEIPT_SIGNING_KEY_ID", "key-1"
            ),
            max_consecutive_work_hours=int(
                os.getenv("HEATRESERVE_MAX_CONSECUTIVE_WORK_HOURS", "3")
            ),
        )

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_judge(self) -> bool:
        return self.mode == "judge"

    @property
    def uses_postgres(self) -> bool:
        url = self.database_url or ""
        return url.startswith("postgresql")
