# Contributing to MiruID

Thank you for contributing to **MiruID**! This guide covers our privacy policy, how to add new country document plugins, our Clean Architecture standards, and the pull request workflow.

> [!CAUTION]
> **Privacy & Synthetic Data Policy — Zero Real PII**
>
> **NEVER** commit real ID card photos, real national ID numbers (NIK, SSN, passport numbers, etc.), real tax numbers, or any personally identifiable information (PII) to this repository—including in tests, fixtures, docs, issues, or PR screenshots.
>
> Always use synthetic fixtures generated via `scripts/generate_synthetic_ids.py` or clearly fabricated test values. Any PR containing real PII or real ID images will be rejected immediately.

---

## Adding a New Country `DocumentPlugin`

MiruID follows the **Open/Closed Principle**: adding a new country or document type requires zero changes to the core extraction pipeline (`app/application/pipeline.py`).

### Step 1: Create the Country Package

Create a directory using the ISO 3166-1 alpha-3 lowercase country code under `app/plugins/`:

```text
app/plugins/<iso3>/
├── __init__.py
├── <doc>_validator.py   # Pure deterministic validation rules
└── <doc>.py             # Pydantic schema + DocumentPlugin implementation
```

See `app/plugins/idn/ktp.py` and `app/plugins/idn/nik_validator.py` for a complete reference implementation.

### Step 2: Define the Pydantic Schema

Wrap each extracted field in `ExtractedField[T]` from `app/domain/schemas.py` and add `@field_validator` normalizers (e.g., trimming whitespace, formatting ISO dates `YYYY-MM-DD`, uppercasing text):

```python
from pydantic import BaseModel, Field
from app.domain.schemas import ExtractedField


def _empty_str_field() -> ExtractedField[str]:
    return ExtractedField[str]()


class MyDocData(BaseModel):
    document_number: ExtractedField[str] = Field(default_factory=_empty_str_field)
    full_name: ExtractedField[str] = Field(default_factory=_empty_str_field)
    date_of_birth: ExtractedField[str] = Field(default_factory=_empty_str_field)
```

### Step 3: Implement Deterministic Validation Rules

Write pure validation functions in `<doc>_validator.py` that return `list[ValidationCheck]` (e.g., checksum verification, prefix tables, date consistency, format regexes). Avoid external I/O or network calls inside validators.

### Step 4: Implement the `DocumentPlugin` Protocol

Implement the `DocumentPlugin` protocol defined in `app/domain/interfaces.py`:

- **Metadata attributes:** `country_code` (ISO 3166-1 alpha-3 uppercase, e.g. `"SGP"`), `doc_type` (e.g. `"NRIC"`), `description`, and `schema_model`.
- **`classification_rules` property:** Return a sequence of weighted `ClassificationRule(keyword=..., weight=..., required=...)` entries used for auto-detection from OCR text.
- **`build_prompt(ocr_result: OcrResult | None = None) -> str`:** Build a clear, strict extraction prompt instructing the LLM never to hallucinate missing fields and appending `ocr_result` lines when present.
- **`validate(data: BaseModel) -> ValidationResult`:** Verify the schema type and run your deterministic validator checks.
- **`offline_parse(ocr_result: OcrResult) -> BaseModel`:** Provide a deterministic regex fallback parser for 100% offline mode (no LLM).

### Step 5: Register the Plugin

Register your plugin in `app/plugins/__init__.py` inside `register_default_plugins()`:

```python
from app.plugins.<iso3>.<doc> import MyCountryDocPlugin

def register_default_plugins(registry: DocumentRegistry) -> DocumentRegistry:
    ...
    registry.register(MyCountryDocPlugin())
    return registry
```

Once registered, `GET /v1/documents`, `POST /v1/extract`, and auto-classification pick it up automatically.

### Step 6: Write Unit Tests

Add thorough unit tests under `tests/`:

- Schema field normalization (dates, whitespace, missing values).
- Deterministic validator pass/fail edge cases and checksums.
- Classification keyword scoring (positive and negative cases).
- Offline regex parser extraction.
- End-to-end pipeline test with mocked OCR/LLM ports (no real API calls in unit tests).

---

## Architecture & Engineering Standards

### Clean Architecture Dependency Rule

Dependencies must point **inward only**:

```text
app/api/  &  app/infrastructure/  &  app/plugins/
                      │
                      ▼
               app/application/
                      │
                      ▼
                 app/domain/
```

- `app/domain/` — Entities, Pydantic schemas, `Protocol` ports, transport-agnostic exceptions, and `DocumentRegistry`. **Zero** imports from `application/`, `infrastructure/`, `api/`, `plugins/`, or HTTP frameworks.
- `app/application/` — Use-case orchestration (`ExtractionPipeline`) depending strictly on domain ports.
- `app/infrastructure/` — Concrete adapters (`OpenCVPreprocessor`, `PaddleOcrEngine`, `OpenAICompatibleLlmParser`), nested Pydantic `Settings`, and PII-masked JSON logging.
- `app/api/` — FastAPI routers, dependency wiring, and domain-exception-to-HTTP-status mapping.
- `app/plugins/` — Isolated country/document plugins.

### SOLID Principles

- **SRP:** Keep modules, classes, and functions focused on a single responsibility.
- **OCP:** Extend capabilities via `DocumentPlugin`, `ExtractionStrategy`, and `DocumentRegistry` instead of `if/elif` chains.
- **LSP:** Every adapter implementing a domain `Protocol` must honor its return types and domain exceptions.
- **ISP:** Inject narrow settings slices (`OcrSettings`, `LlmSettings`, `QualityGateSettings`) rather than the entire `Settings` object.
- **DIP:** Depend on abstractions in `app/domain/interfaces.py`, never concrete third-party libraries in use cases.

---

## Local Development & Quality Checks

Install dependencies with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --frozen
```

Run the full local quality suite before committing:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run pytest -v --cov=app --cov-report=term-missing --cov-fail-under=80
```

---

## Pull Request Workflow

1. **Open a GitHub Issue first** describing the problem, goal, and acceptance criteria.
2. **Branch from `main`** using the naming convention `<type>/issue-<num>-<short-slug>` (e.g., `feat/issue-42-sgp-nric-plugin`). Never push directly to `main`.
3. **Keep every commit `<= 400` changed lines** (`insertions + deletions`, excluding `uv.lock`). Verify staged changes with:
   ```bash
   ./.agents/skills/clean-pr-workflow/scripts/check_commit_size.sh
   ```
   Split larger changes into cohesive, reviewable commits.
4. **Use Conventional Commits** referencing the issue number, e.g. `feat(plugins): add SGP NRIC validator (#42)`.
5. **Open a Pull Request** targeting `main` with `Closes #<num>` in the description and complete every item in the PR checklist.
