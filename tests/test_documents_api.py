"""API tests for document discovery endpoints."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.domain.interfaces import DocumentPlugin
from app.domain.registry import DocumentRegistry


def test_list_documents_default_registry_includes_idn_plugins(api_client: TestClient) -> None:
    """GET /v1/documents returns built-in plugins including IDN/KTP and IDN/SIM."""
    response = api_client.get("/v1/documents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == len(payload["documents"])
    registered = {(doc["country_code"], doc["doc_type"]) for doc in payload["documents"]}
    assert ("IDN", "KTP") in registered
    assert ("IDN", "SIM") in registered


def test_list_documents_explicit_empty_registry(
    client_factory: Callable[..., TestClient],
) -> None:
    """GET /v1/documents returns empty list and total 0 when given an empty registry."""
    client = client_factory(registry=DocumentRegistry())
    response = client.get("/v1/documents")

    assert response.status_code == 200
    assert response.json() == {"documents": [], "total": 0}


def test_list_documents_populated_registry_sorted(
    client_factory: Callable[..., TestClient],
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    """GET /v1/documents returns documents sorted by (country_code, doc_type)."""
    registry = DocumentRegistry()
    registry.register(
        stub_plugin_factory("SGP", "nric", "Singapore National Registration Identity Card")
    )
    registry.register(stub_plugin_factory("IDN", "sim", "Indonesian Driver's License"))
    registry.register(stub_plugin_factory("IDN", "ktp", "Indonesian National Identity Card"))

    client = client_factory(registry=registry)

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


def test_openapi_schema_includes_documents_endpoint(api_client: TestClient) -> None:
    """GET /openapi.json exposes the /v1/documents path."""
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/v1/documents" in schema["paths"]
