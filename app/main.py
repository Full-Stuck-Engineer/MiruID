"""FastAPI application factory and ASGI entrypoint."""

from fastapi import FastAPI

from app.api.error_handlers import register_exception_handlers
from app.api.health import router as health_router
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings if settings is not None else get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title=resolved_settings.service_name,
        version=resolved_settings.version,
    )
    if settings is not None:
        application.dependency_overrides[get_settings] = lambda: resolved_settings

    register_exception_handlers(application)
    application.include_router(health_router)
    return application


app = create_app()
