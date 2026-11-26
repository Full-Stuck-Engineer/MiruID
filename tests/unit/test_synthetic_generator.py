"""Unit tests for the synthetic Indonesian ID card generator and fixtures."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.domain.exceptions import ImageTooBlurryError
from app.infrastructure.config import QualityGateSettings
from app.infrastructure.engines.preprocessor import OpenCVPreprocessor
from app.plugins.idn.ktp import IndonesiaKtpPlugin
from app.plugins.idn.npwp import IndonesiaNpwpPlugin
from app.plugins.idn.sim import IndonesiaSimPlugin
from scripts.generate_synthetic_ids import main
from scripts.renderers import (
    CARD_HEIGHT,
    CARD_WIDTH,
    generate_ktp_record,
    generate_npwp_record,
    generate_sim_record,
)
from scripts.renderers.degradations import DEGRADATION_PRESETS
from tests.fixtures.synthetic import (
    generate_synthetic_ktp_bytes,
    generate_synthetic_npwp_bytes,
    generate_synthetic_sim_bytes,
)


@pytest.mark.unit
class TestSeedDeterminism:
    """Same seed must produce identical records and JPEG bytes."""

    def test_ktp_seed_determinism(self) -> None:
        img_a, rec_a = generate_synthetic_ktp_bytes(seed=101, preset="clean")
        img_b, rec_b = generate_synthetic_ktp_bytes(seed=101, preset="clean")
        _, rec_c = generate_synthetic_ktp_bytes(seed=202, preset="clean")

        assert rec_a == rec_b
        assert img_a == img_b
        assert rec_a != rec_c

    def test_sim_seed_determinism(self) -> None:
        img_a, rec_a = generate_synthetic_sim_bytes(seed=303, preset="tilted")
        img_b, rec_b = generate_synthetic_sim_bytes(seed=303, preset="tilted")

        assert rec_a == rec_b
        assert img_a == img_b

    def test_npwp_seed_determinism(self) -> None:
        img_a, rec_a = generate_synthetic_npwp_bytes(seed=404, preset="glare")
        img_b, rec_b = generate_synthetic_npwp_bytes(seed=404, preset="glare")

        assert rec_a == rec_b
        assert img_a == img_b


@pytest.mark.unit
class TestPluginValidatorCompliance:
    """100% of generated ground-truth records must pass MiruID plugin validators."""

    def test_ktp_records_pass_plugin_validation(self) -> None:
        plugin = IndonesiaKtpPlugin()
        genders_seen: set[str] = set()

        for seed in range(1, 31):
            record = generate_ktp_record(seed=seed)
            genders_seen.add(record.gender)
            result = plugin.validate(record.to_schema())
            assert result.is_valid, f"Seed {seed} failed KTP validation: {result.checks}"

        assert genders_seen == {"LAKI-LAKI", "PEREMPUAN"}

    @pytest.mark.parametrize("variant", ["legacy", "nik_linked"])
    def test_sim_records_pass_plugin_validation(self, variant: str) -> None:
        plugin = IndonesiaSimPlugin()

        for seed in range(1, 21):
            record = generate_sim_record(seed=seed, variant=variant)  # type: ignore[arg-type]
            result = plugin.validate(record.to_schema())
            assert result.is_valid, (
                f"Seed {seed} ({variant}) failed SIM validation: {result.checks}"
            )
            if variant == "legacy":
                assert 12 <= len(record.sim_number) <= 14
            else:
                assert len(record.sim_number) == 16

    @pytest.mark.parametrize("variant", ["legacy_15", "individual_16", "corporate_16"])
    def test_npwp_records_pass_plugin_validation(self, variant: str) -> None:
        plugin = IndonesiaNpwpPlugin()

        for seed in range(1, 21):
            record = generate_npwp_record(seed=seed, variant=variant)  # type: ignore[arg-type]
            result = plugin.validate(record.to_schema())
            assert result.is_valid, (
                f"Seed {seed} ({variant}) failed NPWP validation: {result.checks}"
            )
            if variant == "legacy_15":
                assert record.npwp_15 is not None
                assert record.npwp_16 is None
            elif variant == "individual_16":
                assert record.npwp_16 is not None
                assert not record.npwp_16.startswith("0")
            else:
                assert record.npwp_16 is not None
                assert record.npwp_16.startswith("0")


@pytest.mark.unit
class TestDegradationPresets:
    """Degradation presets must produce valid ID-1 images and trigger quality gates."""

    @pytest.mark.parametrize("preset", DEGRADATION_PRESETS)
    def test_all_presets_render_valid_id1_jpegs(self, preset: str) -> None:
        jpeg_bytes, _ = generate_synthetic_ktp_bytes(seed=42, preset=preset)
        assert jpeg_bytes.startswith(b"\xff\xd8")
        with Image.open(io.BytesIO(jpeg_bytes)) as img:
            assert img.size == (CARD_WIDTH, CARD_HEIGHT)

    async def test_clean_preset_passes_preprocessor_quality_gate(self) -> None:
        preprocessor = OpenCVPreprocessor(QualityGateSettings(strict_quality_gate=True))
        for generator in (
            generate_synthetic_ktp_bytes,
            generate_synthetic_sim_bytes,
            generate_synthetic_npwp_bytes,
        ):
            jpeg_bytes, _ = generator(seed=42, preset="clean")
            preprocessed = await preprocessor.preprocess(jpeg_bytes)
            assert not preprocessed.quality.is_blurry
            assert not preprocessed.quality.has_glare
            assert preprocessed.quality.is_acceptable

    async def test_blurry_preset_triggers_image_too_blurry_error(self) -> None:
        preprocessor = OpenCVPreprocessor(QualityGateSettings(strict_quality_gate=True))
        for generator in (
            generate_synthetic_ktp_bytes,
            generate_synthetic_sim_bytes,
            generate_synthetic_npwp_bytes,
        ):
            jpeg_bytes, _ = generator(seed=42, preset="blurry")
            with pytest.raises(ImageTooBlurryError):
                await preprocessor.preprocess(jpeg_bytes)

    async def test_glare_preset_triggers_has_glare(self) -> None:
        preprocessor = OpenCVPreprocessor(QualityGateSettings(strict_quality_gate=True))
        for generator in (
            generate_synthetic_ktp_bytes,
            generate_synthetic_sim_bytes,
            generate_synthetic_npwp_bytes,
        ):
            jpeg_bytes, _ = generator(seed=42, preset="glare")
            preprocessed = await preprocessor.preprocess(jpeg_bytes)
            assert preprocessed.quality.has_glare is True

    async def test_low_light_preset_reduces_brightness(self) -> None:
        settings = QualityGateSettings(strict_quality_gate=False)
        preprocessor = OpenCVPreprocessor(settings)
        jpeg_bytes, _ = generate_synthetic_ktp_bytes(seed=42, preset="low_light")
        preprocessed = await preprocessor.preprocess(jpeg_bytes)
        assert preprocessed.quality.brightness is not None
        assert preprocessed.quality.brightness < settings.min_brightness


@pytest.mark.unit
class TestSyntheticGeneratorCli:
    """CLI must write JPEG files and a valid manifest.json into the target directory."""

    def test_cli_generates_images_and_manifest(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "dataset"
        exit_code = main(
            [
                "--seed",
                "77",
                "--count",
                "2",
                "--doc-types",
                "ktp,sim,npwp",
                "--preset",
                "mixed",
                "--output-dir",
                str(out_dir),
            ]
        )
        assert exit_code == 0

        manifest_path = out_dir / "manifest.json"
        assert manifest_path.is_file()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["seed"] == 77
        assert manifest["count_per_doc_type"] == 2
        assert manifest["preset"] == "mixed"
        assert manifest["total_images"] == 6
        assert len(manifest["items"]) == 6

        doc_types_seen = {item["doc_type"] for item in manifest["items"]}
        assert doc_types_seen == {"KTP", "SIM", "NPWP"}

        for item in manifest["items"]:
            assert item["country"] == "IDN"
            assert item["preset"] in DEGRADATION_PRESETS
            img_path = out_dir / item["filename"]
            assert img_path.is_file()
            assert img_path.read_bytes().startswith(b"\xff\xd8")
            assert isinstance(item["expected"], dict)
