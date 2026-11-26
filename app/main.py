"""FastAPI application factory and ASGI entrypoint."""

from fastapi import FastAPI

from app.api.error_handlers import register_exception_handlers
from app.api.health import router as health_router
from app.api.v1.documents import router as documents_router
from app.domain.registry import DocumentRegistry
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.logging import configure_logging
from app.plugins import create_default_registry


def create_app(
    settings: Settings | None = None,
    registry: DocumentRegistry | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.version,
    )
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings

    application.state.registry = registry if registry is not None else create_default_registry()

    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(documents_router)
    return application


app = create_app()
