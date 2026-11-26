"""Application-layer extraction pipeline orchestrator."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel

from app.domain.interfaces import (
    DocumentClassifier,
    ExtractionStrategy,
    ImagePreprocessor,
)
from app.domain.registry import DocumentRegistry
from app.domain.schemas import ExtractionResponse

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Orchestrates document lookup, preprocessing, and extraction via domain ports."""

    def __init__(
        self,
        preprocessor: ImagePreprocessor,
        strategy: ExtractionStrategy,
        registry: DocumentRegistry,
        classifier: DocumentClassifier | None = None,
    ) -> None:
        self._preprocessor = preprocessor
        self._strategy = strategy
        self._registry = registry
        self._classifier = classifier

    async def run(
        self,
        image_bytes: bytes,
        country_code: str,
        doc_type: str,
        *,
        request_id: str | None = None,
    ) -> ExtractionResponse[dict[str, Any]]:
        """Execute the end-to-end extraction pipeline for a single document image."""
        start = time.perf_counter()

        plugin = self._registry.get(country_code, doc_type)
        preprocessed = await self._preprocessor.preprocess(image_bytes)
        output = await self._strategy.extract(preprocessed, plugin)

        data: dict[str, Any] = (
            output.data.model_dump() if isinstance(output.data, BaseModel) else dict(output.data)
        )
        processing_ms = round((time.perf_counter() - start) * 1000.0, 2)
        meta = output.meta.model_copy(
            update={
                "processing_ms": processing_ms,
                "request_id": request_id,
            }
        )

        logger.info(
            "Extraction completed: request_id=%s country_code=%s doc_type=%s "
            "strategy=%s processing_ms=%.2f is_valid=%s",
            request_id,
            output.document.country_code,
            output.document.doc_type,
            meta.strategy,
            meta.processing_ms,
            output.validation.is_valid,
        )

        return ExtractionResponse[dict[str, Any]](
            success=True,
            document=output.document,
            data=data,
            validation=output.validation,
            meta=meta,
        )


__all__ = ["ExtractionPipeline"]
