# =============================================================================
# Stage 1: Dependency & package builder
# =============================================================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen --no-install-project --extra ocr

COPY app/ ./app/
COPY README.md ./
RUN uv sync --no-dev --frozen --extra ocr

# =============================================================================
# Stage 2: Minimal non-root runtime
# =============================================================================
FROM python:3.12-slim AS runtime

ARG PRELOAD_OCR_MODELS=true
ARG OCR_LANG=id

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system appuser \
    && useradd --system --gid appuser --create-home appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PADDLE_PDX_CACHE_HOME=/app/.paddle_cache

RUN mkdir -p /app/.paddle_cache \
    && chown -R appuser:appuser /app/.paddle_cache

USER appuser

RUN if [ "$PRELOAD_OCR_MODELS" = "true" ]; then \
        python -c "from app.infrastructure.config import OcrSettings; from app.infrastructure.engines.ocr_paddle import PaddleOcrEngine; PaddleOcrEngine(OcrSettings(lang='${OCR_LANG}')).warmup()"; \
    fi

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
