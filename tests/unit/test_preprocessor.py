"""Unit tests for the in-memory OpenCVPreprocessor and QualityGateSettings."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.domain.exceptions import ImageTooBlurryError, InvalidImageError
from app.domain.interfaces import ImagePreprocessor
from app.domain.schemas import PreprocessedImage
from app.infrastructure.config import QualityGateSettings
from app.infrastructure.engines.preprocessor import OpenCVPreprocessor

pytestmark = pytest.mark.unit

_EXIF_ORIENTATION_TAG = 274


def _encode_image_bytes(
    image: Image.Image,
    *,
    image_format: str = "JPEG",
    exif: Image.Exif | None = None,
    quality: int = 95,
) -> bytes:
    """Encode a Pillow image strictly in memory."""
    buf = io.BytesIO()
    save_kwargs: dict[str, object] = {"format": image_format}
    if image_format.upper() == "JPEG":
        save_kwargs["quality"] = quality
    if exif is not None:
        save_kwargs["exif"] = exif.tobytes()
    image.save(buf, **save_kwargs)  # type: ignore[arg-type]
    return buf.getvalue()


def _make_sharp_card_image(
    width: int = 640,
    height: int = 400,
    *,
    bg: int = 128,
    fg: int = 20,
    accent: int = 230,
) -> Image.Image:
    """Generate a high-contrast synthetic ID card image in memory."""
    img = Image.new("RGB", (width, height), color=(bg, bg, bg))
    draw = ImageDraw.Draw(img)

    step = 16
    for x in range(0, width, step):
        color = (fg, fg, fg) if (x // step) % 2 == 0 else (accent, accent, accent)
        draw.line([(x, 0), (x, height)], fill=color, width=2)
    for y in range(0, height, step):
        color = (accent, accent, accent) if (y // step) % 2 == 0 else (fg, fg, fg)
        draw.line([(0, y), (width, y)], fill=color, width=2)

    draw.rectangle([24, 24, width - 24, height - 24], outline=(fg, fg, fg), width=4)
    draw.text((40, 48), "MIRUID SYNTHETIC CARD 1234567890", fill=(fg, fg, fg))
    draw.text((40, 88), "NAME: TEST HOLDER / DOB: 1990-01-01", fill=(accent, accent, accent))
    return img


def test_structural_conformance_with_image_preprocessor_protocol() -> None:
    preprocessor = OpenCVPreprocessor(QualityGateSettings())
    assert isinstance(preprocessor, ImagePreprocessor)
    assert isinstance(OpenCVPreprocessor(), ImagePreprocessor)


async def test_sharp_synthetic_card_passes_quality_gate() -> None:
    payload = _encode_image_bytes(_make_sharp_card_image(640, 400))
    preprocessor = OpenCVPreprocessor(QualityGateSettings())

    result = await preprocessor.preprocess(payload)

    assert isinstance(result, PreprocessedImage)
    assert result.mime_type == "image/jpeg"
    assert result.width == 640
    assert result.height == 400
    assert result.orientation_corrected is False
    assert result.quality.is_blurry is False
    assert result.quality.has_glare is False
    assert result.quality.is_acceptable is True
    assert result.quality.blur_score >= 100.0
    assert result.quality.brightness is not None
    assert 40.0 <= result.quality.brightness <= 220.0

    with Image.open(io.BytesIO(result.image_bytes)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.size == (640, 400)


async def test_blurred_image_raises_when_strict_quality_gate_enabled() -> None:
    blurred = _make_sharp_card_image(480, 320).filter(ImageFilter.GaussianBlur(radius=12))
    payload = _encode_image_bytes(blurred)
    settings = QualityGateSettings(min_blur_score=100.0, strict_quality_gate=True)
    preprocessor = OpenCVPreprocessor(settings)

    with pytest.raises(ImageTooBlurryError) as exc_info:
        await preprocessor.preprocess(payload)

    assert exc_info.value.details is not None
    assert "blur_score" in exc_info.value.details
    assert "threshold" in exc_info.value.details
    assert exc_info.value.details["threshold"] == 100.0
    assert exc_info.value.details["blur_score"] < 100.0


async def test_blurred_image_returns_result_when_strict_quality_gate_disabled() -> None:
    blurred = _make_sharp_card_image(480, 320).filter(ImageFilter.GaussianBlur(radius=12))
    payload = _encode_image_bytes(blurred)
    settings = QualityGateSettings(min_blur_score=100.0, strict_quality_gate=False)
    preprocessor = OpenCVPreprocessor(settings)

    result = await preprocessor.preprocess(payload)

    assert isinstance(result, PreprocessedImage)
    assert result.quality.is_blurry is True
    assert result.quality.is_acceptable is False
    assert result.quality.blur_score < settings.min_blur_score


async def test_glare_overexposed_region_sets_has_glare_without_raising() -> None:
    img = _make_sharp_card_image(600, 400, bg=110, fg=20, accent=180)
    arr = np.array(img, dtype=np.uint8)
    # Paint a large pure-white glare patch (~25% of pixels >= 250).
    arr[0:200, 0:300, :] = 255
    payload = _encode_image_bytes(Image.fromarray(arr, mode="RGB"), image_format="PNG")

    settings = QualityGateSettings(
        glare_pixel_ratio_threshold=0.05,
        strict_quality_gate=True,
    )
    preprocessor = OpenCVPreprocessor(settings)

    result = await preprocessor.preprocess(payload)

    assert result.quality.is_blurry is False
    assert result.quality.has_glare is True
    assert result.quality.glare_ratio >= settings.glare_pixel_ratio_threshold
    assert result.quality.is_acceptable is False


async def test_dark_underexposed_image_marks_unacceptable() -> None:
    # Dark high-contrast pattern: mean brightness well below 40, but sharp edges.
    img = _make_sharp_card_image(480, 320, bg=8, fg=0, accent=36)
    payload = _encode_image_bytes(img, image_format="PNG")
    settings = QualityGateSettings(min_brightness=40.0, strict_quality_gate=False)
    preprocessor = OpenCVPreprocessor(settings)

    result = await preprocessor.preprocess(payload)

    assert result.quality.brightness is not None
    assert result.quality.brightness < settings.min_brightness
    assert result.quality.is_acceptable is False


async def test_aspect_ratio_preserving_downscale_and_no_upscale() -> None:
    large_payload = _encode_image_bytes(_make_sharp_card_image(2400, 1200))
    small_payload = _encode_image_bytes(_make_sharp_card_image(400, 200))
    settings = QualityGateSettings(max_image_dim=1200, strict_quality_gate=False)
    preprocessor = OpenCVPreprocessor(settings)

    downscaled = await preprocessor.preprocess(large_payload)
    assert (downscaled.width, downscaled.height) == (1200, 600)
    assert (downscaled.quality.width, downscaled.quality.height) == (1200, 600)

    untouched = await preprocessor.preprocess(small_payload)
    assert (untouched.width, untouched.height) == (400, 200)
    assert (untouched.quality.width, untouched.quality.height) == (400, 200)


async def test_exif_orientation_transposes_upright_and_tracks_flag() -> None:
    raw_img = _make_sharp_card_image(400, 600)

    rotated_exif = Image.Exif()
    rotated_exif[_EXIF_ORIENTATION_TAG] = 6  # 90° CW -> dims swap to 600x400
    rotated_payload = _encode_image_bytes(raw_img, image_format="JPEG", exif=rotated_exif)

    normal_exif = Image.Exif()
    normal_exif[_EXIF_ORIENTATION_TAG] = 1
    normal_payload = _encode_image_bytes(raw_img, image_format="JPEG", exif=normal_exif)

    preprocessor = OpenCVPreprocessor(QualityGateSettings(strict_quality_gate=False))

    rotated_result = await preprocessor.preprocess(rotated_payload)
    assert rotated_result.orientation_corrected is True
    assert (rotated_result.width, rotated_result.height) == (600, 400)

    normal_result = await preprocessor.preprocess(normal_payload)
    assert normal_result.orientation_corrected is False
    assert (normal_result.width, normal_result.height) == (400, 600)


@pytest.mark.parametrize("apply_clahe", [True, False])
async def test_clahe_toggle_paths_succeed(apply_clahe: bool) -> None:
    payload = _encode_image_bytes(_make_sharp_card_image(480, 320))
    settings = QualityGateSettings(apply_clahe=apply_clahe)
    preprocessor = OpenCVPreprocessor(settings)

    result = await preprocessor.preprocess(payload)

    assert result.mime_type == "image/jpeg"
    assert result.quality.is_acceptable is True
    with Image.open(io.BytesIO(result.image_bytes)) as decoded:
        assert decoded.format == "JPEG"
        assert decoded.size == (480, 320)


async def test_empty_corrupted_and_oversized_payloads_raise_invalid_image_error() -> None:
    preprocessor = OpenCVPreprocessor(QualityGateSettings(max_image_size_mb=1))

    with pytest.raises(InvalidImageError, match="empty"):
        await preprocessor.preprocess(b"")

    with pytest.raises(InvalidImageError, match="decode"):
        await preprocessor.preprocess(b"not-a-valid-image-payload")

    oversized_payload = b"\x00" * (1024 * 1024 + 1)
    with pytest.raises(InvalidImageError, match="maximum allowed size") as exc_info:
        await preprocessor.preprocess(oversized_payload)
    assert exc_info.value.details is not None
    assert exc_info.value.details["max_bytes"] == 1024 * 1024


def test_blur_threshold_and_min_blur_score_env_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BLUR_THRESHOLD", raising=False)
    monkeypatch.delenv("MIN_BLUR_SCORE", raising=False)

    monkeypatch.setenv("MIN_BLUR_SCORE", "145.5")
    assert QualityGateSettings().min_blur_score == pytest.approx(145.5)

    monkeypatch.setenv("BLUR_THRESHOLD", "210.25")
    assert QualityGateSettings().min_blur_score == pytest.approx(210.25)

    monkeypatch.delenv("MIN_BLUR_SCORE", raising=False)
    assert QualityGateSettings().min_blur_score == pytest.approx(210.25)
