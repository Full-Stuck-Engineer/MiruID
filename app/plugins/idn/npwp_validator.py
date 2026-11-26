"""Deterministic Indonesian NPWP (15-digit & 16-digit) parser and validator."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.domain.schemas import ValidationCheck
from app.plugins.idn.nik_validator import validate_nik

if TYPE_CHECKING:
    from app.plugins.idn.npwp import NpwpData

_PUNCTUATION_RE = re.compile(r"[\s.\-]+")
_NPWP_15_DIGITS_RE = re.compile(r"^[0-9]{15}$")
_NPWP_16_DIGITS_RE = re.compile(r"^[0-9]{16}$")


def _strip_npwp_punctuation(raw: str) -> str:
    """Strip whitespace, dots, and hyphens from a raw NPWP string."""
    return _PUNCTUATION_RE.sub("", raw.strip())


def normalize_npwp_15(raw: str) -> str | None:
    """Normalize a 15-digit NPWP string to canonical XX.XXX.XXX.X-XXX.XXX format.

    Returns None when the stripped value does not consist of exactly 15 ASCII digits.
    """
    if not raw:
        return None
    digits = _strip_npwp_punctuation(raw)
    if not _NPWP_15_DIGITS_RE.match(digits):
        return None
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:15]}"


def extract_kpp_code(npwp_15: str) -> str | None:
    """Extract the 3-digit KPP code (digits 10-12) from a valid 15-digit NPWP."""
    if not npwp_15:
        return None
    digits = _strip_npwp_punctuation(npwp_15)
    if not _NPWP_15_DIGITS_RE.match(digits):
        return None
    return digits[9:12]


def normalize_npwp_16(raw: str) -> str | None:
    """Normalize a 16-digit NPWP string to 16 contiguous ASCII digits.

    Returns None when the stripped value does not consist of exactly 16 ASCII digits.
    """
    if not raw:
        return None
    digits = _strip_npwp_punctuation(raw)
    if not _NPWP_16_DIGITS_RE.match(digits):
        return None
    return digits


def validate_npwp(data: NpwpData) -> list[ValidationCheck]:
    """Validate extracted Indonesian NPWP fields deterministically."""
    raw_15 = data.npwp_15.value.strip() if data.npwp_15.value else ""
    raw_16 = data.npwp_16.value.strip() if data.npwp_16.value else ""

    if not raw_15 and not raw_16:
        return [
            ValidationCheck(
                name="npwp_identifier_present",
                passed=False,
                message="At least one of npwp_15 or npwp_16 must be present.",
            )
        ]

    checks: list[ValidationCheck] = [
        ValidationCheck(
            name="npwp_identifier_present",
            passed=True,
            message="At least one NPWP identifier is present.",
        )
    ]

    digits_15: str | None = None
    if raw_15:
        canonical_15 = normalize_npwp_15(raw_15)
        if canonical_15 is not None:
            digits_15 = _strip_npwp_punctuation(canonical_15)
            checks.append(
                ValidationCheck(
                    name="npwp_15_format_valid",
                    passed=True,
                    message=f"Valid 15-digit NPWP format ({canonical_15}).",
                )
            )
        else:
            stripped_15 = _strip_npwp_punctuation(raw_15)
            checks.append(
                ValidationCheck(
                    name="npwp_15_format_valid",
                    passed=False,
                    message=(
                        "NPWP-15 must contain exactly 15 ASCII digits "
                        f"(got {len(stripped_15)} characters)."
                    ),
                )
            )

    digits_16: str | None = None
    if raw_16:
        normalized_16 = normalize_npwp_16(raw_16)
        if normalized_16 is None:
            stripped_16 = _strip_npwp_punctuation(raw_16)
            checks.append(
                ValidationCheck(
                    name="npwp_16_format_valid",
                    passed=False,
                    message=(
                        "NPWP-16 must contain exactly 16 ASCII digits "
                        f"(got {len(stripped_16)} characters)."
                    ),
                )
            )
        elif normalized_16.startswith("0"):
            digits_16 = normalized_16
            checks.append(
                ValidationCheck(
                    name="npwp_16_format_valid",
                    passed=True,
                    message=f"Valid 16-digit corporate/0-prefixed NPWP ({normalized_16}).",
                )
            )
        else:
            digits_16 = normalized_16
            nik_checks = validate_nik(normalized_16)
            failed_nik_checks = [check for check in nik_checks if not check.passed]
            if failed_nik_checks:
                reasons = "; ".join(check.message or check.name for check in failed_nik_checks)
                checks.append(
                    ValidationCheck(
                        name="npwp_16_format_valid",
                        passed=False,
                        message=f"Invalid 16-digit individual NIK-NPWP: {reasons}",
                    )
                )
            else:
                checks.append(
                    ValidationCheck(
                        name="npwp_16_format_valid",
                        passed=True,
                        message=f"Valid 16-digit individual NIK-NPWP ({normalized_16}).",
                    )
                )

    if digits_15 is not None and digits_16 is not None and digits_16.startswith("0"):
        expected_16 = f"0{digits_15}"
        if digits_16 == expected_16:
            checks.append(
                ValidationCheck(
                    name="npwp_15_16_consistency",
                    passed=True,
                    message="16-digit corporate NPWP matches '0' + 15-digit NPWP.",
                )
            )
        else:
            checks.append(
                ValidationCheck(
                    name="npwp_15_16_consistency",
                    passed=False,
                    message=(
                        f"16-digit corporate NPWP ({digits_16}) does not match "
                        f"'0' + 15-digit NPWP ({expected_16})."
                    ),
                )
            )

    return checks


__all__ = [
    "extract_kpp_code",
    "normalize_npwp_15",
    "normalize_npwp_16",
    "validate_npwp",
]
