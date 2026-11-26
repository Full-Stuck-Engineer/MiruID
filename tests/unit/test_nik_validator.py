"""Unit tests for Indonesian province codes and deterministic NIK validation."""

from __future__ import annotations

from datetime import date

import pytest

from app.plugins.idn.nik_validator import (
    ParsedNik,
    normalize_gender,
    parse_nik,
    validate_nik,
)
from app.plugins.idn.province_codes import PROVINCE_NAMES, VALID_PROVINCE_CODES


def _checks_by_name(
    nik: str | None,
    *,
    extracted_dob: str | None = None,
    extracted_gender: str | None = None,
    reference_year: int | None = 2026,
) -> dict[str, bool]:
    checks = validate_nik(
        nik,
        extracted_dob=extracted_dob,
        extracted_gender=extracted_gender,
        reference_year=reference_year,
    )
    return {check.name: check.passed for check in checks}


class TestProvinceCodes:
    """Verify Kemendagri 2-digit province code coverage."""

    def test_contains_all_38_provinces(self) -> None:
        assert len(PROVINCE_NAMES) == 38
        assert len(VALID_PROVINCE_CODES) == 38
        assert frozenset(PROVINCE_NAMES) == VALID_PROVINCE_CODES

    def test_includes_new_papua_provinces(self) -> None:
        for code in ("91", "92", "93", "94", "95", "96"):
            assert code in VALID_PROVINCE_CODES
            assert PROVINCE_NAMES[code]


class TestParseNik:
    """Test parse_nik decoding for synthetic male, female, and edge-case NIKs."""

    def test_parse_valid_male_nik(self) -> None:
        # Synthetic: 31 (DKI Jakarta), 71, 01, 15-08-1995 (male), 0001
        parsed = parse_nik("3171011508950001", reference_year=2026)

        assert parsed == ParsedNik(
            province_code="31",
            regency_code="71",
            district_code="01",
            birth_date=date(1995, 8, 15),
            gender="LAKI-LAKI",
            serial="0001",
        )

    def test_parse_valid_female_nik_with_plus_40_offset(self) -> None:
        # Synthetic: 32 (Jawa Barat), 73, 01, 57-08-1995 -> day 17 (female), 0002
        parsed = parse_nik("3273015708950002", reference_year=2026)

        assert parsed == ParsedNik(
            province_code="32",
            regency_code="73",
            district_code="01",
            birth_date=date(1995, 8, 17),
            gender="PEREMPUAN",
            serial="0002",
        )

    def test_parse_leap_year_2000_male_and_female(self) -> None:
        # Synthetic: 96 (Papua Barat Daya), 29-02-2000 (male) & 69-02-2000 (female)
        male = parse_nik("9601012902000001", reference_year=2026)
        female = parse_nik("9601016902000002", reference_year=2026)

        assert male is not None
        assert male.birth_date == date(2000, 2, 29)
        assert male.gender == "LAKI-LAKI"

        assert female is not None
        assert female.birth_date == date(2000, 2, 29)
        assert female.gender == "PEREMPUAN"

    def test_parse_handles_spaces_and_hyphens(self) -> None:
        parsed = parse_nik("3171-0115-0895-0001", reference_year=2026)
        assert parsed is not None
        assert parsed.birth_date == date(1995, 8, 15)

    def test_parse_uses_expected_dob_century_for_centenarian(self) -> None:
        # Synthetic: 15-05-1920 -> DDMMYY = 150520
        parsed = parse_nik(
            "3171011505200001",
            reference_year=2026,
            expected_dob=date(1920, 5, 15),
        )
        assert parsed is not None
        assert parsed.birth_date == date(1920, 5, 15)

    @pytest.mark.parametrize(
        "invalid_nik",
        [
            "",
            "12345",
            "31710115089500019",
            "317101150895000A",
            "٠١٢٣٤٥٦٧٨٩٠١٢٣٤٥",  # non-ASCII digits
            "9971011508950001",  # invalid province code 99
            "3171012902990001",  # 1999 is not a leap year
            "3171013201950001",  # day 32 (male)
            "3171017201950001",  # day 72 -> 32 (female)
            "3171014001950001",  # day 40 (male, invalid)
            "3171010001950001",  # day 00
            "3171011513950001",  # month 13
            "3171013104950001",  # April 31
        ],
    )
    def test_parse_returns_none_for_invalid_niks(self, invalid_nik: str) -> None:
        assert parse_nik(invalid_nik, reference_year=2026) is None


class TestValidateNik:
    """Test validate_nik granular ValidationCheck outputs."""

    def test_missing_or_malformed_nik_fails_format_check_only(self) -> None:
        assert _checks_by_name(None) == {"nik_format_16_digits": False}
        assert _checks_by_name("   ") == {"nik_format_16_digits": False}
        assert _checks_by_name("31710115") == {"nik_format_16_digits": False}

    def test_valid_nik_without_extracted_fields(self) -> None:
        results = _checks_by_name("3171011508950001")
        assert results == {
            "nik_format_16_digits": True,
            "nik_province_code_valid": True,
            "nik_date_valid": True,
        }

    def test_valid_nik_with_matching_dob_and_gender(self) -> None:
        results = _checks_by_name(
            "3273015708950002",
            extracted_dob="1995-08-17",
            extracted_gender="PEREMPUAN",
        )
        assert results == {
            "nik_format_16_digits": True,
            "nik_province_code_valid": True,
            "nik_date_valid": True,
            "nik_dob_matches_extracted": True,
            "nik_gender_matches_extracted": True,
        }

    def test_invalid_province_code_still_checks_date(self) -> None:
        results = _checks_by_name("9971011508950001")
        assert results == {
            "nik_format_16_digits": True,
            "nik_province_code_valid": False,
            "nik_date_valid": True,
        }

    def test_mismatched_dob_and_gender_fail_cross_checks(self) -> None:
        results = _checks_by_name(
            "3171011508950001",
            extracted_dob="1995-08-16",
            extracted_gender="PEREMPUAN",
        )
        assert results["nik_format_16_digits"] is True
        assert results["nik_province_code_valid"] is True
        assert results["nik_date_valid"] is True
        assert results["nik_dob_matches_extracted"] is False
        assert results["nik_gender_matches_extracted"] is False

    def test_invalid_extracted_dob_and_gender_fail_gracefully(self) -> None:
        results = _checks_by_name(
            "3171011508950001",
            extracted_dob="not-a-date",
            extracted_gender="UNKNOWN",
        )
        assert results["nik_dob_matches_extracted"] is False
        assert results["nik_gender_matches_extracted"] is False

    def test_invalid_nik_date_fails_cross_checks(self) -> None:
        results = _checks_by_name(
            "3171013102950001",
            extracted_dob="1995-02-28",
            extracted_gender="LAKI-LAKI",
        )
        assert results["nik_date_valid"] is False
        assert results["nik_dob_matches_extracted"] is False
        assert results["nik_gender_matches_extracted"] is False

    def test_dmy_extracted_dob_supported_in_cross_check(self) -> None:
        results = _checks_by_name(
            "3171011508950001",
            extracted_dob="15-08-1995",
            extracted_gender="M",
        )
        assert results["nik_dob_matches_extracted"] is True
        assert results["nik_gender_matches_extracted"] is True


def test_normalize_gender_aliases() -> None:
    assert normalize_gender("laki-laki") == "LAKI-LAKI"
    assert normalize_gender("LAKI LAKI") == "LAKI-LAKI"
    assert normalize_gender("male") == "LAKI-LAKI"
    assert normalize_gender("M") == "LAKI-LAKI"
    assert normalize_gender("perempuan") == "PEREMPUAN"
    assert normalize_gender("female") == "PEREMPUAN"
    assert normalize_gender("F") == "PEREMPUAN"
    assert normalize_gender("wanita") == "PEREMPUAN"
    assert normalize_gender("OTHER") is None
