"""Concrete ExtractionStrategy adapters orchestrating OCR and LLM engines."""

from __future__ import annotations

import time

from app.domain.exceptions import ExtractionFailedError
from app.domain.interfaces import DocumentPlugin, LlmParser, OcrEngine
from app.domain.schemas import (
    DocumentInfo,
    ExtractionMeta,
    ExtractionOutput,
    OcrResult,
    PreprocessedImage,
)
from app.infrastructure.engines.llm_parser import format_ocr_prompt


class HybridOcrLlmExtractor:
    """Hybrid OCR + LLM extraction strategy conforming to ``ExtractionStrategy``."""

    STRATEGY_NAME = "hybrid_paddle_llm"

    def __init__(
        self,
        ocr_engine: OcrEngine | None,
        llm_parser: LlmParser,
    ) -> None:
        self._ocr_engine = ocr_engine
        self._llm_parser = llm_parser

    async def extract(
        self,
        preprocessed: PreprocessedImage,
        plugin: DocumentPlugin,
        ocr_result: OcrResult | None = None,
    ) -> ExtractionOutput:
        """Run OCR (if not already provided), parse via LLM, and validate via plugin."""
        start = time.perf_counter()

        resolved_ocr = ocr_result
        if resolved_ocr is None:
            if self._ocr_engine is None:
                raise ExtractionFailedError("OCR engine is not configured.")
            resolved_ocr = await self._ocr_engine.extract(preprocessed)

        prompt = plugin.build_prompt(resolved_ocr)
        if not prompt or not prompt.strip():
            prompt = format_ocr_prompt(resolved_ocr)

        parsed = await self._llm_parser.parse(prompt, plugin.schema_model)
        validation = plugin.validate(parsed)
        processing_ms = round((time.perf_counter() - start) * 1000.0, 2)

        return ExtractionOutput(
            document=DocumentInfo(
                country_code=plugin.country_code,
                doc_type=plugin.doc_type,
                confidence=1.0,
            ),
            data=parsed,
            validation=validation,
            meta=ExtractionMeta(
                strategy=self.STRATEGY_NAME,
                processing_ms=processing_ms,
                ocr_used=True,
                llm_used=True,
            ),
            raw_ocr_text=resolved_ocr.raw_text,
        )


__all__ = ["HybridOcrLlmExtractor"]
