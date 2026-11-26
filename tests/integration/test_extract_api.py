"""Integration tests for POST /v1/extract and ExtractionPipeline / HybridOcrLlmExtractor."""

from __future__ import annotations

import io
import uuid
from collections.abc import Sequence
from typing import TypeVar

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import BaseModel

from app.application.pipeline import ExtractionPipeline
from app.domain.exceptions import (
    ExtractionFailedError,
    ImageTooBlurryError,
    ProviderTimeoutError,
)
from app.domain.interfaces import DocumentClassifier, ExtractionStrategy
from app.domain.registry import DocumentRegistry
from app.domain.schemas import (
    ClassificationRule,
    OcrLine,
    OcrResult,
    PreprocessedImage,
    QualityMetrics,
    ValidationCheck,
    ValidationResult,
)
from app.infrastructure.config import ApiSettings, OcrSettings, Settings
from app.infrastructure.engines.classifier import HeuristicDocumentClassifier
from app.infrastructure.engines.extractors import HybridOcrLlmExtractor
from app.main import create_app

TModel = TypeVar("TModel", bound=BaseModel)


class DummyIdSchema(BaseModel):
    """Test schema for dummy document plugin."""

    id_number: str
    full_name: str


class DummyDocumentPlugin:
    """Minimal DocumentPlugin used for pipeline and API integration tests."""

    country_code: str = "IDN"
    doc_type: str = "KTP"
    description: str = "Dummy Indonesian KTP"
    schema_model: type[BaseModel] = DummyIdSchema

    def __init__(self, *, empty_prompt: bool = False) -> None:
        self._empty_prompt = empty_prompt

    @property
    def classification_rules(self) -> Sequence[ClassificationRule]:
        return (
            ClassificationRule(keyword="NIK", weight=2.0, required=True),
            ClassificationRule(keyword="PROVINSI", weight=1.5),
            ClassificationRule(keyword="SEUMUR HIDUP", weight=1.5),
        )

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        if self._empty_prompt:
            return ""
        raw = ocr_result.raw_text if ocr_result is not None else ""
        return f"Parse IDN/KTP fields from:\n{raw}"

    def validate(self, data: BaseModel) -> ValidationResult:
        assert isinstance(data, DummyIdSchema)
        passed = len(data.id_number) == 16
        msg = None if passed else "ID number must be 16 digits"
        return ValidationResult(
            is_valid=passed,
            checks=[ValidationCheck(name="id_length", passed=passed, message=msg)],
        )

    def offline_parse(self, ocr_result: OcrResult) -> BaseModel:
        return DummyIdSchema(id_number="0000000000000000", full_name=ocr_result.raw_text)


class FakePreprocessor:
    """Stub ImagePreprocessor that either returns a valid image or raises."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error

    async def preprocess(self, image_bytes: bytes) -> PreprocessedImage:
        if self._error is not None:
            raise self._error
        quality = QualityMetrics(
            blur_score=250.0,
            brightness=130.0,
            glare_ratio=0.01,
            width=800,
            height=500,
        )
        return PreprocessedImage(
            image_bytes=image_bytes,
            mime_type="image/jpeg",
            width=800,
            height=500,
            quality=quality,
        )


class FakeOcrEngine:
    """Stub OcrEngine returning deterministic OCR lines."""

    def __init__(self, raw_text: str = "NIK 3171234567890001\nNAMA BUDI SANTOSO") -> None:
        self.raw_text = raw_text
        self.call_count = 0

    async def extract(self, preprocessed: PreprocessedImage) -> OcrResult:
        self.call_count += 1
        lines = [OcrLine(text=line, confidence=0.95) for line in self.raw_text.splitlines()]
        return OcrResult(lines=lines, raw_text=self.raw_text, language="id", processing_ms=12.5)


class FakeLlmParser:
    """Stub LlmParser returning a valid DummyIdSchema or raising a configured error."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.last_prompt: str | None = None

    async def parse(
        self,
        prompt: str,
        schema_model: type[TModel],
        preprocessed: PreprocessedImage | None = None,
    ) -> TModel:
        self.last_prompt = prompt
        if self._error is not None:
            raise self._error
        return schema_model.model_validate(
            {"id_number": "3171234567890001", "full_name": "BUDI SANTOSO"}
        )


def _make_sample_jpeg_bytes() -> bytes:
    """Generate a tiny valid JPEG payload in memory."""
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(120, 140, 160)).save(buf, format="JPEG")
    return buf.getvalue()


def _build_test_client(
    *,
    preprocessor: FakePreprocessor | None = None,
    ocr_engine: FakeOcrEngine | None = None,
    llm_parser: FakeLlmParser | None = None,
    strategy: ExtractionStrategy | None = None,
    classifier: DocumentClassifier | None = None,
    enable_auto_classifier: bool = True,
    max_upload_size_mb: int = 10,
    register_dummy: bool = True,
) -> TestClient:
    """Construct a TestClient with an isolated registry and fake pipeline."""
    registry = DocumentRegistry()
    if register_dummy:
        registry.register(DummyDocumentPlugin())

    resolved_ocr = ocr_engine if ocr_engine is not None else FakeOcrEngine()
    resolved_strategy = (
        strategy
        if strategy is not None
        else HybridOcrLlmExtractor(
            ocr_engine=resolved_ocr,
            llm_parser=llm_parser if llm_parser is not None else FakeLlmParser(),
        )
    )
    resolved_classifier = (
        classifier
        if classifier is not None
        else (HeuristicDocumentClassifier() if enable_auto_classifier else None)
    )
    pipeline = ExtractionPipeline(
        preprocessor=preprocessor if preprocessor is not None else FakePreprocessor(),
        strategy=resolved_strategy,
        registry=registry,
        classifier=resolved_classifier,
        ocr_engine=resolved_ocr,
    )
    settings = Settings(
        api=ApiSettings(max_upload_size_mb=max_upload_size_mb),
        ocr=OcrSettings(enabled=False),
    )
    app = create_app(settings=settings, registry=registry, pipeline=pipeline)
    return TestClient(app)


@pytest.mark.integration
def test_extract_happy_path_with_custom_and_generated_request_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """POST /v1/extract returns 200 ExtractionResponse, propagates X-Request-ID, and logs no PII."""
    sample_bytes = _make_sample_jpeg_bytes()

    with _build_test_client() as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("ktp.jpg", sample_bytes, "image/jpeg")},
            data={"country": "IDN", "doc_type": "KTP"},
            headers={"X-Request-ID": "req-custom-123"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["document"] == {
            "country_code": "IDN",
            "doc_type": "KTP",
            "confidence": 1.0,
            "detected_automatically": False,
        }
        assert body["data"] == {
            "id_number": "3171234567890001",
            "full_name": "BUDI SANTOSO",
        }
        assert body["validation"]["is_valid"] is True
        assert body["meta"]["strategy"] == "hybrid_paddle_llm"
        assert body["meta"]["processing_ms"] >= 0
        assert body["meta"]["request_id"] == "req-custom-123"
        assert body["meta"]["ocr_used"] is True
        assert body["meta"]["llm_used"] is True

        # Verify structured completion log contains metadata but zero PII/OCR text
        log_output = capsys.readouterr().out
        assert "req-custom-123" in log_output
        assert "hybrid_paddle_llm" in log_output
        assert "BUDI SANTOSO" not in log_output
        assert "3171234567890001" not in log_output

        # Omitting X-Request-ID generates a valid UUID4 request_id
        response_auto = client.post(
            "/v1/extract",
            files={"file": ("ktp.jpg", sample_bytes, "image/jpeg")},
            data={"country": "IDN", "doc_type": "KTP"},
        )
        assert response_auto.status_code == 200
        generated_id = response_auto.json()["meta"]["request_id"]
        assert generated_id is not None
        assert str(uuid.UUID(generated_id)) == generated_id


@pytest.mark.integration
def test_extract_rejects_invalid_mime_type() -> None:
    """POST /v1/extract returns 400 UNSUPPORTED_MEDIA_TYPE for disallowed MIME types."""
    with _build_test_client() as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
            data={"country": "IDN", "doc_type": "KTP"},
            headers={"X-Request-ID": "req-mime-400"},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert body["request_id"] == "req-mime-400"


@pytest.mark.integration
def test_extract_rejects_empty_file_upload() -> None:
    """POST /v1/extract returns 400 INVALID_IMAGE for zero-byte uploads."""
    with _build_test_client() as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
            data={"country": "IDN", "doc_type": "KTP"},
            headers={"X-Request-ID": "req-empty-400"},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "INVALID_IMAGE"
    assert body["request_id"] == "req-empty-400"


@pytest.mark.integration
def test_extract_rejects_oversized_file_upload() -> None:
    """POST /v1/extract returns 413 PAYLOAD_TOO_LARGE when upload exceeds max_upload_size_mb."""
    oversized_payload = b"x" * (1024 * 1024 + 1)
    with _build_test_client(max_upload_size_mb=1) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("huge.jpg", oversized_payload, "image/jpeg")},
            data={"country": "IDN", "doc_type": "KTP"},
            headers={"X-Request-ID": "req-large-413"},
        )

    assert response.status_code == 413
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "PAYLOAD_TOO_LARGE"
    assert body["request_id"] == "req-large-413"


@pytest.mark.integration
def test_extract_returns_422_on_blurry_image() -> None:
    """POST /v1/extract maps ImageTooBlurryError to 422 IMAGE_TOO_BLURRY with request_id."""
    blur_error = ImageTooBlurryError(
        "Image is too blurry for reliable extraction.",
        details={"blur_score": 12.5, "threshold": 100.0},
    )
    with _build_test_client(preprocessor=FakePreprocessor(error=blur_error)) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("blurry.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
            data={"country": "IDN", "doc_type": "KTP"},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "IMAGE_TOO_BLURRY"
    assert body["details"] == {"blur_score": 12.5, "threshold": 100.0}
    assert body["request_id"] is not None
    assert str(uuid.UUID(body["request_id"])) == body["request_id"]


@pytest.mark.integration
def test_extract_returns_400_on_unsupported_document() -> None:
    """POST /v1/extract maps UnsupportedDocumentError to 400 UNSUPPORTED_DOCUMENT."""
    with _build_test_client() as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("card.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
            data={"country": "ZZZ", "doc_type": "UNKNOWN"},
            headers={"X-Request-ID": "req-unsup-400"},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "UNSUPPORTED_DOCUMENT"
    assert body["request_id"] == "req-unsup-400"


@pytest.mark.integration
def test_extract_returns_504_on_llm_timeout() -> None:
    """POST /v1/extract maps ProviderTimeoutError to 504 PROVIDER_TIMEOUT."""
    timeout_parser = FakeLlmParser(error=ProviderTimeoutError("LLM provider timed out."))
    with _build_test_client(llm_parser=timeout_parser) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("card.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
            data={"country": "IDN", "doc_type": "KTP"},
            headers={"X-Request-ID": "req-timeout-504"},
        )

    assert response.status_code == 504
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "PROVIDER_TIMEOUT"
    assert body["request_id"] == "req-timeout-504"


@pytest.mark.unit
async def test_hybrid_ocr_llm_extractor_direct_and_prompt_fallback() -> None:
    """HybridOcrLlmExtractor orchestrates OCR, prompt fallback, LLM parsing, and validation."""
    ocr = FakeOcrEngine()
    llm = FakeLlmParser()
    extractor = HybridOcrLlmExtractor(ocr_engine=ocr, llm_parser=llm)
    preprocessed = await FakePreprocessor().preprocess(_make_sample_jpeg_bytes())

    # Standard plugin prompt
    output = await extractor.extract(preprocessed, DummyDocumentPlugin())
    assert ocr.call_count == 1
    assert output.document.country_code == "IDN"
    assert output.document.doc_type == "KTP"
    assert output.meta.strategy == "hybrid_paddle_llm"
    assert output.meta.ocr_used is True
    assert output.meta.llm_used is True
    assert output.meta.processing_ms >= 0
    assert output.validation.is_valid is True
    assert output.raw_ocr_text == ocr.raw_text
    assert llm.last_prompt is not None
    assert "Parse IDN/KTP fields from:" in llm.last_prompt

    # Precomputed OCR result + empty plugin prompt falls back to format_ocr_prompt
    precomputed_ocr = OcrResult(
        lines=[OcrLine(text="NIK 3171234567890001", confidence=0.92)],
        raw_text="NIK 3171234567890001",
    )
    output_fallback = await extractor.extract(
        preprocessed,
        DummyDocumentPlugin(empty_prompt=True),
        ocr_result=precomputed_ocr,
    )
    assert ocr.call_count == 1  # did not re-run OCR
    assert output_fallback.raw_ocr_text == "NIK 3171234567890001"
    assert llm.last_prompt is not None
    assert "OCR Lines (reading order):" in llm.last_prompt


@pytest.mark.unit
async def test_hybrid_ocr_llm_extractor_raises_when_ocr_engine_missing() -> None:
    """HybridOcrLlmExtractor raises ExtractionFailedError without OCR engine or result."""
    extractor = HybridOcrLlmExtractor(ocr_engine=None, llm_parser=FakeLlmParser())
    preprocessed = await FakePreprocessor().preprocess(_make_sample_jpeg_bytes())

    with pytest.raises(ExtractionFailedError, match="OCR engine is not configured"):
        await extractor.extract(preprocessed, DummyDocumentPlugin())


@pytest.mark.integration
def test_extract_auto_detect_when_country_and_doc_type_omitted() -> None:
    """Omitting country and doc_type auto-classifies and executes OCR exactly once."""
    ocr = FakeOcrEngine(
        raw_text="PROVINSI DKI JAKARTA\nNIK 3171234567890001\nNAMA BUDI SANTOSO\nSEUMUR HIDUP"
    )
    with _build_test_client(ocr_engine=ocr) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("ktp.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
            headers={"X-Request-ID": "req-auto-200"},
        )

    assert response.status_code == 200
    assert ocr.call_count == 1
    body = response.json()
    assert body["success"] is True
    assert body["document"]["country_code"] == "IDN"
    assert body["document"]["doc_type"] == "KTP"
    assert body["document"]["detected_automatically"] is True
    assert body["document"]["confidence"] == pytest.approx(1.0)
    assert body["meta"]["request_id"] == "req-auto-200"


@pytest.mark.integration
def test_extract_auto_detect_with_partial_country_hint() -> None:
    """Providing only country narrows candidates and still auto-classifies with single OCR call."""
    ocr = FakeOcrEngine(raw_text="PROVINSI DKI JAKARTA\nNIK 3171234567890001\nSEUMUR HIDUP")
    with _build_test_client(ocr_engine=ocr) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("ktp.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
            data={"country": "IDN"},
        )

    assert response.status_code == 200
    assert ocr.call_count == 1
    body = response.json()
    assert body["document"]["detected_automatically"] is True
    assert body["document"]["country_code"] == "IDN"
    assert body["document"]["doc_type"] == "KTP"


@pytest.mark.integration
def test_extract_auto_detect_returns_400_for_unrecognized_document() -> None:
    """Auto-detection returns 400 UNSUPPORTED_DOCUMENT when OCR text matches no plugin."""
    ocr = FakeOcrEngine(raw_text="SUPERMARKET RECEIPT\nTOTAL RP 42.000\nTHANK YOU")
    with _build_test_client(ocr_engine=ocr) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("receipt.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
            headers={"X-Request-ID": "req-auto-400"},
        )

    assert response.status_code == 400
    assert ocr.call_count == 1
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "UNSUPPORTED_DOCUMENT"
    assert body["request_id"] == "req-auto-400"


@pytest.mark.integration
def test_extract_auto_detect_returns_400_when_classifier_unconfigured() -> None:
    """Auto-detection fails cleanly with 400 UNSUPPORTED_DOCUMENT if no classifier is wired."""
    with _build_test_client(enable_auto_classifier=False) as client:
        response = client.post(
            "/v1/extract",
            files={"file": ("ktp.jpg", _make_sample_jpeg_bytes(), "image/jpeg")},
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "UNSUPPORTED_DOCUMENT"
