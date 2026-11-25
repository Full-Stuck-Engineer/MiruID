---
trigger: always_on
---

# MiruID Engineering Workflow

For any feature, bugfix, or refactor in this repository, load and follow the **`clean-pr-workflow`** skill (`.agents/skills/clean-pr-workflow/SKILL.md`):

1. **GitHub Issue first** (`gh issue create`) before writing code or branching.
2. **Clean Architecture & SOLID** boundaries (`domain/` -> `application/` -> `infrastructure/` / `api/` / `plugins/`).
3. **Max 400 changed lines per commit** (`./.agents/skills/clean-pr-workflow/scripts/check_commit_size.sh`).
4. **Pull Request required** (`gh pr create` with `Closes #<num>`); never push directly to `main`.
