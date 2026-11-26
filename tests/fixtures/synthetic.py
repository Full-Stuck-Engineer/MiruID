"""In-memory synthetic ID card generators for unit and integration tests.

Zero disk writes: all functions return (jpeg_bytes, ground_truth_record).
"""

from __future__ import annotations

from scripts.renderers import (
    KtpRecord,
    NpwpRecord,
    NpwpVariant,
    SimRecord,
    SimVariant,
    generate_ktp_record,
    generate_npwp_record,
    generate_sim_record,
)
from scripts.renderers.degradations import apply_degradation, image_to_jpeg_bytes
from scripts.renderers.ktp import render_ktp
from scripts.renderers.npwp import render_npwp
from scripts.renderers.sim import render_sim


def generate_synthetic_ktp_bytes(
    *,
    seed: int = 42,
    preset: str = "clean",
) -> tuple[bytes, KtpRecord]:
    """Generate an in-memory synthetic e-KTP JPEG image and its ground-truth record."""
    record = generate_ktp_record(seed=seed)
    image = apply_degradation(render_ktp(record), preset=preset, seed=seed)
    return image_to_jpeg_bytes(image), record


def generate_synthetic_sim_bytes(
    *,
    seed: int = 42,
    preset: str = "clean",
    variant: SimVariant | None = None,
) -> tuple[bytes, SimRecord]:
    """Generate an in-memory synthetic SIM JPEG image and its ground-truth record."""
    record = generate_sim_record(seed=seed, variant=variant)
    image = apply_degradation(render_sim(record), preset=preset, seed=seed)
    return image_to_jpeg_bytes(image), record


def generate_synthetic_npwp_bytes(
    *,
    seed: int = 42,
    preset: str = "clean",
    variant: NpwpVariant | None = None,
) -> tuple[bytes, NpwpRecord]:
    """Generate an in-memory synthetic NPWP JPEG image and its ground-truth record."""
    record = generate_npwp_record(seed=seed, variant=variant)
    image = apply_degradation(render_npwp(record), preset=preset, seed=seed)
    return image_to_jpeg_bytes(image), record


__all__ = [
    "generate_synthetic_ktp_bytes",
    "generate_synthetic_npwp_bytes",
    "generate_synthetic_sim_bytes",
]
