"""CLI for generating a deterministic synthetic Indonesian ID card dataset.

Usage:
    uv run python scripts/generate_synthetic_ids.py --seed 42 --count 3 --preset mixed
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Ensure repo root is importable when invoked directly as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.renderers import (  # noqa: E402
    generate_ktp_record,
    generate_npwp_record,
    generate_sim_record,
)
from scripts.renderers.degradations import (  # noqa: E402
    DEGRADATION_PRESETS,
    apply_degradation,
    image_to_jpeg_bytes,
)
from scripts.renderers.ktp import render_ktp  # noqa: E402
from scripts.renderers.npwp import render_npwp  # noqa: E402
from scripts.renderers.sim import render_sim  # noqa: E402

_SUPPORTED_DOC_TYPES = ("ktp", "sim", "npwp")
_PRESET_CHOICES = (*DEGRADATION_PRESETS, "mixed")


def _parse_doc_types(raw: str) -> list[str]:
    doc_types = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not doc_types:
        raise ValueError("--doc-types must specify at least one document type.")
    invalid = [item for item in doc_types if item not in _SUPPORTED_DOC_TYPES]
    if invalid:
        raise ValueError(f"Unsupported doc types {invalid}. Choose from {_SUPPORTED_DOC_TYPES}.")
    return doc_types


def generate_dataset(
    *,
    output_dir: Path,
    seed: int = 42,
    count: int = 3,
    doc_types: Sequence[str] = _SUPPORTED_DOC_TYPES,
    preset: str = "clean",
) -> dict[str, Any]:
    """Generate synthetic ID JPEG files and write manifest.json to output_dir."""
    if count <= 0:
        raise ValueError("--count must be a positive integer.")
    if preset not in _PRESET_CHOICES:
        raise ValueError(f"Unsupported preset '{preset}'. Choose from {_PRESET_CHOICES}.")

    output_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []

    for type_idx, doc_type in enumerate(doc_types):
        for idx in range(count):
            item_seed = seed * 10_000 + type_idx * 1_000 + idx
            item_preset = (
                DEGRADATION_PRESETS[idx % len(DEGRADATION_PRESETS)] if preset == "mixed" else preset
            )

            if doc_type == "ktp":
                ktp_record = generate_ktp_record(seed=item_seed)
                base_image = render_ktp(ktp_record)
                expected = ktp_record.to_dict()
            elif doc_type == "sim":
                sim_record = generate_sim_record(seed=item_seed)
                base_image = render_sim(sim_record)
                expected = sim_record.to_dict()
            else:
                npwp_record = generate_npwp_record(seed=item_seed)
                base_image = render_npwp(npwp_record)
                expected = npwp_record.to_dict()

            degraded = apply_degradation(base_image, preset=item_preset, seed=item_seed)
            filename = f"{doc_type}_{idx:03d}_{item_preset}.jpg"
            (output_dir / filename).write_bytes(image_to_jpeg_bytes(degraded))

            items.append(
                {
                    "filename": filename,
                    "country": "IDN",
                    "doc_type": doc_type.upper(),
                    "preset": item_preset,
                    "seed": item_seed,
                    "expected": expected,
                }
            )

    manifest: dict[str, Any] = {
        "seed": seed,
        "count_per_doc_type": count,
        "preset": preset,
        "total_images": len(items),
        "items": items,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser for synthetic dataset generation."""
    parser = argparse.ArgumentParser(
        description="Generate a safe, deterministic synthetic Indonesian ID card dataset.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Base RNG seed (default: 42).")
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of cards to generate per document type (default: 3).",
    )
    parser.add_argument(
        "--doc-types",
        type=str,
        default="ktp,sim,npwp",
        help="Comma-separated document types: ktp,sim,npwp (default: ktp,sim,npwp).",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default="clean",
        choices=_PRESET_CHOICES,
        help="Image degradation preset or 'mixed' (default: clean).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tests/synthetic_dataset"),
        help="Output directory for JPEG images and manifest.json.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    doc_types = _parse_doc_types(args.doc_types)
    manifest = generate_dataset(
        output_dir=args.output_dir,
        seed=args.seed,
        count=args.count,
        doc_types=doc_types,
        preset=args.preset,
    )
    print(
        f"Generated {manifest['total_images']} synthetic ID images in {args.output_dir} "
        f"(seed={args.seed}, preset={args.preset})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
