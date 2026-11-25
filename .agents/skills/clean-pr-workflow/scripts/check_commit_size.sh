#!/usr/bin/env bash
set -euo pipefail

MAX_LINES="${MAX_COMMIT_LINES:-400}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: not inside a git repository." >&2
  exit 1
fi

numstat=$(git diff --cached --numstat)
if [ -z "$numstat" ]; then
  echo "Error: no staged changes found. Stage files with 'git add' first." >&2
  exit 1
fi

total=0
lockfile_warn=0

while IFS=$'\t' read -r added deleted path; do
  [ -z "$path" ] && continue
  if [ "$path" = "uv.lock" ]; then
    lockfile_warn=1
    continue
  fi
  if [ "$added" = "-" ] || [ "$deleted" = "-" ]; then
    echo "  [binary] $path"
    continue
  fi
  file_total=$((added + deleted))
  total=$((total + file_total))
  printf "  %4d lines (+%d/-%d)  %s\n" "$file_total" "$added" "$deleted" "$path"
done <<< "$numstat"

if [ "$lockfile_warn" -eq 1 ]; then
  echo "Note: excluded uv.lock from the 400-line calculation."
fi

echo "Total staged changes (excluding lockfiles): ${total} / ${MAX_LINES} lines"

if [ "$total" -gt "$MAX_LINES" ]; then
  echo "FAIL: staged diff exceeds ${MAX_LINES} lines (${total}). Split into smaller commits." >&2
  exit 1
fi

echo "PASS: staged diff is within the ${MAX_LINES}-line commit limit."
