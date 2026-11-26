"""FastAPI dependency providers."""

from fastapi import Request

from app.domain.registry import DocumentRegistry


def get_registry(request: Request) -> DocumentRegistry:
    """Return the application's configured document plugin registry."""
    return request.app.state.registry
