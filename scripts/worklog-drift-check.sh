#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# worklog-drift-check.sh: the Bridge work-log and STATUS.md drift check
#
# One check behind three clients, each wiring it in its own way:
#
#   Claude Code   Stop hook in the tracked .claude/settings.json, through the
#                 .claude/hooks/worklog-drift-check.sh entry point:
#                   "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/worklog-drift-check.sh"
#   Codex CLI     Stop hook in .codex/hooks.json, with --client codex
#   Mistral Vibe  post_agent hook in .vibe/hooks.toml, with --client vibe
#
# Nudges the agent to log before it ends a turn in which it changed code, docs
# or configs but work/log.md was not touched. Keeps the work system an actual
# working memory instead of drift.
#
# Two gates: (1) code/doc changed but work/log.md not touched today; (2) a
# STATUS.md whose body asserts completion while its frontmatter status: is not
# done (zombie-claim drift). Either fires, the turn goes back with the reason.
#
# How each client hears the verdict:
#   claude  pass: exit 0, silent         block: exit 2, reason on stderr
#   codex   pass: exit 0, {} on stdout   block: exit 2, reason on stderr
#           Codex expects JSON on stdout when a Stop hook exits 0. A turn this
#           hook has already continued once (stop_hook_active) is let go:
#           Codex documents no cap on continuations, so blocking again could
#           loop forever.
#   vibe    pass: exit 0, empty stdout   block: exit 0 and
#           {"decision": "deny", "reason": "..."} on stdout
#           Vibe treats exit 2 as a hook failure, not a block, and caps the
#           retries at three per turn on its own. It runs the command through a
#           shell from the directory it was started in.
#   any     exit 1 on an unknown argument or client, so a miswired hook shows
#           up as a hook error instead of passing every turn in silence.
#
# Claude finds the checkout through CLAUDE_PROJECT_DIR. Codex and Vibe send a
# JSON payload on stdin; its cwd, or else the hook's own directory, resolves to
# the git toplevel. They ignore CLAUDE_PROJECT_DIR, which can leak in from a
# surrounding Claude session and name a different checkout.
#
# python3 reads the payload's cwd and writes Vibe's JSON. Without it both
# clients use the hook's own directory, and a Vibe block arrives as a hook
# failure (exit 2, reason on stderr) instead of a retry. The Codex loop guard is
# a plain grep and holds without python3.
#
# A nudge, not a sandbox: `touch work/log.md` games Gate 1.

set -u

client=claude
while [ $# -gt 0 ]; do
  case "$1" in
    --client)
      if [ $# -lt 2 ]; then
        echo "worklog-drift-check: --client needs a value (claude|codex|vibe)" >&2
        exit 1
      fi
      client="$2"; shift 2 ;;
    --client=*)
      client="${1#--client=}"; shift ;;
    *)
      echo "worklog-drift-check: unknown argument '$1' (usage: [--client claude|codex|vibe])" >&2
      exit 1 ;;
  esac
done
case "$client" in
  claude|codex|vibe) ;;
  *) echo "worklog-drift-check: unknown client '$client' (claude|codex|vibe)" >&2
     exit 1 ;;
esac

# pass: let the turn end, in the client's own terms.
pass() {
  [ "$client" = codex ] && printf '{}\n'
  exit 0
}

# block: send the turn back with the reason read from stdin.
block() {
  local reason
  reason=$(cat)
  if [ "$client" = vibe ]; then
    if printf '%s' "$reason" | python3 -c 'import json, sys; print(json.dumps({"decision": "deny", "reason": sys.stdin.read()}))' 2>/dev/null; then
      exit 0
    fi
    # No python3, no JSON. Fall through to stderr and exit 2, which Vibe
    # reports as a hook failure: visible beats silent.
  fi
  printf '%s\n' "$reason" >&2
  exit 2
}

# Read the payload only from an open, non-terminal stdin. With fd 0 closed, the
# pipe bash creates for $(cat) lands on fd 0 itself and cat waits forever. Ask
# with `[ -e /dev/fd/0 ]`, which opens nothing: a probe like
# `{ : <&0; } 2>/dev/null` first opens /dev/null onto the free fd 0 and then
# reports stdin as open.
payload=""
if [ "$client" != claude ] && [ -e /dev/fd/0 ] && [ ! -t 0 ]; then
  payload=$(cat)
fi

# payload_field <key>: a top-level payload value as text (booleans lowercased).
payload_field() {
  [ -n "$payload" ] || return 0
  printf '%s' "$payload" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get(sys.argv[1])
except Exception:
    value = None
print("" if value is None else (str(value).lower() if isinstance(value, bool) else value))' "$1" 2>/dev/null
}

# payload_is_true <key>: the payload sets <key> to true. The grep fallback keeps
# the Codex loop guard alive when python3 is missing or broken; inside a JSON
# string the key's quotes are escaped, so message text cannot match it.
payload_is_true() {
  [ "$(payload_field "$1")" = "true" ] && return 0
  printf '%s' "$payload" | tr -d '\n' | grep -Eq "\"$1\"[[:space:]]*:[[:space:]]*true"
}

if [ "$client" = claude ]; then
  cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || pass
else
  [ "$client" = codex ] && payload_is_true stop_hook_active && pass
  hook_cwd=$(payload_field cwd)
  if [ -n "$hook_cwd" ]; then
    cd "$hook_cwd" 2>/dev/null || pass
  fi
  top=$(git rev-parse --show-toplevel 2>/dev/null) || pass
  cd "$top" 2>/dev/null || pass
fi
git rev-parse --git-dir >/dev/null 2>&1 || pass

branch=$(git branch --show-current 2>/dev/null || echo "")
case "$branch" in
  user/*) ;;
  *) pass ;;  # only enforce on user branches
esac

[ -f work/log.md ] || pass

# Respect an opt-out marker the user can drop for a pure-reading session
[ -f .bridge-nolog ] && pass

# ---------------------------------------------------------------------------
# Gate 2, zombie-claim drift: a STATUS.md whose body asserts completion while
# its frontmatter status: is not done. Runs before the log-drift gate so it
# fires even when log.md was already touched today. A `touch` can game it; not
# the threat model, since this is a nudge, like Gate 1.
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
  # finished sub-items while its own status stays doing, which is by design, not
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
  # a task carrying a section headed "why review and not doing", and the gate
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
  # is nothing but the claim. ✅ is deliberately absent: it is a checklist mark.
  CLAIM='^[[:space:]]*(#{1,6}[[:space:]]*)?(status|ergebnis|outcome)[[:space:]]*:[[:space:]]*(done|erledigt|abgeschlossen|fertig)|^[[:space:]]*#{1,6}[[:space:]]*(abgeschlossen|erledigt|done|fertig)[[:space:]]*$'
  if echo "$body" | grep -qiE "$CLAIM"; then
    block <<EOF
Bridge STATUS.md drift detected.

$sf claims the TASK is finished (a status line, or a heading that is
nothing but the claim) while its frontmatter says status: $fm_status.

Set status: done (after the review hop the human confirms), or remove the
completion claim from the body. Blocked? keep doing/review + add blocked_by:.
EOF
  fi
done

# Any tracked files modified in working tree?
changed=$(git status --porcelain 2>/dev/null | awk '{print $2}')
[ -z "$changed" ] && pass

# log.md itself changed → good, we're logging. Allow stop.
echo "$changed" | grep -qx "work/log.md" && pass

# Did we edit anything that should have a log entry? (code, docs, configs)
if ! echo "$changed" | grep -qE '\.(md|py|ts|tsx|js|yaml|yml|json|sh|rs|go)$|^(skills|protocols|contexts|agents|personas|calendar|mandants|remotes)/'; then
  pass
fi

# Freshness check via mtime, locale- and format-agnostic. If log.md was
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
[ "$log_date" = "$today" ] && pass

block <<EOF
Bridge work-log drift detected.

Modified files without a log entry today:
$(echo "$changed" | head -5 | sed 's/^/  - /')
$( [ "$(echo "$changed" | wc -l)" -gt 5 ] && echo "  ... and $(( $(echo "$changed" | wc -l) - 5 )) more" )

Add a row to work/log.md (format: | YYYY-MM-DD HH:MM | glyph | context | what |)
before ending the turn, or drop an empty .bridge-nolog file for a read-only session.
EOF
