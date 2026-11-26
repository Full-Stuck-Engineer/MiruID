"""Local in-memory PaddleOCR engine adapter."""

from __future__ import annotations

import asyncio
import inspect
import statistics
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any

import cv2
import numpy as np

from app.domain.exceptions import ExtractionFailedError, InvalidImageError
from app.domain.schemas import OcrLine, OcrResult, PreprocessedImage
from app.infrastructure.config import OcrSettings

_DEFAULT_ROW_TOLERANCE = 0.02
_MISSING_DEPS_MESSAGE = (
    "PaddleOCR optional dependencies are not installed. Install with 'uv sync --extra ocr'."
)


class PaddleOcrEngine:
    """In-memory local PaddleOCR adapter conforming to ``OcrEngine``."""

    def __init__(
        self,
        settings: OcrSettings | None = None,
        *,
        backend: Any | None = None,
    ) -> None:
        self._settings = settings if settings is not None else OcrSettings()
        self._backend: Any | None = backend
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        """Return whether the underlying PaddleOCR backend has been initialized."""
        return self._backend is not None

    def warmup(self) -> None:
        """Lazily initialize the singleton PaddleOCR backend in a thread-safe manner."""
        if self._backend is not None:
            return
        with self._lock:
            if self._backend is not None:
                return
            self._backend = self._create_backend()

    async def extract(self, preprocessed: PreprocessedImage) -> OcrResult:
        """Run OCR in a worker thread without blocking the asyncio event loop."""
        return await asyncio.to_thread(self._extract_sync, preprocessed)

    def _create_backend(self) -> Any:
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise ExtractionFailedError(_MISSING_DEPS_MESSAGE) from exc

        kwargs = self._build_backend_kwargs(PaddleOCR)
        try:
            return PaddleOCR(**kwargs)
        except TypeError:
            # Fallback for 2.x/3.x keyword argument differences when signature uses **kwargs.
            fallback_kwargs: dict[str, Any] = {"lang": self._settings.lang}
            if "use_textline_orientation" in kwargs:
                fallback_kwargs["use_angle_cls"] = self._settings.use_angle_cls
            try:
                return PaddleOCR(**fallback_kwargs)
            except Exception as fallback_exc:
                raise ExtractionFailedError(
                    "Failed to initialize PaddleOCR backend."
                ) from fallback_exc
        except Exception as exc:
            raise ExtractionFailedError("Failed to initialize PaddleOCR backend.") from exc

    def _build_backend_kwargs(self, paddle_cls: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"lang": self._settings.lang}
        try:
            params = inspect.signature(paddle_cls).parameters
        except (TypeError, ValueError):
            kwargs["use_textline_orientation"] = self._settings.use_angle_cls
            return kwargs

        has_var_keyword = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        if "use_textline_orientation" in params or has_var_keyword:
            kwargs["use_textline_orientation"] = self._settings.use_angle_cls
        elif "use_angle_cls" in params:
            kwargs["use_angle_cls"] = self._settings.use_angle_cls

        if "show_log" in params:
            kwargs["show_log"] = False

        if self._settings.model_dir and "model_dir" in params:
            kwargs["model_dir"] = self._settings.model_dir

        return kwargs

    def _extract_sync(self, preprocessed: PreprocessedImage) -> OcrResult:
        start = time.perf_counter()
        image = self._decode_image(preprocessed.image_bytes)
        height, width = int(image.shape[0]), int(image.shape[1])

        if self._backend is None:
            self.warmup()
        backend = self._backend

        try:
            raw_output = self._run_backend(backend, image)
            lines = self._parse_output(raw_output, width=width, height=height)
        except (InvalidImageError, ExtractionFailedError):
            raise
        except Exception as exc:
            raise ExtractionFailedError("OCR engine failed to extract text from image.") from exc

        sorted_lines = _sort_reading_order(lines)
        elapsed_ms = max(0.0, (time.perf_counter() - start) * 1000.0)
        return OcrResult(
            lines=sorted_lines,
            raw_text="\n".join(line.text for line in sorted_lines),
            language=self._settings.lang,
            processing_ms=elapsed_ms,
        )

    def _decode_image(self, image_bytes: bytes) -> np.ndarray[Any, Any]:
        if not image_bytes:
            raise InvalidImageError("Image payload is empty.")

        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None or image.size == 0 or image.ndim < 2:
            raise InvalidImageError("Unable to decode image payload for OCR.")
        if image.shape[0] <= 0 or image.shape[1] <= 0:
            raise InvalidImageError("Decoded image has invalid dimensions.")
        return image

    def _run_backend(self, backend: Any, image: np.ndarray[Any, Any]) -> Any:
        predict_fn = getattr(backend, "predict", None)
        if callable(predict_fn):
            return predict_fn(image)

        ocr_fn = getattr(backend, "ocr", None)
        if callable(ocr_fn):
            try:
                return ocr_fn(image, cls=self._settings.use_angle_cls)
            except TypeError:
                return ocr_fn(image)

        raise ExtractionFailedError("Configured OCR backend does not expose predict() or ocr().")

    def _parse_output(self, raw_output: Any, *, width: int, height: int) -> list[OcrLine]:
        if raw_output is None:
            return []

        if _is_v3_item(raw_output):
            return self._parse_v3_items([raw_output], width=width, height=height)

        if isinstance(raw_output, Iterable) and not isinstance(
            raw_output, (str, bytes, Mapping, np.ndarray)
        ):
            items = list(raw_output)
            if not items:
                return []
            if any(_is_v3_item(item) for item in items if item is not None):
                return self._parse_v3_items(items, width=width, height=height)
            return self._parse_v2_items(items, width=width, height=height)

        return []

    def _parse_v3_items(self, items: list[Any], *, width: int, height: int) -> list[OcrLine]:
        lines: list[OcrLine] = []
        for item in items:
            if item is None:
                continue
            texts = _get_v3_field(item, "rec_texts")
            scores = _get_v3_field(item, "rec_scores")
            boxes = _first_non_empty_v3_field(item, ("dt_polys", "rec_polys", "rec_boxes"))
            if texts is None:
                continue

            text_list = list(texts)
            score_list = list(scores) if scores is not None else [1.0] * len(text_list)
            box_list = list(boxes) if boxes is not None else [None] * len(text_list)

            for idx, text in enumerate(text_list):
                score = score_list[idx] if idx < len(score_list) else 0.0
                raw_box = box_list[idx] if idx < len(box_list) else None
                line = self._build_line(text, score, raw_box, width=width, height=height)
                if line is not None:
                    lines.append(line)
        return lines

    def _parse_v2_items(self, items: list[Any], *, width: int, height: int) -> list[OcrLine]:
        lines: list[OcrLine] = []
        for entry in items:
            if entry is None:
                continue
            if _is_v2_detection(entry):
                raw_box, (text, score) = entry[0], entry[1]
                line = self._build_line(text, score, raw_box, width=width, height=height)
                if line is not None:
                    lines.append(line)
                continue

            if isinstance(entry, Iterable) and not isinstance(entry, (str, bytes, Mapping)):
                for detection in entry:
                    if detection is None or not _is_v2_detection(detection):
                        continue
                    raw_box, (text, score) = detection[0], detection[1]
                    line = self._build_line(text, score, raw_box, width=width, height=height)
                    if line is not None:
                        lines.append(line)
        return lines

    def _build_line(
        self,
        text: Any,
        score: Any,
        raw_box: Any,
        *,
        width: int,
        height: int,
    ) -> OcrLine | None:
        if not isinstance(text, str):
            return None
        cleaned = text.strip()
        if not cleaned:
            return None

        confidence = float(score)
        if confidence < self._settings.min_confidence:
            return None

        clamped_confidence = _clamp01(confidence)
        bbox = _normalize_bbox(raw_box, width=width, height=height)
        return OcrLine(text=cleaned, confidence=clamped_confidence, bbox=bbox)


def _get_v3_field(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        if key in item:
            return item[key]
        res = item.get("res")
        if isinstance(res, Mapping) and key in res:
            return res[key]
        return None

    if hasattr(item, key):
        return getattr(item, key)

    res_attr = getattr(item, "res", None)
    if isinstance(res_attr, Mapping) and key in res_attr:
        return res_attr[key]

    return None


def _first_non_empty_v3_field(item: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = _get_v3_field(item, key)
        if value is None:
            continue
        if hasattr(value, "__len__") and len(value) == 0:
            continue
        return value
    return None


def _is_v3_item(item: Any) -> bool:
    return _get_v3_field(item, "rec_texts") is not None


def _is_v2_detection(item: Any) -> bool:
    if not isinstance(item, (list, tuple)) or len(item) != 2:
        return False
    text_score = item[1]
    return (
        isinstance(text_score, (list, tuple))
        and len(text_score) == 2
        and isinstance(text_score[0], str)
    )


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _normalize_bbox(raw_box: Any, *, width: int, height: int) -> list[float] | None:
    if raw_box is None or width <= 0 or height <= 0:
        return None

    box = raw_box.tolist() if hasattr(raw_box, "tolist") else raw_box
    if not isinstance(box, (list, tuple)) or not box:
        return None

    # Case 1: flat [x_min, y_min, x_max, y_max] box (e.g., PaddleOCR 3.x rec_boxes).
    if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
        xs = [float(box[0]), float(box[2])]
        ys = [float(box[1]), float(box[3])]
    else:
        # Case 2: polygon of [x, y] points (e.g., dt_polys or PaddleOCR 2.x quad).
        try:
            xs = [float(pt[0]) for pt in box]
            ys = [float(pt[1]) for pt in box]
        except (TypeError, IndexError, ValueError):
            return None

    if not xs or not ys:
        return None

    x_min = _clamp01(min(xs) / width)
    y_min = _clamp01(min(ys) / height)
    x_max = _clamp01(max(xs) / width)
    y_max = _clamp01(max(ys) / height)
    return [x_min, y_min, x_max, y_max]


def _sort_reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    if len(lines) <= 1:
        return lines

    with_bbox: list[tuple[OcrLine, float, float, float]] = []
    without_bbox: list[OcrLine] = []

    for line in lines:
        if line.bbox is not None and len(line.bbox) == 4:
            x_min, y_min, _, y_max = line.bbox
            y_center = (y_min + y_max) / 2.0
            line_height = max(0.0, y_max - y_min)
            with_bbox.append((line, y_center, x_min, line_height))
        else:
            without_bbox.append(line)

    if len(with_bbox) <= 1:
        return [item[0] for item in with_bbox] + without_bbox

    positive_heights = [item[3] for item in with_bbox if item[3] > 0.0]
    row_tolerance = (
        statistics.median(positive_heights) / 2.0 if positive_heights else _DEFAULT_ROW_TOLERANCE
    )
    if row_tolerance <= 0.0:
        row_tolerance = _DEFAULT_ROW_TOLERANCE

    with_bbox.sort(key=lambda item: (item[1], item[2]))

    bands: list[list[tuple[OcrLine, float, float, float]]] = []
    band_y_means: list[float] = []

    for item in with_bbox:
        _, y_center, _, _ = item
        if bands and abs(y_center - band_y_means[-1]) <= row_tolerance:
            bands[-1].append(item)
            band_y_means[-1] = sum(entry[1] for entry in bands[-1]) / len(bands[-1])
        else:
            bands.append([item])
            band_y_means.append(y_center)

    ordered: list[OcrLine] = []
    for band in bands:
        band.sort(key=lambda entry: entry[2])
        ordered.extend(entry[0] for entry in band)

    ordered.extend(without_bbox)
    return ordered
