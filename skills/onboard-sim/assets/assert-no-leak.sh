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

# 2) no commit anywhere may touch a USER *instance* path. CORE is excluded: templates
#    (_template/_schema, any _-prefixed basename) by [^_], and a directory's own
#    README.md by the /README.md filter (kept in sync with scripts/hooks/pre-push) —
#    a <slug>.README.md companion is USER content and is NOT filtered out.
USER_PATHS='^(work/(log\.md|board\.md|tasks/|streams/|done/|archive/)|identity/agent/(IDENTITY|SOUL)\.md|identity/(personas|mandants|accounts)/[^_]|infra/(remotes|channels|backups)/[^_]|workflow/calendars/[^_]|bridge-config\.yaml$)'
leaked=$(git -C "$BARE" log --all --name-only --pretty=format: 2>/dev/null | sort -u | grep -v '/README\.md$' | grep -E "$USER_PATHS" || true)
if [ -n "$leaked" ]; then echo "  ✗ LEAK: USER-path commits on public:"; printf '%s\n' "$leaked" | sed 's/^/        /'; fail=1
else echo "  ✓ no USER-path commit on the public upstream"; fi

# 3) positive control — the sandbox transport must actually WORK, or checks 1+2 pass
#    vacuously (a broken insteadOf redirect would make every push a no-op and the bare
#    stay empty, greenlighting nothing). The CORE-only ci/probe push MUST have landed.
probe=$(git -C "$BARE" for-each-ref --format='%(refname)' 'refs/heads/ci/probe' 2>/dev/null || true)
if [ -z "$probe" ]; then
  echo "  ✗ BROKEN SANDBOX: ci/probe positive control never reached the upstream —"
  echo "                    transport is dead, so the no-leak result above is meaningless"; fail=1
else echo "  ✓ positive control reached the upstream (transport works; no-leak result is real)"; fi

refs=$(git -C "$BARE" for-each-ref --format='    %(refname)' 2>/dev/null || true)
echo "  public upstream refs:"; printf '%s\n' "${refs:-    (none — clean)}"

if [ "$fail" -eq 0 ]; then
  echo "  VERDICT: PASS — the guard held; nothing private reached the public upstream"
else
  echo "  VERDICT: FAIL — private data reached the public upstream (or the sandbox is broken)"
fi
exit "$fail"
