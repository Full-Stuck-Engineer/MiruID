"""Unified lightweight OpenAI-compatible LLM/VLM structured parser adapter."""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, TypeVar, cast

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

from app.domain.exceptions import ExtractionFailedError, ProviderTimeoutError
from app.domain.schemas import OcrResult, PreprocessedImage
from app.infrastructure.config import LlmSettings

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)

LOW_CONFIDENCE_THRESHOLD = 0.70

BASE_SYSTEM_PROMPT = (
    "You are a precision identity-document field extraction engine.\n"
    "Follow these rules strictly:\n"
    "1. Extract ONLY information explicitly supported by the provided OCR text or image.\n"
    "2. Never invent, guess, extrapolate, or fabricate missing values.\n"
    "3. Normalize complete dates to ISO format YYYY-MM-DD.\n"
    "4. Fix obvious OCR character confusions (e.g., 0/O, 1/I) ONLY when contextually certain.\n"
    "5. Strictly return null for any field that is missing, obscured, illegible, or ambiguous.\n"
    "6. Output must conform strictly to the requested JSON schema."
)

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)

_STRUCTURED_FALLBACK_ERRORS = (
    openai.BadRequestError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
)


def format_ocr_prompt(ocr_result: OcrResult) -> str:
    """Format an ``OcrResult`` into a compact, deterministic prompt payload."""
    if ocr_result.lines:
        formatted_lines = ["OCR Lines (reading order):"]
        for idx, line in enumerate(ocr_result.lines, start=1):
            hint = ", low-confidence" if line.confidence < LOW_CONFIDENCE_THRESHOLD else ""
            formatted_lines.append(f"{idx}. [conf={line.confidence:.2f}{hint}] {line.text}")
        return "\n".join(formatted_lines)

    raw_text = ocr_result.raw_text.strip()
    if raw_text:
        return f"OCR Text:\n{raw_text}"

    return "OCR Lines (reading order):\n(no text detected)"


def _strip_markdown_fences(raw_content: str) -> str:
    """Remove optional outer markdown code fences from an LLM JSON response."""
    stripped = raw_content.strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match is not None:
        return match.group(1).strip()
    return stripped


def _build_user_content(
    prompt: str,
    preprocessed: PreprocessedImage | None,
) -> str | list[dict[str, Any]]:
    """Build text-only or multimodal user content without touching disk."""
    if preprocessed is None:
        return prompt

    encoded = base64.b64encode(preprocessed.image_bytes).decode("ascii")
    return [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{preprocessed.mime_type};base64,{encoded}"},
        },
    ]


def _build_messages(
    system_prompt: str,
    prompt: str,
    preprocessed: PreprocessedImage | None,
) -> list[ChatCompletionMessageParam]:
    """Assemble OpenAI chat messages for structured or JSON-mode completion."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _build_user_content(prompt, preprocessed)},
    ]
    return cast(list[ChatCompletionMessageParam], messages)


def _build_json_mode_system_prompt(schema_model: type[BaseModel]) -> str:
    """Append the target Pydantic JSON schema to the base system prompt."""
    schema_json = json.dumps(schema_model.model_json_schema(), sort_keys=True)
    return (
        f"{BASE_SYSTEM_PROMPT}\n\n"
        "Return ONLY a single valid JSON object matching this JSON Schema:\n"
        f"{schema_json}"
    )


class OpenAICompatibleLlmParser:
    """OpenAI-compatible / Ollama structured parser conforming to ``LlmParser``."""

    def __init__(
        self,
        settings: LlmSettings | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._settings = settings if settings is not None else LlmSettings()
        self._client = (
            client
            if client is not None
            else AsyncOpenAI(
                base_url=self._settings.base_url,
                api_key=self._settings.api_key or "not-needed",
                timeout=self._settings.timeout_seconds,
                max_retries=self._settings.max_retries,
            )
        )

    async def parse(
        self,
        prompt: str,
        schema_model: type[TModel],
        preprocessed: PreprocessedImage | None = None,
    ) -> TModel:
        """Parse prompt (and optional image) into ``schema_model``."""
        try:
            parsed = await self._parse_structured(prompt, schema_model, preprocessed)
            if parsed is not None:
                return parsed
            logger.debug(
                "Structured output missing parsed payload; falling back to JSON mode (model=%s)",
                self._settings.model,
            )
        except _STRUCTURED_FALLBACK_ERRORS:
            logger.debug(
                "Strict json_schema rejected by provider; falling back to JSON mode (model=%s)",
                self._settings.model,
            )
        except (openai.APITimeoutError, TimeoutError) as exc:
            raise ProviderTimeoutError("LLM provider timed out.") from exc
        except (
            openai.RateLimitError,
            openai.APIStatusError,
            openai.APIConnectionError,
            openai.APIError,
        ) as exc:
            raise ExtractionFailedError("LLM provider request failed.") from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ExtractionFailedError("LLM returned invalid structured output.") from exc

        return await self._parse_json_mode(prompt, schema_model, preprocessed)

    async def _parse_structured(
        self,
        prompt: str,
        schema_model: type[TModel],
        preprocessed: PreprocessedImage | None,
    ) -> TModel | None:
        """Primary structured-output path via ``beta.chat.completions.parse``."""
        messages = _build_messages(BASE_SYSTEM_PROMPT, prompt, preprocessed)
        completion = await self._client.beta.chat.completions.parse(
            model=self._settings.model,
            messages=messages,
            response_format=schema_model,
            temperature=self._settings.temperature,
        )
        if not completion.choices:
            raise ExtractionFailedError("LLM returned invalid structured output.")

        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise ExtractionFailedError("LLM refused structured extraction request.")

        parsed = getattr(message, "parsed", None)
        if parsed is None:
            return None
        if isinstance(parsed, schema_model):
            return parsed
        return schema_model.model_validate(parsed)

    async def _parse_json_mode(
        self,
        prompt: str,
        schema_model: type[TModel],
        preprocessed: PreprocessedImage | None,
    ) -> TModel:
        """Fallback JSON-object mode for providers without strict json_schema support."""
        system_prompt = _build_json_mode_system_prompt(schema_model)
        messages = _build_messages(system_prompt, prompt, preprocessed)
        try:
            completion = await self._client.chat.completions.create(
                model=self._settings.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=self._settings.temperature,
            )
        except (openai.APITimeoutError, TimeoutError) as exc:
            raise ProviderTimeoutError("LLM provider timed out.") from exc
        except (
            openai.RateLimitError,
            openai.APIStatusError,
            openai.APIConnectionError,
            openai.APIError,
        ) as exc:
            raise ExtractionFailedError("LLM provider request failed.") from exc

        if not completion.choices:
            raise ExtractionFailedError("LLM returned invalid structured output.")

        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise ExtractionFailedError("LLM refused structured extraction request.")

        content = message.content
        if not isinstance(content, str) or not content.strip():
            raise ExtractionFailedError("LLM returned invalid structured output.")

        cleaned = _strip_markdown_fences(content)
        try:
            payload = json.loads(cleaned)
            return schema_model.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ExtractionFailedError("LLM returned invalid structured output.") from exc


__all__ = [
    "BASE_SYSTEM_PROMPT",
    "OpenAICompatibleLlmParser",
    "format_ocr_prompt",
]
