---
name: pr-review
description: >-
  Reviews MiruID Pull Requests against Clean Architecture, SOLID principles,
  privacy/security rules, linked-issue hygiene, and the 400-line-per-commit cap.
  Use when asked to review a PR, inspect a pull request diff, or audit PR hygiene.
---

# MiruID Pull Request Review

Follow this procedure when reviewing a Pull Request. Report structured findings in chat first; only post to GitHub (`gh pr review`) when explicitly asked.

## 1. Gather PR Context & Hygiene

1. Run the hygiene checker (uses `gh api` REST to verify linked issue and `<= 400` changed lines per commit):
   ```bash
   ./.agents/skills/pr-review/scripts/check_pr_hygiene.sh <pr_number>
   ```
2. Fetch the PR diff:
   ```bash
   gh api repos/{owner}/{repo}/pulls/<pr_number> -H "Accept: application/vnd.github.v3.diff"
   ```
   (Or `gh pr diff <pr_number>`.)

## 2. Audit Against MiruID Gates

### A. PR Hygiene
- PR body references a GitHub Issue (`Closes #<num>`, `Fixes #<num>`, or `Resolves #<num>`).
- Every commit in the PR has `<= 400` changed lines (`additions + deletions`, excluding `uv.lock`).
- CI / local checks (`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -v`) pass.

### B. Clean Architecture & SOLID
- **Dependency Rule:** `app/domain/` has zero imports from `app/application/`, `app/infrastructure/`, `app/api/`, `app/plugins/`, or HTTP frameworks. HTTP status mapping lives only in `app/api/error_handlers.py`.
- **Single Responsibility (SRP):** Classes/modules have one clear reason to change; no monolithic god-modules.
- **Open/Closed (OCP):** New document types, countries, or extraction modes extend via `DocumentPlugin`, `ExtractionStrategy`, and `DocumentRegistry`—flag `if/elif` chains on `country`, `doc_type`, or `EXTRACTION_MODE`.
- **Liskov Substitution (LSP):** Adapters honor their `Protocol` contracts and raise domain exceptions consistently.
- **Interface Segregation (ISP):** Engines/adapters receive narrow config slices (`OcrSettings`, `LlmSettings`, `QualityGateSettings`) rather than the entire `Settings` object.
- **Dependency Inversion (DIP):** `ExtractionPipeline` depends only on `app/domain/interfaces.py` abstractions.

### C. Privacy & Security (`[SEC-01]`)
- Zero disk writes of uploaded image bytes or raw OCR dumps (`tempfile`, `open(..., "wb")`, `cv2.imwrite`).
- Zero PII (`nik`, `npwp_15`, `npwp_16`, `sim_number`, `full_name`, `address`, base64 payloads) logged or echoed in `ErrorResponse`.

### D. Correctness & Tests
- Edge cases, null handling, and failure paths (timeouts, malformed inputs) are covered by unit or integration tests.

## 3. Report Findings

Present:
1. **Verdict:** `Approve`, `Request Changes`, or `Comment`.
2. **Hygiene Summary:** Output of `check_pr_hygiene.sh`.
3. **Findings** grouped by severity (`Blocker`, `Suggestion`, `Nit`) with exact file paths, line numbers, and concrete fixes.
4. Ask if the user wants the review posted to GitHub (`gh pr review <pr_number> --comment|--request-changes|--approve --body "..."`).
