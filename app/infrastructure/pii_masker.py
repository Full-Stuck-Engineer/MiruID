"""PII and secret redaction utilities and stdlib logging filter."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED_NIK = "[REDACTED_NIK]"
REDACTED_NPWP = "[REDACTED_NPWP]"
REDACTED_BASE64 = "[REDACTED_BASE64]"
REDACTED_SECRET = "[REDACTED_SECRET]"
REDACTED_PII = "[REDACTED_PII]"

SENSITIVE_KEY_TOKENS: Mapping[str, str] = {
    "nik": REDACTED_NIK,
    "npwp": REDACTED_NPWP,
    "npwp_15": REDACTED_NPWP,
    "npwp_16": REDACTED_NPWP,
    "sim_number": REDACTED_PII,
    "full_name": REDACTED_PII,
    "taxpayer_name": REDACTED_PII,
    "address": REDACTED_PII,
    "date_of_birth": REDACTED_PII,
    "api_key": REDACTED_SECRET,
    "authorization": REDACTED_SECRET,
    "raw_ocr_text": REDACTED_PII,
    "image_bytes": REDACTED_BASE64,
}

_DATA_URL_BASE64_RE = re.compile(
    r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=_-]+",
    re.IGNORECASE,
)
_BEARER_TOKEN_RE = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)
_PREFIXED_API_KEY_RE = re.compile(
    r"\b(?:sk|pk|rk|api|key)[-_](?:proj-|live-|test-)?[A-Za-z0-9_-]{12,}\b",
    re.IGNORECASE,
)
_KV_SECRET_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|access[_-]?token|secret[_-]?key)\s*[:=]\s*)(['\"]?)([A-Za-z0-9._~+/=-]{8,})\2",
)
_FORMATTED_NPWP_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}\b")
_NIK_RE = re.compile(r"\b\d{16}\b")
_BARE_NPWP_RE = re.compile(r"\b\d{15}\b")
_LONG_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/]{48,}={0,2}(?![A-Za-z0-9+/=_-])")

_STANDARD_LOG_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _replace_long_base64(match: re.Match[str]) -> str:
    candidate = match.group(0)
    # Avoid redacting lowercase Unix filesystem paths such as /usr/local/lib/...
    if candidate.startswith("/") and candidate.islower() and not candidate.endswith("="):
        return candidate
    return REDACTED_BASE64


def mask_pii_text(text: str) -> str:
    """Redact NIKs, NPWPs, base64 image payloads, and bearer/API secrets from text."""
    if not text:
        return text

    masked = _DATA_URL_BASE64_RE.sub(REDACTED_BASE64, text)
    masked = _BEARER_TOKEN_RE.sub(f"Bearer {REDACTED_SECRET}", masked)
    masked = _PREFIXED_API_KEY_RE.sub(REDACTED_SECRET, masked)
    masked = _KV_SECRET_RE.sub(rf"\1\2{REDACTED_SECRET}\2", masked)
    masked = _FORMATTED_NPWP_RE.sub(REDACTED_NPWP, masked)
    masked = _NIK_RE.sub(REDACTED_NIK, masked)
    masked = _BARE_NPWP_RE.sub(REDACTED_NPWP, masked)
    masked = _LONG_BASE64_RE.sub(_replace_long_base64, masked)
    return masked


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_pii_text(value)
    if isinstance(value, (bytes, bytearray)):
        return REDACTED_BASE64
    if isinstance(value, Mapping):
        return mask_pii_dict(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    return value


def mask_pii_dict(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively mask sensitive keys and string values in nested mappings and lists."""
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        key_str = str(key)
        normalized = _normalize_key(key_str)
        if normalized in SENSITIVE_KEY_TOKENS:
            sanitized[key_str] = SENSITIVE_KEY_TOKENS[normalized]
        else:
            sanitized[key_str] = _sanitize_value(value)
    return sanitized


class PiiMaskingFilter(logging.Filter):
    """Logging filter that redacts PII and secrets from LogRecord before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize record message, formatting args, and extra attributes in place."""
        if isinstance(record.msg, str):
            record.msg = mask_pii_text(record.msg)
        elif isinstance(record.msg, Mapping):
            record.msg = mask_pii_dict(record.msg)

        if isinstance(record.args, Mapping):
            record.args = mask_pii_dict(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(_sanitize_value(arg) for arg in record.args)
        elif record.args is not None:
            record.args = _sanitize_value(record.args)

        if isinstance(record.exc_text, str):
            record.exc_text = mask_pii_text(record.exc_text)

        for attr_name in list(record.__dict__.keys()):
            if attr_name in _STANDARD_LOG_RECORD_ATTRS:
                continue
            normalized = _normalize_key(attr_name)
            if normalized in SENSITIVE_KEY_TOKENS:
                record.__dict__[attr_name] = SENSITIVE_KEY_TOKENS[normalized]
            else:
                record.__dict__[attr_name] = _sanitize_value(record.__dict__[attr_name])

        return True


__all__ = [
    "PiiMaskingFilter",
    "REDACTED_BASE64",
    "REDACTED_NIK",
    "REDACTED_NPWP",
    "REDACTED_PII",
    "REDACTED_SECRET",
    "SENSITIVE_KEY_TOKENS",
    "mask_pii_dict",
    "mask_pii_text",
]
