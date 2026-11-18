#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# overlay-autosync.sh — unattended sync of every subscribed org overlay.
#
# The companion to upstream-autoupdate.sh. That one keeps CORE current; this one
# keeps the ORG layer current. Without it, staying current is a thing somebody
# has to remember, and the failure is silent: an overlay drifts for weeks while
# every session keeps using the copy it happens to hold. Measured on the
# instance this comes from: 71 days stale, 124 overlay commits behind, 6 of 26
# org skills present — and the skill somebody was looking for was in the other 20.
#
# WHY THIS CAN RUN UNATTENDED AT ALL. The engine's non-interactive sync splits
# the work exactly where the trust boundary sits:
#   · config, contexts, projects, mandants, accounts   → applied
#   · updates to behavioural files ALREADY accepted    → applied (the [y] gate
#     is first-materialize only: `first_time = dest not in prev_files`)
#   · behavioural files arriving for the FIRST time    → SKIPPED, listed, never
#     silently installed
# So the publisher stays responsible for what it ships, the consumer keeps one
# decision per genuinely new tool, and nothing in between needs a human.
# A new skill is therefore REPORTED, not applied — that is the point, not a gap.
#
# A skill folder is held WHOLE when one file in it is new, so an overlay that
# ships a new reference or test with most skill changes leaves accepted skills
# behind every morning. The consumer can give a standing answer per overlay:
# materialize.unattended_accept: known (skill folders already held) or all (new
# skills and agents too). Default none. See docs/org-overlays.md.
#
# THE DECISION LIVES IN THE ENGINE: `overlay.py sync --unattended` plans each
# overlay and applies it only when the plan needs nobody. This script schedules
# it, writes the report and sends the notification.
#   · a conflict with a local edit     → the overlay is HELD, nothing written
#   · a planned deletion               → HELD, nothing written
#   · a new behavioural file           → applied without it, listed as pending
#   · inside pull_interval_days        → not-due, nothing fetched
# Why a conflict holds the whole overlay: plain `sync --yes` keeps the local side
# and advances the lock pin, and from the next run on the file reads as an
# ordinary local edit. The upstream change was lost and nothing said so any
# more. Why a deletion holds it: an unattended run applies and updates, it never
# deletes. The engine's own prune guard lets up to LARGE_PRUNE_THRESHOLD (5)
# clean orphans go under --yes; measured when this script was first written,
# exactly 5 were planned, and one of them
# (skills/meeting-transcription/scripts/anchor_transcript.py) was a TRACKED file
# CORE ships, an orphan only because the overlay had stopped shipping that skill.
# A deletion is a human's call, so it escalates to one.
#
# Notifies when the outcome CHANGES, not every morning: a held overlay stays
# held until somebody acts, and the same message daily is noise. `/overlay
# status` shows the last run at any time.
#
# Env (optional): SIGNAL_ACCOUNT + SIGNAL_RECIPIENT (both set → Signal push).
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 1

REPORT="work/overlay-status.md"
LOG="${TMPDIR:-/tmp}/ob-overlay-autosync.log"
LAST_SENT=".bridge/overlay-autosync.notified"

notify() {
  { [ -n "${SIGNAL_ACCOUNT:-}" ] && [ -n "${SIGNAL_RECIPIENT:-}" ] \
    && command -v signal-cli >/dev/null 2>&1 \
    && signal-cli -a "$SIGNAL_ACCOUNT" send -m "$1" "$SIGNAL_RECIPIENT" >/dev/null 2>&1; } || true
}
notify_on_change() {  # $1 = message; sent only when it differs from the last one
  [ "$(cat "$LAST_SENT" 2>/dev/null)" = "$1" ] && return 0
  notify "$1"; mkdir -p .bridge; printf '%s' "$1" > "$LAST_SENT"
}
report() { mkdir -p work; { echo "# Overlay Auto-Sync, $(date '+%F %T')"; echo; printf '%s\n' "$@"; } > "$REPORT"; }

# The interpreter comes from one shared definition, not a copy per script:
# scripts/lib/bridge-python.sh, which carries the reasoning and the candidate
# list. It sets $PY or returns non-zero.
. "$(dirname "$0")/lib/bridge-python.sh" || true
if [ -z "$PY" ]; then
  report "- 🔴 no python3 with PyYAML found; the overlay engine cannot run" \
         "- tried: \`\$BRIDGE_PYTHON\`, \`python3\`, /opt/homebrew, /usr/local, /usr/bin" \
         "- a scheduled run gets a minimal PATH; set \`BRIDGE_PYTHON\` or install PyYAML for the interpreter it finds"
  notify_on_change "🔴 overlay auto-sync cannot run: no python3 with PyYAML"
  echo "overlay-autosync: no usable python3"; exit 1
fi

branch=$(git branch --show-current 2>/dev/null || echo "")
case "$branch" in
  user/*) ;;
  *) report "- ⚠ skipped: not on a user/* branch (on '${branch:-detached}')" \
            "- the overlay engine only materializes on a user/* branch"
     echo "overlay-autosync: skipped, branch '${branch:-detached}'"; exit 0 ;;
esac

# Nothing subscribed → say so once and stay quiet. Not an error.
#
# A FAILED list and an EMPTY list are different answers and must never print the
# same. The first version discarded stderr and tested stdout for content, so any
# error at all — a missing dependency, an unreadable lockfile, a syntax error —
# rendered as "✓ no overlays subscribed": a green tick on a question nobody could
# answer. That is the fail-OPEN shape this repo already learned once, in the
# merge-tree guard that grepped localized prose.
subs=$(LC_ALL=C "$PY" scripts/overlay.py list 2>"$LOG.list") ; list_rc=$?
if [ "$list_rc" -ne 0 ]; then
  report "- 🔴 cannot read the overlay subscriptions (exit $list_rc)" \
         "- this is NOT the same as having none; nothing was synced" \
         "" '```' "$(tail -5 "$LOG.list" 2>/dev/null)" '```'
  notify_on_change "🔴 overlay auto-sync: cannot read subscriptions (exit $list_rc). Nothing synced."
  echo "overlay-autosync: list failed (exit $list_rc)"; exit 1
fi
if [ -z "$subs" ]; then
  report "- ✓ no overlays subscribed"; echo "overlay-autosync: no overlays"; exit 0
fi

# LC_ALL=C: the output is parsed, and a localized git underneath would move the
# strings. Same lesson as the merge-tree guard in upstream-autoupdate.sh, where
# grepping localized prose failed OPEN.
LC_ALL=C "$PY" scripts/overlay.py sync --unattended </dev/null >"$LOG" 2>&1
rc=$?
lines=$(grep -E '^unattended [^ ]+: ' "$LOG" 2>/dev/null)
held=$(printf '%s\n' "$lines" | grep -c ': held' ) || held=0
failed=$(printf '%s\n' "$lines" | grep -c ': failed') || failed=0
pending=$(printf '%s\n' "$lines" | grep -c 'pending: ') || pending=0

if [ -z "$lines" ]; then
  report "- 🔴 overlay sync produced no result (exit $rc), see \`$LOG\`"
  notify_on_change "🔴 overlay auto-sync FAILED (exit $rc). See $LOG"
  echo "overlay-autosync: failed (exit $rc)"; exit 1
fi

bullets=$(printf '%s\n' "$lines" | sed 's/^unattended /- /')
status=$(LC_ALL=C "$PY" scripts/overlay.py status 2>/dev/null)
next=""
[ "$held" -gt 0 ] && next="- held: review with \`/overlay diff\`, then run \`/overlay sync\` interactively"
[ "$pending" -gt 0 ] && next="${next:+$next
}- pending: new behavioural files wait for an explicit \`[y]\` in \`/overlay sync\` (or set \`materialize.unattended_accept\`, docs/org-overlays.md)"
report "$bullets" ${next:+"" "$next"} "" '```' "$status" '```'

summary=$(printf '%s\n' "$lines" | grep -v ': not-due' | sed 's/^unattended //')
if [ "$failed" -gt 0 ]; then
  notify_on_change "🔴 overlay auto-sync FAILED: $summary"
elif [ "$held" -gt 0 ] || [ "$pending" -gt 0 ]; then
  notify_on_change "⚠ overlay auto-sync needs you: $summary"
elif [ -n "$summary" ]; then
  notify_on_change "✅ overlay auto-sync: $summary"
fi
echo "overlay-autosync: held=$held failed=$failed pending=$pending"
[ "$failed" -eq 0 ]
