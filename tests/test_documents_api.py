"""API tests for document discovery endpoints."""

from collections.abc import Sequence

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.domain.registry import DocumentRegistry
from app.domain.schemas import ClassificationRule, OcrResult, ValidationResult
from app.infrastructure.config import Settings
from app.main import create_app


class _StubSchema(BaseModel):
    value: str = ""


class _StubPlugin:
    """Minimal DocumentPlugin implementation for API wiring tests."""

    schema_model: type[BaseModel] = _StubSchema
    classification_rules: Sequence[ClassificationRule] = ()

    def __init__(self, country_code: str, doc_type: str, description: str) -> None:
        self.country_code = country_code
        self.doc_type = doc_type
        self.description = description

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        return ""

    def validate(self, data: BaseModel) -> ValidationResult:
        return ValidationResult(is_valid=True)

    def offline_parse(self, ocr_result: OcrResult) -> BaseModel:
        return _StubSchema()


def test_list_documents_default_empty_registry() -> None:
    """GET /v1/documents returns empty list and total 0 with default registry."""
    client = TestClient(create_app(Settings()))

    response = client.get("/v1/documents")

    assert response.status_code == 200
    assert response.json() == {"documents": [], "total": 0}


def test_list_documents_populated_registry_sorted() -> None:
    """GET /v1/documents returns documents sorted by (country_code, doc_type)."""
    registry = DocumentRegistry()
    registry.register(_StubPlugin("SGP", "nric", "Singapore National Registration Identity Card"))
    registry.register(_StubPlugin("IDN", "sim", "Indonesian Driver's License"))
    registry.register(_StubPlugin("IDN", "ktp", "Indonesian National Identity Card"))

    client = TestClient(create_app(Settings(), registry=registry))

    response = client.get("/v1/documents")

    assert response.status_code == 200
    assert response.json() == {
        "documents": [
            {
                "country_code": "IDN",
                "doc_type": "KTP",
                "description": "Indonesian National Identity Card",
            },
            {
                "country_code": "IDN",
                "doc_type": "SIM",
                "description": "Indonesian Driver's License",
            },
            {
                "country_code": "SGP",
                "doc_type": "NRIC",
                "description": "Singapore National Registration Identity Card",
            },
        ],
        "total": 3,
    }


def test_openapi_schema_includes_documents_endpoint() -> None:
    """GET /openapi.json exposes the /v1/documents path."""
    client = TestClient(create_app(Settings()))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/v1/documents" in schema["paths"]
