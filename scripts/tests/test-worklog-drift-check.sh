#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Fixture test for the Stop hook (.claude/hooks/worklog-drift-check.sh).
#
# Gate 1 nudges when files changed and work/log.md carries no row today.
# Gate 2 is the zombie-claim gate: a STATUS.md whose body asserts THE TASK is
# finished while its frontmatter `status:` says otherwise.
#
# Gate 2 is the one with teeth and the one that can fail in BOTH directions, so
# both are asserted here. The false-positive cases are not invented: they are
# the two live tasks the gate fired on, reduced to their shape. Completion
# words describe sub-objects all the time ("the letters are finished", "-> done,
# see section 2", a check mark in a list), and a body under `status: review`
# says the work is finished BY DESIGN, because review means
# finished-awaiting-confirmation in this repo's model.
#
# Too eager is not the harmless direction. A guard that is always wrong gets
# switched off, and on the instance this was found on it had been off for 57
# days behind a `.bridge-nolog` marker, which is worse than having no guard.
#
# Run: bash scripts/tests/test-worklog-drift-check.sh   (from repo root)
set -u
cd "$(dirname "$0")/../.."

HOOK="$(pwd)/.claude/hooks/worklog-drift-check.sh"
PASS=0; FAIL=0
TMPS=""
cleanup() { for d in $TMPS; do rm -rf "$d"; done; }
trap cleanup EXIT

# A fixture repo on a user/* branch carrying a log row for today, so Gate 1 is
# satisfied and only Gate 2 can speak.
make_fixture() {
  local d; d=$(mktemp -d); TMPS="$TMPS $d"
  git -C "$d" init -q -b user/test
  mkdir -p "$d/work"
  printf '| %s 09:00 | X | t | row |\n' "$(date '+%Y-%m-%d')" > "$d/work/log.md"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@e -c user.name=t commit -qm base >/dev/null 2>&1
  echo "$d"
}

# write_status <dir> <relpath> <status> <body>
# Commit a placeholder first, then write: `git status --porcelain` folds an
# untracked DIRECTORY into one line ("?? work/tasks/") and never names the file
# inside it. The live hits were on CHANGED, tracked files; the untracked-new
# case has its own assertion below.
write_status() {
  local d="$1" rel="$2" st="$3" body="$4"
  mkdir -p "$d/$(dirname "$rel")"
  printf -- '---\nslug: x\nstatus: backlog\n---\n' > "$d/$rel"
  git -C "$d" add -A >/dev/null 2>&1
  git -C "$d" -c user.email=t@e -c user.name=t commit -qm fixture >/dev/null 2>&1
  { printf -- '---\nslug: x\nstatus: %s\n---\n\n' "$st"; printf '%s\n' "$body"; } > "$d/$rel"
}

# run_gate <dir> -> "<exit>:<gate>" where gate is 1, 2 or "-".
# The exit code ALONE cannot tell the two gates apart, and that is not
# theoretical: a portability defect once made Gate 1 fire on every turn, so the
# Gate 2 "must fire" rows went green while Gate 2 never spoke. An assertion
# that is satisfied by the wrong gate proves nothing about the right one.
run_gate() {
  local out code
  out=$( cd "$1" && CLAUDE_PROJECT_DIR="$1" bash "$HOOK" 2>&1 >/dev/null ); code=$?
  case "$out" in
    *"claims the TASK is finished"*) echo "$code:2" ;;
    *"work-log drift"*)              echo "$code:1" ;;
    *)                               echo "$code:-" ;;
  esac
}

check() { # check <label> <expected "exit:gate"> <actual>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); printf '  ok    %s\n' "$1"
  else FAIL=$((FAIL+1)); printf '  FAIL  %s (expected %s, got %s)\n' "$1" "$2" "$3"; fi
}

echo "Gate 2 - must fire (a real zombie claim):"
d=$(make_fixture)
write_status "$d" work/tasks/a/STATUS.md doing "## Status

Status: done"
check "a status line claims done while status: doing" "2:2" "$(run_gate "$d")"

d=$(make_fixture)
write_status "$d" work/tasks/a/STATUS.md doing "## Done

Nothing left open."
check "a heading that is nothing but the claim" "2:2" "$(run_gate "$d")"

echo "Gate 2 - must NOT fire:"
d=$(make_fixture)
write_status "$d" work/tasks/a/STATUS.md review "## Why review and not doing

The analysis is finished and handed over. What is missing is not my work."
check "status: review carrying completion language (review IS finished-in-review)" "0:-" "$(run_gate "$d")"

d=$(make_fixture)
write_status "$d" work/tasks/a/STATUS.md doing "## State 10.09 (weekly): nothing has gone out yet

The letters are finished and helped.

## Next Steps

- second item
      -> done, see section 2. The sender side stands."
check "sub-results and deliverables under status: doing" "0:-" "$(run_gate "$d")"

d=$(make_fixture)
write_status "$d" work/tasks/a/STATUS.md done "All done."
check "status: done" "0:-" "$(run_gate "$d")"

d=$(make_fixture)
mkdir -p "$d/work/tasks/a"
printf -- '---\nslug: x\nstatus: doing\nblocked_by: "waiting on the customer"\n---\n\nStatus: done\n' > "$d/work/tasks/a/STATUS.md"
check "blocked_by is set" "0:-" "$(run_gate "$d")"

d=$(make_fixture)
write_status "$d" work/streams/a/STATUS.md doing "Status: done"
check "a stream (long-runner, never reaches done)" "0:-" "$(run_gate "$d")"

d=$(make_fixture)
mkdir -p "$d/work/tasks/new"
printf -- '---\nslug: x\nstatus: doing\n---\n\nStatus: done\n' > "$d/work/tasks/new/STATUS.md"
check "an untracked new task (porcelain folds the directory)" "2:2" "$(run_gate "$d")"

echo
echo "Gate 1 - must still fire:"
d=$(make_fixture)
printf 'x\n' > "$d/note.md"
touch -t 202601010000 "$d/work/log.md"   # old, but unchanged
check "a changed file with no log row today" "2:1" "$(run_gate "$d")"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
