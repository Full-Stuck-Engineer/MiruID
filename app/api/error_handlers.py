"""FastAPI exception handlers mapping domain, validation, and unhandled errors to ErrorResponse."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    ExtractionFailedError,
    ImageTooBlurryError,
    InvalidImageError,
    MiruDomainError,
    ProviderTimeoutError,
    UnsupportedDocumentError,
)
from app.domain.schemas import ErrorResponse
from app.infrastructure.logging import request_id_var
from app.infrastructure.pii_masker import mask_pii_dict, mask_pii_text

logger = logging.getLogger(__name__)

_DOMAIN_ERROR_STATUS_MAP: dict[type[MiruDomainError], int] = {
    ImageTooBlurryError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    InvalidImageError: status.HTTP_400_BAD_REQUEST,
    UnsupportedDocumentError: status.HTTP_400_BAD_REQUEST,
    ProviderTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    ExtractionFailedError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    MiruDomainError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def _resolve_request_id(request: Request) -> str | None:
    """Resolve request_id from request.state, contextvar, or X-Request-ID header."""
    state_request_id: str | None = getattr(request.state, "request_id", None)
    if state_request_id is not None:
        return state_request_id
    ctx_request_id = request_id_var.get()
    if ctx_request_id is not None:
        return ctx_request_id
    return request.headers.get("X-Request-ID")


def _status_code_for_domain_error(exc: MiruDomainError) -> int:
    """Return the HTTP status code for a domain exception using its MRO."""
    for cls in type(exc).__mro__:
        if cls in _DOMAIN_ERROR_STATUS_MAP:
            return _DOMAIN_ERROR_STATUS_MAP[cls]
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _sanitize_validation_errors(errors: Any) -> list[dict[str, Any]]:
    """Strip raw input values and context from Pydantic validation errors."""
    sanitized: list[dict[str, Any]] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        raw_loc = err.get("loc", ())
        loc = [str(part) for part in raw_loc] if isinstance(raw_loc, (list, tuple)) else []
        sanitized.append(
            {
                "loc": loc,
                "type": str(err.get("type", "validation_error")),
                "msg": mask_pii_text(str(err.get("msg", "Invalid value."))),
            }
        )
    return sanitized


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    """Serialize MiruDomainError subclasses into a sanitized ErrorResponse."""
    assert isinstance(exc, MiruDomainError)
    status_code = _status_code_for_domain_error(exc)
    request_id = _resolve_request_id(request)
    safe_details = mask_pii_dict(exc.details) if exc.details is not None else None

    logger.warning(
        "Domain error handled (request_id=%s, error_code=%s, status_code=%d)",
        request_id,
        exc.error_code,
        status_code,
    )
    payload = ErrorResponse(
        error_code=exc.error_code,
        message=mask_pii_text(exc.message),
        details=safe_details,
        request_id=request_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitized 422 ErrorResponse without echoing raw request input values."""
    assert isinstance(exc, RequestValidationError)
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    request_id = _resolve_request_id(request)
    safe_errors = _sanitize_validation_errors(exc.errors())

    logger.warning(
        "Validation error handled (request_id=%s, error_code=%s, status_code=%d)",
        request_id,
        "VALIDATION_ERROR",
        status_code,
    )
    payload = ErrorResponse(
        error_code="VALIDATION_ERROR",
        message="Request validation failed.",
        details={"errors": safe_errors} if safe_errors else None,
        request_id=request_id,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitized 500 ErrorResponse without leaking internal details or PII."""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    request_id = _resolve_request_id(request)
    logger.error(
        "Unhandled exception handled "
        "(request_id=%s, error_code=%s, status_code=%d, exception_type=%s)",
        request_id,
        "INTERNAL_ERROR",
        status_code,
        type(exc).__name__,
    )
    payload = ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="An internal error occurred.",
        details=None,
        request_id=request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain, validation, and fallback exception handlers on the FastAPI app."""
    app.add_exception_handler(MiruDomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
