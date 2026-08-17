from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .auth import AuthError, authenticate_api_key, judge_auth
from .config import Settings
from .domain import DecisionReceipt
from .receipts import verify_receipt
from .service import HeatReserveService
from .sources import SourceFetchError, SourceParseError, SourceStaleError

LOGGER = logging.getLogger("heatreserve.api")
_web_dir_env = os.getenv("HEATRESERVE_WEB_DIR", "")
WEB_DIR = Path(_web_dir_env) if _web_dir_env else Path(__file__).resolve().parents[2] / "web"


# ── Request models ──────────────────────────────────────────────────────────

class CommitmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: str
    policy_id: str
    policy_version: str


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: str


class AllocatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_minor: int | None = Field(default=None, ge=0)


class ReceiptVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt: DecisionReceipt


# ── Exceptions ───────────────────────────────────────────────────────────────

class ServiceUnavailableError(RuntimeError):
    pass


# ── Rate limiter ─────────────────────────────────────────────────────────────

class FixedWindowLimiter:
    def __init__(self, limit: int = 90, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


# ── Auth helper ───────────────────────────────────────────────────────────────

def _resolve_auth(request: Request, service: "HeatReserveService"):
    """Return authorization context. Raises AuthError if auth required but missing/invalid."""
    settings = service.settings
    if settings.auth_mode == "none" or settings.is_judge or settings.mode == "replay":
        return judge_auth()
    if settings.auth_mode == "apikey":
        api_key = request.headers.get("X-API-Key")
        return authenticate_api_key(api_key, settings.api_keys)
    return judge_auth()


# ── Logging ───────────────────────────────────────────────────────────────────

def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


# ── Lifespan ─────────────────────────────────────────────────────────────────

def _lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rate_limiter = FixedWindowLimiter()
        app.state.service = None
        app.state.startup_error = None
        try:
            app.state.service = HeatReserveService(settings)
        except Exception as exc:
            app.state.startup_error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("HeatReserve service failed readiness initialization")
        yield
    return lifespan


# ── Middleware ────────────────────────────────────────────────────────────────

def _install_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def security_and_rate_limit(request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        limiter: FixedWindowLimiter = request.app.state.rate_limiter
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not limiter.allow(client):
            return _secured(_error(429, "RATE_LIMITED", "Too many requests. Try again shortly."))
        started = time.perf_counter()
        response = await call_next(request)
        _security_headers(response)
        LOGGER.info(
            "request method=%s path=%s status=%s duration_ms=%.2f",
            request.method, request.url.path, response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response


def _security_headers(response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )


def _secured(response: JSONResponse) -> JSONResponse:
    _security_headers(response)
    return response


# ── Exception handlers ────────────────────────────────────────────────────────

def _install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        return _error(422, "VALIDATION_ERROR", "Request validation failed.", exc.errors())

    @app.exception_handler(AuthError)
    async def auth_error_handler(_: Request, exc: AuthError):
        code = 401 if exc.code == "AUTH_REQUIRED" else 403
        return _error(code, exc.code, str(exc))

    @app.exception_handler(ServiceUnavailableError)
    async def unavailable_handler(_: Request, exc: ServiceUnavailableError):
        return _error(503, "SERVICE_NOT_READY", str(exc))

    @app.exception_handler(SourceFetchError)
    async def source_fetch_handler(_: Request, exc: SourceFetchError):
        return _error(503, "SOURCE_UNAVAILABLE", str(exc))

    @app.exception_handler(SourceStaleError)
    async def source_stale_handler(_: Request, exc: SourceStaleError):
        return _error(503, "SOURCE_STALE", str(exc))

    @app.exception_handler(SourceParseError)
    async def source_parse_handler(_: Request, exc: SourceParseError):
        return _error(502, "SOURCE_PARSE_ERROR", str(exc))

    @app.exception_handler(KeyError)
    async def not_found_handler(_: Request, exc: KeyError):
        return _error(404, "NOT_FOUND", str(exc).strip("'"))

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError):
        return _error(409, "CONFLICT", str(exc))

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        LOGGER.exception("Unhandled request error path=%s", request.url.path, exc_info=exc)
        return _error(500, "INTERNAL_ERROR", "The request could not be completed.")


# ── Routers ───────────────────────────────────────────────────────────────────

def _health_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @router.get("/health/ready")
    def ready(request: Request):
        service = getattr(request.app.state, "service", None)
        if service is None:
            return JSONResponse(status_code=503, content={
                "ready": False,
                "errors": [getattr(request.app.state, "startup_error", "service unavailable")],
            })
        result = service.readiness()
        return result if result["ready"] else JSONResponse(status_code=503, content=result)

    return router


def _judge_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/judge/reset")
    def judge_reset(request: Request):
        return _service(request).reset_demo()

    @router.post("/v1/judge/run")
    def judge_run(request: Request):
        return _service(request).run_judge_demo()

    @router.get("/v1/episodes/{episode_id}")
    def episode(request: Request, episode_id: str):
        return _service(request).get_episode(episode_id)

    return router


def _decision_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/workers/{worker_id}/commitments")
    def commitment(request: Request, worker_id: str, body: CommitmentRequest):
        service = _service(request)
        _resolve_auth(request, service)
        record = service.create_commitment(
            worker_id, body.episode_id, body.policy_id, body.policy_version
        )
        payload = {
            "commitment_id": record.commitment_id or None,
            "created": record.created,
            "decision": record.decision,
        }
        if record.decision.status != "QUALIFIED":
            details = {
                "error": {
                    "code": "NOT_QUALIFIED",
                    "message": "Commitment not created.",
                    "details": payload,
                }
            }
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT, content=_jsonable(details)
            )
        code = status.HTTP_201_CREATED if record.created else status.HTTP_200_OK
        return JSONResponse(status_code=code, content=_jsonable(payload))

    @router.post("/v1/workers/{worker_id}/plans", status_code=201)
    def plan(request: Request, worker_id: str, body: PlanRequest):
        service = _service(request)
        _resolve_auth(request, service)
        return service.create_plan(worker_id, body.episode_id)

    return router


def _support_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/allocator/scenarios")
    def allocator(request: Request, body: AllocatorRequest):
        service = _service(request)
        return {"results": service.allocator_scenarios(body.budget_minor)}

    @router.get("/v1/receipts/{receipt_id}")
    def receipt(request: Request, receipt_id: str):
        return _service(request).receipt(receipt_id)

    @router.post("/v1/receipts/verify")
    def receipt_verify(body: ReceiptVerifyRequest):
        return verify_receipt(body.receipt)

    @router.get("/v1/evidence/sources")
    def evidence_sources(request: Request):
        return {"sources": _service(request).evidence_sources()}

    @router.get("/v1/evidence/live")
    def evidence_live(request: Request):
        """
        Returns the current live-source status.
        In judge/replay mode, returns the fixture evidence summary.
        In live mode, returns actual adapter status (freshness, sha256, age).
        """
        service = _service(request)
        if service.settings.is_live:
            return service.live_source_status()
        # Fixture mode: return evidence class label clearly
        return {
            "status": "FIXTURE",
            "mode": service.settings.mode,
            "provider": "fixture",
            "evidence_class": "SIMULATED",
            "sources": service.evidence_sources(),
        }

    return router


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging(settings.log_level)
    app = FastAPI(
        title="HeatReserve API",
        version="0.3.0",
        description=(
            "Anticipatory heat-adaptation decision infrastructure. "
            f"Mode: {settings.mode}. "
            "AI plans. Policy controls money."
        ),
        lifespan=_lifespan(settings),
    )
    _install_middleware(app, settings)
    _install_exception_handlers(app)
    for router in (
        _health_router(),
        _judge_router(),
        _decision_router(),
        _support_router(),
    ):
        app.include_router(router)
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def web_index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    return app


def _service(request: Request) -> HeatReserveService:
    service = getattr(request.app.state, "service", None)
    if service is None:
        detail = getattr(request.app.state, "startup_error", "service unavailable")
        raise ServiceUnavailableError(detail)
    return service


def _error(
    status_code: int, code: str, message: str, details: Any | None = None
) -> JSONResponse:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=_jsonable(payload))


def _jsonable(value: Any) -> Any:
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder(value)


app = create_app()
