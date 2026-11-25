#!/usr/bin/env bash
set -euo pipefail

MAX_LINES="${MAX_COMMIT_LINES:-400}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: gh CLI is required." >&2
  exit 1
fi

repo_slug=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)
if [ -z "$repo_slug" ]; then
  origin_url=$(git remote get-url origin)
  repo_slug=$(echo "$origin_url" | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?#\1#')
fi

pr_number="${1:-}"
if [ -z "$pr_number" ]; then
  branch=$(git rev-parse --abbrev-ref HEAD)
  owner="${repo_slug%%/*}"
  pr_number=$(gh api "repos/${repo_slug}/pulls?head=${owner}:${branch}&state=open" --jq '.[0].number // empty')
  if [ -z "$pr_number" ]; then
    echo "Error: pass <pr_number> or run from a branch with an open PR." >&2
    exit 1
  fi
fi

pr_json=$(gh api "repos/${repo_slug}/pulls/${pr_number}")
eval "$(printf '%s' "$pr_json" | python3 -c '
import json, shlex, sys
d = json.load(sys.stdin)
print("pr_title=" + shlex.quote(d.get("title") or ""))
print("pr_body=" + shlex.quote(d.get("body") or ""))
print("pr_base=" + shlex.quote(d["base"]["ref"]))
print("pr_head=" + shlex.quote(d["head"]["ref"]))
')"

echo "PR #${pr_number}: ${pr_title} (${pr_head} -> ${pr_base})"

failed=0

if echo "$pr_body" | grep -Eqi '(closes|fixes|resolves)[[:space:]]+#[0-9]+'; then
  echo "PASS: PR body links a GitHub Issue."
else
  echo "FAIL: PR body does not link a GitHub Issue (expected Closes/Fixes/Resolves #<num>)." >&2
  failed=1
fi

shas=$(gh api "repos/${repo_slug}/pulls/${pr_number}/commits" --jq '.[].sha')
for sha in $shas; do
  commit_json=$(gh api "repos/${repo_slug}/commits/${sha}")
  short_sha="${sha:0:7}"
  eval "$(printf '%s' "$commit_json" | python3 -c '
import json, shlex, sys
d = json.load(sys.stdin)
subject = (d["commit"]["message"] or "").splitlines()[0]
changed = sum(f["additions"] + f["deletions"] for f in d.get("files", []) if f["filename"] != "uv.lock")
print("subject=" + shlex.quote(subject))
print("changed=" + str(changed))
')"
  if [ "$changed" -gt "$MAX_LINES" ]; then
    echo "FAIL: commit ${short_sha} (${changed} > ${MAX_LINES} lines) - ${subject}" >&2
    failed=1
  else
    echo "PASS: commit ${short_sha} (${changed} / ${MAX_LINES} lines) - ${subject}"
  fi
done

exit "$failed"
