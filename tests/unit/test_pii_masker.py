"""Unit tests for PII masking, logging filter attachment, and error handler PII safety."""

from __future__ import annotations

import base64
import json
import logging
import sys

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.error_handlers import register_exception_handlers
from app.domain.exceptions import ExtractionFailedError
from app.infrastructure.logging import JsonFormatter, configure_logging
from app.infrastructure.pii_masker import (
    REDACTED_BASE64,
    REDACTED_NIK,
    REDACTED_NPWP,
    REDACTED_PII,
    REDACTED_SECRET,
    PiiMaskingFilter,
    mask_pii_dict,
    mask_pii_text,
)

FAKE_NIK = "3171234567890001"
FAKE_NPWP_FORMATTED = "01.234.567.8-901.000"
FAKE_NPWP_BARE = "012345678901000"
FAKE_API_KEY = "sk-proj-abc1234567890XYZsecret"
FAKE_BEARER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
FAKE_LONG_B64 = base64.b64encode(b"fake-id-card-jpeg-image-bytes-" * 4).decode("ascii")
FAKE_DATA_URL = f"data:image/jpeg;base64,{FAKE_LONG_B64}"


def test_mask_pii_text_redacts_nik_npwp_base64_and_secrets() -> None:
    """mask_pii_text redacts NIKs, formatted/bare NPWPs, data URLs, base64, and secrets."""
    raw = (
        f"NIK={FAKE_NIK} NPWP={FAKE_NPWP_FORMATTED} bare={FAKE_NPWP_BARE} "
        f"img={FAKE_DATA_URL} raw_b64={FAKE_LONG_B64} "
        f"Authorization: Bearer {FAKE_BEARER} key={FAKE_API_KEY} api_key=supersecretvalue99"
    )
    masked = mask_pii_text(raw)

    for secret in (
        FAKE_NIK,
        FAKE_NPWP_FORMATTED,
        FAKE_NPWP_BARE,
        FAKE_LONG_B64,
        FAKE_BEARER,
        FAKE_API_KEY,
        "supersecretvalue99",
    ):
        assert secret not in masked

    assert REDACTED_NIK in masked
    assert REDACTED_NPWP in masked
    assert REDACTED_BASE64 in masked
    assert REDACTED_SECRET in masked


def test_mask_pii_text_preserves_safe_text_and_boundaries() -> None:
    """mask_pii_text leaves empty text, safe metadata, and lowercase paths intact."""
    assert mask_pii_text("") == ""
    safe = (
        "request_id=550e8400-e29b-41d4-a716-446655440000 "
        "status=200 latency_ms=14.25 path=/usr/local/lib/python/sitepackages/miruid/app"
    )
    assert mask_pii_text(safe) == safe

    # Word boundary prevents redacting 17-digit sequences as a 16-digit NIK.
    seventeen_digits = "12345678901234567"
    assert mask_pii_text(seventeen_digits) == seventeen_digits


def test_mask_pii_dict_recursively_masks_nested_dicts_and_lists() -> None:
    """mask_pii_dict redacts sensitive keys and string values across nested structures."""
    original = {
        "request_id": "req-001",
        "blur_score": 42.5,
        "nik": FAKE_NIK,
        "npwp_15": FAKE_NPWP_FORMATTED,
        "npwp_16": FAKE_NIK,
        "sim_number": "1234-5678-9012",
        "full_name": "BUDI SANTOSO",
        "taxpayer_name": "BUDI SANTOSO",
        "address": "JL. SUDIRMAN NO 1 JAKARTA",
        "date_of_birth": "1990-01-15",
        "api_key": FAKE_API_KEY,
        "Authorization": f"Bearer {FAKE_BEARER}",
        "raw_ocr_text": f"NIK {FAKE_NIK} BUDI SANTOSO",
        "image_bytes": b"\xff\xd8\xff\xe0raw-jpeg",
        "nested": {
            "items": [
                {"full_name": "SITI AMINAH", "note": f"found {FAKE_NIK}"},
                {"blob": FAKE_DATA_URL, "raw": b"binary-data", "count": 2},
            ],
            "tuple_vals": (f"NPWP {FAKE_NPWP_BARE}", 100),
        },
    }

    masked = mask_pii_dict(original)

    # Original mapping is not mutated.
    assert original["nik"] == FAKE_NIK
    assert original["full_name"] == "BUDI SANTOSO"

    assert masked["request_id"] == "req-001"
    assert masked["blur_score"] == 42.5
    assert masked["nik"] == REDACTED_NIK
    assert masked["npwp_15"] == REDACTED_NPWP
    assert masked["npwp_16"] == REDACTED_NPWP
    assert masked["sim_number"] == REDACTED_PII
    assert masked["full_name"] == REDACTED_PII
    assert masked["taxpayer_name"] == REDACTED_PII
    assert masked["address"] == REDACTED_PII
    assert masked["date_of_birth"] == REDACTED_PII
    assert masked["api_key"] == REDACTED_SECRET
    assert masked["Authorization"] == REDACTED_SECRET
    assert masked["raw_ocr_text"] == REDACTED_PII
    assert masked["image_bytes"] == REDACTED_BASE64

    nested_items = masked["nested"]["items"]
    assert nested_items[0]["full_name"] == REDACTED_PII
    assert nested_items[0]["note"] == f"found {REDACTED_NIK}"
    assert nested_items[1]["blob"] == REDACTED_BASE64
    assert nested_items[1]["raw"] == REDACTED_BASE64
    assert nested_items[1]["count"] == 2
    assert masked["nested"]["tuple_vals"] == (f"NPWP {REDACTED_NPWP}", 100)


def test_pii_masking_filter_with_caplog(caplog: pytest.LogCaptureFixture) -> None:
    """PiiMaskingFilter redacts msg, tuple/dict args, and extra fields in captured logs."""
    test_logger = logging.getLogger("miruid.test.pii_filter")
    pii_filter = PiiMaskingFilter()
    test_logger.addFilter(pii_filter)
    try:
        with caplog.at_level(logging.INFO, logger="miruid.test.pii_filter"):
            test_logger.info(
                "Parsed NIK=%s NPWP=%s img=%s auth=%s",
                FAKE_NIK,
                FAKE_NPWP_FORMATTED,
                FAKE_DATA_URL,
                f"Bearer {FAKE_BEARER}",
                extra={
                    "full_name": "BUDI SANTOSO",
                    "api_key": FAKE_API_KEY,
                    "details": {"nik": FAKE_NIK, "note": FAKE_LONG_B64},
                },
            )
            test_logger.info(
                "Mapping log nik=%(nik)s name=%(full_name)s",
                {"nik": FAKE_NIK, "full_name": "BUDI SANTOSO"},
            )
    finally:
        test_logger.removeFilter(pii_filter)

    assert len(caplog.records) == 2
    for leaked in (
        FAKE_NIK,
        FAKE_NPWP_FORMATTED,
        FAKE_DATA_URL,
        FAKE_LONG_B64,
        FAKE_BEARER,
        FAKE_API_KEY,
        "BUDI SANTOSO",
    ):
        assert leaked not in caplog.text

    first = caplog.records[0]
    assert first.__dict__["full_name"] == REDACTED_PII
    assert first.__dict__["api_key"] == REDACTED_SECRET
    assert first.__dict__["details"] == {"nik": REDACTED_NIK, "note": REDACTED_BASE64}


def test_json_formatter_masks_exception_pii() -> None:
    """JsonFormatter redacts PII inside formatted exception tracebacks."""
    formatter = JsonFormatter()
    try:
        raise ValueError(f"Failed for NIK {FAKE_NIK} and key {FAKE_API_KEY}")
    except ValueError:
        record = logging.LogRecord(
            name="miruid.test.json",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Error processing %s",
            args=(FAKE_NPWP_FORMATTED,),
            exc_info=sys.exc_info(),
        )

    rendered = json.loads(formatter.format(record))
    assert FAKE_NPWP_FORMATTED not in rendered["message"]
    assert REDACTED_NPWP in rendered["message"]
    assert FAKE_NIK not in rendered["exc_info"]
    assert FAKE_API_KEY not in rendered["exc_info"]
    assert REDACTED_NIK in rendered["exc_info"]
    assert REDACTED_SECRET in rendered["exc_info"]


def test_configure_logging_attaches_filter_without_duplicates() -> None:
    """configure_logging attaches PiiMaskingFilter to root and uvicorn loggers idempotently."""
    uv_logger = logging.getLogger("uvicorn.access")
    uv_handler = logging.StreamHandler()
    uv_logger.addHandler(uv_handler)
    try:
        configure_logging("INFO")
        configure_logging("DEBUG")

        root_logger = logging.getLogger()
        root_filters = [f for f in root_logger.filters if isinstance(f, PiiMaskingFilter)]
        assert len(root_filters) == 1
        assert len(root_logger.handlers) == 1
        handler_filters = [
            f for f in root_logger.handlers[0].filters if isinstance(f, PiiMaskingFilter)
        ]
        assert len(handler_filters) == 1

        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger_obj = logging.getLogger(name)
            filters = [f for f in logger_obj.filters if isinstance(f, PiiMaskingFilter)]
            assert len(filters) == 1

        uv_handler_filters = [f for f in uv_handler.filters if isinstance(f, PiiMaskingFilter)]
        assert len(uv_handler_filters) == 1
    finally:
        uv_logger.removeHandler(uv_handler)


def test_error_handlers_never_leak_pii_in_response_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Domain, validation, and unhandled error handlers redact PII from responses and logs."""

    class _SampleBody(BaseModel):
        count: int
        nik: str

    app = FastAPI()
    register_exception_handlers(app)
    router = APIRouter()

    @router.get("/domain-pii")
    def raise_domain_pii() -> None:
        raise ExtractionFailedError(
            f"Failed parsing NIK {FAKE_NIK}",
            details={
                "nik": FAKE_NIK,
                "full_name": "BUDI SANTOSO",
                "raw_ocr_text": f"NPWP {FAKE_NPWP_FORMATTED}",
                "blur_score": 11.2,
            },
        )

    @router.post("/validate-pii")
    def validate_pii(body: _SampleBody) -> dict[str, str]:
        return {"nik": body.nik}

    @router.get("/unexpected-pii")
    def raise_unexpected_pii() -> None:
        raise RuntimeError(f"Crash on NIK {FAKE_NIK} and Bearer {FAKE_BEARER}")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.WARNING, logger="app.api.error_handlers"):
        domain_resp = client.get("/domain-pii", headers={"X-Request-ID": "req-dom-1"})
        val_resp = client.post(
            "/validate-pii",
            json={"count": f"not-an-int-{FAKE_NIK}", "nik": FAKE_NIK},
            headers={"X-Request-ID": "req-val-2"},
        )
        unhandled_resp = client.get("/unexpected-pii", headers={"X-Request-ID": "req-err-3"})

    # 1. Domain error response & logs
    assert domain_resp.status_code == 500
    domain_body = domain_resp.json()
    assert domain_body["request_id"] == "req-dom-1"
    assert domain_body["details"]["nik"] == REDACTED_NIK
    assert domain_body["details"]["full_name"] == REDACTED_PII
    assert domain_body["details"]["raw_ocr_text"] == REDACTED_PII
    assert domain_body["details"]["blur_score"] == 11.2
    assert FAKE_NIK not in domain_resp.text
    assert "BUDI SANTOSO" not in domain_resp.text

    # 2. Validation error response & logs (must not echo raw Pydantic input)
    assert val_resp.status_code == 422
    val_body = val_resp.json()
    assert val_body["error_code"] == "VALIDATION_ERROR"
    assert val_body["request_id"] == "req-val-2"
    assert FAKE_NIK not in val_resp.text
    assert all("input" not in err for err in val_body["details"]["errors"])

    # 3. Unhandled error response & logs
    assert unhandled_resp.status_code == 500
    assert unhandled_resp.json()["request_id"] == "req-err-3"
    assert FAKE_NIK not in unhandled_resp.text
    assert FAKE_BEARER not in unhandled_resp.text

    # 4. Captured error handler logs must contain request_ids & error_codes, never PII
    assert "req-dom-1" in caplog.text
    assert "req-val-2" in caplog.text
    assert "req-err-3" in caplog.text
    assert "EXTRACTION_FAILED" in caplog.text
    assert "VALIDATION_ERROR" in caplog.text
    assert "INTERNAL_ERROR" in caplog.text
    for secret in (FAKE_NIK, FAKE_NPWP_FORMATTED, FAKE_BEARER, "BUDI SANTOSO"):
        assert secret not in caplog.text
