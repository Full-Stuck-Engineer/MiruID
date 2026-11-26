"""Unit tests for DocumentRegistry and default plugin registry factories."""

from collections.abc import Callable

import pytest

from app.domain.exceptions import PluginConfigurationError, UnsupportedDocumentError
from app.domain.interfaces import DocumentPlugin
from app.domain.registry import DocumentRegistry
from app.domain.schemas import (
    ClassificationRule,
    SupportedDocument,
    SupportedDocumentsResponse,
)
from app.plugins import create_default_registry, register_default_plugins


def test_register_and_lookup_case_insensitive_and_trimmed(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    ktp_plugin = stub_plugin_factory(" idn ", " ktp ", "Indonesian e-KTP")
    assert isinstance(ktp_plugin, DocumentPlugin)

    registry.register(ktp_plugin)

    assert registry.get("IDN", "KTP") is ktp_plugin
    assert registry.get("idn", "ktp") is ktp_plugin
    assert registry.get("  IdN  ", "\tKtP\n") is ktp_plugin


def test_deterministic_sorting_for_plugins_documents_and_rules(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    rule_sgp = ClassificationRule(keyword="NRIC", weight=2.0, required=True)
    rule_idn_sim = ClassificationRule(keyword="SIM", weight=1.5)
    rule_idn_ktp = ClassificationRule(keyword="NIK", weight=2.0, required=True)

    sgp_nric = stub_plugin_factory("sgp", "nric", "Singapore NRIC", [rule_sgp])
    idn_sim = stub_plugin_factory("IDN", "sim", "Indonesian SIM", [rule_idn_sim])
    idn_ktp = stub_plugin_factory("idn", "ktp", "Indonesian KTP", [rule_idn_ktp])

    registry.register(sgp_nric)
    registry.register(idn_sim)
    registry.register(idn_ktp)

    assert registry.list_plugins() == [idn_ktp, idn_sim, sgp_nric]
    assert registry.list_documents() == [
        SupportedDocument(country_code="IDN", doc_type="KTP", description="Indonesian KTP"),
        SupportedDocument(country_code="IDN", doc_type="SIM", description="Indonesian SIM"),
        SupportedDocument(country_code="SGP", doc_type="NRIC", description="Singapore NRIC"),
    ]

    rules = registry.get_classification_rules()
    assert list(rules.keys()) == [("IDN", "KTP"), ("IDN", "SIM"), ("SGP", "NRIC")]
    assert rules[("IDN", "KTP")] == (rule_idn_ktp,)
    assert rules[("IDN", "SIM")] == (rule_idn_sim,)
    assert rules[("SGP", "NRIC")] == (rule_sgp,)


def test_duplicate_registration_rejected_across_casing_and_whitespace(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    first = stub_plugin_factory("IDN", "KTP", "First KTP")
    duplicate = stub_plugin_factory(" idn ", " ktp ", "Duplicate KTP")

    registry.register(first)

    with pytest.raises(PluginConfigurationError) as exc_info:
        registry.register(duplicate)

    assert exc_info.value.error_code == "PLUGIN_CONFIGURATION_ERROR"
    assert exc_info.value.details == {"country_code": "IDN", "doc_type": "KTP"}
    assert registry.get("IDN", "KTP") is first


@pytest.mark.parametrize(
    "bad_country",
    ["", "   ", "ID", "IDNN", "123", "I1N", "I-N", "ID_"],
)
def test_invalid_country_code_rejected(
    bad_country: str,
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    plugin = stub_plugin_factory(bad_country, "KTP")

    with pytest.raises(PluginConfigurationError) as exc_info:
        registry.register(plugin)

    assert exc_info.value.error_code == "PLUGIN_CONFIGURATION_ERROR"
    assert len(registry) == 0


@pytest.mark.parametrize("bad_doc_type", ["", "   ", "\t\n"])
def test_invalid_doc_type_rejected(
    bad_doc_type: str,
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    plugin = stub_plugin_factory("IDN", bad_doc_type)

    with pytest.raises(PluginConfigurationError) as exc_info:
        registry.register(plugin)

    assert exc_info.value.error_code == "PLUGIN_CONFIGURATION_ERROR"
    assert len(registry) == 0


def test_missing_plugin_raises_unsupported_document_with_details(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    registry.register(stub_plugin_factory("sgp", "nric", "Singapore NRIC"))
    registry.register(stub_plugin_factory("idn", "ktp", "Indonesian KTP"))

    with pytest.raises(UnsupportedDocumentError) as exc_info:
        registry.get(" mys ", " mykad ")

    err = exc_info.value
    assert err.error_code == "UNSUPPORTED_DOCUMENT"
    assert "MYS/MYKAD" in err.message
    assert "IDN/KTP" in err.message
    assert "SGP/NRIC" in err.message
    assert err.details == {
        "country_code": "MYS",
        "doc_type": "MYKAD",
        "supported_documents": ["IDN/KTP", "SGP/NRIC"],
    }


def test_missing_plugin_on_empty_registry() -> None:
    registry = DocumentRegistry()

    with pytest.raises(UnsupportedDocumentError) as exc_info:
        registry.get("idn", "ktp")

    err = exc_info.value
    assert err.error_code == "UNSUPPORTED_DOCUMENT"
    assert err.details == {
        "country_code": "IDN",
        "doc_type": "KTP",
        "supported_documents": [],
    }


def test_len_and_contains_normalized(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    registry = DocumentRegistry()
    assert len(registry) == 0
    assert ("IDN", "KTP") not in registry

    registry.register(stub_plugin_factory("IDN", "KTP"))
    registry.register(stub_plugin_factory("SGP", "NRIC"))

    assert len(registry) == 2
    assert ("IDN", "KTP") in registry
    assert (" idn ", " ktp ") in registry
    assert ("sgp", "nric") in registry
    assert ("MYS", "MYKAD") not in registry


def test_default_registry_factories_and_response_schema(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    default_registry = create_default_registry()
    assert ("IDN", "KTP") in default_registry
    assert ("IDN", "SIM") in default_registry

    fresh_registry = DocumentRegistry()
    assert register_default_plugins(fresh_registry) is fresh_registry
    assert ("IDN", "KTP") in fresh_registry
    assert ("IDN", "SIM") in fresh_registry

    ktp = stub_plugin_factory("IDN", "KTP", "Indonesian KTP")
    custom_registry = create_default_registry(plugins=[ktp])
    assert len(custom_registry) == 1
    assert custom_registry.get("idn", "ktp") is ktp

    empty_resp = SupportedDocumentsResponse()
    assert empty_resp.documents == []
    assert empty_resp.total == 0
