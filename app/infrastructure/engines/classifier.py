"""Heuristic auto-document classifier conforming to the DocumentClassifier port."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache

from app.domain.interfaces import DocumentPlugin
from app.domain.schemas import ClassificationResult, ClassificationRule, OcrResult

_WHITESPACE_RE = re.compile(r"\s+")
_OCR_CHAR_MAP = str.maketrans({"0": "O", "1": "I", "|": "I", "!": "I", "5": "S", "8": "B"})
_DEFAULT_FUZZY_DISCOUNT = 0.85
_DEFAULT_MIN_CONFIDENCE = 0.25
_DEFAULT_MIN_MARGIN = 0.10


def _normalize_text(text: str) -> str:
    """Upper-case text and collapse repeated whitespace into single spaces."""
    return _WHITESPACE_RE.sub(" ", text.strip().upper())


def _ocr_normalize(text: str) -> str:
    """Apply common OCR character-confusion normalization after standard normalization."""
    return _normalize_text(text).translate(_OCR_CHAR_MAP)


def _wrap_letter_boundaries(pattern: str, keyword: str) -> str:
    """Anchor alphabetic edges so short keywords do not match inside longer words."""
    prefix = r"(?<![A-Z])" if keyword and keyword[0].isalpha() else ""
    suffix = r"(?![A-Z])" if keyword and keyword[-1].isalpha() else ""
    return f"{prefix}{pattern}{suffix}"


@lru_cache(maxsize=512)
def _compile_exact_pattern(norm_keyword: str) -> re.Pattern[str]:
    """Compile a case-normalized exact match regex with alphabetic word boundaries."""
    return re.compile(_wrap_letter_boundaries(re.escape(norm_keyword), norm_keyword))


@lru_cache(maxsize=512)
def _compile_fuzzy_pattern(ocr_norm_keyword: str) -> re.Pattern[str]:
    """Compile an OCR-typo and minor-spacing tolerant regex for a normalized keyword."""
    tokens = [tok for tok in re.split(r"[^A-Z0-9]+", ocr_norm_keyword) if tok]
    if not tokens:
        return re.compile(re.escape(ocr_norm_keyword))

    token_patterns = [r"\s?".join(re.escape(ch) for ch in token) for token in tokens]
    body = r"[\s./\-:]*".join(token_patterns)
    return re.compile(_wrap_letter_boundaries(body, tokens[0][0] + tokens[-1][-1]))


def _extract_ocr_text(ocr_result: OcrResult) -> str:
    """Return raw OCR text, falling back to joining recognized lines."""
    if ocr_result.raw_text.strip():
        return ocr_result.raw_text
    if ocr_result.lines:
        return "\n".join(line.text for line in ocr_result.lines)
    return ""


class HeuristicDocumentClassifier:
    """Dynamic, OCP-compliant keyword-scoring classifier over registered DocumentPlugins."""

    def __init__(
        self,
        *,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        min_margin: float = _DEFAULT_MIN_MARGIN,
        fuzzy_discount: float = _DEFAULT_FUZZY_DISCOUNT,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0.")
        if not 0.0 <= min_margin <= 1.0:
            raise ValueError("min_margin must be between 0.0 and 1.0.")
        if not 0.0 < fuzzy_discount <= 1.0:
            raise ValueError("fuzzy_discount must be in (0.0, 1.0].")

        self._min_confidence = min_confidence
        self._min_margin = min_margin
        self._fuzzy_discount = fuzzy_discount

    def classify(
        self,
        ocr_result: OcrResult,
        plugins: Sequence[DocumentPlugin],
    ) -> ClassificationResult | None:
        """Select the best matching plugin from OCR output, or return None if ambiguous/unknown."""
        raw_text = _extract_ocr_text(ocr_result)
        if not raw_text.strip() or not plugins:
            return None

        norm_text = _normalize_text(raw_text)
        ocr_norm_text = _ocr_normalize(raw_text)

        scored: list[tuple[float, DocumentPlugin, list[str]]] = []
        for plugin in plugins:
            rules = plugin.classification_rules
            if not rules:
                continue

            score, matched_rules = self._score_plugin(rules, norm_text, ocr_norm_text)
            if score > 0.0:
                scored.append((score, plugin, matched_rules))

        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)
        top_score, top_plugin, top_matched = scored[0]

        if top_score < self._min_confidence:
            return None

        if len(scored) >= 2:
            second_score = scored[1][0]
            if (top_score - second_score) < self._min_margin:
                return None

        return ClassificationResult(
            country_code=top_plugin.country_code,
            doc_type=top_plugin.doc_type,
            confidence=round(min(1.0, top_score), 4),
            matched_rules=top_matched,
        )

    def _score_plugin(
        self,
        rules: Sequence[ClassificationRule],
        norm_text: str,
        ocr_norm_text: str,
    ) -> tuple[float, list[str]]:
        """Score a single plugin's rules against normalized and OCR-normalized text."""
        total_weight = sum(rule.weight for rule in rules)
        if total_weight <= 0.0:
            return 0.0, []

        matched_weight = 0.0
        matched_rules: list[str] = []

        for rule in rules:
            norm_kw = _normalize_text(rule.keyword)
            if not norm_kw:
                continue

            if _compile_exact_pattern(norm_kw).search(norm_text):
                matched_weight += rule.weight
                matched_rules.append(rule.keyword)
                continue

            ocr_kw = _ocr_normalize(rule.keyword)
            if _compile_exact_pattern(ocr_kw).search(ocr_norm_text) or _compile_fuzzy_pattern(
                ocr_kw
            ).search(ocr_norm_text):
                matched_weight += rule.weight * self._fuzzy_discount
                matched_rules.append(rule.keyword)
                continue

            if rule.required:
                return 0.0, []

        return matched_weight / total_weight, matched_rules


__all__ = ["HeuristicDocumentClassifier"]
