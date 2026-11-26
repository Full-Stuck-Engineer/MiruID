"""Country and document plugin registry."""

from collections.abc import Iterable

from app.domain.interfaces import DocumentPlugin
from app.domain.registry import DocumentRegistry
from app.plugins.idn.ktp import IndonesiaKtpPlugin
from app.plugins.idn.sim import IndonesiaSimPlugin


def register_default_plugins(registry: DocumentRegistry) -> DocumentRegistry:
    """Register built-in country/document plugins."""
    registry.register(IndonesiaKtpPlugin())
    registry.register(IndonesiaSimPlugin())
    return registry


def create_default_registry(
    plugins: Iterable[DocumentPlugin] | None = None,
) -> DocumentRegistry:
    """Create a DocumentRegistry populated with either provided or default plugins."""
    registry = DocumentRegistry()
    if plugins is not None:
        for plugin in plugins:
            registry.register(plugin)
        return registry
    return register_default_plugins(registry)


__all__ = ["create_default_registry", "register_default_plugins"]
