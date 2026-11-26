"""FastAPI dependency providers."""

from fastapi import Request

from app.domain.interfaces import OcrEngine
from app.domain.registry import DocumentRegistry


def get_registry(request: Request) -> DocumentRegistry:
    """Return the application's configured document plugin registry."""
    return request.app.state.registry


def get_ocr_engine(request: Request) -> OcrEngine | None:
    """Return the application's configured OCR engine, if enabled."""
    engine: OcrEngine | None = getattr(request.app.state, "ocr_engine", None)
    return engine
