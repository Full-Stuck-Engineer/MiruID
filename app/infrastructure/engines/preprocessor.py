"""In-memory OpenCV & Pillow image preprocessor and quality gate."""

from __future__ import annotations

import asyncio
import io
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from app.domain.exceptions import ImageTooBlurryError, InvalidImageError
from app.domain.schemas import PreprocessedImage, QualityMetrics
from app.infrastructure.config import QualityGateSettings

_EXIF_ORIENTATION_TAG = 274
_GLARE_PIXEL_VALUE = 250
_JPEG_QUALITY = 95
_CLAHE_CLIP_LIMIT = 2.0
_CLAHE_TILE_GRID_SIZE = (8, 8)
_BYTES_PER_MB = 1024 * 1024


class OpenCVPreprocessor:
    """In-memory image preprocessor conforming to ``ImagePreprocessor``."""

    def __init__(self, settings: QualityGateSettings | None = None) -> None:
        self._settings = settings if settings is not None else QualityGateSettings()

    async def preprocess(self, image_bytes: bytes) -> PreprocessedImage:
        """Decode, orient, resize, quality-gate, and normalize an image in memory."""
        return await asyncio.to_thread(self._preprocess_sync, image_bytes)

    def _preprocess_sync(self, image_bytes: bytes) -> PreprocessedImage:
        self._validate_payload(image_bytes)
        bgr, orientation_corrected = self._decode_and_orient(image_bytes)
        bgr = self._resize_if_needed(bgr)
        quality = self._measure_quality(bgr)

        if self._settings.strict_quality_gate and quality.is_blurry:
            raise ImageTooBlurryError(
                "Image is too blurry for reliable extraction.",
                details={
                    "blur_score": round(quality.blur_score, 2),
                    "threshold": self._settings.min_blur_score,
                },
            )

        if self._settings.apply_clahe:
            bgr = self._apply_clahe(bgr)

        encoded_bytes = self._encode_jpeg(bgr)
        height, width = bgr.shape[:2]
        return PreprocessedImage(
            image_bytes=encoded_bytes,
            mime_type="image/jpeg",
            width=int(width),
            height=int(height),
            quality=quality,
            orientation_corrected=orientation_corrected,
        )

    def _validate_payload(self, image_bytes: bytes) -> None:
        if not image_bytes:
            raise InvalidImageError("Image payload is empty.")

        max_bytes = self._settings.max_image_size_mb * _BYTES_PER_MB
        if len(image_bytes) > max_bytes:
            raise InvalidImageError(
                "Image payload exceeds maximum allowed size.",
                details={
                    "size_bytes": len(image_bytes),
                    "max_bytes": max_bytes,
                },
            )

    def _decode_and_orient(self, image_bytes: bytes) -> tuple[np.ndarray[Any, Any], bool]:
        try:
            with Image.open(io.BytesIO(image_bytes)) as pil_img:
                exif = pil_img.getexif()
                orientation = exif.get(_EXIF_ORIENTATION_TAG, 1)
                orientation_corrected = orientation != 1
                transposed = ImageOps.exif_transpose(pil_img)
                rgb_img = (transposed if transposed is not None else pil_img).convert("RGB")
                rgb_array = np.asarray(rgb_img, dtype=np.uint8)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise InvalidImageError("Unable to decode image payload.") from exc

        if rgb_array.ndim != 3 or rgb_array.shape[0] == 0 or rgb_array.shape[1] == 0:
            raise InvalidImageError("Decoded image has invalid dimensions.")

        bgr: np.ndarray[Any, Any] = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
        return bgr, orientation_corrected

    def _resize_if_needed(self, bgr: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        height, width = bgr.shape[:2]
        longest_side = max(height, width)
        max_dim = self._settings.max_image_dim
        if longest_side <= max_dim:
            return bgr

        scale = max_dim / float(longest_side)
        new_width = max(1, int(round(width * scale)))
        new_height = max(1, int(round(height * scale)))
        resized: np.ndarray[Any, Any] = cv2.resize(
            bgr,
            (new_width, new_height),
            interpolation=cv2.INTER_AREA,
        )
        return resized

    def _measure_quality(self, bgr: np.ndarray[Any, Any]) -> QualityMetrics:
        height, width = bgr.shape[:2]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        glare_ratio = float(np.mean(gray >= _GLARE_PIXEL_VALUE))

        is_blurry = blur_score < self._settings.min_blur_score
        has_glare = glare_ratio >= self._settings.glare_pixel_ratio_threshold
        brightness_ok = self._settings.min_brightness <= brightness <= self._settings.max_brightness
        is_acceptable = not (is_blurry or has_glare or not brightness_ok)

        return QualityMetrics(
            blur_score=blur_score,
            brightness=brightness,
            glare_ratio=glare_ratio,
            width=int(width),
            height=int(height),
            is_blurry=is_blurry,
            has_glare=has_glare,
            is_acceptable=is_acceptable,
        )

    def _apply_clahe(self, bgr: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(
            clipLimit=_CLAHE_CLIP_LIMIT,
            tileGridSize=_CLAHE_TILE_GRID_SIZE,
        )
        enhanced_l = clahe.apply(l_channel)
        merged_lab = cv2.merge((enhanced_l, a_channel, b_channel))
        enhanced_bgr: np.ndarray[Any, Any] = cv2.cvtColor(merged_lab, cv2.COLOR_LAB2BGR)
        return enhanced_bgr

    def _encode_jpeg(self, bgr: np.ndarray[Any, Any]) -> bytes:
        success, encoded = cv2.imencode(
            ".jpg",
            bgr,
            [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY],
        )
        if not success:
            raise InvalidImageError("Failed to encode preprocessed image as JPEG.")
        return bytes(encoded.tobytes())
