"""Unit tests for HeuristicDocumentClassifier."""

from __future__ import annotations

import time
from collections.abc import Sequence

import pytest
from pydantic import BaseModel

from app.domain.interfaces import DocumentClassifier, DocumentPlugin
from app.domain.schemas import ClassificationRule, OcrLine, OcrResult, ValidationResult
from app.infrastructure.engines.classifier import HeuristicDocumentClassifier
from app.plugins.idn import IndonesiaKtpPlugin, IndonesiaNpwpPlugin, IndonesiaSimPlugin


class _SyntheticSchema(BaseModel):
    nric: str = ""


class _SyntheticSgpNricPlugin:
    """Custom non-IDN plugin to verify strict Open/Closed Principle compliance."""

    country_code: str = "SGP"
    doc_type: str = "NRIC"
    description: str = "Singapore National Registration Identity Card"
    schema_model: type[BaseModel] = _SyntheticSchema

    _RULES: tuple[ClassificationRule, ...] = (
        ClassificationRule(keyword="REPUBLIC OF SINGAPORE", weight=2.5, required=True),
        ClassificationRule(keyword="IDENTITY CARD NO", weight=2.0),
        ClassificationRule(keyword="RACE", weight=1.0),
        ClassificationRule(keyword="DATE OF BIRTH", weight=1.0),
    )

    @property
    def classification_rules(self) -> Sequence[ClassificationRule]:
        return self._RULES

    def build_prompt(self, ocr_result: OcrResult | None = None) -> str:
        return ""

    def validate(self, data: BaseModel) -> ValidationResult:
        return ValidationResult(is_valid=True)

    def offline_parse(self, ocr_result: OcrResult) -> BaseModel:
        return _SyntheticSchema()


def _default_idn_plugins() -> list[DocumentPlugin]:
    return [IndonesiaKtpPlugin(), IndonesiaSimPlugin(), IndonesiaNpwpPlugin()]


@pytest.mark.unit
def test_classifier_conforms_to_protocol() -> None:
    """HeuristicDocumentClassifier satisfies the DocumentClassifier runtime protocol."""
    classifier = HeuristicDocumentClassifier()
    assert isinstance(classifier, DocumentClassifier)


@pytest.mark.unit
def test_classifier_identifies_clear_ktp_sim_and_npwp() -> None:
    """Clear OCR text for KTP, SIM, and NPWP classifies accurately without cross-talk."""
    classifier = HeuristicDocumentClassifier()
    plugins = _default_idn_plugins()

    ktp_ocr = OcrResult(
        raw_text=(
            "PROVINSI DKI JAKARTA\n"
            "KARTU TANDA PENDUDUK\n"
            "NIK : 3171234567890001\n"
            "RT/RW : 001/002\n"
            "GOL. DARAH : O\n"
            "KEWARGANEGARAAN : WNI\n"
            "BERLAKU HINGGA : SEUMUR HIDUP"
        )
    )
    ktp_res = classifier.classify(ktp_ocr, plugins)
    assert ktp_res is not None
    assert ktp_res.country_code == "IDN"
    assert ktp_res.doc_type == "KTP"
    assert ktp_res.confidence == pytest.approx(1.0)
    assert "NIK" in ktp_res.matched_rules
    assert "PROVINSI" in ktp_res.matched_rules

    sim_ocr = OcrResult(
        raw_text=(
            "KEPOLISIAN NEGARA REPUBLIK INDONESIA\n"
            "SURAT IZIN MENGEMUDI\n"
            "DRIVING LICENSE\n"
            "POLRI\n"
            "GOL. SIM : A\n"
            "BERLAKU S/D : 17-08-2029"
        )
    )
    sim_res = classifier.classify(sim_ocr, plugins)
    assert sim_res is not None
    assert sim_res.country_code == "IDN"
    assert sim_res.doc_type == "SIM"
    assert sim_res.confidence >= 0.8
    assert "SURAT IZIN MENGEMUDI" in sim_res.matched_rules

    npwp_ocr = OcrResult(
        raw_text=(
            "KEMENTERIAN KEUANGAN REPUBLIK INDONESIA\n"
            "DIREKTORAT JENDERAL PAJAK\n"
            "NPWP : 01.234.567.8-012.000\n"
            "NOMOR POKOK WAJIB PAJAK\n"
            "KPP PRATAMA JAKARTA SETIABUDI\n"
            "TERDAFTAR : 01-02-2020"
        )
    )
    npwp_res = classifier.classify(npwp_ocr, plugins)
    assert npwp_res is not None
    assert npwp_res.country_code == "IDN"
    assert npwp_res.doc_type == "NPWP"
    assert npwp_res.confidence == pytest.approx(1.0)
    assert "NPWP" in npwp_res.matched_rules


@pytest.mark.unit
def test_classifier_handles_ocr_typos_and_spacing_splits() -> None:
    """OCR character substitutions (0->O, 1->I) and split tokens (NPW P) still classify."""
    classifier = HeuristicDocumentClassifier()
    plugins = _default_idn_plugins()

    noisy_ktp = OcrResult(
        raw_text=("PR0VINSI JAWA BARAT\nN1K : 3273011708950001\nRT / RW : 003/005\nSEUMUR HIDUP")
    )
    ktp_res = classifier.classify(noisy_ktp, plugins)
    assert ktp_res is not None
    assert ktp_res.country_code == "IDN"
    assert ktp_res.doc_type == "KTP"
    assert ktp_res.confidence < 1.0
    assert "NIK" in ktp_res.matched_rules
    assert "PROVINSI" in ktp_res.matched_rules

    noisy_npwp = OcrResult(
        raw_text=("NPW P : 01.234.567.8-012.000\nD1REKT0RAT JENDERAL PAJAK\nKPP PRATAMA BANDUNG")
    )
    npwp_res = classifier.classify(noisy_npwp, plugins)
    assert npwp_res is not None
    assert npwp_res.country_code == "IDN"
    assert npwp_res.doc_type == "NPWP"
    assert "NPWP" in npwp_res.matched_rules


@pytest.mark.unit
def test_classifier_falls_back_to_ocr_lines_when_raw_text_empty() -> None:
    """Classifier reads ocr_result.lines when raw_text is empty."""
    classifier = HeuristicDocumentClassifier()
    ocr = OcrResult(
        raw_text="",
        lines=[
            OcrLine(text="SURAT IZIN MENGEMUDI", confidence=0.95),
            OcrLine(text="POLRI", confidence=0.92),
            OcrLine(text="SIM C", confidence=0.90),
        ],
    )
    result = classifier.classify(ocr, _default_idn_plugins())
    assert result is not None
    assert result.country_code == "IDN"
    assert result.doc_type == "SIM"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_text",
    [
        "",
        "   \n  ",
        "INVOICE #12345\nTOTAL RP 75.000\nTERIMA KASIH",
        "TEKNIK ELEKTRO\nKLINIK SIMPANG LIMA\nINI KARTU MEMBER",
        "PROVINSI DKI JAKARTA\nRT/RW 001/002\nSEUMUR HIDUP",  # missing required NIK
        "DIREKTORAT JENDERAL PAJAK\nKPP PRATAMA JAKARTA",  # missing required NPWP
    ],
)
def test_classifier_returns_none_for_non_id_blank_or_missing_required(raw_text: str) -> None:
    """Receipts, blank text, substring traps, and missing required keywords return None."""
    classifier = HeuristicDocumentClassifier()
    result = classifier.classify(OcrResult(raw_text=raw_text), _default_idn_plugins())
    assert result is None


@pytest.mark.unit
def test_classifier_returns_none_when_top_candidates_are_ambiguous() -> None:
    """Conflicting keywords with scores within min_margin return None."""
    classifier = HeuristicDocumentClassifier(min_confidence=0.25, min_margin=0.10)
    mixed_ocr = OcrResult(
        raw_text=(
            "NIK 3171234567890001\n"
            "PROVINSI DKI JAKARTA\n"
            "SEUMUR HIDUP\n"
            "NPWP 01.234.567.8-012.000\n"
            "DIREKTORAT JENDERAL PAJAK"
        )
    )
    assert classifier.classify(mixed_ocr, _default_idn_plugins()) is None


@pytest.mark.unit
def test_classifier_ocp_with_custom_synthetic_plugin() -> None:
    """Classifier dynamically scores any new DocumentPlugin with zero hardcoded rules."""
    classifier = HeuristicDocumentClassifier()
    plugins: list[DocumentPlugin] = [*_default_idn_plugins(), _SyntheticSgpNricPlugin()]

    sgp_ocr = OcrResult(
        raw_text=(
            "REPUBLIC OF SINGAPORE\n"
            "IDENTITY CARD NO S1234567A\n"
            "RACE CHINESE\n"
            "DATE OF BIRTH 01-01-1990"
        )
    )
    result = classifier.classify(sgp_ocr, plugins)
    assert result is not None
    assert result.country_code == "SGP"
    assert result.doc_type == "NRIC"
    assert result.confidence == pytest.approx(1.0)


@pytest.mark.unit
def test_classifier_constructor_validates_thresholds() -> None:
    """Invalid threshold parameters raise ValueError."""
    with pytest.raises(ValueError, match="min_confidence"):
        HeuristicDocumentClassifier(min_confidence=1.5)
    with pytest.raises(ValueError, match="min_margin"):
        HeuristicDocumentClassifier(min_margin=-0.1)
    with pytest.raises(ValueError, match="fuzzy_discount"):
        HeuristicDocumentClassifier(fuzzy_discount=0.0)


@pytest.mark.unit
def test_classifier_latency_under_five_milliseconds() -> None:
    """Heuristic classification runs in well under 5ms per call."""
    classifier = HeuristicDocumentClassifier()
    plugins = _default_idn_plugins()
    ocr = OcrResult(
        raw_text=(
            "PROVINSI DKI JAKARTA\n"
            "KARTU TANDA PENDUDUK\n"
            "NIK : 3171234567890001\n"
            "RT/RW : 001/002\n"
            "SEUMUR HIDUP"
        )
    )

    # Warm regex LRU cache
    assert classifier.classify(ocr, plugins) is not None

    iterations = 50
    start = time.perf_counter()
    for _ in range(iterations):
        classifier.classify(ocr, plugins)
    avg_ms = ((time.perf_counter() - start) * 1000.0) / iterations
    assert avg_ms < 5.0
