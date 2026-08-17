from fastapi.testclient import TestClient

from heatreserve.api import create_app


def test_health_and_security_headers(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["fixture_manifest"] == "VERIFIED"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_judge_run_is_complete_and_tamper_evident(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/judge/run")
        assert response.status_code == 200
        body = response.json()
        assert body["commitment"]["decision"]["status"] == "QUALIFIED"
        assert body["receipt_verification"]["valid"] is True
        assert body["tamper_verification"]["valid"] is False
        assert body["reconciliation"]["ledger_reconciles"] is True


def test_commitment_endpoint_is_idempotent(settings) -> None:
    payload = {
        "episode_id": "episode:demo-delhi-001",
        "policy_id": "delhi-rider-adaptation",
        "policy_version": "1.0.0",
    }
    with TestClient(create_app(settings)) as client:
        client.post("/v1/judge/reset")
        first = client.post("/v1/workers/demo-worker-001/commitments", json=payload)
        second = client.post("/v1/workers/demo-worker-001/commitments", json=payload)
        assert first.status_code == 201
        assert second.status_code == 200
        assert first.json()["commitment_id"] == second.json()["commitment_id"]


def test_invalid_request_returns_structured_error(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/allocator/scenarios", json={"budget_minor": -1})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_frontend_is_served_without_external_dependency(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "HeatReserve" in response.text
        assert "https://fonts" not in response.text


def test_liveness_survives_fixture_readiness_failure(settings, tmp_path) -> None:
    import shutil

    broken = tmp_path / "broken-fixtures"
    shutil.copytree(settings.fixture_dir, broken)
    (broken / "warning.json").write_bytes((broken / "warning.json").read_bytes() + b" ")
    bad_settings = settings.__class__(
        mode=settings.mode,
        database_path=tmp_path / "broken.db",
        database_url=None,
        fixture_dir=broken,
        planner_provider=settings.planner_provider,
        ollama_url=settings.ollama_url,
        ollama_model=settings.ollama_model,
        planner_timeout_seconds=settings.planner_timeout_seconds,
        log_level=settings.log_level,
        allowed_origins=settings.allowed_origins,
        source_provider="fixture",
        source_timeout_seconds=10.0,
        source_max_age_seconds=3600,
        open_meteo_lat=settings.open_meteo_lat,
        open_meteo_lon=settings.open_meteo_lon,
        open_meteo_zone_id=settings.open_meteo_zone_id,
        auth_mode="none",
        api_keys=frozenset(),
        receipt_signing_key_path=None,
        receipt_signing_key_id="key-1",
        max_consecutive_work_hours=3,
    )
    with TestClient(create_app(bad_settings), raise_server_exceptions=False) as client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["ready"] is False
        blocked = client.post("/v1/judge/run")
        assert blocked.status_code == 503
        assert blocked.json()["error"]["code"] == "SERVICE_NOT_READY"


def test_plan_rejects_worker_without_zone_bound_hourly_facts(settings) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/workers/demo-worker-004/plans",
            json={"episode_id": "episode:demo-delhi-001"},
        )
        assert response.status_code == 409
        assert "No verified hourly replay facts" in response.json()["error"]["message"]


def test_receipt_verify_endpoint_validates_schema_and_digest(settings) -> None:
    with TestClient(create_app(settings)) as client:
        receipt = client.post("/v1/judge/run").json()["receipt"]
        verified = client.post("/v1/receipts/verify", json={"receipt": receipt})
        assert verified.status_code == 200
        assert verified.json()["valid"] is True

        malformed = dict(receipt)
        malformed.pop("plan_sha256")
        rejected = client.post("/v1/receipts/verify", json={"receipt": malformed})
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"
