"""Indonesian Electronic National Identity Card (e-KTP) document plugin."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.domain.schemas import (
    ClassificationRule,
    ExtractedField,
    OcrResult,
    ValidationCheck,
    ValidationResult,
)
from app.plugins.idn.nik_validator import normalize_gender, validate_nik

_RT_RW_RE = re.compile(r"^\s*([0-9]{1,3})\s*[/\-]\s*([0-9]{1,3})\s*$")
_DMY_RE = re.compile(r"^([0-9]{2})[-/]([0-9]{2})[-/]([0-9]{4})$")
_YMD_RE = re.compile(r"^([0-9]{4})[-/]([0-9]{2})[-/]([0-9]{2})$")
_OFFLINE_NIK_RE = re.compile(r"(?<!\d)([0-9]{16})(?!\d)")
_OFFLINE_RT_RW_RE = re.compile(r"\b([0-9]{1,3}\s*/\s*[0-9]{1,3})\b")
_OFFLINE_DOB_RE = re.compile(r"\b([0-9]{2}[-/][0-9]{2}[-/][0-9]{4})\b")


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


class KtpAddress(BaseModel):
    """Structured Indonesian residential address extracted from an e-KTP."""

    street: ExtractedField[str] = Field(default_factory=_empty_str_field)
    rt_rw: ExtractedField[str] = Field(default_factory=_empty_str_field)
    kelurahan_desa: ExtractedField[str] = Field(default_factory=_empty_str_field)
    kecamatan: ExtractedField[str] = Field(default_factory=_empty_str_field)
    city_regency: ExtractedField[str] = Field(default_factory=_empty_str_field)
    province: ExtractedField[str] = Field(default_factory=_empty_str_field)

    @field_validator("rt_rw")
    @classmethod
    def _normalize_rt_rw(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        if not trimmed:
            return field.model_copy(update={"value": None})
        match = _RT_RW_RE.match(trimmed)
        if match:
            rt, rw = match.groups()
            return field.model_copy(update={"value": f"{int(rt):03d}/{int(rw):03d}"})
        return field.model_copy(update={"value": trimmed})


class KtpData(BaseModel):
    """Structured fields extracted from an Indonesian e-KTP."""

    nik: ExtractedField[str] = Field(default_factory=_empty_str_field)
    full_name: ExtractedField[str] = Field(default_factory=_empty_str_field)
    place_of_birth: ExtractedField[str] = Field(default_factory=_empty_str_field)
    date_of_birth: ExtractedField[str] = Field(default_factory=_empty_str_field)
    gender: ExtractedField[str] = Field(default_factory=_empty_str_field)
    blood_type: ExtractedField[str] = Field(default_factory=_empty_str_field)
    address: KtpAddress = Field(default_factory=KtpAddress)
    religion: ExtractedField[str] = Field(default_factory=_empty_str_field)
    marital_status: ExtractedField[str] = Field(default_factory=_empty_str_field)
    occupation: ExtractedField[str] = Field(default_factory=_empty_str_field)
    nationality: ExtractedField[str] = Field(default_factory=_empty_str_field)
    valid_until: ExtractedField[str] = Field(default_factory=_empty_str_field)

    @field_validator("nik")
    @classmethod
    def _normalize_nik(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        return field.model_copy(update={"value": trimmed or None})

    @field_validator("date_of_birth")
    @classmethod
    def _normalize_date_of_birth(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        if not trimmed:
            return field.model_copy(update={"value": None})
        return field.model_copy(update={"value": _normalize_date_value(trimmed)})

    @field_validator("gender")
    @classmethod
    def _normalize_gender(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        if not trimmed:
            return field.model_copy(update={"value": None})
        normalized = normalize_gender(trimmed)
        if normalized is not None:
            return field.model_copy(update={"value": normalized})
        return field.model_copy(update={"value": trimmed.upper()})

    @field_validator("valid_until")
    @classmethod
    def _normalize_valid_until(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        collapsed = " ".join(field.value.strip().split())
        if not collapsed:
            return field.model_copy(update={"value": None})
        upper = collapsed.upper()
        if upper == "SEUMUR HIDUP":
            return field.model_copy(update={"value": "SEUMUR HIDUP"})
        return field.model_copy(update={"value": _normalize_date_value(upper)})


class IndonesiaKtpPlugin:
    """DocumentPlugin implementation for Indonesian e-KTP (IDN/KTP)."""

    country_code: str = "IDN"
    doc_type: str = "KTP"
    description: str = "Indonesian Electronic National Identity Card (e-KTP)"
    schema_model: type[BaseModel] = KtpData

    _CLASSIFICATION_RULES: tuple[ClassificationRule, ...] = (
        ClassificationRule(keyword="NIK", weight=2.0, required=True),
        ClassificationRule(keyword="KARTU TANDA PENDUDUK", weight=2.5),
        ClassificationRule(keyword="PROVINSI", weight=1.5),
        ClassificationRule(keyword="GOL. DARAH", weight=1.5),
        ClassificationRule(keyword="KEWARGANEGARAAN", weight=1.5),
        ClassificationRule(keyword="BERLAKU HINGGA", weight=1.5),
        ClassificationRule(keyword="SEUMUR HIDUP", weight=1.5),
        ClassificationRule(keyword="RT/RW", weight=1.5),
    )

    @property
    def classification_rules(self) -> Sequence[ClassificationRule]:
        """Return weighted OCR keyword rules identifying an Indonesian e-KTP."""
        return self._CLASSIFICATION_RULES

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        """Build an e-KTP-tailored extraction prompt for structured LLM parsing."""
        instructions = [
            "Extract structured fields from this Indonesian e-KTP (Kartu Tanda Penduduk).",
            "Follow these rules strictly:",
            "- Return valid JSON matching the KtpData schema.",
            "- Never hallucinate or guess missing values; if a field is missing, '-', "
            "or illegible, set value to null and confidence to 0.0.",
            "- Split combined 'TEMPAT/TGL LAHIR' lines (e.g. 'JAKARTA, 17-08-1995') "
            "into place_of_birth ('JAKARTA') and date_of_birth ('1995-08-17' in YYYY-MM-DD).",
            "- Normalize gender to 'LAKI-LAKI' or 'PEREMPUAN'.",
            "- Handle 'GOL. DARAH' carefully: if '-' or absent, set value to null; "
            "do not confuse 'O' with '0'.",
            "- Format address.rt_rw as 'XXX/XXX' (e.g. '001/002').",
            "- Keep 'BERLAKU HINGGA' as 'SEUMUR HIDUP' when lifetime validity is shown.",
            "- Normalize textual fields (full_name, place_of_birth, address fields, "
            "religion, marital_status, occupation, nationality) to UPPERCASE.",
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
        """Validate extracted e-KTP data using deterministic Indonesian NIK rules."""
        if not isinstance(data, KtpData):
            return ValidationResult(
                is_valid=False,
                checks=[
                    ValidationCheck(
                        name="ktp_schema_type",
                        passed=False,
                        message=f"Expected KtpData instance, got {type(data).__name__}.",
                    )
                ],
            )

        checks = validate_nik(
            data.nik.value,
            extracted_dob=data.date_of_birth.value,
            extracted_gender=data.gender.value,
        )
        return ValidationResult(
            is_valid=all(check.passed for check in checks),
            checks=checks,
        )

    def offline_parse(self, ocr_result: OcrResult) -> KtpData:
        """Deterministic regex fallback parser when no LLM is available."""
        text = ocr_result.raw_text or "\n".join(line.text for line in ocr_result.lines)
        upper_text = text.upper()

        nik_field = _empty_str_field()
        nik_match = _OFFLINE_NIK_RE.search(text)
        if nik_match:
            nik_field = ExtractedField[str](
                value=nik_match.group(1),
                confidence=0.7,
                source="ocr_offline",
            )

        dob_field = _empty_str_field()
        dob_match = _OFFLINE_DOB_RE.search(text)
        if dob_match:
            dob_field = ExtractedField[str](
                value=dob_match.group(1),
                confidence=0.6,
                source="ocr_offline",
            )

        gender_field = _empty_str_field()
        if "LAKI-LAKI" in upper_text or "LAKI LAKI" in upper_text:
            gender_field = ExtractedField[str](
                value="LAKI-LAKI",
                confidence=0.7,
                source="ocr_offline",
            )
        elif "PEREMPUAN" in upper_text:
            gender_field = ExtractedField[str](
                value="PEREMPUAN",
                confidence=0.7,
                source="ocr_offline",
            )

        rt_rw_field = _empty_str_field()
        rt_rw_match = _OFFLINE_RT_RW_RE.search(text)
        if rt_rw_match:
            rt_rw_field = ExtractedField[str](
                value=rt_rw_match.group(1),
                confidence=0.6,
                source="ocr_offline",
            )

        valid_until_field = _empty_str_field()
        if "SEUMUR HIDUP" in upper_text:
            valid_until_field = ExtractedField[str](
                value="SEUMUR HIDUP",
                confidence=0.8,
                source="ocr_offline",
            )

        return KtpData(
            nik=nik_field,
            date_of_birth=dob_field,
            gender=gender_field,
            address=KtpAddress(rt_rw=rt_rw_field),
            valid_until=valid_until_field,
        )


__all__ = ["IndonesiaKtpPlugin", "KtpAddress", "KtpData"]
