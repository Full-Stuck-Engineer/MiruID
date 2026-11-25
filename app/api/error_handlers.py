"""FastAPI exception handlers mapping domain and unhandled errors to ErrorResponse."""

import logging

from fastapi import FastAPI, Request, status
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
    """Resolve request_id from contextvar with X-Request-ID header fallback."""
    ctx_request_id = request_id_var.get()
    if ctx_request_id is not None:
        return ctx_request_id
    return request.headers.get("X-Request-ID")


def _status_code_for_domain_error(exc: MiruDomainError) -> int:
    """Return the HTTP status code for a domain exception using its MRO."""
    for cls in type(exc).__mro__:
        if cls in _DOMAIN_ERROR_STATUS_MAP:
            return _DOMAIN_ERROR_STATUS_MAP[cls]  # type: ignore[index]
    return status.HTTP_500_INTERNAL_SERVER_ERROR


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    """Serialize MiruDomainError subclasses into a standardized ErrorResponse."""
    assert isinstance(exc, MiruDomainError)
    status_code = _status_code_for_domain_error(exc)
    payload = ErrorResponse(
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
        request_id=_resolve_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Return a sanitized 500 ErrorResponse without leaking internal details or PII."""
    logger.exception("Unhandled exception during request processing: %s", type(exc).__name__)
    payload = ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="An internal error occurred.",
        details=None,
        request_id=_resolve_request_id(request),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=payload.model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register domain and fallback exception handlers on the FastAPI application."""
    app.add_exception_handler(MiruDomainError, _handle_domain_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
