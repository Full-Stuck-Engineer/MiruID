"""Domain Pydantic v2 schemas for MiruID."""

from typing import Any

from pydantic import BaseModel, Field


class ExtractedField[T](BaseModel):
    """Single extracted field with value, confidence score, and optional source."""

    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str | None = None


class QualityMetrics(BaseModel):
    """Image quality measurements produced during preprocessing."""

    blur_score: float = Field(ge=0.0)
    brightness: float | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    is_acceptable: bool = True


class PreprocessedImage(BaseModel):
    """Normalized image payload ready for OCR or VLM extraction."""

    image_bytes: bytes
    mime_type: str = "image/jpeg"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    quality: QualityMetrics
    orientation_corrected: bool = False


class OcrLine(BaseModel):
    """Single recognized text line from an OCR engine."""

    text: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    bbox: list[float] | None = None


class OcrResult(BaseModel):
    """Aggregated OCR output for a preprocessed image."""

    lines: list[OcrLine] = Field(default_factory=list)
    raw_text: str = ""
    language: str | None = None
    processing_ms: float = Field(default=0.0, ge=0.0)


class ValidationCheck(BaseModel):
    """Outcome of a single domain validation rule."""

    name: str
    passed: bool
    message: str | None = None


class ValidationResult(BaseModel):
    """Aggregated validation outcome for extracted document fields."""

    is_valid: bool
    checks: list[ValidationCheck] = Field(default_factory=list)


class DocumentInfo(BaseModel):
    """Identified document type metadata."""

    country_code: str
    doc_type: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ClassificationRule(BaseModel):
    """Keyword-based rule used to classify a document from OCR text."""

    keyword: str
    weight: float = Field(default=1.0, gt=0.0)
    required: bool = False


class ClassificationResult(BaseModel):
    """Result returned by a document classifier."""

    country_code: str
    doc_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    matched_rules: list[str] = Field(default_factory=list)


class ExtractionMeta(BaseModel):
    """Execution metadata for an extraction request."""

    strategy: str
    processing_ms: float = Field(default=0.0, ge=0.0)
    request_id: str | None = None
    ocr_used: bool = False
    llm_used: bool = False


class ExtractionOutput(BaseModel):
    """Internal domain result produced by an extraction strategy."""

    document: DocumentInfo
    data: BaseModel | dict[str, Any]
    validation: ValidationResult
    meta: ExtractionMeta
    raw_ocr_text: str | None = None


class ExtractionResponse[TData](BaseModel):
    """Generic API-facing extraction response envelope."""

    success: bool = True
    document: DocumentInfo
    data: TData
    validation: ValidationResult
    meta: ExtractionMeta


class ErrorResponse(BaseModel):
    """Standardized error response envelope."""

    success: bool = False
    error_code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class SupportedDocument(BaseModel):
    """Metadata describing a registered document plugin."""

    country_code: str
    doc_type: str
    description: str


class SupportedDocumentsResponse(BaseModel):
    """Response payload listing all supported document types."""

    documents: list[SupportedDocument] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
