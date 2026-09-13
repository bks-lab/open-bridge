#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Fixture test for the shared drift check (scripts/worklog-drift-check.sh), run
# through the Claude Code Stop hook (.claude/hooks/worklog-drift-check.sh) and
# directly with --client codex and --client vibe, plus the two declarations
# that wire it into those clients (.codex/hooks.json, .vibe/hooks.toml).
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

# ---------------------------------------------------------------------------
# The same check behind Codex and Mistral Vibe. Each client has its own hook
# contract, so the script takes --client and speaks it:
#   claude  exit 2 + reason on stderr blocks; a silent exit 0 ends the turn
#   codex   Stop hook: exit 2 + reason on stderr blocks; a pass prints {}
#           (Codex expects JSON on stdout for Stop); stop_hook_active=true lets
#           the turn end, because Codex documents no cap on continuations
#   vibe    post_agent hook: always exit 0 (exit 2 is a hook FAILURE there);
#           a block is {"decision":"deny","reason":...} on stdout
# The non-Claude clients find the checkout from the payload's cwd or the git
# toplevel. Every client run sets CLAUDE_PROJECT_DIR to a CLEAN decoy: a client
# that wrongly read it would see no drift and fail the "must block" rows.
# ---------------------------------------------------------------------------
SCRIPT="$(pwd)/scripts/worklog-drift-check.sh"
DECOY=$(make_fixture)

drift_fixture() {
  local d; d=$(make_fixture)
  printf 'x\n' > "$d/note.md"
  touch -t 202601010000 "$d/work/log.md"
  echo "$d"
}

# run_client <client> <cwd> <stdin payload> -> sets OUT, ERR, CODE
run_client() {
  local errf; errf=$(mktemp); TMPS="$TMPS $errf"
  OUT=$( cd "$2" && printf '%s' "$3" | CLAUDE_PROJECT_DIR="$DECOY" bash "$SCRIPT" --client "$1" 2>"$errf" ); CODE=$?
  ERR=$(cat "$errf")
}

gate_of() { # gate_of <text> -> 1, 2 or -
  case "$1" in
    *"claims the TASK is finished"*) echo 2 ;;
    *"work-log drift"*)              echo 1 ;;
    *)                               echo - ;;
  esac
}

vibe_verdict() { # vibe_verdict <stdout> -> "<decision>:<gate>", "none" or "invalid-json"
  [ -z "$1" ] && { echo none; return; }
  printf '%s' "$1" | python3 -c '
import json, sys
d = json.load(sys.stdin)
r = d.get("reason", "")
g = "2" if "claims the TASK is finished" in r else ("1" if "work-log drift" in r else "-")
print(str(d.get("decision")) + ":" + g)' 2>/dev/null || echo invalid-json
}

echo
echo "Codex (Stop hook):"
d=$(drift_fixture)
run_client codex / "{\"cwd\": \"$d\", \"stop_hook_active\": false}"
check "drift blocks: exit 2, reason on stderr, nothing on stdout" "2:1:" "$CODE:$(gate_of "$ERR"):$OUT"
run_client codex / "{\"cwd\": \"$d\", \"stop_hook_active\": true}"
check "a turn the hook already continued is let go (no loop)" "0:{}" "$CODE:$OUT"
d=$(make_fixture)
run_client codex / "{\"cwd\": \"$d\"}"
check "a clean checkout ends the turn with {} on stdout" "0:{}" "$CODE:$OUT"
d=$(drift_fixture)
run_client codex "$d/work" '{}'
check "no cwd in the payload: the git toplevel of the hook's directory" "2:1" "$CODE:$(gate_of "$ERR")"

echo
echo "Mistral Vibe (post_agent hook):"
d=$(drift_fixture)
run_client vibe / "{\"cwd\": \"$d\"}"
check "drift denies: exit 0 and the Gate 1 reason as JSON" "0:deny:1" "$CODE:$(vibe_verdict "$OUT")"
d=$(make_fixture)
write_status "$d" work/tasks/a/STATUS.md doing "Status: done"
run_client vibe / "{\"cwd\": \"$d\"}"
check "a zombie claim denies with the Gate 2 reason" "0:deny:2" "$CODE:$(vibe_verdict "$OUT")"
d=$(make_fixture)
run_client vibe / "{\"cwd\": \"$d\"}"
check "a clean checkout passes through: exit 0, empty stdout" "0:none" "$CODE:$(vibe_verdict "$OUT")"

echo
echo "Claude path and arguments:"
# Run from a CLEAN checkout, with CLAUDE_PROJECT_DIR naming a drifted one and a
# stray BRIDGE_PROJECT_DIR (the launcher-era variable) naming the clean one. Only
# a hook that follows CLAUDE_PROJECT_DIR through the entry point blocks here; an
# earlier row that ran from / passed for a hook that ignored the variable.
d=$(drift_fixture)
out=$( cd "$DECOY" && BRIDGE_PROJECT_DIR="$DECOY" CLAUDE_PROJECT_DIR="$d" bash "$HOOK" 2>&1 >/dev/null ); code=$?
check "CLAUDE_PROJECT_DIR decides, through the entry point; BRIDGE_PROJECT_DIR does not" "2:1" "$code:$(gate_of "$out")"
bash "$SCRIPT" --client gemini </dev/null >/dev/null 2>&1; code=$?
check "an unknown client fails loudly instead of passing silently" "1" "$code"
bash "$SCRIPT" --client codex --bogus </dev/null >/dev/null 2>&1; code=$?
check "an unknown extra argument fails loudly too" "1" "$code"
bash "$SCRIPT" --client </dev/null >/dev/null 2>&1; code=$?
check "--client without a value fails loudly" "1" "$code"
d=$(drift_fixture)
OUT=$( cd / && printf '{"cwd": "%s"}' "$d" | CLAUDE_PROJECT_DIR="$DECOY" bash "$SCRIPT" --client=vibe 2>/dev/null ); CODE=$?
check "the --client=vibe form works like --client vibe" "0:deny:1" "$CODE:$(vibe_verdict "$OUT")"
t=$(mktemp -d); TMPS="$TMPS $t"; mkdir -p "$t/.claude/hooks"; cp "$HOOK" "$t/.claude/hooks/"
out=$(bash "$t/.claude/hooks/worklog-drift-check.sh" </dev/null 2>&1); code=$?
case "$out" in *"is missing"*) m=named ;; *) m=silent ;; esac
check "the entry point names a missing shared script instead of a bare 127" "1:named" "$code:$m"

echo
echo "Hook declarations run the shared check as written:"
# The exact command strings from .codex/hooks.json and .vibe/hooks.toml, run the
# way each client runs them: through a shell, from the checkout. Codex documents
# $(git rev-parse --show-toplevel) in its own examples; Vibe's hook executor
# calls asyncio.create_subprocess_shell (its 2.25.1 changelog says "without a
# shell", but the code is what runs).
# Each runs in a fixture holding a copy of the script, so the verdict depends on
# the fixture and not on the branch this suite happens to run on.
decl() { # decl <codex|vibe> -> the declared command string
  python3 - "$1" <<'PY'
import json, sys
if sys.argv[1] == "codex":
    with open(".codex/hooks.json") as f:
        print(json.load(f)["hooks"]["Stop"][0]["hooks"][0]["command"])
else:
    try:
        import tomllib
    except ImportError:
        sys.exit("reading .vibe/hooks.toml needs python3 >= 3.11 (tomllib)")
    with open(".vibe/hooks.toml", "rb") as f:
        hooks = tomllib.load(f)["hooks"]
    print(next(h["command"] for h in hooks if h.get("type") == "post_agent"))
PY
}
with_script() { mkdir -p "$1/scripts"; cp "$SCRIPT" "$1/scripts/worklog-drift-check.sh"; }
run_vibe_cmd() { # run_vibe_cmd <dir> -> stdout of the declared command, via sh
  ( cd "$1" && printf '{"cwd": "%s"}' "$1" | CLAUDE_PROJECT_DIR="$DECOY" sh -c "$VIBE_CMD" )
}

CODEX_CMD=$(decl codex 2>&1); VIBE_CMD=$(decl vibe 2>&1)
case "$CODEX_CMD" in *scripts/worklog-drift-check.sh*"--client codex"*) ok=yes ;; *) ok="no ($CODEX_CMD)" ;; esac
check ".codex/hooks.json: Stop runs worklog-drift-check.sh --client codex" "yes" "$ok"
case "$VIBE_CMD" in *scripts/worklog-drift-check.sh*"--client vibe"*) ok=yes ;; *) ok="no ($VIBE_CMD)" ;; esac
check ".vibe/hooks.toml: post_agent runs worklog-drift-check.sh --client vibe" "yes" "$ok"

# The gate is read from stderr, not only the exit code: bash exits 2 on a
# syntax error too, so a garbled or missing declaration once passed this row.
d=$(drift_fixture); with_script "$d"
errf=$(mktemp); TMPS="$TMPS $errf"
out=$( cd "$d" && printf '{}' | CLAUDE_PROJECT_DIR="$DECOY" bash -c "$CODEX_CMD" 2>"$errf" ); code=$?
check "the Codex command, through a shell, blocks a drifted checkout" "2:1:" "$code:$(gate_of "$(cat "$errf")"):$out"
d=$(make_fixture); with_script "$d"
out=$( cd "$d" && printf '{}' | CLAUDE_PROJECT_DIR="$DECOY" bash -c "$CODEX_CMD" 2>/dev/null ); code=$?
check "the Codex command prints {} for a clean checkout" "0:{}" "$code:$out"
d=$(drift_fixture); with_script "$d"
out=$(run_vibe_cmd "$d" 2>/dev/null); code=$?
check "the Vibe command, through sh from the checkout, denies a drifted one" "0:deny:1" "$code:$(vibe_verdict "$out")"
d=$(make_fixture); with_script "$d"
out=$(run_vibe_cmd "$d" 2>/dev/null); code=$?
check "the Vibe command passes a clean checkout through" "0:none" "$code:$(vibe_verdict "$out")"

echo
echo "Robustness:"
# A closed stdin once hung the payload read: the pipe bash opens for $(cat) can
# land on fd 0 itself. Watched for five seconds, then killed.
d=$(make_fixture)
( cd "$d" && exec bash "$SCRIPT" --client codex <&- >/dev/null 2>&1 ) & pid=$!
i=0; while [ "$i" -lt 50 ] && kill -0 "$pid" 2>/dev/null; do sleep 0.1; i=$((i+1)); done
if kill -0 "$pid" 2>/dev/null; then kill -9 "$pid" 2>/dev/null; hung=yes; else hung=no; fi
wait "$pid" 2>/dev/null
check "a closed stdin does not hang the codex client" "no" "$hung"

# Without python3 (a failing stub stands in for it) Codex must still let a
# continued turn end, or it can loop, and a Vibe block must still be visible.
nopy=$(mktemp -d); TMPS="$TMPS $nopy"
printf '#!/bin/sh\nexit 127\n' > "$nopy/python3"; chmod +x "$nopy/python3"
d=$(drift_fixture)
OUT=$( cd "$d" && printf '{"stop_hook_active": true}' | PATH="$nopy:$PATH" CLAUDE_PROJECT_DIR="$DECOY" bash "$SCRIPT" --client codex 2>/dev/null ); CODE=$?
check "no python3: the Codex loop guard still lets a continued turn end" "0:{}" "$CODE:$OUT"
errf=$(mktemp); TMPS="$TMPS $errf"
OUT=$( cd "$d" && printf '{}' | PATH="$nopy:$PATH" CLAUDE_PROJECT_DIR="$DECOY" bash "$SCRIPT" --client vibe 2>"$errf" ); CODE=$?
check "no python3: a Vibe block falls back to exit 2 with the reason on stderr" "2:1:" "$CODE:$(gate_of "$(cat "$errf")"):$OUT"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
