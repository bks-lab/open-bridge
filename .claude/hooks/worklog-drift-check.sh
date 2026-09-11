#!/usr/bin/env bash
# worklog-drift-check.sh — Claude Code Stop hook
#
# Nudges Claude to log before ending the turn when the session made
# code/doc edits but work/log.md was not touched. Keeps the work-system
# as actual working memory instead of drift.
#
# Wired in the tracked .claude/settings.json (Stop hook):
#
#   {
#     "hooks": {
#       "Stop": [
#         {
#           "hooks": [
#             {"type": "command",
#              "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/worklog-drift-check.sh"}
#           ]
#         }
#       ]
#     }
#   }
#
# Two gates: (1) code/doc changed but work/log.md not touched today; (2) a
# STATUS.md whose body asserts completion while its frontmatter status: is not
# done (zombie-claim drift). Either fires → block stop (exit 2).
#
# Exit codes:
#   0 — allow stop (no drift, or not applicable)
#   2 — block stop with reminder (Claude sees it in-band and adds a log entry)

set -u

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

branch=$(git branch --show-current 2>/dev/null || echo "")
case "$branch" in
  user/*) ;;
  *) exit 0 ;;  # only enforce on user branches
esac

[ -f work/log.md ] || exit 0

# Respect an opt-out marker the user can drop for a pure-reading session
[ -f .bridge-nolog ] && exit 0

# ---------------------------------------------------------------------------
# Gate 2 — zombie-claim drift: a STATUS.md whose body asserts completion while
# its frontmatter status: is not done. Runs before the log-drift gate so it
# fires even when log.md was already touched today. A `touch` can game it; not
# the threat model — this is a nudge, like Gate 1.
# ---------------------------------------------------------------------------
# -uall: without it `git status --porcelain` collapses an untracked DIRECTORY
# to one line ("?? work/tasks/") and never names the file inside, so a brand
# new task's STATUS.md was invisible to this gate until its directory was
# tracked. Gate 1 below keeps the default listing on purpose: it asks whether
# work happened, and one line for a new folder answers that just as well.
status_files=$(git status --porcelain -uall 2>/dev/null \
               | awk '{print $2}' \
               | grep -E '(^|/)STATUS\.md$' || true)
for sf in $status_files; do
  [ -f "$sf" ] || continue   # deleted/renamed-away → skip

  # Streams never reach `done` (AGENTS.md: long-runners close via `mv` to
  # work/done/, never via status:). A stream body legitimately reports ✅ on
  # finished sub-items while its own status stays doing — that is by design, not
  # zombie-claim drift. Gate 2 is meaningful only for finite tasks (work/tasks/),
  # so skip streams to avoid a guaranteed false positive on every mature stream.
  case "$sf" in work/streams/*) continue ;; esac

  # Frontmatter status: (first match wins; tolerate quotes + trailing comment).
  fm_status=$(grep -m1 -E '^status:' "$sf" 2>/dev/null \
              | sed -E 's/^status:[[:space:]]*"?([A-Za-z_-]+)"?.*/\1/')
  [ -z "$fm_status" ] && continue       # no status field → not in scope
  [ "$fm_status" = "done" ] && continue # already done → no mismatch
  # `review` means finished and awaiting a human's confirmation (AGENTS.md:
  # never set an item straight to Done). A review body that says the work is
  # finished is therefore CORRECT, not drift. Live proof of the false positive:
  # a task carrying a section headed "why review and not doing" — the gate
  # fired on a file that explains its own status.
  [ "$fm_status" = "review" ] && continue

  # Blocked task (non-empty blocked_by:) → legitimately carries close/done language
  # in its body while status stays doing/review; the flag IS the "not yet done"
  # signal. This matches the reminder's own "Blocked? keep doing/review + add
  # blocked_by:" guidance, so skip it rather than fire a guaranteed false positive.
  grep -qE '^blocked_by:[[:space:]]*"?[^"[:space:]]' "$sf" 2>/dev/null && continue

  # Body (drop the leading YAML frontmatter block) asserts completion?
  body=$(awk 'BEGIN{fm=0} /^---[[:space:]]*$/{fm++; next} fm>=2' "$sf" 2>/dev/null)
  # A whole-task claim only. The earlier form matched those words ANYWHERE in
  # the body, and completion words describe sub-objects constantly: "the
  # letters are finished", "→ done, see section 2", a ✅ in a checklist. Both
  # live hits were of that kind, one of them under a heading that read "noch
  # nichts raus" (nothing has gone out yet). A word-level match cannot tell a
  # finished DELIVERABLE from a finished TASK, so it asks for the two shapes an
  # author only writes about the task itself: a status line, or a heading that
  # is nothing but the claim. ✅ is deliberately absent — it is a checklist mark.
  CLAIM='^[[:space:]]*(#{1,6}[[:space:]]*)?(status|ergebnis|outcome)[[:space:]]*:[[:space:]]*(done|erledigt|abgeschlossen|fertig)|^[[:space:]]*#{1,6}[[:space:]]*(abgeschlossen|erledigt|done|fertig)[[:space:]]*$'
  if echo "$body" | grep -qiE "$CLAIM"; then
    cat >&2 <<EOF
Bridge STATUS.md drift detected.

$sf claims the TASK is finished (a status line, or a heading that is
nothing but the claim) while its frontmatter says status: $fm_status.

Set status: done (after the review hop the human confirms), or remove the
completion claim from the body. Blocked? keep doing/review + add blocked_by:.
EOF
    exit 2
  fi
done

# Any tracked files modified in working tree?
changed=$(git status --porcelain 2>/dev/null | awk '{print $2}')
[ -z "$changed" ] && exit 0

# log.md itself changed → good, we're logging. Allow stop.
echo "$changed" | grep -qx "work/log.md" && exit 0

# Did we edit anything that should have a log entry? (code, docs, configs)
if ! echo "$changed" | grep -qE '\.(md|py|ts|tsx|js|yaml|yml|json|sh|rs|go)$|^(skills|protocols|contexts|agents|personas|calendar|mandants|remotes)/'; then
  exit 0
fi

# Freshness check via mtime — locale- and format-agnostic. If log.md was
# touched today, we trust it. This is a nudge hook, not a security check;
# `touch work/log.md` would game it, but that's not the threat model.
today=$(date '+%Y-%m-%d')
# GNU first, BSD second, and both probed with a flag the OTHER one rejects.
# The previous order asked BSD first with `stat -f`, which on GNU coreutils is
# `--file-system` and EXITS 0 with filesystem info: the `||` fallback never
# ran, log_date became that text, never matched today, and Gate 1 fired on
# every turn. A fallback chain whose first link succeeds wrongly has no second
# link. `stat -c` and `date -d` fail cleanly on macOS, `stat -f %m` and
# `date -r` fail cleanly on GNU, so each pair is unambiguous.
log_epoch=$(stat -c %Y work/log.md 2>/dev/null \
            || stat -f %m work/log.md 2>/dev/null \
            || echo 0)
log_date=$(date -d "@$log_epoch" '+%Y-%m-%d' 2>/dev/null \
           || date -r "$log_epoch" '+%Y-%m-%d' 2>/dev/null \
           || echo "")
[ "$log_date" = "$today" ] && exit 0

cat >&2 <<EOF
Bridge work-log drift detected.

Modified files without a log entry today:
$(echo "$changed" | head -5 | sed 's/^/  - /')
$( [ "$(echo "$changed" | wc -l)" -gt 5 ] && echo "  ... and $(( $(echo "$changed" | wc -l) - 5 )) more" )

Add a row to work/log.md (format: | YYYY-MM-DD HH:MM | glyph | context | what |)
before ending the turn, or drop an empty .bridge-nolog file for a read-only session.
EOF

exit 2
