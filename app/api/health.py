"""Health check endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.infrastructure.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Return service health status and metadata."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
    }
