"""Indonesian Taxpayer Identification Number (NPWP) document plugin."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.schemas import (
    ClassificationRule,
    ExtractedField,
    OcrResult,
    ValidationCheck,
    ValidationResult,
)
from app.plugins.idn.npwp_validator import (
    extract_kpp_code,
    normalize_npwp_15,
    normalize_npwp_16,
    validate_npwp,
)

_DMY_RE = re.compile(r"^([0-9]{2})[-/]([0-9]{2})[-/]([0-9]{4})$")
_YMD_RE = re.compile(r"^([0-9]{4})[-/]([0-9]{2})[-/]([0-9]{2})$")
_OFFLINE_NPWP_15_FORMATTED_RE = re.compile(
    r"(?<!\d)([0-9]{2}\.[0-9]{3}\.[0-9]{3}\.[0-9]-[0-9]{3}\.[0-9]{3})(?!\d)"
)
_OFFLINE_NPWP_15_PLAIN_RE = re.compile(r"(?<!\d)([0-9]{15})(?!\d)")
_OFFLINE_NPWP_16_FORMATTED_RE = re.compile(
    r"(?<!\d)([0-9]{4}[\s.\-][0-9]{4}[\s.\-][0-9]{4}[\s.\-][0-9]{4})(?!\d)"
)
_OFFLINE_NPWP_16_PLAIN_RE = re.compile(r"(?<!\d)([0-9]{16})(?!\d)")
_OFFLINE_KPP_NAME_RE = re.compile(
    r"(KPP\s+(?:PRATAMA|MADYA|WAJIB\s+PAJAK\s+BESAR|KHUSUS)[^\n]*)",
    re.IGNORECASE,
)
_OFFLINE_REGISTERED_DATE_RE = re.compile(
    r"TERDAFTAR\s*[:\-]?\s*([0-9]{2}[-/][0-9]{2}[-/][0-9]{4}|[0-9]{4}[-/][0-9]{2}[-/][0-9]{2})",
    re.IGNORECASE,
)


def _empty_str_field() -> ExtractedField[str]:
    """Return an empty ExtractedField[str] instance for Pydantic default_factory."""
    return ExtractedField[str]()


def _normalize_date_value(raw: str) -> str:
    """Normalize DD-MM-YYYY, DD/MM/YYYY, or YYYY/MM/DD dates to ISO YYYY-MM-DD."""
    text = raw.strip()
    if not text:
        return text

    ymd_match = _YMD_RE.match(text)
    if ymd_match:
        year, month, day = (int(part) for part in ymd_match.groups())
    else:
        dmy_match = _DMY_RE.match(text)
        if not dmy_match:
            return text
        day, month, year = (int(part) for part in dmy_match.groups())

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return text


class NpwpData(BaseModel):
    """Structured fields extracted from an Indonesian NPWP card."""

    npwp_15: ExtractedField[str] = Field(default_factory=_empty_str_field)
    npwp_16: ExtractedField[str] = Field(default_factory=_empty_str_field)
    taxpayer_name: ExtractedField[str] = Field(default_factory=_empty_str_field)
    address: ExtractedField[str] = Field(default_factory=_empty_str_field)
    kpp_name: ExtractedField[str] = Field(default_factory=_empty_str_field)
    kpp_code: ExtractedField[str] = Field(default_factory=_empty_str_field)
    registered_date: ExtractedField[str] = Field(default_factory=_empty_str_field)

    @field_validator("npwp_15")
    @classmethod
    def _normalize_npwp_15_field(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        if not trimmed:
            return field.model_copy(update={"value": None})
        normalized = normalize_npwp_15(trimmed)
        return field.model_copy(update={"value": normalized if normalized is not None else trimmed})

    @field_validator("npwp_16")
    @classmethod
    def _normalize_npwp_16_field(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        if not trimmed:
            return field.model_copy(update={"value": None})
        normalized = normalize_npwp_16(trimmed)
        return field.model_copy(update={"value": normalized if normalized is not None else trimmed})

    @field_validator("registered_date")
    @classmethod
    def _normalize_registered_date(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        if not trimmed:
            return field.model_copy(update={"value": None})
        return field.model_copy(update={"value": _normalize_date_value(trimmed)})

    @field_validator("kpp_code")
    @classmethod
    def _normalize_kpp_code(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        return field.model_copy(update={"value": trimmed or None})

    @model_validator(mode="after")
    def _populate_kpp_code_from_npwp_15(self) -> NpwpData:
        if self.kpp_code.value is None and self.npwp_15.value is not None:
            extracted = extract_kpp_code(self.npwp_15.value)
            if extracted is not None:
                self.kpp_code = ExtractedField[str](
                    value=extracted,
                    confidence=self.npwp_15.confidence,
                    source=self.npwp_15.source,
                )
        return self


class IndonesiaNpwpPlugin:
    """DocumentPlugin implementation for Indonesian NPWP (IDN/NPWP)."""

    country_code: str = "IDN"
    doc_type: str = "NPWP"
    description: str = "Indonesian Taxpayer Identification Number Card (NPWP)"
    schema_model: type[BaseModel] = NpwpData

    _CLASSIFICATION_RULES: tuple[ClassificationRule, ...] = (
        ClassificationRule(keyword="NPWP", weight=2.5, required=True),
        ClassificationRule(keyword="NOMOR POKOK WAJIB PAJAK", weight=2.5),
        ClassificationRule(keyword="DIREKTORAT JENDERAL PAJAK", weight=2.0),
        ClassificationRule(keyword="KEMENTERIAN KEUANGAN", weight=1.5),
        ClassificationRule(keyword="KPP PRATAMA", weight=1.5),
        ClassificationRule(keyword="TERDAFTAR", weight=1.0),
    )

    @property
    def classification_rules(self) -> Sequence[ClassificationRule]:
        """Return weighted OCR keyword rules identifying an Indonesian NPWP card."""
        return self._CLASSIFICATION_RULES

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        """Build an NPWP-tailored extraction prompt for structured LLM parsing."""
        instructions = [
            "Extract structured fields from this Indonesian NPWP (Nomor Pokok Wajib Pajak) card.",
            "Follow these rules strictly:",
            "- Return valid JSON matching the NpwpData schema.",
            "- Never hallucinate or guess missing values; if a field is missing, '-', "
            "or illegible, set value to null and confidence to 0.0.",
            "- Support both legacy 15-digit NPWP cards (format XX.XXX.XXX.X-XXX.XXX -> npwp_15) "
            "and newer dual-number cards displaying both NPWP16 (16-digit NIK-based individual "
            "or 0-prefixed corporate number -> npwp_16) and NPWP15 (-> npwp_15).",
            "- Normalize npwp_15 to 'XX.XXX.XXX.X-XXX.XXX' and npwp_16 to 16 digits.",
            "- Extract the 'TERDAFTAR' registration date into registered_date in ISO YYYY-MM-DD.",
            "- Extract the tax office header (e.g. 'KPP PRATAMA JAKARTA SETIABUDI SATU') "
            "into kpp_name, and the 3-digit KPP code (digits 10-12 of npwp_15) into kpp_code.",
            "- Normalize textual fields (taxpayer_name, address, kpp_name) to UPPERCASE.",
        ]

        if ocr_result is not None:
            if ocr_result.lines:
                ocr_block = "\n".join(
                    f"- [{line.confidence:.2f}] {line.text}" for line in ocr_result.lines
                )
            else:
                ocr_block = ocr_result.raw_text.strip()

            if ocr_block:
                instructions.append("\nOCR Output:\n" + ocr_block)

        return "\n".join(instructions)

    def validate(self, data: BaseModel) -> ValidationResult:
        """Validate extracted NPWP data using deterministic 15/16-digit NPWP rules."""
        if not isinstance(data, NpwpData):
            return ValidationResult(
                is_valid=False,
                checks=[
                    ValidationCheck(
                        name="npwp_schema_type",
                        passed=False,
                        message=f"Expected NpwpData instance, got {type(data).__name__}.",
                    )
                ],
            )

        checks = validate_npwp(data)
        return ValidationResult(
            is_valid=all(check.passed for check in checks),
            checks=checks,
        )

    def offline_parse(self, ocr_result: OcrResult) -> NpwpData:
        """Deterministic regex fallback parser when no LLM is available."""
        text = ocr_result.raw_text or "\n".join(line.text for line in ocr_result.lines)

        npwp_15_field = _empty_str_field()
        npwp_15_match = _OFFLINE_NPWP_15_FORMATTED_RE.search(
            text
        ) or _OFFLINE_NPWP_15_PLAIN_RE.search(text)
        if npwp_15_match:
            npwp_15_field = ExtractedField[str](
                value=npwp_15_match.group(1),
                confidence=0.7,
                source="ocr_offline",
            )

        npwp_16_field = _empty_str_field()
        npwp_16_match = _OFFLINE_NPWP_16_FORMATTED_RE.search(
            text
        ) or _OFFLINE_NPWP_16_PLAIN_RE.search(text)
        if npwp_16_match:
            npwp_16_field = ExtractedField[str](
                value=npwp_16_match.group(1),
                confidence=0.7,
                source="ocr_offline",
            )

        kpp_name_field = _empty_str_field()
        kpp_name_match = _OFFLINE_KPP_NAME_RE.search(text)
        if kpp_name_match:
            kpp_name_field = ExtractedField[str](
                value=" ".join(kpp_name_match.group(1).strip().split()).upper(),
                confidence=0.65,
                source="ocr_offline",
            )

        registered_date_field = _empty_str_field()
        date_match = _OFFLINE_REGISTERED_DATE_RE.search(text)
        if date_match:
            registered_date_field = ExtractedField[str](
                value=date_match.group(1),
                confidence=0.65,
                source="ocr_offline",
            )

        return NpwpData(
            npwp_15=npwp_15_field,
            npwp_16=npwp_16_field,
            kpp_name=kpp_name_field,
            registered_date=registered_date_field,
        )


__all__ = ["IndonesiaNpwpPlugin", "NpwpData"]
