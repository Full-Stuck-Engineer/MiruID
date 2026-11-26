"""FastAPI dependency providers."""

from fastapi import Request

from app.application.pipeline import ExtractionPipeline
from app.domain.interfaces import OcrEngine
from app.domain.registry import DocumentRegistry


def get_registry(request: Request) -> DocumentRegistry:
    """Return the application's configured document plugin registry."""
    return request.app.state.registry


def get_ocr_engine(request: Request) -> OcrEngine | None:
    """Return the application's configured OCR engine, if enabled."""
    engine: OcrEngine | None = getattr(request.app.state, "ocr_engine", None)
    return engine


def get_pipeline(request: Request) -> ExtractionPipeline:
    """Return the application's configured extraction pipeline."""
    pipeline: ExtractionPipeline = request.app.state.pipeline
    return pipeline
