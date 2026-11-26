"""Unit tests for FastAPI exception handlers and ErrorResponse formatting."""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.error_handlers import register_exception_handlers
from app.domain.exceptions import (
    ExtractionFailedError,
    ImageTooBlurryError,
    InvalidImageError,
    MiruDomainError,
    ProviderTimeoutError,
    UnsupportedDocumentError,
)
from app.infrastructure.logging import request_id_var


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    router = APIRouter()

    @router.get("/blurry")
    def raise_blurry() -> None:
        raise ImageTooBlurryError("Image is too blurry", details={"blur_score": 12.5})

    @router.get("/invalid-image")
    def raise_invalid_image() -> None:
        raise InvalidImageError("Corrupted image bytes")

    @router.get("/unsupported")
    def raise_unsupported() -> None:
        raise UnsupportedDocumentError("Unsupported document type")

    @router.get("/timeout")
    def raise_timeout() -> None:
        raise ProviderTimeoutError("Upstream LLM timed out")

    @router.get("/extraction-failed")
    def raise_extraction_failed() -> None:
        raise ExtractionFailedError("Failed to parse fields")

    @router.get("/domain-base")
    def raise_domain_base() -> None:
        raise MiruDomainError("Generic domain failure")

    @router.get("/unhandled")
    def raise_unhandled() -> None:
        raise RuntimeError("Sensitive PII: NIK 3171234567890001 leaked")

    app.include_router(router)
    return app


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code", "expected_details"),
    [
        ("/blurry", 422, "IMAGE_TOO_BLURRY", {"blur_score": 12.5}),
        ("/invalid-image", 400, "INVALID_IMAGE", None),
        ("/unsupported", 400, "UNSUPPORTED_DOCUMENT", None),
        ("/timeout", 504, "PROVIDER_TIMEOUT", None),
        ("/extraction-failed", 500, "EXTRACTION_FAILED", None),
        ("/domain-base", 500, "DOMAIN_ERROR", None),
    ],
)
def test_domain_exception_status_and_shape(
    path: str,
    expected_status: int,
    expected_code: str,
    expected_details: dict[str, float] | None,
) -> None:
    """Domain exceptions map to expected HTTP status codes and ErrorResponse JSON shape."""
    client = TestClient(_build_test_app())
    response = client.get(path)

    assert response.status_code == expected_status
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == expected_code
    assert isinstance(body["message"], str) and body["message"]
    assert body["details"] == expected_details
    assert body["request_id"] is None


def test_request_id_from_contextvar_and_header_fallback() -> None:
    """ErrorResponse populates request_id from request_id_var, falling back to X-Request-ID."""
    client = TestClient(_build_test_app())

    header_resp = client.get("/invalid-image", headers={"X-Request-ID": "hdr-req-123"})
    assert header_resp.status_code == 400
    assert header_resp.json()["request_id"] == "hdr-req-123"

    token = request_id_var.set("ctx-req-456")
    try:
        ctx_resp = client.get("/invalid-image", headers={"X-Request-ID": "hdr-req-123"})
    finally:
        request_id_var.reset(token)

    assert ctx_resp.status_code == 400
    assert ctx_resp.json()["request_id"] == "ctx-req-456"


def test_unhandled_exception_returns_sanitized_500() -> None:
    """Unhandled exceptions return 500 INTERNAL_ERROR with zero PII or traceback leakage."""
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    response = client.get("/unhandled", headers={"X-Request-ID": "err-req-789"})

    assert response.status_code == 500
    body = response.json()
    assert body == {
        "success": False,
        "error_code": "INTERNAL_ERROR",
        "message": "An internal error occurred.",
        "details": None,
        "request_id": "err-req-789",
    }
    raw_text = response.text
    assert "3171234567890001" not in raw_text
    assert "PII" not in raw_text
    assert "Traceback" not in raw_text
    assert "RuntimeError" not in raw_text
