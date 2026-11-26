"""Deterministic Indonesian NIK (Nomor Induk Kependudukan) parser and validator.

Reusable across Indonesian identity document plugins (e-KTP, SIM, NPWP).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.domain.schemas import ValidationCheck
from app.plugins.idn.province_codes import PROVINCE_NAMES, VALID_PROVINCE_CODES

NikGender = Literal["LAKI-LAKI", "PEREMPUAN"]

_NIK_DIGITS_RE = re.compile(r"^[0-9]{16}$")
_SEPARATOR_RE = re.compile(r"[\s-]+")
_ISO_DATE_RE = re.compile(r"^([0-9]{4})[-/]([0-9]{2})[-/]([0-9]{2})$")
_DMY_DATE_RE = re.compile(r"^([0-9]{2})[-/]([0-9]{2})[-/]([0-9]{4})$")

_MALE_ALIASES: frozenset[str] = frozenset(
    {"LAKI-LAKI", "LAKI LAKI", "LAKILAKI", "L", "M", "MALE", "PRIA"}
)
_FEMALE_ALIASES: frozenset[str] = frozenset({"PEREMPUAN", "P", "F", "FEMALE", "WANITA"})

_FEMALE_DAY_OFFSET = 40


@dataclass(frozen=True, slots=True)
class ParsedNik:
    """Structured components decoded from a valid 16-digit Indonesian NIK."""

    province_code: str
    regency_code: str
    district_code: str
    birth_date: date
    gender: NikGender
    serial: str


def _clean_nik(nik: str) -> str:
    """Strip surrounding whitespace and internal spaces/hyphens from a raw NIK string."""
    return _SEPARATOR_RE.sub("", nik.strip())


def _parse_dob_string(raw_dob: str) -> date | None:
    """Parse an extracted DOB string in YYYY-MM-DD or DD-MM-YYYY format."""
    text = raw_dob.strip()
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


def normalize_gender(raw_gender: str) -> NikGender | None:
    """Normalize common Indonesian/English gender strings to LAKI-LAKI or PEREMPUAN."""
    normalized = " ".join(raw_gender.strip().upper().split())
    if normalized in _MALE_ALIASES:
        return "LAKI-LAKI"
    if normalized in _FEMALE_ALIASES:
        return "PEREMPUAN"
    return None


def _resolve_century(yy: int, *, reference_year: int | None, expected_dob: date | None) -> int:
    """Resolve a 2-digit NIK birth year to a 4-digit calendar year."""
    if expected_dob is not None and expected_dob.year % 100 == yy:
        return expected_dob.year

    ref_year = reference_year if reference_year is not None else date.today().year
    cutoff = ref_year % 100
    return (2000 + yy) if yy <= cutoff else (1900 + yy)


def _decode_nik_dob_and_gender(
    ddmmyy: str,
    *,
    reference_year: int | None = None,
    expected_dob: date | None = None,
) -> tuple[date, NikGender] | None:
    """Decode DDMMYY from NIK digits 6..12, handling the female +40 day rule."""
    raw_day = int(ddmmyy[0:2])
    month = int(ddmmyy[2:4])
    yy = int(ddmmyy[4:6])

    if raw_day > _FEMALE_DAY_OFFSET:
        day = raw_day - _FEMALE_DAY_OFFSET
        gender: NikGender = "PEREMPUAN"
    else:
        day = raw_day
        gender = "LAKI-LAKI"

    year = _resolve_century(yy, reference_year=reference_year, expected_dob=expected_dob)
    try:
        return date(year, month, day), gender
    except ValueError:
        return None


def parse_nik(
    nik: str,
    *,
    reference_year: int | None = None,
    expected_dob: date | None = None,
) -> ParsedNik | None:
    """Parse a 16-digit Indonesian NIK into structured fields, or return None if invalid."""
    if not nik:
        return None

    cleaned = _clean_nik(nik)
    if not _NIK_DIGITS_RE.match(cleaned):
        return None

    province_code = cleaned[0:2]
    if province_code not in VALID_PROVINCE_CODES:
        return None

    decoded = _decode_nik_dob_and_gender(
        cleaned[6:12],
        reference_year=reference_year,
        expected_dob=expected_dob,
    )
    if decoded is None:
        return None

    birth_date, gender = decoded
    return ParsedNik(
        province_code=province_code,
        regency_code=cleaned[2:4],
        district_code=cleaned[4:6],
        birth_date=birth_date,
        gender=gender,
        serial=cleaned[12:16],
    )


def validate_nik(
    nik: str | None,
    *,
    extracted_dob: str | None = None,
    extracted_gender: str | None = None,
    reference_year: int | None = None,
) -> list[ValidationCheck]:
    """Validate an Indonesian NIK and cross-check against extracted DOB and gender."""
    if nik is None or not nik.strip():
        return [
            ValidationCheck(
                name="nik_format_16_digits",
                passed=False,
                message="NIK is missing or empty.",
            )
        ]

    cleaned = _clean_nik(nik)
    if not _NIK_DIGITS_RE.match(cleaned):
        return [
            ValidationCheck(
                name="nik_format_16_digits",
                passed=False,
                message=(
                    f"NIK must contain exactly 16 ASCII digits (got {len(cleaned)} characters)."
                ),
            )
        ]

    checks: list[ValidationCheck] = [
        ValidationCheck(
            name="nik_format_16_digits",
            passed=True,
            message="NIK has valid 16-digit format.",
        )
    ]

    province_code = cleaned[0:2]
    if province_code in VALID_PROVINCE_CODES:
        checks.append(
            ValidationCheck(
                name="nik_province_code_valid",
                passed=True,
                message=f"Valid province code '{province_code}' ({PROVINCE_NAMES[province_code]}).",
            )
        )
    else:
        checks.append(
            ValidationCheck(
                name="nik_province_code_valid",
                passed=False,
                message=f"Unknown Indonesian province code '{province_code}'.",
            )
        )

    parsed_extracted_dob = _parse_dob_string(extracted_dob) if extracted_dob else None
    ddmmyy = cleaned[6:12]
    decoded = _decode_nik_dob_and_gender(
        ddmmyy,
        reference_year=reference_year,
        expected_dob=parsed_extracted_dob,
    )

    if decoded is not None:
        nik_birth_date, nik_gender = decoded
        checks.append(
            ValidationCheck(
                name="nik_date_valid",
                passed=True,
                message=f"Valid NIK birth date ({nik_birth_date.isoformat()}, {nik_gender}).",
            )
        )
    else:
        nik_birth_date = None
        nik_gender = None
        checks.append(
            ValidationCheck(
                name="nik_date_valid",
                passed=False,
                message=f"Invalid calendar date encoded in NIK ('{ddmmyy}').",
            )
        )

    if extracted_dob is not None and extracted_dob.strip():
        if parsed_extracted_dob is None:
            checks.append(
                ValidationCheck(
                    name="nik_dob_matches_extracted",
                    passed=False,
                    message=f"Extracted date_of_birth '{extracted_dob}' is not a valid date.",
                )
            )
        elif nik_birth_date is None:
            checks.append(
                ValidationCheck(
                    name="nik_dob_matches_extracted",
                    passed=False,
                    message="Cannot compare DOB because NIK birth date is invalid.",
                )
            )
        elif nik_birth_date == parsed_extracted_dob:
            checks.append(
                ValidationCheck(
                    name="nik_dob_matches_extracted",
                    passed=True,
                    message="NIK birth date matches extracted date_of_birth.",
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    name="nik_dob_matches_extracted",
                    passed=False,
                    message=(
                        f"NIK birth date ({nik_birth_date.isoformat()}) does not match "
                        f"extracted date_of_birth ({parsed_extracted_dob.isoformat()})."
                    ),
                )
            )

    if extracted_gender is not None and extracted_gender.strip():
        normalized_gender = normalize_gender(extracted_gender)
        if normalized_gender is None:
            checks.append(
                ValidationCheck(
                    name="nik_gender_matches_extracted",
                    passed=False,
                    message=f"Unrecognized extracted gender '{extracted_gender}'.",
                )
            )
        elif nik_gender is None:
            checks.append(
                ValidationCheck(
                    name="nik_gender_matches_extracted",
                    passed=False,
                    message="Cannot compare gender because NIK birth date is invalid.",
                )
            )
        elif nik_gender == normalized_gender:
            checks.append(
                ValidationCheck(
                    name="nik_gender_matches_extracted",
                    passed=True,
                    message=f"NIK gender ({nik_gender}) matches extracted gender.",
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    name="nik_gender_matches_extracted",
                    passed=False,
                    message=(
                        f"NIK gender ({nik_gender}) does not match "
                        f"extracted gender ({normalized_gender})."
                    ),
                )
            )

    return checks


__all__ = ["NikGender", "ParsedNik", "normalize_gender", "parse_nik", "validate_nik"]
