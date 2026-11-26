"""Unit tests for deterministic Indonesian NPWP parser and validator."""

from __future__ import annotations

import pytest

from app.domain.schemas import ExtractedField
from app.plugins.idn.npwp import NpwpData
from app.plugins.idn.npwp_validator import (
    extract_kpp_code,
    normalize_npwp_15,
    normalize_npwp_16,
    validate_npwp,
)


class TestNpwpHelpers:
    """Test pure helper functions for NPWP normalization and KPP extraction."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("01.234.567.8-901.000", "01.234.567.8-901.000"),
            ("012345678901000", "01.234.567.8-901.000"),
            ("  01 234 567 8 - 901 000  ", "01.234.567.8-901.000"),
            ("09.876.543.2-012.001", "09.876.543.2-012.001"),
            ("", None),
            ("   ", None),
            ("01.234.567.8-901.00", None),
            ("01.234.567.8-901.0000", None),
            ("01.234.567.8-901.00A", None),
        ],
    )
    def test_normalize_npwp_15(self, raw: str, expected: str | None) -> None:
        assert normalize_npwp_15(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("01.234.567.8-901.000", "901"),
            ("012345678901000", "901"),
            ("09.876.543.2-012.001", "012"),
            ("", None),
            ("0123456789", None),
            ("01.234.567.8-ABC.000", None),
        ],
    )
    def test_extract_kpp_code(self, raw: str, expected: str | None) -> None:
        assert extract_kpp_code(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("3171011508950001", "3171011508950001"),
            ("3171 0115 0895 0001", "3171011508950001"),
            ("3171.0115.0895.0001", "3171011508950001"),
            ("0012-3456-7890-1000", "0012345678901000"),
            ("", None),
            ("   ", None),
            ("317101150895000", None),
            ("31710115089500012", None),
            ("317101150895000X", None),
        ],
    )
    def test_normalize_npwp_16(self, raw: str, expected: str | None) -> None:
        assert normalize_npwp_16(raw) == expected


class TestValidateNpwp:
    """Test validate_npwp across legacy, individual NIK, and corporate NPWPs."""

    def test_missing_both_identifiers_fails(self) -> None:
        checks = validate_npwp(NpwpData())
        assert len(checks) == 1
        assert checks[0].name == "npwp_identifier_present"
        assert checks[0].passed is False

    def test_legacy_15_digit_only_valid(self) -> None:
        data = NpwpData(npwp_15=ExtractedField[str](value="01.234.567.8-901.000", confidence=0.98))
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert set(by_name.keys()) == {"npwp_identifier_present", "npwp_15_format_valid"}
        assert all(check.passed for check in checks)

    def test_legacy_15_digit_malformed_fails(self) -> None:
        data = NpwpData(npwp_15=ExtractedField[str](value="01.234.567.8-901", confidence=0.8))
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert by_name["npwp_identifier_present"].passed is True
        assert by_name["npwp_15_format_valid"].passed is False

    @pytest.mark.parametrize(
        "synthetic_nik",
        [
            "3171011508950001",  # Male, DKI Jakarta, 1995-08-15
            "3273015708950002",  # Female (+40 day), Jawa Barat, 1995-08-17
        ],
    )
    def test_individual_16_digit_nik_npwp_valid(self, synthetic_nik: str) -> None:
        data = NpwpData(npwp_16=ExtractedField[str](value=synthetic_nik, confidence=0.97))
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert set(by_name.keys()) == {"npwp_identifier_present", "npwp_16_format_valid"}
        assert all(check.passed for check in checks)

    @pytest.mark.parametrize(
        ("invalid_nik", "expected_fragment"),
        [
            ("9971011508950001", "province code"),
            ("3171013102950001", "calendar date"),
            ("31710115089500", "16 ASCII digits"),
        ],
    )
    def test_individual_16_digit_invalid_nik_fails(
        self, invalid_nik: str, expected_fragment: str
    ) -> None:
        data = NpwpData(npwp_16=ExtractedField[str](value=invalid_nik, confidence=0.9))
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert by_name["npwp_identifier_present"].passed is True
        assert by_name["npwp_16_format_valid"].passed is False
        assert expected_fragment in (by_name["npwp_16_format_valid"].message or "")

    def test_dual_number_individual_card_passes_without_corporate_consistency_check(self) -> None:
        data = NpwpData(
            npwp_15=ExtractedField[str](value="12.345.678.9-012.000", confidence=0.95),
            npwp_16=ExtractedField[str](value="3171011508950001", confidence=0.98),
        )
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert set(by_name.keys()) == {
            "npwp_identifier_present",
            "npwp_15_format_valid",
            "npwp_16_format_valid",
        }
        assert all(check.passed for check in checks)

    def test_corporate_0_prefixed_16_digit_only_valid(self) -> None:
        data = NpwpData(npwp_16=ExtractedField[str](value="0012345678901000", confidence=0.96))
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert set(by_name.keys()) == {"npwp_identifier_present", "npwp_16_format_valid"}
        assert all(check.passed for check in checks)

    def test_corporate_dual_number_matching_passes_consistency(self) -> None:
        data = NpwpData(
            npwp_15=ExtractedField[str](value="01.234.567.8-901.000", confidence=0.98),
            npwp_16=ExtractedField[str](value="0012 3456 7890 1000", confidence=0.98),
        )
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert set(by_name.keys()) == {
            "npwp_identifier_present",
            "npwp_15_format_valid",
            "npwp_16_format_valid",
            "npwp_15_16_consistency",
        }
        assert all(check.passed for check in checks)

    def test_corporate_dual_number_mismatching_fails_consistency(self) -> None:
        data = NpwpData(
            npwp_15=ExtractedField[str](value="01.234.567.8-901.000", confidence=0.98),
            npwp_16=ExtractedField[str](value="0012345678901999", confidence=0.98),
        )
        checks = validate_npwp(data)
        by_name = {check.name: check for check in checks}

        assert by_name["npwp_identifier_present"].passed is True
        assert by_name["npwp_15_format_valid"].passed is True
        assert by_name["npwp_16_format_valid"].passed is True
        assert by_name["npwp_15_16_consistency"].passed is False
