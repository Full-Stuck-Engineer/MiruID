"""Pillow and NumPy image degradation presets for synthetic ID card testing."""

from __future__ import annotations

import io
import random
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DegradationPreset = Literal["clean", "tilted", "blurry", "glare", "low_light"]

DEGRADATION_PRESETS: tuple[DegradationPreset, ...] = (
    "clean",
    "tilted",
    "blurry",
    "glare",
    "low_light",
)


def apply_degradation(
    image: Image.Image,
    preset: str = "clean",
    *,
    seed: int = 0,
) -> Image.Image:
    """Apply a deterministic image degradation preset to a rendered ID card."""
    rgb = image.convert("RGB")

    if preset == "clean":
        return rgb.copy()

    if preset == "tilted":
        rng = random.Random(seed)
        angle = rng.choice((-7.0, -5.0, 5.0, 7.0))
        return rgb.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=False,
            fillcolor=(32, 36, 42),
        )

    if preset == "blurry":
        return rgb.filter(ImageFilter.GaussianBlur(radius=8.0))

    if preset == "glare":
        glared = rgb.copy()
        draw = ImageDraw.Draw(glared)
        width, height = glared.size
        rng = random.Random(seed)
        cx = int(width * rng.uniform(0.32, 0.58))
        cy = int(height * rng.uniform(0.32, 0.58))
        rx = int(width * 0.24)
        ry = int(height * 0.28)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(255, 255, 255))
        return glared

    if preset == "low_light":
        arr = np.asarray(rgb, dtype=np.float32)
        darkened = np.clip(arr * 0.16, 0.0, 255.0).astype(np.uint8)
        return Image.fromarray(darkened, mode="RGB")

    raise ValueError(
        f"Unsupported degradation preset '{preset}'. Expected one of {DEGRADATION_PRESETS}."
    )


def image_to_jpeg_bytes(image: Image.Image, *, quality: int = 92) -> bytes:
    """Encode a PIL image to deterministic in-memory JPEG bytes."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


__all__ = [
    "DEGRADATION_PRESETS",
    "DegradationPreset",
    "apply_degradation",
    "image_to_jpeg_bytes",
]
