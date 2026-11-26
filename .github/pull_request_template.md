## Linked Issue

Closes #

## Summary

<!-- Concise summary of what changed and why. -->

-

## Verification

<!-- Describe how you verified these changes locally (commands run, coverage, manual checks). -->

- [ ] Unit tests pass (`uv run pytest -v --cov=app --cov-report=term-missing --cov-fail-under=80`)
- [ ] Linting & formatting pass (`uv run ruff check . && uv run ruff format --check .`)
- [ ] Static type checks pass (`uv run mypy app tests`)
- [ ] Every commit is `<= 400` changed lines (`./.agents/skills/clean-pr-workflow/scripts/check_commit_size.sh`)
- [ ] Clean Architecture & SOLID boundaries are respected (`domain/` -> `application/` -> `infrastructure/` / `api/` / `plugins/`)
- [ ] **Privacy Check:** Zero real PII, credentials, or real ID card photos are included anywhere in this PR
