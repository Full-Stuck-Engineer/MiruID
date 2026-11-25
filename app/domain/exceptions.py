"""Transport-agnostic domain exceptions for MiruID."""

from typing import Any


class MiruDomainError(Exception):
    """Base exception for all MiruID domain errors."""

    error_code: str = "DOMAIN_ERROR"

    def __init__(
        self, message: str, *, error_code: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code
        self.message = message
        self.details = details


class ImageTooBlurryError(MiruDomainError):
    error_code = "IMAGE_TOO_BLURRY"


class InvalidImageError(MiruDomainError):
    error_code = "INVALID_IMAGE"


class UnsupportedDocumentError(MiruDomainError):
    error_code = "UNSUPPORTED_DOCUMENT"


class ProviderTimeoutError(MiruDomainError):
    error_code = "PROVIDER_TIMEOUT"


class ExtractionFailedError(MiruDomainError):
    error_code = "EXTRACTION_FAILED"
