---
name: clean-pr-workflow
description: >-
  Enforces MiruID engineering workflow for any feature, bugfix, or refactor:
  create a GitHub Issue first, follow Clean Architecture and SOLID principles,
  keep every commit at or below 400 changed lines, and ship via a Pull Request.
---

# Clean Architecture, SOLID & PR Workflow

Follow this procedure for every feature, bugfix, or refactor in this repository.

## 1. Pre-Flight: GitHub Issue & Branch

1. **Create a GitHub Issue first** (before writing code or creating a branch):
   ```bash
   gh issue create --title "<type>: <concise summary>" --body "<goal and acceptance criteria>"
   ```
2. **Branch from `main`** using the issue number:
   ```bash
   git checkout -b <type>/issue-<num>-<slug>
   ```
   Examples: `feat/issue-12-core-interfaces`, `fix/issue-15-blur-threshold`, `chore/issue-1-clean-pr-workflow`.
   Never commit or push directly to `main`.

## 2. Design Gate: Clean Architecture & SOLID

Before writing or modifying code, verify every change against these rules:

- **Dependency Rule (Clean Architecture):**
  - `app/domain/` contains only entities/schemas, port `Protocol`/ABC interfaces, transport-agnostic exceptions, and `DocumentRegistry`. Zero imports from `application/`, `infrastructure/`, `api/`, `plugins/`, or HTTP frameworks.
  - `app/application/` orchestrates use cases (`ExtractionPipeline`) against domain ports only.
  - `app/infrastructure/` implements adapters (`engines/`), nested config, and logging.
  - `app/api/` handles HTTP routing, DI wiring, and exception-to-HTTP-status mapping (`error_handlers.py`).
  - `app/plugins/` houses isolated country/document plugins.
- **Single Responsibility (SRP):** Keep modules, classes, and functions small and focused on one reason to change.
- **Open/Closed (OCP):** Extend behavior via `DocumentPlugin`, `ExtractionStrategy`, and `DocumentRegistry` instead of `if/elif` chains on country, document type, or extraction mode.
- **Liskov Substitution (LSP):** Any adapter implementing a `Protocol` in `app/domain/interfaces.py` must honor its return types and domain exceptions cleanly.
- **Interface Segregation (ISP):** Inject narrow config slices (`OcrSettings`, `LlmSettings`, `QualityGateSettings`) and focused protocols rather than monolithic objects.
- **Dependency Inversion (DIP):** High-level use cases depend on abstractions in `app/domain/interfaces.py`, never concrete libraries (`cv2`, `paddleocr`, `openai`).

## 3. Commit Gate: Max 400 Changed Lines

Every commit MUST stay at or below **400 changed lines** (`insertions + deletions`, excluding `uv.lock`).

1. Stage one cohesive, logical unit of work (e.g., domain contracts, then adapter, then tests).
2. Check staged diff size with the helper script:
   ```bash
   ./.agents/skills/clean-pr-workflow/scripts/check_commit_size.sh
   ```
   If it reports `> 400` lines, unstage part of the diff and split into multiple smaller commits.
3. Run quality checks before committing:
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run pytest -v
   ```
4. Commit with a conventional message referencing the issue:
   ```bash
   git commit -m "<type>: <summary> (#<num>)"
   ```

## 4. Pull Request Gate

1. Push the feature branch and open a Pull Request targeting `main`:
   ```bash
   git push -u origin HEAD
   gh pr create --base main --title "<type>: <summary>" --body "Closes #<num>\n\n<summary of changes and verification>"
   ```
2. Verify `gh pr view` shows the PR open and linked to the issue.
