"""Structured JSON logging with request_id context propagation and PII masking."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.infrastructure.pii_masker import PiiMaskingFilter, mask_pii_text

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_UVICORN_LOGGER_NAMES: tuple[str, ...] = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
)


def _attach_pii_filter(
    target: logging.Logger | logging.Handler,
    pii_filter: PiiMaskingFilter,
) -> None:
    """Attach PiiMaskingFilter to a logger or handler once without duplicates."""
    if not any(isinstance(existing, PiiMaskingFilter) for existing in target.filters):
        target.addFilter(pii_filter)


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize a log record to a single-line JSON string."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": mask_pii_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exc_info"] = mask_pii_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure root and uvicorn stdlib logging with JSON formatting and PII masking."""
    level = logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)
    pii_filter = PiiMaskingFilter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    _attach_pii_filter(handler, pii_filter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    _attach_pii_filter(root_logger, pii_filter)

    for logger_name in _UVICORN_LOGGER_NAMES:
        uv_logger = logging.getLogger(logger_name)
        _attach_pii_filter(uv_logger, pii_filter)
        for uv_handler in uv_logger.handlers:
            _attach_pii_filter(uv_handler, pii_filter)
