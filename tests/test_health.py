"""Smoke tests for health endpoint, configuration, and JSON logging."""

import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.infrastructure.logging import JsonFormatter, request_id_var


def test_health_endpoint_returns_ok(
    api_client: TestClient,
    default_settings: Settings,
) -> None:
    """GET /health returns 200 with service metadata."""
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": default_settings.service_name,
        "version": default_settings.version,
    }


def test_docs_endpoint_returns_200(api_client: TestClient) -> None:
    """GET /docs returns 200 for OpenAPI Swagger UI."""
    response = api_client.get("/docs")

    assert response.status_code == 200


def test_settings_nested_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested BaseSettings sub-models respect prefixed and flat env overrides."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("API_PORT", "9000")
    monkeypatch.setenv("OCR_LANG", "en")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("ENABLE_PLAYGROUND", "true")
    monkeypatch.setenv("MIN_BLUR_SCORE", "75.5")
    monkeypatch.setenv("UNKNOWN_IGNORED_VAR", "ignored")

    settings = Settings()

    assert settings.log_level == "DEBUG"
    assert settings.app_env == "production"
    assert settings.version == "1.2.3"
    assert settings.api.port == 9000
    assert settings.ocr.lang == "en"
    assert settings.llm.model == "gpt-4o-mini"
    assert settings.llm.base_url == "https://api.example.com/v1"
    assert settings.playground.enable_playground is True
    assert settings.quality_gate.min_blur_score == 75.5


def test_json_formatter_includes_request_id_and_exc_info() -> None:
    """JsonFormatter emits single-line JSON with request_id contextvar and optional exc_info."""
    formatter = JsonFormatter()
    token = request_id_var.set("req-12345")
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.LogRecord(
                name="miru.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed %s",
                args=("step",),
                exc_info=sys.exc_info(),
            )

        formatted = formatter.format(record)
    finally:
        request_id_var.reset(token)

    assert "\n" not in formatted
    payload = json.loads(formatted)
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "miru.test"
    assert payload["request_id"] == "req-12345"
    assert payload["message"] == "failed step"
    assert "timestamp" in payload
    assert "ValueError: boom" in payload["exc_info"]
