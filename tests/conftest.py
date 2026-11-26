"""Shared pytest fixtures and test helpers for MiruID."""

from collections.abc import Iterator, Sequence
from typing import Protocol

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.domain.registry import DocumentRegistry
from app.domain.schemas import ClassificationRule, OcrResult, ValidationResult
from app.infrastructure.config import Settings
from app.main import create_app


class StubSchema(BaseModel):
    """Minimal Pydantic schema used by StubDocumentPlugin."""

    value: str = ""


class StubDocumentPlugin:
    """Reusable DocumentPlugin stub for registry and API tests."""

    schema_model: type[BaseModel] = StubSchema

    def __init__(
        self,
        country_code: str = "IDN",
        doc_type: str = "KTP",
        description: str = "Stub document",
        classification_rules: Sequence[ClassificationRule] = (),
    ) -> None:
        self.country_code = country_code
        self.doc_type = doc_type
        self.description = description
        self.classification_rules: tuple[ClassificationRule, ...] = tuple(classification_rules)

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        """Build a deterministic stub extraction prompt."""
        return f"Extract {self.country_code}/{self.doc_type}"

    def validate(self, data: BaseModel) -> ValidationResult:
        """Return a passing ValidationResult."""
        return ValidationResult(is_valid=True)

    def offline_parse(self, ocr_result: OcrResult) -> BaseModel:
        """Parse raw OCR text into StubSchema."""
        return StubSchema(value=ocr_result.raw_text)


class StubPluginFactory(Protocol):
    """Callable protocol for constructing StubDocumentPlugin instances."""

    def __call__(
        self,
        country_code: str = "IDN",
        doc_type: str = "KTP",
        description: str = "Stub document",
        classification_rules: Sequence[ClassificationRule] = (),
    ) -> StubDocumentPlugin: ...


class ClientFactory(Protocol):
    """Callable protocol for constructing FastAPI TestClient instances."""

    def __call__(
        self,
        *,
        settings: Settings | None = None,
        registry: DocumentRegistry | None = None,
    ) -> TestClient: ...


def make_stub_plugin(
    country_code: str = "IDN",
    doc_type: str = "KTP",
    description: str = "Stub document",
    classification_rules: Sequence[ClassificationRule] = (),
) -> StubDocumentPlugin:
    """Create a StubDocumentPlugin conforming to the DocumentPlugin protocol."""
    return StubDocumentPlugin(
        country_code=country_code,
        doc_type=doc_type,
        description=description,
        classification_rules=classification_rules,
    )


@pytest.fixture
def default_settings() -> Settings:
    """Return a default Settings instance."""
    return Settings()


@pytest.fixture
def stub_plugin_factory() -> StubPluginFactory:
    """Return the make_stub_plugin helper for constructing DocumentPlugin stubs."""
    return make_stub_plugin


@pytest.fixture
def client_factory(default_settings: Settings) -> Iterator[ClientFactory]:
    """Return a factory for FastAPI TestClient instances and close them on teardown."""
    clients: list[TestClient] = []

    def _create_client(
        *,
        settings: Settings | None = None,
        registry: DocumentRegistry | None = None,
    ) -> TestClient:
        resolved_settings = settings if settings is not None else default_settings
        client = TestClient(create_app(resolved_settings, registry=registry))
        clients.append(client)
        return client

    yield _create_client
    for client in clients:
        client.close()


@pytest.fixture
def api_client(client_factory: ClientFactory) -> TestClient:
    """Return a default FastAPI TestClient configured with default_settings."""
    return client_factory()
