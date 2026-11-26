"""Tests for the minimal web playground UI routes, static assets, and quality metadata."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.application.pipeline import ExtractionPipeline
from app.domain.interfaces import DocumentPlugin
from app.domain.registry import DocumentRegistry
from app.domain.schemas import (
    DocumentInfo,
    ExtractionMeta,
    ExtractionOutput,
    OcrResult,
    PreprocessedImage,
    QualityMetrics,
    ValidationResult,
)
from app.infrastructure.config import PlaygroundSettings, Settings


def test_playground_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """PlaygroundSettings enables the playground by default when env var is unset."""
    monkeypatch.delenv("ENABLE_PLAYGROUND", raising=False)

    settings = Settings()

    assert settings.playground.enable_playground is True


def test_playground_routes_and_assets_return_200_when_enabled(
    client_factory: Callable[..., TestClient],
) -> None:
    """GET /, /playground, and static assets return 200 when ENABLE_PLAYGROUND=true."""
    settings = Settings(playground=PlaygroundSettings(enable_playground=True))
    client = client_factory(settings=settings)

    root_res = client.get("/")
    assert root_res.status_code == 200
    assert "text/html" in root_res.headers["content-type"]
    assert "MiruID Playground" in root_res.text
    assert "/static/playground/app.js" in root_res.text

    playground_res = client.get("/playground")
    assert playground_res.status_code == 200
    assert "text/html" in playground_res.headers["content-type"]
    assert "MiruID Playground" in playground_res.text

    js_res = client.get("/static/playground/app.js")
    assert js_res.status_code == 200
    assert "/v1/documents" in js_res.text
    assert "/v1/extract" in js_res.text

    css_res = client.get("/static/playground/styles.css")
    assert css_res.status_code == 200
    assert "--primary" in css_res.text

    render_res = client.get("/static/playground/render.js")
    assert render_res.status_code == 200
    assert "renderQualityPills" in render_res.text


def test_playground_routes_and_assets_return_404_when_disabled(
    client_factory: Callable[..., TestClient],
) -> None:
    """GET /, /playground, and static assets return 404 when ENABLE_PLAYGROUND=false."""
    settings = Settings(playground=PlaygroundSettings(enable_playground=False))
    client = client_factory(settings=settings)

    assert client.get("/").status_code == 404
    assert client.get("/playground").status_code == 404
    assert client.get("/static/playground/app.js").status_code == 404
    assert client.get("/static/playground/render.js").status_code == 404
    assert client.get("/static/playground/styles.css").status_code == 404


def test_extraction_meta_quality_defaults_to_none() -> None:
    """ExtractionMeta.quality is optional and defaults to None for backward compatibility."""
    meta = ExtractionMeta(strategy="hybrid")

    assert meta.quality is None


class _StubPreprocessor:
    """Stub preprocessor returning deterministic quality metrics."""

    def __init__(self, quality: QualityMetrics) -> None:
        self._quality = quality

    async def preprocess(self, image_bytes: bytes) -> PreprocessedImage:
        return PreprocessedImage(
            image_bytes=image_bytes,
            width=self._quality.width,
            height=self._quality.height,
            quality=self._quality,
        )


class _StubStrategy:
    """Stub extraction strategy returning a minimal ExtractionOutput."""

    async def extract(
        self,
        image: PreprocessedImage,
        plugin: DocumentPlugin,
        ocr_result: OcrResult | None = None,
    ) -> ExtractionOutput:
        return ExtractionOutput(
            document=DocumentInfo(
                country_code=plugin.country_code,
                doc_type=plugin.doc_type,
            ),
            data=plugin.offline_parse(OcrResult(raw_text="ok")),
            validation=ValidationResult(is_valid=True),
            meta=ExtractionMeta(strategy="stub"),
        )


@pytest.mark.asyncio
async def test_pipeline_populates_meta_quality(
    stub_plugin_factory: Callable[..., DocumentPlugin],
) -> None:
    """ExtractionPipeline.run() attaches preprocessed quality metrics to response.meta.quality."""
    quality = QualityMetrics(
        blur_score=185.4,
        brightness=128.0,
        glare_ratio=0.01,
        width=800,
        height=500,
        is_blurry=False,
        has_glare=False,
        is_acceptable=True,
    )
    registry = DocumentRegistry()
    registry.register(stub_plugin_factory("IDN", "KTP", "Indonesian KTP"))

    pipeline = ExtractionPipeline(
        preprocessor=_StubPreprocessor(quality),
        strategy=_StubStrategy(),
        registry=registry,
    )

    response = await pipeline.run(b"fake-image-bytes", country_code="IDN", doc_type="KTP")

    assert response.meta.quality == quality
