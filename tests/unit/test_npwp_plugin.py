"""Unit tests for the Indonesian NPWP plugin (IDN/NPWP)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.domain.interfaces import DocumentPlugin
from app.domain.schemas import ExtractedField, OcrLine, OcrResult
from app.plugins import create_default_registry
from app.plugins.idn.npwp import IndonesiaNpwpPlugin, NpwpData


class _OtherSchema(BaseModel):
    value: str = ""


class TestNpwpSchema:
    """Test Pydantic normalization and KPP derivation on NpwpData."""

    @pytest.mark.parametrize(
        ("raw", "expected", "expected_kpp"),
        [
            ("012345678901000", "01.234.567.8-901.000", "901"),
            ("  09.876.543.2-012.001  ", "09.876.543.2-012.001", "012"),
            ("12345", "12345", None),
            ("   ", None, None),
        ],
    )
    def test_npwp_15_normalization_and_kpp_derivation(
        self, raw: str, expected: str | None, expected_kpp: str | None
    ) -> None:
        data = NpwpData(
            npwp_15=ExtractedField[str](value=raw, confidence=0.94, source="llm"),
        )
        assert data.npwp_15.value == expected
        assert data.kpp_code.value == expected_kpp
        if expected_kpp is not None:
            assert data.kpp_code.confidence == 0.94
            assert data.kpp_code.source == "llm"

    def test_explicit_kpp_code_not_overwritten(self) -> None:
        data = NpwpData(
            npwp_15=ExtractedField[str](value="01.234.567.8-901.000", confidence=0.95),
            kpp_code=ExtractedField[str](value="  063  ", confidence=0.99, source="llm"),
        )
        assert data.kpp_code.value == "063"
        assert data.kpp_code.confidence == 0.99

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("3171 0115 0895 0001", "3171011508950001"),
            ("0012.3456.7890.1000", "0012345678901000"),
            ("invalid-16", "invalid-16"),
            ("   ", None),
        ],
    )
    def test_npwp_16_normalization(self, raw: str, expected: str | None) -> None:
        data = NpwpData(npwp_16=ExtractedField[str](value=raw, confidence=0.93))
        assert data.npwp_16.value == expected
        assert data.npwp_16.confidence == 0.93

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("15-04-2019", "2019-04-15"),
            ("15/04/2019", "2019-04-15"),
            ("2019-04-15", "2019-04-15"),
            ("2019/04/15", "2019-04-15"),
            ("31-02-2019", "31-02-2019"),
            ("   ", None),
        ],
    )
    def test_registered_date_normalization(self, raw: str, expected: str | None) -> None:
        data = NpwpData(registered_date=ExtractedField[str](value=raw, confidence=0.91))
        assert data.registered_date.value == expected
        assert data.registered_date.confidence == 0.91


class TestIndonesiaNpwpPlugin:
    """Test IndonesiaNpwpPlugin protocol conformance, prompts, validation, and offline parse."""

    def test_conforms_to_document_plugin_protocol(self) -> None:
        plugin = IndonesiaNpwpPlugin()

        assert isinstance(plugin, DocumentPlugin)
        assert plugin.country_code == "IDN"
        assert plugin.doc_type == "NPWP"
        assert plugin.schema_model is NpwpData
        assert "NPWP" in plugin.description

    def test_classification_rules_contain_expected_keywords(self) -> None:
        plugin = IndonesiaNpwpPlugin()
        rules = {rule.keyword: rule for rule in plugin.classification_rules}

        expected_keywords = {
            "NPWP",
            "NOMOR POKOK WAJIB PAJAK",
            "DIREKTORAT JENDERAL PAJAK",
            "KEMENTERIAN KEUANGAN",
            "KPP PRATAMA",
            "TERDAFTAR",
        }
        assert expected_keywords.issubset(rules.keys())
        assert rules["NPWP"].required is True

    def test_build_prompt_without_ocr_includes_npwp_guidance(self) -> None:
        plugin = IndonesiaNpwpPlugin()
        prompt = plugin.build_prompt()

        assert "NPWP16" in prompt
        assert "NPWP15" in prompt
        assert "TERDAFTAR" in prompt
        assert "KPP PRATAMA" in prompt
        assert "null" in prompt

    def test_build_prompt_with_ocr_lines_and_raw_text(self) -> None:
        plugin = IndonesiaNpwpPlugin()

        ocr_with_lines = OcrResult(
            lines=[
                OcrLine(text="DIREKTORAT JENDERAL PAJAK", confidence=0.98),
                OcrLine(text="NPWP : 01.234.567.8-901.000", confidence=0.96),
            ],
            raw_text="DIREKTORAT JENDERAL PAJAK\nNPWP : 01.234.567.8-901.000",
        )
        prompt_lines = plugin.build_prompt(ocr_with_lines)
        assert "[0.98] DIREKTORAT JENDERAL PAJAK" in prompt_lines
        assert "[0.96] NPWP : 01.234.567.8-901.000" in prompt_lines

        ocr_raw_only = OcrResult(raw_text="NPWP 01.234.567.8-901.000")
        prompt_raw = plugin.build_prompt(ocr_raw_only)
        assert "NPWP 01.234.567.8-901.000" in prompt_raw

    def test_validate_passing_and_failing_cases(self) -> None:
        plugin = IndonesiaNpwpPlugin()

        valid_corporate = NpwpData(
            npwp_15=ExtractedField[str](value="01.234.567.8-901.000", confidence=0.98),
            npwp_16=ExtractedField[str](value="0012345678901000", confidence=0.98),
        )
        result_ok = plugin.validate(valid_corporate)
        assert result_ok.is_valid is True
        assert len(result_ok.checks) == 4

        mismatch_corporate = NpwpData(
            npwp_15=ExtractedField[str](value="01.234.567.8-901.000", confidence=0.98),
            npwp_16=ExtractedField[str](value="0012345678901999", confidence=0.98),
        )
        result_bad = plugin.validate(mismatch_corporate)
        assert result_bad.is_valid is False
        assert [c.name for c in result_bad.checks if not c.passed] == ["npwp_15_16_consistency"]

    def test_validate_rejects_wrong_schema_type(self) -> None:
        plugin = IndonesiaNpwpPlugin()
        result = plugin.validate(_OtherSchema(value="unexpected"))

        assert result.is_valid is False
        assert len(result.checks) == 1
        assert result.checks[0].name == "npwp_schema_type"

    def test_offline_parse_legacy_15_digit_card(self) -> None:
        plugin = IndonesiaNpwpPlugin()
        ocr = OcrResult(
            raw_text=(
                "KEMENTERIAN KEUANGAN REPUBLIK INDONESIA\n"
                "DIREKTORAT JENDERAL PAJAK\n"
                "KPP PRATAMA JAKARTA SETIABUDI SATU\n"
                "NPWP : 01.234.567.8-011.000\n"
                "TERDAFTAR : 15-04-2019\n"
            )
        )

        parsed = plugin.offline_parse(ocr)
        assert isinstance(parsed, NpwpData)
        assert parsed.npwp_15.value == "01.234.567.8-011.000"
        assert parsed.npwp_16.value is None
        assert parsed.kpp_code.value == "011"
        assert parsed.kpp_name.value == "KPP PRATAMA JAKARTA SETIABUDI SATU"
        assert parsed.registered_date.value == "2019-04-15"
        assert plugin.validate(parsed).is_valid is True

    def test_offline_parse_dual_number_individual_card(self) -> None:
        plugin = IndonesiaNpwpPlugin()
        ocr = OcrResult(
            raw_text=(
                "DIREKTORAT JENDERAL PAJAK\n"
                "NPWP16 : 3171 0115 0895 0001\n"
                "NPWP15 : 12.345.678.9-012.000\n"
                "KPP PRATAMA BANDUNG CIBEUNYING\n"
                "TERDAFTAR 01/07/2024\n"
            )
        )

        parsed = plugin.offline_parse(ocr)
        assert parsed.npwp_16.value == "3171011508950001"
        assert parsed.npwp_15.value == "12.345.678.9-012.000"
        assert parsed.kpp_code.value == "012"
        assert parsed.registered_date.value == "2024-07-01"
        assert plugin.validate(parsed).is_valid is True

    def test_offline_parse_empty_ocr_returns_empty_npwp_data(self) -> None:
        plugin = IndonesiaNpwpPlugin()
        parsed = plugin.offline_parse(OcrResult(raw_text=""))
        assert parsed.npwp_15.value is None
        assert parsed.npwp_16.value is None
        assert parsed.kpp_code.value is None
        assert parsed.kpp_name.value is None
        assert parsed.registered_date.value is None

    def test_default_registry_registers_idn_npwp(self) -> None:
        registry = create_default_registry()
        assert ("IDN", "NPWP") in registry
        plugin = registry.get("idn", "npwp")
        assert isinstance(plugin, IndonesiaNpwpPlugin)
