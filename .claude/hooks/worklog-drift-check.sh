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
status_files=$(git status --porcelain 2>/dev/null \
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

  # Body (drop the leading YAML frontmatter block) asserts completion?
  body=$(awk 'BEGIN{fm=0} /^---[[:space:]]*$/{fm++; next} fm>=2' "$sf" 2>/dev/null)
  if echo "$body" | grep -qiE 'done|✅|erledigt|abgeschlossen|fertig'; then
    cat >&2 <<EOF
Bridge STATUS.md drift detected.

$sf asserts done (body text says done/✅/erledigt/abgeschlossen/fertig)
but frontmatter status: $fm_status.

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
log_date=$(stat -f '%Sm' -t '%Y-%m-%d' work/log.md 2>/dev/null \
           || date -d "@$(stat -c %Y work/log.md)" '+%Y-%m-%d' 2>/dev/null \
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
