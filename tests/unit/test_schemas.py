"""Unit tests for domain exceptions, schemas, and Protocol interfaces."""

import json
from collections.abc import Sequence

import pytest
from pydantic import BaseModel, ValidationError

import app.domain.exceptions as exc
import app.domain.interfaces as iface
import app.domain.schemas as sch


class DummyData(BaseModel):
    full_name: sch.ExtractedField[str]
    birth_year: sch.ExtractedField[int]


def test_extracted_field_bounds_and_nulls() -> None:
    empty = sch.ExtractedField[str]()
    assert (empty.value, empty.confidence, empty.source) == (None, 0.0, None)
    assert sch.ExtractedField[int](value=1995, confidence=0.95, source="ocr").value == 1995
    with pytest.raises(ValidationError):
        sch.ExtractedField[str](value="A", confidence=-0.1)
    with pytest.raises(ValidationError):
        sch.ExtractedField[str](value="A", confidence=1.1)


def test_generic_extraction_response_serialization() -> None:
    payload = sch.ExtractionResponse[DummyData](
        document=sch.DocumentInfo(country_code="IDN", doc_type="ktp", confidence=0.98),
        data=DummyData(
            full_name=sch.ExtractedField[str](value="BUDI", confidence=0.9, source="vlm"),
            birth_year=sch.ExtractedField[int](value=None, confidence=0.0),
        ),
        validation=sch.ValidationResult(
            is_valid=True, checks=[sch.ValidationCheck(name="nik_format", passed=True)]
        ),
        meta=sch.ExtractionMeta(
            strategy="hybrid", processing_ms=42.5, request_id="req-1", ocr_used=True
        ),
    )
    raw = json.loads(payload.model_dump_json())
    assert raw["success"] is True
    assert raw["data"]["full_name"]["value"] == "BUDI"
    assert raw["data"]["birth_year"]["value"] is None
    assert sch.ExtractionResponse[DummyData].model_validate(raw).data.full_name.value == "BUDI"


def test_error_response_and_domain_exceptions() -> None:
    err = exc.ImageTooBlurryError("Too blurry", details={"blur_score": 10.0})
    assert isinstance(err, exc.MiruDomainError)
    assert err.error_code == "IMAGE_TOO_BLURRY"
    assert exc.InvalidImageError("bad").error_code == "INVALID_IMAGE"
    assert exc.UnsupportedDocumentError("unknown").error_code == "UNSUPPORTED_DOCUMENT"
    assert exc.ProviderTimeoutError("timeout").error_code == "PROVIDER_TIMEOUT"
    assert exc.ExtractionFailedError("failed").error_code == "EXTRACTION_FAILED"
    resp = sch.ErrorResponse(
        error_code=err.error_code, message=err.message, details=err.details, request_id="req-xyz"
    )
    assert (resp.success, resp.request_id) == (False, "req-xyz")


def test_protocol_structural_subtyping() -> None:
    class StubPreprocessor:
        async def preprocess(self, image_bytes: bytes) -> sch.PreprocessedImage:
            q = sch.QualityMetrics(blur_score=100.0, width=100, height=100)
            return sch.PreprocessedImage(image_bytes=image_bytes, width=100, height=100, quality=q)

    class StubOcr:
        async def extract(self, preprocessed: sch.PreprocessedImage) -> sch.OcrResult:
            return sch.OcrResult(raw_text="KTP")

    class StubLlm:
        async def parse(
            self,
            prompt: str,
            schema_model: type[BaseModel],
            preprocessed: sch.PreprocessedImage | None = None,
        ) -> BaseModel:
            return schema_model()

    class StubPlugin:
        country_code, doc_type, description = "IDN", "ktp", "Indonesian KTP"
        schema_model = DummyData
        classification_rules = [sch.ClassificationRule(keyword="NIK", required=True)]

        def build_prompt(self, ocr_result: sch.OcrResult | None = None) -> str:
            return "extract"

        def validate(self, data: BaseModel) -> sch.ValidationResult:
            return sch.ValidationResult(is_valid=True)

        def offline_parse(self, ocr_result: sch.OcrResult) -> BaseModel:
            return DummyData(
                full_name=sch.ExtractedField[str](), birth_year=sch.ExtractedField[int]()
            )

    class StubStrategy:
        async def extract(
            self,
            preprocessed: sch.PreprocessedImage,
            plugin: iface.DocumentPlugin,
            ocr_result: sch.OcrResult | None = None,
        ) -> sch.ExtractionOutput:
            return sch.ExtractionOutput(
                document=sch.DocumentInfo(country_code="IDN", doc_type="ktp"),
                data={},
                validation=sch.ValidationResult(is_valid=True),
                meta=sch.ExtractionMeta(strategy="stub"),
            )

    class StubClassifier:
        def classify(
            self, ocr_result: sch.OcrResult, plugins: Sequence[iface.DocumentPlugin]
        ) -> sch.ClassificationResult | None:
            return sch.ClassificationResult(country_code="IDN", doc_type="ktp", confidence=1.0)

    for stub, proto in [
        (StubPreprocessor(), iface.ImagePreprocessor),
        (StubOcr(), iface.OcrEngine),
        (StubLlm(), iface.LlmParser),
        (StubPlugin(), iface.DocumentPlugin),
        (StubStrategy(), iface.ExtractionStrategy),
        (StubClassifier(), iface.DocumentClassifier),
    ]:
        assert isinstance(stub, proto)
    assert not isinstance(object(), iface.ImagePreprocessor)


async def test_async_protocol_stubs_auto_mode() -> None:
    """pytest-asyncio auto mode executes async protocol stubs without explicit markers."""

    class AsyncPreprocessor:
        async def preprocess(self, image_bytes: bytes) -> sch.PreprocessedImage:
            quality = sch.QualityMetrics(blur_score=120.0, width=640, height=480)
            return sch.PreprocessedImage(
                image_bytes=image_bytes, width=640, height=480, quality=quality
            )

    class AsyncOcr:
        async def extract(self, preprocessed: sch.PreprocessedImage) -> sch.OcrResult:
            return sch.OcrResult(raw_text=f"LEN={len(preprocessed.image_bytes)}")

    preprocessor: iface.ImagePreprocessor = AsyncPreprocessor()
    ocr: iface.OcrEngine = AsyncOcr()

    preprocessed = await preprocessor.preprocess(b"fake-image-bytes")
    ocr_result = await ocr.extract(preprocessed)

    assert preprocessed.width == 640
    assert ocr_result.raw_text == "LEN=16"
