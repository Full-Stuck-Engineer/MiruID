"""Global document plugin registry for MiruID."""

import re

from app.domain.exceptions import PluginConfigurationError, UnsupportedDocumentError
from app.domain.interfaces import DocumentPlugin
from app.domain.schemas import ClassificationRule, SupportedDocument

_ISO_ALPHA3_PATTERN = re.compile(r"^[A-Z]{3}$")


def _normalize_key(country_code: str, doc_type: str) -> tuple[str, str]:
    """Normalize a (country_code, doc_type) pair for consistent indexing and lookup."""
    return country_code.strip().upper(), doc_type.strip().upper()


class DocumentRegistry:
    """In-memory registry mapping normalized (country_code, doc_type) pairs to plugins."""

    def __init__(self) -> None:
        self._plugins: dict[tuple[str, str], DocumentPlugin] = {}

    def register(self, plugin: DocumentPlugin) -> None:
        """Validate and register a document plugin."""
        norm_country, norm_doc_type = _normalize_key(plugin.country_code, plugin.doc_type)

        if not _ISO_ALPHA3_PATTERN.match(norm_country):
            raise PluginConfigurationError(
                f"Invalid country_code '{plugin.country_code}': must match ISO 3166-1 alpha-3 "
                "(3 uppercase ASCII letters).",
                details={"country_code": norm_country, "doc_type": norm_doc_type},
            )

        if not norm_doc_type:
            raise PluginConfigurationError(
                "Invalid doc_type: must be a non-empty string.",
                details={"country_code": norm_country, "doc_type": norm_doc_type},
            )

        key = (norm_country, norm_doc_type)
        if key in self._plugins:
            raise PluginConfigurationError(
                f"Document plugin already registered for '{norm_country}/{norm_doc_type}'.",
                details={"country_code": norm_country, "doc_type": norm_doc_type},
            )

        self._plugins[key] = plugin

    def get(self, country_code: str, doc_type: str) -> DocumentPlugin:
        """Retrieve a registered plugin using case-insensitive, whitespace-trimmed lookup."""
        norm_country, norm_doc_type = _normalize_key(country_code, doc_type)
        key = (norm_country, norm_doc_type)

        if key not in self._plugins:
            supported = [f"{c}/{d}" for c, d in sorted(self._plugins)]
            if supported:
                supported_summary = ", ".join(supported)
                message = (
                    f"Unsupported document '{norm_country}/{norm_doc_type}'. "
                    f"Supported documents: {supported_summary}."
                )
            else:
                message = (
                    f"Unsupported document '{norm_country}/{norm_doc_type}'. "
                    "No document plugins are currently registered."
                )
            raise UnsupportedDocumentError(
                message,
                details={
                    "country_code": norm_country,
                    "doc_type": norm_doc_type,
                    "supported_documents": supported,
                },
            )

        return self._plugins[key]

    def list_plugins(self) -> list[DocumentPlugin]:
        """Return all registered plugins sorted by normalized (country_code, doc_type)."""
        return [self._plugins[key] for key in sorted(self._plugins)]

    def list_documents(self) -> list[SupportedDocument]:
        """Return metadata for all registered documents sorted by (country_code, doc_type)."""
        return [
            SupportedDocument(
                country_code=country_code,
                doc_type=doc_type,
                description=self._plugins[(country_code, doc_type)].description,
            )
            for country_code, doc_type in sorted(self._plugins)
        ]

    def get_classification_rules(self) -> dict[tuple[str, str], tuple[ClassificationRule, ...]]:
        """Expose classification rules for all registered plugins in deterministic key order."""
        return {
            key: tuple(self._plugins[key].classification_rules) for key in sorted(self._plugins)
        }

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, key: tuple[str, str]) -> bool:
        country_code, doc_type = key
        return _normalize_key(country_code, doc_type) in self._plugins
