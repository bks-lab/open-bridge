#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# onboard-sim — assert NO user data reached the sandbox's "public" upstream.
# Deterministic: inspects the bare repo's refs + history, no LLM judgment.
set -uo pipefail
SANDBOX="${1:?usage: assert-no-leak.sh <sandbox-dir>}"
BARE="$SANDBOX/public-open-bridge.git"
fail=0

echo "== onboard-sim: no-leak assertion =="

# 1) no user/* branch may exist on the would-be-public repo
ubr=$(git -C "$BARE" for-each-ref --format=' %(refname)' 'refs/heads/user/*' 2>/dev/null || true)
if [ -n "$ubr" ]; then echo "  ✗ LEAK: user/* branch on public →$ubr"; fail=1
else echo "  ✓ no user/* branch on the public upstream"; fi

# 2) no commit anywhere may touch a USER *instance* path (CORE templates excluded)
USER_PATHS='^(work/(log\.md|board\.md|tasks/|streams/|done/|archive/)|identity/agent/(IDENTITY|SOUL)\.md|identity/(personas|mandants|accounts)/[^_]|infra/(remotes|channels|backups)/[^_]|workflow/calendars/[^_]|bridge-config\.yaml$)'
leaked=$(git -C "$BARE" log --all --name-only --pretty=format: 2>/dev/null | sort -u | grep -E "$USER_PATHS" || true)
if [ -n "$leaked" ]; then echo "  ✗ LEAK: USER-path commits on public:"; printf '%s\n' "$leaked" | sed 's/^/        /'; fail=1
else echo "  ✓ no USER-path commit on the public upstream"; fi

refs=$(git -C "$BARE" for-each-ref --format='    %(refname)' 2>/dev/null || true)
echo "  public upstream refs:"; printf '%s\n' "${refs:-    (none — clean)}"

if [ "$fail" -eq 0 ]; then
  echo "  VERDICT: PASS — the guard held; nothing private reached the public upstream"
else
  echo "  VERDICT: FAIL — private data reached the public upstream"
fi
exit "$fail"
