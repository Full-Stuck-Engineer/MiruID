"""Unit tests for the in-memory PaddleOcrEngine adapter and FastAPI lifespan."""

from __future__ import annotations

import io
import logging
import sys
import types
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.domain.exceptions import ExtractionFailedError, InvalidImageError
from app.domain.interfaces import OcrEngine
from app.domain.schemas import OcrResult, PreprocessedImage, QualityMetrics
from app.infrastructure.config import OcrSettings, Settings
from app.infrastructure.engines.ocr_paddle import PaddleOcrEngine
from app.main import create_app

pytestmark = pytest.mark.unit


def _make_jpeg_bytes(width: int = 200, height: int = 100) -> bytes:
    """Create valid synthetic JPEG bytes strictly in memory."""
    img = Image.new("RGB", (width, height), color=(240, 240, 240))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_preprocessed(
    image_bytes: bytes | None = None,
    *,
    width: int = 200,
    height: int = 100,
) -> PreprocessedImage:
    payload = _make_jpeg_bytes(width, height) if image_bytes is None else image_bytes
    return PreprocessedImage(
        image_bytes=payload,
        mime_type="image/jpeg",
        width=width,
        height=height,
        quality=QualityMetrics(blur_score=150.0, width=width, height=height),
    )


class _FakePredictBackend:
    """Stub mimicking PaddleOCR 3.x `.predict(image)` backend."""

    def __init__(self, output: Any) -> None:
        self._output = output
        self.calls: int = 0

    def predict(self, image: np.ndarray[Any, Any]) -> Any:
        self.calls += 1
        assert isinstance(image, np.ndarray)
        return self._output


class _FakeLegacyBackend:
    """Stub mimicking PaddleOCR 2.x `.ocr(image, cls=...)` backend."""

    def __init__(self, output: Any, *, accept_cls: bool = True) -> None:
        self._output = output
        self._accept_cls = accept_cls
        self.cls_seen: list[bool | None] = []

    def ocr(self, image: np.ndarray[Any, Any], **kwargs: Any) -> Any:
        assert isinstance(image, np.ndarray)
        if not self._accept_cls and "cls" in kwargs:
            raise TypeError("unexpected keyword argument 'cls'")
        self.cls_seen.append(kwargs.get("cls"))
        return self._output


class _RaisingBackend:
    """Stub raising a runtime error containing sensitive PII."""

    def predict(self, image: np.ndarray[Any, Any]) -> Any:
        raise RuntimeError("sensitive_nik_3171012345678901 leaked inside backend")


def test_structural_conformance_with_ocr_engine_protocol() -> None:
    engine = PaddleOcrEngine()
    assert isinstance(engine, OcrEngine)
    assert engine.is_ready is False


async def test_paddleocr_v3_dict_dt_polys_and_normalization() -> None:
    raw = [
        {
            "rec_texts": ["REPUBLIK INDONESIA", "PROVINSI DKI JAKARTA"],
            "rec_scores": [0.98, 0.92],
            "dt_polys": [
                np.array([[20, 10], [180, 10], [180, 30], [20, 30]], dtype=np.float32),
                [[-10, 40], [220, 40], [220, 60], [-10, 60]],
            ],
        }
    ]
    backend = _FakePredictBackend(raw)
    engine = PaddleOcrEngine(OcrSettings(lang="id", min_confidence=0.5), backend=backend)

    result = await engine.extract(_make_preprocessed(width=200, height=100))

    assert isinstance(result, OcrResult)
    assert result.language == "id"
    assert result.processing_ms >= 0.0
    assert len(result.lines) == 2
    assert result.lines[0].text == "REPUBLIK INDONESIA"
    assert result.lines[0].confidence == pytest.approx(0.98)
    assert result.lines[0].bbox == pytest.approx([0.1, 0.1, 0.9, 0.3])
    assert result.lines[1].text == "PROVINSI DKI JAKARTA"
    assert result.lines[1].bbox == pytest.approx([0.0, 0.4, 1.0, 0.6])
    assert result.raw_text == "REPUBLIK INDONESIA\nPROVINSI DKI JAKARTA"


async def test_paddleocr_v3_object_res_with_rec_boxes() -> None:
    result_obj = types.SimpleNamespace(
        res={
            "rec_texts": ["NIK", "3171012345678901"],
            "rec_scores": [0.95, 0.99],
            "rec_boxes": np.array([[10, 20, 50, 40], [60, 22, 190, 42]], dtype=np.float32),
        }
    )
    engine = PaddleOcrEngine(OcrSettings(lang="id"), backend=_FakePredictBackend([result_obj]))

    result = await engine.extract(_make_preprocessed(width=200, height=100))

    assert [line.text for line in result.lines] == ["NIK", "3171012345678901"]
    assert result.lines[0].bbox == pytest.approx([0.05, 0.2, 0.25, 0.4])
    assert result.lines[1].bbox == pytest.approx([0.3, 0.22, 0.95, 0.42])


@pytest.mark.parametrize("accept_cls", [True, False])
async def test_paddleocr_v2_ocr_response_parsing(accept_cls: bool) -> None:
    raw = [
        [
            [[[10, 10], [90, 10], [90, 25], [10, 25]], ("NAMA", 0.91)],
            [[[100, 12], [190, 12], [190, 27], [100, 27]], ("BUDI SANTOSO", 0.96)],
        ]
    ]
    backend = _FakeLegacyBackend(raw, accept_cls=accept_cls)
    engine = PaddleOcrEngine(OcrSettings(lang="id", use_angle_cls=True), backend=backend)

    result = await engine.extract(_make_preprocessed(width=200, height=100))

    assert [line.text for line in result.lines] == ["NAMA", "BUDI SANTOSO"]
    assert result.lines[0].bbox == pytest.approx([0.05, 0.1, 0.45, 0.25])
    assert result.lines[1].bbox == pytest.approx([0.5, 0.12, 0.95, 0.27])
    assert backend.cls_seen == ([True] if accept_cls else [None])


async def test_reading_order_sorts_rows_and_left_to_right_with_jitter() -> None:
    raw = [
        {
            "rec_texts": [
                "JAKARTA",
                "3171012345678901",
                "BUDI SANTOSO",
                "NIK",
                "NAMA",
                "ALAMAT",
            ],
            "rec_scores": [0.95, 0.99, 0.94, 0.97, 0.96, 0.93],
            # Intentionally shuffled across 3 rows with slight vertical jitter on the same row.
            "rec_boxes": [
                [80, 74, 180, 90],  # Row 3 right (y_center=0.82)
                [80, 12, 190, 28],  # Row 1 right (y_center=0.20, slight jitter vs 0.18)
                [80, 42, 185, 58],  # Row 2 right (y_center=0.50)
                [10, 10, 50, 26],  # Row 1 left (y_center=0.18)
                [10, 45, 60, 61],  # Row 2 left (y_center=0.53, slight jitter vs 0.50)
                [10, 72, 65, 88],  # Row 3 left (y_center=0.80)
            ],
        }
    ]
    engine = PaddleOcrEngine(OcrSettings(lang="id"), backend=_FakePredictBackend(raw))

    result = await engine.extract(_make_preprocessed(width=200, height=100))

    assert [line.text for line in result.lines] == [
        "NIK",
        "3171012345678901",
        "NAMA",
        "BUDI SANTOSO",
        "ALAMAT",
        "JAKARTA",
    ]
    assert result.raw_text == "NIK\n3171012345678901\nNAMA\nBUDI SANTOSO\nALAMAT\nJAKARTA"


async def test_filters_low_confidence_and_blank_lines() -> None:
    raw = [
        {
            "rec_texts": ["   ", "", "LOW_CONF", "  VALID LINE  ", "BORDERLINE"],
            "rec_scores": [0.99, 0.99, 0.59, 0.88, 0.60],
            "rec_boxes": [
                [10, 5, 50, 15],
                [10, 15, 50, 25],
                [10, 25, 80, 35],
                [10, 40, 120, 55],
                [10, 65, 120, 80],
            ],
        }
    ]
    engine = PaddleOcrEngine(
        OcrSettings(lang="id", min_confidence=0.6),
        backend=_FakePredictBackend(raw),
    )

    result = await engine.extract(_make_preprocessed(width=200, height=100))

    assert [line.text for line in result.lines] == ["VALID LINE", "BORDERLINE"]
    assert [line.confidence for line in result.lines] == pytest.approx([0.88, 0.60])


@pytest.mark.parametrize(
    "raw_output",
    [
        [],
        [None],
        None,
        [{"rec_texts": [], "rec_scores": [], "dt_polys": []}],
        [[]],
    ],
)
async def test_empty_ocr_outputs_return_empty_result(raw_output: Any) -> None:
    engine = PaddleOcrEngine(OcrSettings(lang="en"), backend=_FakePredictBackend(raw_output))

    result = await engine.extract(_make_preprocessed())

    assert result.lines == []
    assert result.raw_text == ""
    assert result.language == "en"
    assert result.processing_ms >= 0.0


@pytest.mark.parametrize("bad_bytes", [b"", b"not-a-valid-image-payload"])
async def test_invalid_or_empty_image_bytes_raises_invalid_image_error(bad_bytes: bytes) -> None:
    engine = PaddleOcrEngine(backend=_FakePredictBackend([]))

    with pytest.raises(InvalidImageError):
        await engine.extract(_make_preprocessed(image_bytes=bad_bytes))


async def test_backend_runtime_exception_wrapped_without_leaking_pii() -> None:
    engine = PaddleOcrEngine(backend=_RaisingBackend())

    with pytest.raises(ExtractionFailedError) as exc_info:
        await engine.extract(_make_preprocessed())

    assert "3171012345678901" not in exc_info.value.message
    assert "sensitive_nik" not in exc_info.value.message


async def test_singleton_warmup_and_repeated_extract_initialize_backend_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_calls: list[dict[str, Any]] = []

    class _FakePaddleOCR:
        def __init__(
            self,
            *,
            lang: str = "en",
            use_textline_orientation: bool = True,
            model_dir: str | None = None,
        ) -> None:
            init_calls.append(
                {
                    "lang": lang,
                    "use_textline_orientation": use_textline_orientation,
                    "model_dir": model_dir,
                }
            )

        def predict(self, image: np.ndarray[Any, Any]) -> list[dict[str, Any]]:
            return [
                {
                    "rec_texts": ["OK"],
                    "rec_scores": [0.99],
                    "rec_boxes": [[10, 10, 50, 30]],
                }
            ]

    fake_module = types.ModuleType("paddleocr")
    fake_module.PaddleOCR = _FakePaddleOCR  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake_module)

    engine = PaddleOcrEngine(
        OcrSettings(lang="id", use_angle_cls=False, model_dir="/app/.paddle_cache")
    )
    assert engine.is_ready is False

    engine.warmup()
    assert engine.is_ready is True
    engine.warmup()

    first = await engine.extract(_make_preprocessed())
    second = await engine.extract(_make_preprocessed())

    assert len(init_calls) == 1
    assert init_calls[0] == {
        "lang": "id",
        "use_textline_orientation": False,
        "model_dir": "/app/.paddle_cache",
    }
    assert first.raw_text == "OK"
    assert second.raw_text == "OK"


def test_missing_paddleocr_dependency_raises_extraction_failed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "paddleocr", None)
    engine = PaddleOcrEngine(OcrSettings(lang="id"))

    with pytest.raises(ExtractionFailedError, match="uv sync --extra ocr"):
        engine.warmup()

    assert engine.is_ready is False


def test_fastapi_lifespan_warms_up_engine_once_on_startup() -> None:
    warmup_calls = 0

    class _SpyOcrEngine:
        def warmup(self) -> None:
            nonlocal warmup_calls
            warmup_calls += 1

        async def extract(self, preprocessed: PreprocessedImage) -> OcrResult:
            return OcrResult()

    spy_engine = _SpyOcrEngine()
    application = create_app(settings=Settings(), ocr_engine=spy_engine)

    assert warmup_calls == 0
    with TestClient(application) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert application.state.ocr_engine is spy_engine
        assert warmup_calls == 1


def test_fastapi_lifespan_logs_warning_when_paddleocr_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setitem(sys.modules, "paddleocr", None)
    settings = Settings(ocr=OcrSettings(enabled=True, lang="id"))
    application = create_app(settings=settings)
    main_logger = logging.getLogger("app.main")
    main_logger.addHandler(caplog.handler)
    try:
        with (
            caplog.at_level(logging.WARNING, logger="app.main"),
            TestClient(application) as client,
        ):
            response = client.get("/health")
            assert response.status_code == 200
    finally:
        main_logger.removeHandler(caplog.handler)

    assert isinstance(application.state.ocr_engine, PaddleOcrEngine)
    assert application.state.ocr_engine.is_ready is False
    assert any(
        record.levelno == logging.WARNING and "Skipping OCR engine warmup" in record.message
        for record in caplog.records
    )
