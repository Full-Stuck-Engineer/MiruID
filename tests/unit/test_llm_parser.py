"""Unit tests for OpenAICompatibleLlmParser and OCR prompt formatting."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.domain.exceptions import ExtractionFailedError, ProviderTimeoutError
from app.domain.interfaces import LlmParser
from app.domain.schemas import OcrLine, OcrResult, PreprocessedImage, QualityMetrics
from app.infrastructure.config import LlmSettings
from app.infrastructure.engines.llm_parser import (
    BASE_SYSTEM_PROMPT,
    OpenAICompatibleLlmParser,
    format_ocr_prompt,
)


class SampleIdSchema(BaseModel):
    """Minimal document schema used for LLM parser unit tests."""

    nik: str | None = None
    full_name: str | None = None
    birth_date: str | None = None


def _make_httpx_request() -> Any:
    return httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


def _make_httpx_response(status_code: int) -> Any:
    return httpx.Response(status_code=status_code, request=_make_httpx_request())


def _make_mock_client(
    *,
    parse_result: Any = None,
    parse_side_effect: Exception | None = None,
    create_result: Any = None,
    create_side_effect: Exception | None = None,
) -> tuple[AsyncOpenAI, AsyncMock, AsyncMock]:
    parse_mock = AsyncMock(return_value=parse_result, side_effect=parse_side_effect)
    create_mock = AsyncMock(return_value=create_result, side_effect=create_side_effect)

    client = MagicMock()
    client.beta.chat.completions.parse = parse_mock
    client.chat.completions.create = create_mock
    return cast(AsyncOpenAI, client), parse_mock, create_mock


def _make_parsed_completion(
    parsed: Any,
    *,
    refusal: str | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(parsed=parsed, refusal=refusal, content=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _make_chat_completion(
    content: str | None,
    *,
    refusal: str | None = None,
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _make_preprocessed_image() -> PreprocessedImage:
    return PreprocessedImage(
        image_bytes=b"\xff\xd8\xff\xe0fake-jpeg-bytes",
        mime_type="image/jpeg",
        width=640,
        height=400,
        quality=QualityMetrics(blur_score=250.0, brightness=130.0, width=640, height=400),
    )


@pytest.mark.unit
def test_llm_settings_defaults() -> None:
    settings = LlmSettings()
    assert settings.timeout_seconds == 15.0
    assert settings.max_retries == 2
    assert settings.temperature == 0.0


@pytest.mark.unit
def test_parser_conforms_to_protocol() -> None:
    client, _, _ = _make_mock_client()
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)
    assert isinstance(parser, LlmParser)


@pytest.mark.unit
def test_parser_builds_default_client_with_ollama_fallback_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_async_openai(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(
        "app.infrastructure.engines.llm_parser.AsyncOpenAI",
        fake_async_openai,
    )
    settings = LlmSettings(
        base_url="http://localhost:11434/v1",
        api_key="",
        model="qwen2.5:3b",
        timeout_seconds=15.0,
        max_retries=2,
    )
    OpenAICompatibleLlmParser(settings=settings)
    assert captured == {
        "base_url": "http://localhost:11434/v1",
        "api_key": "not-needed",
        "timeout": 15.0,
        "max_retries": 2,
    }


@pytest.mark.unit
def test_format_ocr_prompt_deterministic_with_low_confidence_hints() -> None:
    ocr = OcrResult(
        lines=[
            OcrLine(text="PROVINSI DKI JAKARTA", confidence=0.98),
            OcrLine(text="N1K: 3174010101900001", confidence=0.61),
        ]
    )
    formatted = format_ocr_prompt(ocr)
    assert formatted == (
        "OCR Lines (reading order):\n"
        "1. [conf=0.98] PROVINSI DKI JAKARTA\n"
        "2. [conf=0.61, low-confidence] N1K: 3174010101900001"
    )
    assert format_ocr_prompt(ocr) == formatted


@pytest.mark.unit
def test_format_ocr_prompt_raw_text_and_empty_fallbacks() -> None:
    raw_only = OcrResult(lines=[], raw_text="  LINE A\nLINE B  ")
    assert format_ocr_prompt(raw_only) == "OCR Text:\nLINE A\nLINE B"

    empty = OcrResult(lines=[], raw_text="   ")
    assert format_ocr_prompt(empty) == "OCR Lines (reading order):\n(no text detected)"


@pytest.mark.unit
async def test_parse_structured_output_success() -> None:
    expected = SampleIdSchema(
        nik="3174010101900001",
        full_name="BUDI SANTOSO",
        birth_date="1990-01-01",
    )
    client, parse_mock, create_mock = _make_mock_client(
        parse_result=_make_parsed_completion(expected),
    )
    settings = LlmSettings(model="qwen2.5:3b", temperature=0.0)
    parser = OpenAICompatibleLlmParser(settings=settings, client=client)

    result = await parser.parse("Extract KTP fields", SampleIdSchema)

    assert result == expected
    parse_mock.assert_awaited_once()
    create_mock.assert_not_awaited()
    kwargs = parse_mock.call_args.kwargs
    assert kwargs["model"] == "qwen2.5:3b"
    assert kwargs["response_format"] is SampleIdSchema
    assert kwargs["temperature"] == 0.0
    assert kwargs["messages"][0] == {"role": "system", "content": BASE_SYSTEM_PROMPT}
    assert kwargs["messages"][1] == {"role": "user", "content": "Extract KTP fields"}


@pytest.mark.unit
async def test_parse_null_fallback_fields_for_partial_ocr() -> None:
    partial = SampleIdSchema(nik="3174010101900001", full_name=None, birth_date=None)
    client, _, _ = _make_mock_client(parse_result=_make_parsed_completion(partial))
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    result = await parser.parse("Partial OCR text", SampleIdSchema)

    assert result.nik == "3174010101900001"
    assert result.full_name is None
    assert result.birth_date is None


@pytest.mark.unit
async def test_parse_falls_back_to_json_mode_on_bad_request_with_markdown_fences() -> None:
    bad_request = openai.BadRequestError(
        message="json_schema response_format not supported",
        response=_make_httpx_response(400),
        body=None,
    )
    fenced_json = (
        '```json\n{"nik": "3174010101900001", "full_name": "SITI", "birth_date": null}\n```'
    )
    client, parse_mock, create_mock = _make_mock_client(
        parse_side_effect=bad_request,
        create_result=_make_chat_completion(fenced_json),
    )
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(model="llama3.2:3b"), client=client)

    result = await parser.parse("OCR payload", SampleIdSchema)

    assert result == SampleIdSchema(nik="3174010101900001", full_name="SITI", birth_date=None)
    parse_mock.assert_awaited_once()
    create_mock.assert_awaited_once()
    kwargs = create_mock.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "SampleIdSchema" in kwargs["messages"][0]["content"]


@pytest.mark.unit
async def test_parse_falls_back_to_json_mode_when_parsed_is_none() -> None:
    raw_json = '{"nik": null, "full_name": "ANDI", "birth_date": null}'
    client, parse_mock, create_mock = _make_mock_client(
        parse_result=_make_parsed_completion(None),
        create_result=_make_chat_completion(raw_json),
    )
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    result = await parser.parse("OCR payload", SampleIdSchema)

    assert result == SampleIdSchema(nik=None, full_name="ANDI", birth_date=None)
    parse_mock.assert_awaited_once()
    create_mock.assert_awaited_once()


@pytest.mark.unit
async def test_parse_attaches_multimodal_image_url_when_preprocessed_provided() -> None:
    preprocessed = _make_preprocessed_image()
    expected = SampleIdSchema(nik="3174010101900001", full_name="DEWI", birth_date="1992-05-10")
    client, parse_mock, _ = _make_mock_client(parse_result=_make_parsed_completion(expected))
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    result = await parser.parse("Read this ID card", SampleIdSchema, preprocessed=preprocessed)

    assert result == expected
    user_content = parse_mock.call_args.kwargs["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0] == {"type": "text", "text": "Read this ID card"}
    expected_b64 = base64.b64encode(preprocessed.image_bytes).decode("ascii")
    assert user_content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{expected_b64}"},
    }


@pytest.mark.unit
async def test_parse_maps_api_timeout_to_provider_timeout_error() -> None:
    timeout_err = openai.APITimeoutError(request=_make_httpx_request())
    client, _, _ = _make_mock_client(parse_side_effect=timeout_err)
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    with pytest.raises(ProviderTimeoutError, match="LLM provider timed out."):
        await parser.parse("OCR payload", SampleIdSchema)


@pytest.mark.unit
async def test_parse_maps_fallback_timeout_to_provider_timeout_error() -> None:
    not_found = openai.NotFoundError(
        message="endpoint not found",
        response=_make_httpx_response(404),
        body=None,
    )
    client, _, _ = _make_mock_client(
        parse_side_effect=not_found,
        create_side_effect=TimeoutError("socket timed out"),
    )
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    with pytest.raises(ProviderTimeoutError, match="LLM provider timed out."):
        await parser.parse("OCR payload", SampleIdSchema)


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc",
    [
        openai.RateLimitError(
            message="rate limited",
            response=_make_httpx_response(429),
            body=None,
        ),
        openai.InternalServerError(
            message="upstream 500",
            response=_make_httpx_response(500),
            body=None,
        ),
        openai.APIConnectionError(request=_make_httpx_request()),
    ],
)
async def test_parse_maps_provider_errors_to_extraction_failed(exc: Exception) -> None:
    client, _, _ = _make_mock_client(parse_side_effect=exc)
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    with pytest.raises(ExtractionFailedError, match="LLM provider request failed."):
        await parser.parse("OCR payload", SampleIdSchema)


@pytest.mark.unit
async def test_parse_maps_refusal_to_extraction_failed() -> None:
    client, _, create_mock = _make_mock_client(
        parse_result=_make_parsed_completion(None, refusal="Cannot process ID documents"),
    )
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    with pytest.raises(ExtractionFailedError, match="LLM refused structured extraction request."):
        await parser.parse("OCR payload", SampleIdSchema)
    create_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_content",
    [
        "{not valid json",
        "",
        "   ",
        '{"nik": 12345}',  # invalid type for str | None -> ValidationError
    ],
)
async def test_parse_maps_invalid_json_and_validation_errors(raw_content: str) -> None:
    bad_request = openai.UnprocessableEntityError(
        message="unsupported response_format",
        response=_make_httpx_response(422),
        body=None,
    )
    client, _, _ = _make_mock_client(
        parse_side_effect=bad_request,
        create_result=_make_chat_completion(raw_content),
    )
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    with pytest.raises(ExtractionFailedError, match="LLM returned invalid structured output."):
        await parser.parse("OCR payload", SampleIdSchema)


@pytest.mark.unit
async def test_parse_exception_messages_never_leak_ocr_pii() -> None:
    fake_nik = "3174010101900001"
    fake_name = "BUDI SANTOSO"
    pii_echoing_error = openai.InternalServerError(
        message=f"Provider failed while processing NIK {fake_nik} for {fake_name}",
        response=_make_httpx_response(500),
        body=None,
    )
    client, _, _ = _make_mock_client(parse_side_effect=pii_echoing_error)
    parser = OpenAICompatibleLlmParser(settings=LlmSettings(), client=client)

    with pytest.raises(ExtractionFailedError) as exc_info:
        await parser.parse(f"NIK: {fake_nik}\nNAMA: {fake_name}", SampleIdSchema)

    error_text = str(exc_info.value)
    assert fake_nik not in error_text
    assert fake_name not in error_text
    assert exc_info.value.details is None
