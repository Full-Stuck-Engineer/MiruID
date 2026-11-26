"""Domain port interfaces (Protocols) for MiruID."""

from collections.abc import Sequence
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.domain.schemas import (
    ClassificationResult,
    ClassificationRule,
    ExtractionOutput,
    OcrResult,
    PreprocessedImage,
    ValidationResult,
)

TModel = TypeVar("TModel", bound=BaseModel)


@runtime_checkable
class ImagePreprocessor(Protocol):
    """Port for decoding, orienting, and quality-gating input images."""

    async def preprocess(self, image_bytes: bytes) -> PreprocessedImage: ...


@runtime_checkable
class OcrEngine(Protocol):
    """Port for optical character recognition engines."""

    async def extract(self, preprocessed: PreprocessedImage) -> OcrResult: ...


@runtime_checkable
class LlmParser(Protocol):
    """Port for structured LLM/VLM extraction against a Pydantic schema."""

    async def parse(
        self,
        prompt: str,
        schema_model: type[TModel],
        preprocessed: PreprocessedImage | None = None,
    ) -> TModel: ...


@runtime_checkable
class DocumentPlugin(Protocol):
    """Port for country/document-specific schemas, prompts, and validators."""

    country_code: str
    doc_type: str
    description: str
    schema_model: type[BaseModel]

    @property
    def classification_rules(self) -> Sequence[ClassificationRule]: ...

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str: ...

    def validate(self, data: BaseModel) -> ValidationResult: ...

    def offline_parse(self, ocr_result: OcrResult) -> BaseModel: ...


@runtime_checkable
class ExtractionStrategy(Protocol):
    """Port for orchestrating OCR, LLM, or hybrid extraction strategies."""

    async def extract(
        self,
        preprocessed: PreprocessedImage,
        plugin: DocumentPlugin,
        ocr_result: OcrResult | None = None,
    ) -> ExtractionOutput: ...


@runtime_checkable
class DocumentClassifier(Protocol):
    """Port for selecting a matching DocumentPlugin from OCR output."""

    def classify(
        self,
        ocr_result: OcrResult,
        plugins: Sequence[DocumentPlugin],
    ) -> ClassificationResult | None: ...
