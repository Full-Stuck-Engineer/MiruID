"""Unit tests for the Indonesian e-KTP plugin (IDN/KTP)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.domain.interfaces import DocumentPlugin
from app.domain.schemas import ExtractedField, OcrLine, OcrResult
from app.plugins import create_default_registry
from app.plugins.idn.ktp import IndonesiaKtpPlugin, KtpAddress, KtpData


class _OtherSchema(BaseModel):
    value: str = ""


class TestKtpSchemas:
    """Test Pydantic normalization on KtpAddress and KtpData."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1/2", "001/002"),
            ("001 / 002", "001/002"),
            ("01-02", "001/002"),
            ("12/345", "012/345"),
            ("   ", None),
            ("RT 01", "RT 01"),
        ],
    )
    def test_rt_rw_normalization(self, raw: str, expected: str | None) -> None:
        address = KtpAddress(rt_rw=ExtractedField[str](value=raw, confidence=0.9))
        assert address.rt_rw.value == expected
        assert address.rt_rw.confidence == 0.9

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
    def test_date_of_birth_normalization(self, raw: str, expected: str | None) -> None:
        data = KtpData(date_of_birth=ExtractedField[str](value=raw, confidence=0.95))
        assert data.date_of_birth.value == expected
        assert data.date_of_birth.confidence == 0.95

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("laki-laki", "LAKI-LAKI"),
            ("LAKI LAKI", "LAKI-LAKI"),
            ("M", "LAKI-LAKI"),
            ("male", "LAKI-LAKI"),
            ("perempuan", "PEREMPUAN"),
            ("F", "PEREMPUAN"),
            ("female", "PEREMPUAN"),
            ("wanita", "PEREMPUAN"),
            ("other", "OTHER"),
            ("  ", None),
        ],
    )
    def test_gender_normalization(self, raw: str, expected: str | None) -> None:
        data = KtpData(gender=ExtractedField[str](value=raw, confidence=0.88))
        assert data.gender.value == expected
        assert data.gender.confidence == 0.88

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("seumur hidup", "SEUMUR HIDUP"),
            ("  Seumur   Hidup ", "SEUMUR HIDUP"),
            ("17-08-2030", "2030-08-17"),
            ("   ", None),
        ],
    )
    def test_valid_until_normalization(self, raw: str, expected: str | None) -> None:
        data = KtpData(valid_until=ExtractedField[str](value=raw, confidence=0.92))
        assert data.valid_until.value == expected

    def test_nik_whitespace_trimmed(self) -> None:
        data = KtpData(nik=ExtractedField[str](value="  3171011508950001  ", confidence=0.99))
        assert data.nik.value == "3171011508950001"


class TestIndonesiaKtpPlugin:
    """Test IndonesiaKtpPlugin protocol conformance, prompts, validation, and offline parse."""

    def test_conforms_to_document_plugin_protocol(self) -> None:
        plugin = IndonesiaKtpPlugin()

        assert isinstance(plugin, DocumentPlugin)
        assert plugin.country_code == "IDN"
        assert plugin.doc_type == "KTP"
        assert plugin.schema_model is KtpData
        assert "e-KTP" in plugin.description

    def test_classification_rules_contain_expected_keywords(self) -> None:
        plugin = IndonesiaKtpPlugin()
        rules = {rule.keyword: rule for rule in plugin.classification_rules}

        expected_keywords = {
            "PROVINSI",
            "NIK",
            "KARTU TANDA PENDUDUK",
            "GOL. DARAH",
            "KEWARGANEGARAAN",
            "BERLAKU HINGGA",
            "SEUMUR HIDUP",
            "RT/RW",
        }
        assert expected_keywords.issubset(rules.keys())
        assert rules["NIK"].required is True

    def test_build_prompt_without_ocr_includes_ktp_guidance(self) -> None:
        plugin = IndonesiaKtpPlugin()
        prompt = plugin.build_prompt()

        assert "TEMPAT/TGL LAHIR" in prompt
        assert "GOL. DARAH" in prompt
        assert "SEUMUR HIDUP" in prompt
        assert "null" in prompt
        assert "UPPERCASE" in prompt

    def test_build_prompt_with_ocr_lines_and_raw_text(self) -> None:
        plugin = IndonesiaKtpPlugin()

        ocr_with_lines = OcrResult(
            lines=[
                OcrLine(text="PROVINSI DKI JAKARTA", confidence=0.98),
                OcrLine(text="NIK : 3171011508950001", confidence=0.96),
            ],
            raw_text="PROVINSI DKI JAKARTA\nNIK : 3171011508950001",
        )
        prompt_lines = plugin.build_prompt(ocr_with_lines)
        assert "[0.98] PROVINSI DKI JAKARTA" in prompt_lines
        assert "[0.96] NIK : 3171011508950001" in prompt_lines

        ocr_raw_only = OcrResult(raw_text="NIK 3171011508950001")
        prompt_raw = plugin.build_prompt(ocr_raw_only)
        assert "NIK 3171011508950001" in prompt_raw

    def test_validate_passing_ktp_data(self) -> None:
        plugin = IndonesiaKtpPlugin()
        # Synthetic female NIK: 32 (Jawa Barat), 57-08-1995 -> 1995-08-17, PEREMPUAN
        data = KtpData(
            nik=ExtractedField[str](value="3273015708950002", confidence=0.99),
            date_of_birth=ExtractedField[str](value="17-08-1995", confidence=0.95),
            gender=ExtractedField[str](value="PEREMPUAN", confidence=0.95),
        )

        result = plugin.validate(data)
        assert result.is_valid is True
        assert all(check.passed for check in result.checks)
        assert len(result.checks) == 5

    def test_validate_failing_on_mismatched_gender(self) -> None:
        plugin = IndonesiaKtpPlugin()
        data = KtpData(
            nik=ExtractedField[str](value="3273015708950002", confidence=0.99),
            date_of_birth=ExtractedField[str](value="1995-08-17", confidence=0.95),
            gender=ExtractedField[str](value="LAKI-LAKI", confidence=0.95),
        )

        result = plugin.validate(data)
        assert result.is_valid is False
        failed = [check.name for check in result.checks if not check.passed]
        assert failed == ["nik_gender_matches_extracted"]

    def test_validate_rejects_wrong_schema_type(self) -> None:
        plugin = IndonesiaKtpPlugin()
        result = plugin.validate(_OtherSchema(value="unexpected"))

        assert result.is_valid is False
        assert len(result.checks) == 1
        assert result.checks[0].name == "ktp_schema_type"

    def test_offline_parse_extracts_synthetic_ktp_fields(self) -> None:
        plugin = IndonesiaKtpPlugin()
        ocr = OcrResult(
            raw_text=(
                "PROVINSI DKI JAKARTA\n"
                "NIK : 3171011508950001\n"
                "Tempat/Tgl Lahir : JAKARTA, 15-08-1995\n"
                "Jenis Kelamin : LAKI-LAKI\n"
                "RT/RW : 1/2\n"
                "Berlaku Hingga : SEUMUR HIDUP\n"
            )
        )

        parsed = plugin.offline_parse(ocr)
        assert isinstance(parsed, KtpData)
        assert parsed.nik.value == "3171011508950001"
        assert parsed.date_of_birth.value == "1995-08-15"
        assert parsed.gender.value == "LAKI-LAKI"
        assert parsed.address.rt_rw.value == "001/002"
        assert parsed.valid_until.value == "SEUMUR HIDUP"

        validation = plugin.validate(parsed)
        assert validation.is_valid is True

    def test_offline_parse_empty_ocr_returns_empty_ktp_data(self) -> None:
        plugin = IndonesiaKtpPlugin()
        parsed = plugin.offline_parse(OcrResult(raw_text=""))
        assert parsed.nik.value is None
        assert parsed.date_of_birth.value is None
        assert parsed.gender.value is None

    def test_default_registry_registers_idn_ktp(self) -> None:
        registry = create_default_registry()
        assert ("IDN", "KTP") in registry
        plugin = registry.get("idn", "ktp")
        assert isinstance(plugin, IndonesiaKtpPlugin)
