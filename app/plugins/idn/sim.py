"""Indonesian Driver's License (SIM / Surat Izin Mengemudi) document plugin."""

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
from app.plugins.idn.nik_validator import normalize_gender
from app.plugins.idn.sim_validator import SimClass, normalize_sim_class, validate_sim

_DMY_RE = re.compile(r"^([0-9]{2})[-/]([0-9]{2})[-/]([0-9]{4})$")
_YMD_RE = re.compile(r"^([0-9]{4})[-/]([0-9]{2})[-/]([0-9]{2})$")
_OFFLINE_SIM_NUMBER_RE = re.compile(
    r"(?<!\d)(?:[0-9]{4}[-\s][0-9]{4}[-\s][0-9]{4}(?:[-\s][0-9]{4}|[0-9]{0,2})|[0-9]{16}|[0-9]{12,14})(?!\d)"
)
_OFFLINE_SIM_CLASS_RE = re.compile(
    r"\b(?:GOL\.?\s*SIM|SIM)\s*[:\-]?\s*"
    r"(B\s*(?:II|2|I|1)\s+UMUM|A\s+UMUM|B\s*(?:II|2|I|1)|C\s*(?:II|2|I|1)|D\s*(?:I|1)|[ACD])\b",
    re.IGNORECASE,
)
_OFFLINE_DATE_RE = re.compile(r"\b([0-9]{2}[-/][0-9]{2}[-/][0-9]{4})\b")


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


class SimData(BaseModel):
    """Structured fields extracted from an Indonesian Driver's License (SIM)."""

    sim_number: ExtractedField[str] = Field(default_factory=_empty_str_field)
    sim_class: ExtractedField[str] = Field(default_factory=_empty_str_field)
    full_name: ExtractedField[str] = Field(default_factory=_empty_str_field)
    place_of_birth: ExtractedField[str] = Field(default_factory=_empty_str_field)
    date_of_birth: ExtractedField[str] = Field(default_factory=_empty_str_field)
    blood_type: ExtractedField[str] = Field(default_factory=_empty_str_field)
    gender: ExtractedField[str] = Field(default_factory=_empty_str_field)
    address: ExtractedField[str] = Field(default_factory=_empty_str_field)
    occupation: ExtractedField[str] = Field(default_factory=_empty_str_field)
    issuing_office: ExtractedField[str] = Field(default_factory=_empty_str_field)
    valid_until: ExtractedField[str] = Field(default_factory=_empty_str_field)

    @field_validator("sim_number")
    @classmethod
    def _normalize_sim_number(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip()
        return field.model_copy(update={"value": trimmed or None})

    @field_validator("sim_class")
    @classmethod
    def _normalize_sim_class(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        collapsed = " ".join(field.value.strip().split())
        if not collapsed:
            return field.model_copy(update={"value": None})
        canonical = normalize_sim_class(collapsed)
        if canonical is not None:
            return field.model_copy(update={"value": canonical.value})
        return field.model_copy(update={"value": collapsed.upper()})

    @field_validator("date_of_birth", "valid_until")
    @classmethod
    def _normalize_dates(cls, field: ExtractedField[str]) -> ExtractedField[str]:
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

    @field_validator("blood_type")
    @classmethod
    def _normalize_blood_type(cls, field: ExtractedField[str]) -> ExtractedField[str]:
        if field.value is None:
            return field
        trimmed = field.value.strip().upper()
        if not trimmed or trimmed == "-":
            return field.model_copy(update={"value": None})
        return field.model_copy(update={"value": trimmed})


class IndonesiaSimPlugin:
    """DocumentPlugin implementation for Indonesian Driver's License (IDN/SIM)."""

    country_code: str = "IDN"
    doc_type: str = "SIM"
    description: str = "Indonesian Driver's License (SIM / Surat Izin Mengemudi)"
    schema_model: type[BaseModel] = SimData

    _CLASSIFICATION_RULES: tuple[ClassificationRule, ...] = (
        ClassificationRule(keyword="SURAT IZIN MENGEMUDI", weight=2.5),
        ClassificationRule(keyword="DRIVING LICENSE", weight=2.0),
        ClassificationRule(keyword="KEPOLISIAN NEGARA REPUBLIK INDONESIA", weight=2.0),
        ClassificationRule(keyword="POLRI", weight=1.5),
        ClassificationRule(keyword="SIM", weight=1.5),
        ClassificationRule(keyword="GOL. SIM", weight=1.5),
        ClassificationRule(keyword="BERLAKU S/D", weight=1.5),
    )

    @property
    def classification_rules(self) -> Sequence[ClassificationRule]:
        """Return weighted OCR keyword rules identifying an Indonesian SIM."""
        return self._CLASSIFICATION_RULES

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        """Build a SIM-tailored extraction prompt for structured LLM parsing."""
        instructions = [
            "Extract structured fields from this Indonesian Driver's License "
            "(SIM / Surat Izin Mengemudi).",
            "Follow these rules strictly:",
            "- Return valid JSON matching the SimData schema.",
            "- Never hallucinate or guess missing values; if a field is missing, '-', "
            "or illegible, set value to null and confidence to 0.0.",
            "- Smart SIM cards use numbered fields: "
            "1. Full Name, 2. Place and Date of Birth, 3. Blood Type and Gender "
            "(e.g. 'O - PRIA' or 'A - WANITA'), 4. Address, 5. Occupation, "
            "6. Issuing Office / Polda (e.g. 'METRO JAYA').",
            "- 2024+ NIK-based SIM cards use a 16-digit SIM number matching the holder's NIK "
            "and display vehicle icons (motorcycle, car, bus, truck) alongside the license class.",
            "- Preserve the SIM number digits (12-14 digits for legacy SIMs or 16 digits for "
            "2024+ NIK-linked SIMs).",
            "- Normalize sim_class to Perpol No. 5/2021 values: "
            "'A', 'A UMUM', 'BI', 'BI UMUM', 'BII', 'BII UMUM', 'C', 'CI', 'CII', 'D', or 'DI' "
            "(map OCR variants like 'B1'->'BI', 'B2'->'BII', 'C1'->'CI', 'C2'->'CII', 'D1'->'DI').",
            "- Split combined birth place and date lines into place_of_birth and "
            "date_of_birth (formatted as YYYY-MM-DD).",
            "- Format valid_until as YYYY-MM-DD.",
            "- Normalize gender to 'LAKI-LAKI' (from PRIA/M/L) or 'PEREMPUAN' (from WANITA/F/P).",
            "- Handle blood_type carefully: if '-' or absent, set value to null; "
            "do not confuse 'O' with '0'.",
            "- Normalize textual fields (full_name, place_of_birth, address, occupation, "
            "issuing_office) to UPPERCASE.",
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
        """Validate extracted SIM data using deterministic Indonesian SIM rules."""
        if not isinstance(data, SimData):
            return ValidationResult(
                is_valid=False,
                checks=[
                    ValidationCheck(
                        name="sim_schema_type",
                        passed=False,
                        message=f"Expected SimData instance, got {type(data).__name__}.",
                    )
                ],
            )

        checks = validate_sim(
            data.sim_number.value,
            sim_class=data.sim_class.value,
            valid_until=data.valid_until.value,
            date_of_birth=data.date_of_birth.value,
            gender=data.gender.value,
        )
        return ValidationResult(
            is_valid=all(check.passed for check in checks),
            checks=checks,
        )

    def offline_parse(self, ocr_result: OcrResult) -> SimData:
        """Deterministic regex fallback parser when no LLM is available."""
        text = ocr_result.raw_text or "\n".join(line.text for line in ocr_result.lines)
        upper_text = text.upper()

        sim_number_field = _empty_str_field()
        number_match = _OFFLINE_SIM_NUMBER_RE.search(text)
        if number_match:
            sim_number_field = ExtractedField[str](
                value=number_match.group(0),
                confidence=0.7,
                source="ocr_offline",
            )

        sim_class_field = _empty_str_field()
        class_match = _OFFLINE_SIM_CLASS_RE.search(text)
        if class_match:
            sim_class_field = ExtractedField[str](
                value=class_match.group(1),
                confidence=0.7,
                source="ocr_offline",
            )

        gender_field = _empty_str_field()
        if any(token in upper_text for token in ("LAKI-LAKI", "LAKI LAKI", "PRIA")):
            gender_field = ExtractedField[str](
                value="LAKI-LAKI",
                confidence=0.7,
                source="ocr_offline",
            )
        elif any(token in upper_text for token in ("PEREMPUAN", "WANITA")):
            gender_field = ExtractedField[str](
                value="PEREMPUAN",
                confidence=0.7,
                source="ocr_offline",
            )

        dob_field = _empty_str_field()
        valid_until_field = _empty_str_field()
        dates = _OFFLINE_DATE_RE.findall(text)
        if dates:
            dob_field = ExtractedField[str](
                value=dates[0],
                confidence=0.6,
                source="ocr_offline",
            )
            if len(dates) >= 2:
                valid_until_field = ExtractedField[str](
                    value=dates[-1],
                    confidence=0.6,
                    source="ocr_offline",
                )

        return SimData(
            sim_number=sim_number_field,
            sim_class=sim_class_field,
            date_of_birth=dob_field,
            gender=gender_field,
            valid_until=valid_until_field,
        )


__all__ = ["IndonesiaSimPlugin", "SimClass", "SimData", "normalize_sim_class"]
