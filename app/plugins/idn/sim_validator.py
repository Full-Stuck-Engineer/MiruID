"""Deterministic Indonesian SIM (Surat Izin Mengemudi) parser and validator.

Supports both legacy 12-14 digit SIM numbers (pre-2024) and 16-digit NIK-linked
SIM numbers (2024+), as well as Perpol No. 5/2021 license classes.
"""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum

from app.domain.schemas import ValidationCheck
from app.plugins.idn.nik_validator import parse_nik, validate_nik

_SEPARATOR_RE = re.compile(r"[\s-]+")
_ASCII_DIGITS_RE = re.compile(r"^[0-9]+$")
_ISO_DATE_RE = re.compile(r"^([0-9]{4})[-/]([0-9]{2})[-/]([0-9]{2})$")
_DMY_DATE_RE = re.compile(r"^([0-9]{2})[-/]([0-9]{2})[-/]([0-9]{4})$")
_CLASS_PREFIX_RE = re.compile(r"^(?:(?:GOL\.?\s*)?SIM\s*[:\-]?\s*)+")

_LEGACY_MIN_LEN = 12
_LEGACY_MAX_LEN = 14
_NIK_LINKED_LEN = 16
_MINIMUM_DRIVING_AGE = 17


class SimClass(StrEnum):
    """Indonesian driver's license (SIM) classes under Perpol No. 5/2021."""

    A = "A"
    A_UMUM = "A UMUM"
    BI = "BI"
    BI_UMUM = "BI UMUM"
    BII = "BII"
    BII_UMUM = "BII UMUM"
    C = "C"
    CI = "CI"
    CII = "CII"
    D = "D"
    DI = "DI"


_SIM_CLASS_ALIASES: dict[str, SimClass] = {
    "A": SimClass.A,
    "A UMUM": SimClass.A_UMUM,
    "BI": SimClass.BI,
    "B I": SimClass.BI,
    "B1": SimClass.BI,
    "B 1": SimClass.BI,
    "BI UMUM": SimClass.BI_UMUM,
    "B I UMUM": SimClass.BI_UMUM,
    "B1 UMUM": SimClass.BI_UMUM,
    "B 1 UMUM": SimClass.BI_UMUM,
    "BII": SimClass.BII,
    "B II": SimClass.BII,
    "B2": SimClass.BII,
    "B 2": SimClass.BII,
    "BII UMUM": SimClass.BII_UMUM,
    "B II UMUM": SimClass.BII_UMUM,
    "B2 UMUM": SimClass.BII_UMUM,
    "B 2 UMUM": SimClass.BII_UMUM,
    "C": SimClass.C,
    "CI": SimClass.CI,
    "C I": SimClass.CI,
    "C1": SimClass.CI,
    "C 1": SimClass.CI,
    "CII": SimClass.CII,
    "C II": SimClass.CII,
    "C2": SimClass.CII,
    "C 2": SimClass.CII,
    "D": SimClass.D,
    "DI": SimClass.DI,
    "D I": SimClass.DI,
    "D1": SimClass.DI,
    "D 1": SimClass.DI,
}


def clean_sim_number(sim_number: str) -> str:
    """Strip surrounding whitespace and internal spaces/hyphens from a SIM number."""
    return _SEPARATOR_RE.sub("", sim_number.strip())


def normalize_sim_class(raw_class: str) -> SimClass | None:
    """Normalize OCR variations of Indonesian SIM classes to canonical SimClass values."""
    collapsed = " ".join(raw_class.strip().upper().replace("-", " ").split())
    if not collapsed:
        return None
    stripped = _CLASS_PREFIX_RE.sub("", collapsed).strip()
    return _SIM_CLASS_ALIASES.get(stripped)


def _parse_date_string(raw_date: str) -> date | None:
    """Parse a date string in YYYY-MM-DD, YYYY/MM/DD, DD-MM-YYYY, or DD/MM/YYYY format."""
    text = raw_date.strip()
    if not text:
        return None

    iso_match = _ISO_DATE_RE.match(text)
    if iso_match:
        year, month, day = (int(part) for part in iso_match.groups())
    else:
        dmy_match = _DMY_DATE_RE.match(text)
        if not dmy_match:
            return None
        day, month, year = (int(part) for part in dmy_match.groups())

    try:
        return date(year, month, day)
    except ValueError:
        return None


def _calculate_age(birth_date: date, reference_date: date) -> int:
    """Compute completed calendar years between birth_date and reference_date."""
    had_birthday = (reference_date.month, reference_date.day) >= (birth_date.month, birth_date.day)
    return reference_date.year - birth_date.year - (0 if had_birthday else 1)


def _check_sim_number(
    sim_number: str | None,
    *,
    date_of_birth: str | None,
    gender: str | None,
    reference_year: int,
) -> list[ValidationCheck]:
    """Validate SIM number length/format and cross-check 16-digit NIK-linked SIMs."""
    if sim_number is None or not sim_number.strip():
        return [
            ValidationCheck(
                name="sim_number_format_valid",
                passed=False,
                message="SIM number is missing or empty.",
            )
        ]

    cleaned = clean_sim_number(sim_number)
    if not _ASCII_DIGITS_RE.match(cleaned):
        return [
            ValidationCheck(
                name="sim_number_format_valid",
                passed=False,
                message="SIM number must contain only ASCII digits (after stripping separators).",
            )
        ]

    length = len(cleaned)
    if _LEGACY_MIN_LEN <= length <= _LEGACY_MAX_LEN:
        return [
            ValidationCheck(
                name="sim_number_format_valid",
                passed=True,
                message=f"Valid legacy {length}-digit SIM number format.",
            )
        ]

    if length == _NIK_LINKED_LEN:
        checks: list[ValidationCheck] = [
            ValidationCheck(
                name="sim_number_format_valid",
                passed=True,
                message="Valid 16-digit NIK-linked SIM number format.",
            )
        ]
        nik_checks = validate_nik(
            cleaned,
            extracted_dob=date_of_birth,
            extracted_gender=gender,
            reference_year=reference_year,
        )
        failed_nik_checks = [check for check in nik_checks if not check.passed]
        if not failed_nik_checks:
            parsed_dob = _parse_date_string(date_of_birth) if date_of_birth else None
            parsed = parse_nik(
                cleaned,
                reference_year=reference_year,
                expected_dob=parsed_dob,
            )
            detail = (
                f" ({parsed.birth_date.isoformat()}, {parsed.gender})" if parsed is not None else ""
            )
            checks.append(
                ValidationCheck(
                    name="sim_nik_cross_check",
                    passed=True,
                    message=f"16-digit SIM number matches valid NIK rules{detail}.",
                )
            )
        else:
            reasons = "; ".join(check.message for check in failed_nik_checks if check.message)
            checks.append(
                ValidationCheck(
                    name="sim_nik_cross_check",
                    passed=False,
                    message=f"16-digit SIM NIK cross-check failed: {reasons}",
                )
            )
        return checks

    return [
        ValidationCheck(
            name="sim_number_format_valid",
            passed=False,
            message=(
                f"SIM number must be 12-14 digits (legacy) or 16 digits (NIK-linked), "
                f"got {length} digits."
            ),
        )
    ]


def _check_sim_class(sim_class: str | None) -> ValidationCheck:
    """Validate that the extracted SIM class maps to a Perpol No. 5/2021 class."""
    if sim_class is None or not sim_class.strip():
        return ValidationCheck(
            name="sim_class_valid",
            passed=False,
            message="SIM class is missing or empty.",
        )

    canonical = normalize_sim_class(sim_class)
    if canonical is not None:
        return ValidationCheck(
            name="sim_class_valid",
            passed=True,
            message=f"Valid SIM class '{canonical.value}'.",
        )

    return ValidationCheck(
        name="sim_class_valid",
        passed=False,
        message=f"Unrecognized SIM class '{sim_class}'.",
    )


def _check_not_expired(valid_until: str | None, reference_date: date) -> ValidationCheck:
    """Validate that the SIM expiration date is parseable and not before reference_date."""
    if valid_until is None or not valid_until.strip():
        return ValidationCheck(
            name="sim_not_expired",
            passed=False,
            message="SIM expiration date (valid_until) is missing or empty.",
        )

    expiry_date = _parse_date_string(valid_until)
    if expiry_date is None:
        return ValidationCheck(
            name="sim_not_expired",
            passed=False,
            message=f"Invalid SIM expiration date '{valid_until}'.",
        )

    if expiry_date >= reference_date:
        return ValidationCheck(
            name="sim_not_expired",
            passed=True,
            message=f"SIM is active until {expiry_date.isoformat()}.",
        )

    return ValidationCheck(
        name="sim_not_expired",
        passed=False,
        message=(
            f"SIM expired on {expiry_date.isoformat()} "
            f"(reference date {reference_date.isoformat()})."
        ),
    )


def _check_minimum_age(date_of_birth: str, reference_date: date) -> ValidationCheck:
    """Validate that the license holder is at least 17 years old."""
    dob = _parse_date_string(date_of_birth)
    if dob is None:
        return ValidationCheck(
            name="sim_minimum_age_valid",
            passed=False,
            message=f"Invalid date_of_birth '{date_of_birth}'.",
        )

    age = _calculate_age(dob, reference_date)
    if age >= _MINIMUM_DRIVING_AGE:
        return ValidationCheck(
            name="sim_minimum_age_valid",
            passed=True,
            message=f"Holder age ({age}) meets minimum driving age ({_MINIMUM_DRIVING_AGE}).",
        )

    return ValidationCheck(
        name="sim_minimum_age_valid",
        passed=False,
        message=f"Holder age ({age}) is below minimum driving age ({_MINIMUM_DRIVING_AGE}).",
    )


def validate_sim(
    sim_number: str | None,
    *,
    sim_class: str | None = None,
    valid_until: str | None = None,
    date_of_birth: str | None = None,
    gender: str | None = None,
    reference_date: date | None = None,
) -> list[ValidationCheck]:
    """Validate extracted Indonesian SIM fields using deterministic rules."""
    ref_date = reference_date if reference_date is not None else date.today()
    checks: list[ValidationCheck] = []

    checks.extend(
        _check_sim_number(
            sim_number,
            date_of_birth=date_of_birth,
            gender=gender,
            reference_year=ref_date.year,
        )
    )
    checks.append(_check_sim_class(sim_class))
    checks.append(_check_not_expired(valid_until, ref_date))

    if date_of_birth is not None and date_of_birth.strip():
        checks.append(_check_minimum_age(date_of_birth, ref_date))

    return checks


__all__ = [
    "SimClass",
    "clean_sim_number",
    "normalize_sim_class",
    "validate_sim",
]
