"""Unit tests for the deterministic Indonesian SIM validator."""

from __future__ import annotations

from datetime import date

import pytest

from app.plugins.idn.sim_validator import (
    SimClass,
    clean_sim_number,
    normalize_sim_class,
    validate_sim,
)

_REF_DATE = date(2026, 6, 15)


class TestSimClassNormalization:
    """Test Perpol No. 5/2021 SIM class enum and OCR variation normalization."""

    def test_all_perpol_classes_defined(self) -> None:
        expected = {
            "A",
            "A UMUM",
            "BI",
            "BI UMUM",
            "BII",
            "BII UMUM",
            "C",
            "CI",
            "CII",
            "D",
            "DI",
        }
        assert {member.value for member in SimClass} == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("A", SimClass.A),
            ("a", SimClass.A),
            ("A UMUM", SimClass.A_UMUM),
            ("a  umum", SimClass.A_UMUM),
            ("A-UMUM", SimClass.A_UMUM),
            ("BI", SimClass.BI),
            ("B1", SimClass.BI),
            ("b1", SimClass.BI),
            ("B I", SimClass.BI),
            ("B 1", SimClass.BI),
            ("B1 UMUM", SimClass.BI_UMUM),
            ("B I UMUM", SimClass.BI_UMUM),
            ("BII", SimClass.BII),
            ("B2", SimClass.BII),
            ("B II", SimClass.BII),
            ("B 2", SimClass.BII),
            ("B2 UMUM", SimClass.BII_UMUM),
            ("B II UMUM", SimClass.BII_UMUM),
            ("C", SimClass.C),
            ("CI", SimClass.CI),
            ("C1", SimClass.CI),
            ("C I", SimClass.CI),
            ("CII", SimClass.CII),
            ("C2", SimClass.CII),
            ("C II", SimClass.CII),
            ("D", SimClass.D),
            ("DI", SimClass.DI),
            ("D1", SimClass.DI),
            ("D I", SimClass.DI),
            ("SIM C", SimClass.C),
            ("GOL. SIM : B1", SimClass.BI),
            ("SIM B2 UMUM", SimClass.BII_UMUM),
        ],
    )
    def test_normalize_valid_variants(self, raw: str, expected: SimClass) -> None:
        assert normalize_sim_class(raw) is expected

    @pytest.mark.parametrize("raw", ["", "   ", "Z", "B3", "C3", "D2", "E", "UNKNOWN"])
    def test_normalize_invalid_returns_none(self, raw: str) -> None:
        assert normalize_sim_class(raw) is None


class TestCleanSimNumber:
    """Test separator stripping for SIM numbers."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1234-5678-901234", "12345678901234"),
            ("1234 5678 9012", "123456789012"),
            ("  3171-0115-0895-0001  ", "3171011508950001"),
            ("9012345678901", "9012345678901"),
        ],
    )
    def test_clean_sim_number(self, raw: str, expected: str) -> None:
        assert clean_sim_number(raw) == expected


class TestValidateSimLegacy:
    """Test legacy 12-14 digit SIM number validation."""

    @pytest.mark.parametrize(
        "sim_number",
        [
            "123456789012",
            "1234-5678-9012",
            "1234567890123",
            "1234-5678-901234",
            "1234 5678 901234",
        ],
    )
    def test_valid_legacy_sim_numbers(self, sim_number: str) -> None:
        checks = validate_sim(
            sim_number,
            sim_class="C",
            valid_until="2028-08-17",
            date_of_birth="1995-08-17",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}

        assert by_name["sim_number_format_valid"].passed is True
        assert by_name["sim_class_valid"].passed is True
        assert by_name["sim_not_expired"].passed is True
        assert by_name["sim_minimum_age_valid"].passed is True
        assert "sim_nik_cross_check" not in by_name

    @pytest.mark.parametrize(
        "bad_number",
        [
            None,
            "",
            "   ",
            "12345678901",  # 11 digits
            "123456789012345",  # 15 digits
            "12345678901234567",  # 17 digits
            "1234-ABCD-9012",  # non-digits
        ],
    )
    def test_invalid_sim_numbers_fail_format_check(self, bad_number: str | None) -> None:
        checks = validate_sim(
            bad_number,
            sim_class="A",
            valid_until="2028-01-01",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}
        assert by_name["sim_number_format_valid"].passed is False
        assert "sim_nik_cross_check" not in by_name


class TestValidateSimNikLinked:
    """Test 2024+ 16-digit NIK-linked SIM cross-validation."""

    def test_valid_16_digit_male_sim(self) -> None:
        # Synthetic male NIK: 31 (DKI Jakarta), DOB 15-08-1995
        checks = validate_sim(
            "3171-0115-0895-0001",
            sim_class="A",
            valid_until="2029-08-15",
            date_of_birth="1995-08-15",
            gender="LAKI-LAKI",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}

        assert by_name["sim_number_format_valid"].passed is True
        assert by_name["sim_nik_cross_check"].passed is True
        assert by_name["sim_class_valid"].passed is True
        assert by_name["sim_not_expired"].passed is True
        assert by_name["sim_minimum_age_valid"].passed is True

    def test_valid_16_digit_female_sim(self) -> None:
        # Synthetic female NIK: 32 (Jawa Barat), day 17 + 40 = 57, DOB 17-08-1995
        checks = validate_sim(
            "3273015708950002",
            sim_class="C1",
            valid_until="17-08-2029",
            date_of_birth="17-08-1995",
            gender="WANITA",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}

        assert by_name["sim_number_format_valid"].passed is True
        assert by_name["sim_nik_cross_check"].passed is True
        assert by_name["sim_class_valid"].passed is True
        assert by_name["sim_not_expired"].passed is True
        assert by_name["sim_minimum_age_valid"].passed is True

    def test_16_digit_sim_mismatched_dob_fails_cross_check(self) -> None:
        checks = validate_sim(
            "3171011508950001",
            sim_class="A",
            valid_until="2029-08-15",
            date_of_birth="1995-08-20",
            gender="LAKI-LAKI",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}

        assert by_name["sim_number_format_valid"].passed is True
        assert by_name["sim_nik_cross_check"].passed is False
        assert "date_of_birth" in (by_name["sim_nik_cross_check"].message or "")

    def test_16_digit_sim_mismatched_gender_fails_cross_check(self) -> None:
        checks = validate_sim(
            "3273015708950002",
            sim_class="C",
            valid_until="2029-08-17",
            date_of_birth="1995-08-17",
            gender="LAKI-LAKI",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}

        assert by_name["sim_number_format_valid"].passed is True
        assert by_name["sim_nik_cross_check"].passed is False
        assert "gender" in (by_name["sim_nik_cross_check"].message or "")

    def test_16_digit_sim_invalid_province_fails_cross_check(self) -> None:
        checks = validate_sim(
            "9971011508950001",
            sim_class="A",
            valid_until="2029-08-15",
            reference_date=_REF_DATE,
        )
        by_name = {check.name: check for check in checks}

        assert by_name["sim_number_format_valid"].passed is True
        assert by_name["sim_nik_cross_check"].passed is False
        assert "province" in (by_name["sim_nik_cross_check"].message or "").lower()


class TestValidateSimRules:
    """Test expiration, class, minimum age, and missing/null field handling."""

    def test_expired_vs_active_and_boundary_date(self) -> None:
        expired = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2026-06-14",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in expired}["sim_not_expired"] is False

        boundary = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2026-06-15",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in boundary}["sim_not_expired"] is True

        active = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2026-06-16",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in active}["sim_not_expired"] is True

    def test_missing_and_invalid_expiration_date(self) -> None:
        missing = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until=None,
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in missing}["sim_not_expired"] is False

        invalid = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="31-02-2028",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in invalid}["sim_not_expired"] is False

    def test_minimum_driving_age_checks(self) -> None:
        # Exactly 17 on 2026-06-15
        exact_17 = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2030-06-15",
            date_of_birth="2009-06-15",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in exact_17}["sim_minimum_age_valid"] is True

        # One day shy of 17 on 2026-06-15
        under_17 = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2030-06-15",
            date_of_birth="2009-06-16",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in under_17}["sim_minimum_age_valid"] is False

        # Invalid DOB format
        bad_dob = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2030-06-15",
            date_of_birth="not-a-date",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in bad_dob}["sim_minimum_age_valid"] is False

        # Missing DOB omits optional minimum age check
        no_dob = validate_sim(
            "123456789012",
            sim_class="C",
            valid_until="2030-06-15",
            date_of_birth=None,
            reference_date=_REF_DATE,
        )
        assert "sim_minimum_age_valid" not in {c.name for c in no_dob}

    def test_missing_and_invalid_sim_class(self) -> None:
        missing = validate_sim(
            "123456789012",
            sim_class=None,
            valid_until="2030-06-15",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in missing}["sim_class_valid"] is False

        invalid = validate_sim(
            "123456789012",
            sim_class="Z",
            valid_until="2030-06-15",
            reference_date=_REF_DATE,
        )
        assert {c.name: c.passed for c in invalid}["sim_class_valid"] is False
