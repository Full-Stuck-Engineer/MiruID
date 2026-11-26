"""Unit tests for the Indonesian Driver's License (SIM) plugin (IDN/SIM)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.domain.interfaces import DocumentPlugin
from app.domain.schemas import ExtractedField, OcrLine, OcrResult
from app.plugins import create_default_registry
from app.plugins.idn.sim import IndonesiaSimPlugin, SimData


class _OtherSchema(BaseModel):
    value: str = ""


class TestSimSchemaNormalization:
    """Test Pydantic normalization on SimData fields."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("b1", "BI"),
            ("B2", "BII"),
            ("B I", "BI"),
            ("B II", "BII"),
            ("B1 Umum", "BI UMUM"),
            ("B2 umum", "BII UMUM"),
            ("c1", "CI"),
            ("c2", "CII"),
            ("d1", "DI"),
            ("a umum", "A UMUM"),
            ("unknown", "UNKNOWN"),
            ("   ", None),
        ],
    )
    def test_sim_class_normalization(self, raw: str, expected: str | None) -> None:
        data = SimData(sim_class=ExtractedField[str](value=raw, confidence=0.95))
        assert data.sim_class.value == expected
        assert data.sim_class.confidence == 0.95

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("17-08-1995", "1995-08-17"),
            ("17/08/1995", "1995-08-17"),
            ("1995-08-17", "1995-08-17"),
            ("1995/08/17", "1995-08-17"),
            ("31-02-1995", "31-02-1995"),
            ("   ", None),
        ],
    )
    def test_date_fields_normalization(self, raw: str, expected: str | None) -> None:
        data = SimData(
            date_of_birth=ExtractedField[str](value=raw, confidence=0.9),
            valid_until=ExtractedField[str](value=raw, confidence=0.92),
        )
        assert data.date_of_birth.value == expected
        assert data.valid_until.value == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("pria", "LAKI-LAKI"),
            ("LAKI-LAKI", "LAKI-LAKI"),
            ("M", "LAKI-LAKI"),
            ("wanita", "PEREMPUAN"),
            ("PEREMPUAN", "PEREMPUAN"),
            ("F", "PEREMPUAN"),
            ("other", "OTHER"),
            ("  ", None),
        ],
    )
    def test_gender_normalization(self, raw: str, expected: str | None) -> None:
        data = SimData(gender=ExtractedField[str](value=raw, confidence=0.88))
        assert data.gender.value == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (" o ", "O"),
            ("ab", "AB"),
            ("-", None),
            ("   ", None),
        ],
    )
    def test_blood_type_normalization(self, raw: str, expected: str | None) -> None:
        data = SimData(blood_type=ExtractedField[str](value=raw, confidence=0.9))
        assert data.blood_type.value == expected

    def test_sim_number_whitespace_trimmed(self) -> None:
        data = SimData(
            sim_number=ExtractedField[str](value="  1234-5678-901234  ", confidence=0.98)
        )
        assert data.sim_number.value == "1234-5678-901234"


class TestIndonesiaSimPlugin:
    """Test IndonesiaSimPlugin protocol conformance, prompts, validation, and offline parse."""

    def test_conforms_to_document_plugin_protocol(self) -> None:
        plugin = IndonesiaSimPlugin()

        assert isinstance(plugin, DocumentPlugin)
        assert plugin.country_code == "IDN"
        assert plugin.doc_type == "SIM"
        assert plugin.schema_model is SimData
        assert "SIM" in plugin.description

    def test_classification_rules_contain_expected_keywords(self) -> None:
        plugin = IndonesiaSimPlugin()
        rules = {rule.keyword: rule for rule in plugin.classification_rules}

        expected_keywords = {
            "SURAT IZIN MENGEMUDI",
            "DRIVING LICENSE",
            "KEPOLISIAN NEGARA REPUBLIK INDONESIA",
            "POLRI",
            "SIM",
            "GOL. SIM",
            "BERLAKU S/D",
        }
        assert expected_keywords.issubset(rules.keys())
        assert all(rule.weight > 0 for rule in rules.values())

    def test_build_prompt_without_ocr_includes_sim_guidance(self) -> None:
        plugin = IndonesiaSimPlugin()
        prompt = plugin.build_prompt()

        assert "Smart SIM" in prompt
        assert "2024+" in prompt
        assert "vehicle icons" in prompt
        assert "Perpol No. 5/2021" in prompt
        assert "LAKI-LAKI" in prompt
        assert "null" in prompt
        assert "UPPERCASE" in prompt

    def test_build_prompt_with_ocr_lines_and_raw_text(self) -> None:
        plugin = IndonesiaSimPlugin()

        ocr_with_lines = OcrResult(
            lines=[
                OcrLine(text="SURAT IZIN MENGEMUDI", confidence=0.98),
                OcrLine(text="1234-5678-901234", confidence=0.95),
            ],
            raw_text="SURAT IZIN MENGEMUDI\n1234-5678-901234",
        )
        prompt_lines = plugin.build_prompt(ocr_with_lines)
        assert "[0.98] SURAT IZIN MENGEMUDI" in prompt_lines
        assert "[0.95] 1234-5678-901234" in prompt_lines

        ocr_raw_only = OcrResult(raw_text="DRIVING LICENSE SIM A")
        prompt_raw = plugin.build_prompt(ocr_raw_only)
        assert "DRIVING LICENSE SIM A" in prompt_raw

    def test_validate_passing_nik_linked_sim_data(self) -> None:
        plugin = IndonesiaSimPlugin()
        data = SimData(
            sim_number=ExtractedField[str](value="3273015708950002", confidence=0.99),
            sim_class=ExtractedField[str](value="C1", confidence=0.95),
            date_of_birth=ExtractedField[str](value="17-08-1995", confidence=0.95),
            gender=ExtractedField[str](value="WANITA", confidence=0.95),
            valid_until=ExtractedField[str](value="17-08-2035", confidence=0.95),
        )

        result = plugin.validate(data)
        assert result.is_valid is True
        assert all(check.passed for check in result.checks)
        names = {check.name for check in result.checks}
        assert names == {
            "sim_number_format_valid",
            "sim_nik_cross_check",
            "sim_class_valid",
            "sim_not_expired",
            "sim_minimum_age_valid",
        }

    def test_validate_failing_on_expired_and_bad_class(self) -> None:
        plugin = IndonesiaSimPlugin()
        data = SimData(
            sim_number=ExtractedField[str](value="1234-5678-9012", confidence=0.95),
            sim_class=ExtractedField[str](value="Z", confidence=0.8),
            valid_until=ExtractedField[str](value="2020-01-01", confidence=0.9),
        )

        result = plugin.validate(data)
        assert result.is_valid is False
        failed = {check.name for check in result.checks if not check.passed}
        assert failed == {"sim_class_valid", "sim_not_expired"}

    def test_validate_rejects_wrong_schema_type(self) -> None:
        plugin = IndonesiaSimPlugin()
        result = plugin.validate(_OtherSchema(value="unexpected"))

        assert result.is_valid is False
        assert len(result.checks) == 1
        assert result.checks[0].name == "sim_schema_type"

    def test_offline_parse_extracts_synthetic_smart_sim(self) -> None:
        plugin = IndonesiaSimPlugin()
        ocr = OcrResult(
            raw_text=(
                "KEPOLISIAN NEGARA REPUBLIK INDONESIA\n"
                "SURAT IZIN MENGEMUDI / DRIVING LICENSE\n"
                "GOL. SIM : B1\n"
                "1234-5678-901234\n"
                "1. BUDI SANTOSO\n"
                "2. JAKARTA, 15-08-1995\n"
                "3. O - PRIA\n"
                "BERLAKU S/D 15-08-2035\n"
            )
        )

        parsed = plugin.offline_parse(ocr)
        assert isinstance(parsed, SimData)
        assert parsed.sim_number.value == "1234-5678-901234"
        assert parsed.sim_class.value == "BI"
        assert parsed.date_of_birth.value == "1995-08-15"
        assert parsed.gender.value == "LAKI-LAKI"
        assert parsed.valid_until.value == "2035-08-15"

        validation = plugin.validate(parsed)
        assert validation.is_valid is True

    def test_offline_parse_extracts_2024_nik_sim(self) -> None:
        plugin = IndonesiaSimPlugin()
        ocr = OcrResult(
            raw_text=(
                "INDONESIA DRIVING LICENSE\n"
                "SIM C2\n"
                "3273015708950002\n"
                "BANDUNG, 17-08-1995\n"
                "A - WANITA\n"
                "17-08-2035\n"
            )
        )

        parsed = plugin.offline_parse(ocr)
        assert parsed.sim_number.value == "3273015708950002"
        assert parsed.sim_class.value == "CII"
        assert parsed.gender.value == "PEREMPUAN"
        assert plugin.validate(parsed).is_valid is True

    def test_offline_parse_empty_ocr_returns_empty_sim_data(self) -> None:
        plugin = IndonesiaSimPlugin()
        parsed = plugin.offline_parse(OcrResult(raw_text=""))
        assert parsed.sim_number.value is None
        assert parsed.sim_class.value is None
        assert parsed.date_of_birth.value is None
        assert parsed.gender.value is None
        assert parsed.valid_until.value is None

    def test_default_registry_registers_idn_sim(self) -> None:
        registry = create_default_registry()
        assert ("IDN", "SIM") in registry
        plugin = registry.get("idn", "sim")
        assert isinstance(plugin, IndonesiaSimPlugin)
