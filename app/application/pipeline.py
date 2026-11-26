"""Application-layer extraction pipeline orchestrator."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel

from app.domain.exceptions import ExtractionFailedError, UnsupportedDocumentError
from app.domain.interfaces import (
    DocumentClassifier,
    DocumentPlugin,
    ExtractionStrategy,
    ImagePreprocessor,
    OcrEngine,
)
from app.domain.registry import DocumentRegistry
from app.domain.schemas import ExtractionResponse

logger = logging.getLogger(__name__)


def _normalize_optional(value: str | None) -> str | None:
    """Return an uppercased, trimmed string or None when blank/omitted."""
    if value is None:
        return None
    trimmed = value.strip().upper()
    return trimmed or None


class ExtractionPipeline:
    """Orchestrates document lookup, auto-classification, preprocessing, and extraction."""

    def __init__(
        self,
        preprocessor: ImagePreprocessor,
        strategy: ExtractionStrategy,
        registry: DocumentRegistry,
        classifier: DocumentClassifier | None = None,
        ocr_engine: OcrEngine | None = None,
    ) -> None:
        self._preprocessor = preprocessor
        self._strategy = strategy
        self._registry = registry
        self._classifier = classifier
        self._ocr_engine = ocr_engine

    def _filter_candidate_plugins(
        self,
        country_code: str | None,
        doc_type: str | None,
    ) -> list[DocumentPlugin]:
        """Filter registered plugins by any provided country_code and/or doc_type hint."""
        candidates: list[DocumentPlugin] = []
        for plugin in self._registry.list_plugins():
            if country_code is not None and plugin.country_code.strip().upper() != country_code:
                continue
            if doc_type is not None and plugin.doc_type.strip().upper() != doc_type:
                continue
            candidates.append(plugin)
        return candidates

    async def run(
        self,
        image_bytes: bytes,
        country_code: str | None = None,
        doc_type: str | None = None,
        *,
        request_id: str | None = None,
    ) -> ExtractionResponse[dict[str, Any]]:
        """Execute the end-to-end extraction pipeline for a single document image."""
        start = time.perf_counter()

        norm_country = _normalize_optional(country_code)
        norm_doc_type = _normalize_optional(doc_type)

        if norm_country is not None and norm_doc_type is not None:
            plugin = self._registry.get(norm_country, norm_doc_type)
            preprocessed = await self._preprocessor.preprocess(image_bytes)
            output = await self._strategy.extract(preprocessed, plugin)
            document = output.document.model_copy(update={"detected_automatically": False})
        else:
            preprocessed = await self._preprocessor.preprocess(image_bytes)
            if self._classifier is None:
                raise UnsupportedDocumentError(
                    "Automatic document classification is not configured."
                )
            if self._ocr_engine is None:
                raise ExtractionFailedError(
                    "OCR engine is not configured for automatic document classification."
                )

            candidate_plugins = self._filter_candidate_plugins(norm_country, norm_doc_type)
            if not candidate_plugins:
                raise UnsupportedDocumentError(
                    "No registered document plugins match the provided filter."
                )

            ocr_result = await self._ocr_engine.extract(preprocessed)
            classification = self._classifier.classify(ocr_result, candidate_plugins)
            if classification is None:
                raise UnsupportedDocumentError(
                    "Could not automatically identify document type from image."
                )

            plugin = self._registry.get(classification.country_code, classification.doc_type)
            output = await self._strategy.extract(preprocessed, plugin, ocr_result=ocr_result)
            document = output.document.model_copy(
                update={
                    "detected_automatically": True,
                    "confidence": classification.confidence,
                }
            )

        data: dict[str, Any] = (
            output.data.model_dump() if isinstance(output.data, BaseModel) else dict(output.data)
        )
        processing_ms = round((time.perf_counter() - start) * 1000.0, 2)
        meta = output.meta.model_copy(
            update={
                "processing_ms": processing_ms,
                "request_id": request_id,
                "quality": preprocessed.quality,
            }
        )

        logger.info(
            "Extraction completed: request_id=%s country_code=%s doc_type=%s "
            "detected_automatically=%s strategy=%s processing_ms=%.2f is_valid=%s",
            request_id,
            document.country_code,
            document.doc_type,
            document.detected_automatically,
            meta.strategy,
            meta.processing_ms,
            output.validation.is_valid,
        )

        return ExtractionResponse[dict[str, Any]](
            success=True,
            document=document,
            data=data,
            validation=output.validation,
            meta=meta,
        )


__all__ = ["ExtractionPipeline"]
