"""FastAPI application factory and ASGI entrypoint."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.error_handlers import register_exception_handlers
from app.api.health import router as health_router
from app.api.v1.documents import router as documents_router
from app.domain.exceptions import ExtractionFailedError
from app.domain.interfaces import OcrEngine
from app.domain.registry import DocumentRegistry
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.engines.ocr_paddle import PaddleOcrEngine
from app.infrastructure.logging import configure_logging
from app.plugins import create_default_registry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Warm up configured singleton engines once on application startup."""
    engine = getattr(application.state, "ocr_engine", None)
    warmup = getattr(engine, "warmup", None)
    if callable(warmup):
        try:
            await asyncio.to_thread(warmup)
        except ExtractionFailedError as exc:
            logger.warning("Skipping OCR engine warmup: %s", exc.message)
    yield


def create_app(
    settings: Settings | None = None,
    registry: DocumentRegistry | None = None,
    ocr_engine: OcrEngine | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.version,
        lifespan=lifespan,
    )
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings

    application.state.registry = registry if registry is not None else create_default_registry()
    if ocr_engine is not None:
        application.state.ocr_engine = ocr_engine
    elif resolved_settings.ocr.enabled:
        application.state.ocr_engine = PaddleOcrEngine(resolved_settings.ocr)
    else:
        application.state.ocr_engine = None

    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(documents_router)
    return application


app = create_app()
