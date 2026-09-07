#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# upstream-autoupdate.sh — GUARDED daily auto-merge of upstream CORE updates.
#
# Auto-merges the upstream ref into the current user/* branch ONLY when it is
# provably safe. Otherwise it does NOT merge — it writes a status report and
# (optionally) notifies. Every guard FAILS CLOSED: any error or unknown state
# skips the merge rather than risking a bad one.
#
# Authoritative safety gate = `git merge-tree` (content-based conflict
# prediction). The name-based divergence sentinel is used only for the
# informational report, never as the merge decision (it can flag files that are
# byte-identical after a prior contribution).
#
# Guards (ALL must pass):
#   1. on a user/* branch
#   2. no uncommitted TRACKED changes
#   3. git merge-tree predicts 0 conflicts (read from its EXIT CODE — never
#      from its localized output; see the note at the guard itself)
#
# Env (optional): UPSTREAM_REMOTE (default upstream) · UPSTREAM_REF (default
# upstream/main) · SIGNAL_ACCOUNT + SIGNAL_RECIPIENT (both set → Signal push).
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 1

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_REF="${UPSTREAM_REF:-upstream/main}"
REPORT="work/upstream-status.md"

notify() {  # $1 = message
  { [ -n "${SIGNAL_ACCOUNT:-}" ] && [ -n "${SIGNAL_RECIPIENT:-}" ] \
    && command -v signal-cli >/dev/null 2>&1 \
    && signal-cli -a "$SIGNAL_ACCOUNT" send -m "$1" "$SIGNAL_RECIPIENT" >/dev/null 2>&1; } || true
}
report() { mkdir -p work; { echo "# Upstream Auto-Update — $(date '+%F %T')"; echo; printf '%s\n' "$@"; } > "$REPORT"; }
is_int() { case "$1" in ''|*[!0-9]*) return 1;; *) return 0;; esac; }

git fetch "$UPSTREAM_REMOTE" -q 2>/dev/null || true

behind=$(git rev-list --count "HEAD..$UPSTREAM_REF" 2>/dev/null || echo x)
is_int "$behind" || { report "- 🔴 cannot resolve \`$UPSTREAM_REF\` (fetch failed?)"; echo "autoupdate: no upstream ref"; exit 1; }
if [ "$behind" -eq 0 ]; then
  report "- ✓ up to date (0 behind \`$UPSTREAM_REF\`)"; echo "autoupdate: up to date"; exit 0
fi

# informational divergence count for the report (NOT a gate; unknown → '?')
risk=$(python3 scripts/bridge-divergence-check.py --upstream "$UPSTREAM_REF" --json 2>/dev/null \
       | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("conflict_risk",[])))' 2>/dev/null)
is_int "$risk" || risk="?"

# ---- GUARDS (fail closed) ----
reason=""
branch=$(git branch --show-current 2>/dev/null || echo "")
case "$branch" in user/*) ;; *) reason="not on a user/* branch (on '${branch:-detached}')";; esac

if [ -z "$reason" ] && ! { git diff --quiet && git diff --cached --quiet; }; then
  reason="working tree has uncommitted tracked changes"
fi

if [ -z "$reason" ]; then
  # Authoritative signal is merge-tree's EXIT CODE, not its prose:
  #   0 = clean · 1 = conflicts · >1 = the command itself failed.
  # This used to grep the output for "conflict", which is a LOCALE-DEPENDENT
  # string and silently returned 0 on any non-English git. On de_DE the output
  # reads "KONFLIKT (Inhalt): Merge-Konflikt in <file>" — no match, so the
  # gate that exists to fail closed reported "safe" and the merge went ahead
  # and failed. That is exactly what happened on 2026-09-07 (.gitignore).
  # LC_ALL=C is belt-and-braces: it pins any output we or a human read.
  mt=$(LC_ALL=C git merge-tree --write-tree HEAD "$UPSTREAM_REF" 2>/dev/null)
  mt_rc=$?
  case "$mt_rc" in
    0) : ;;                                                    # provably clean
    1) files=$(printf '%s\n' "$mt" | sed -n 's/^[0-7]\{6\} [0-9a-f]\{40\} [123]\t//p' \
               | sort -u | tr '\n' ' ' | sed 's/ $//')
       reason="merge conflict(s) predicted${files:+ in: $files}" ;;
    *) reason="merge-tree could not verify safety (exit $mt_rc, failing closed)" ;;
  esac
fi

if [ -n "$reason" ]; then
  report "- ⚠ auto-update SKIPPED: $reason" \
         "- $behind commit(s) behind \`$UPSTREAM_REF\` · sentinel conflict-risk: $risk" \
         "- resolve/\`/promote\` diverged CORE files, then merge manually"
  notify "⚠ open-bridge auto-update SKIPPED: $reason ($behind behind). Manual merge needed."
  echo "autoupdate: skipped — $reason"; exit 0
fi

# ---- SAFE → auto-merge (skip the local pre-commit hook for the headless merge) ----
before=$(git rev-parse --short HEAD)
if git -c core.hooksPath=/dev/null merge --no-edit "$UPSTREAM_REF" >/tmp/ob-autoupdate-merge.log 2>&1; then
  after=$(git rev-parse --short HEAD)
  report "- ✅ auto-updated \`$before\` → \`$after\` ($behind commit(s) merged from \`$UPSTREAM_REF\`)"
  notify "✅ open-bridge auto-updated: $behind commit(s) merged ($before→$after)"
  echo "autoupdate: merged $behind commit(s) ($before→$after)"
else
  git merge --abort 2>/dev/null || true
  report "- 🔴 auto-update merge FAILED and was aborted — $behind behind, manual merge needed"
  notify "🔴 open-bridge auto-update merge FAILED (aborted). Manual merge needed."
  echo "autoupdate: merge failed, aborted"; exit 1
fi
