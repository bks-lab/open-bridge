#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test suite for scripts/voicememo-bundler.sh: the capture watcher must never
# go SILENT when it cannot see the Recordings folder.
#
# Why this exists: the bundler only ever logged a line when it had counted
# something. When the Voice Memos folder became unreadable (a privacy /
# container-protection denial stats the directory fine but lists nothing), the
# glob matched zero files, every run exited 0 and wrote nothing. A real outage
# ran 26 hours that way, with launchd counting hundreds of clean runs. Logging
# an ERROR line on every blind run would not have helped either: a liveness
# check that reads log freshness would have stayed green the whole time.
#
# What it locks down:
#   1. healthy scan: a readable folder stamps a heartbeat file on every run,
#      so a liveness check can read that stamp instead of log freshness.
#   2. blind scan: the folder lists no *.m4a while the baseline names files.
#      Exit non-zero, ONE "scan-blind" log line per outage (not one per run),
#      no heartbeat stamp, and a marker recording when the outage began.
#   3. recovery: the next seeing run logs "recovered", clears the marker and
#      stamps the heartbeat again.
#   4. empty baseline: a machine whose baseline lists nothing may legitimately
#      see zero files. Exit 0, heartbeat stamped, no blind line.
#   5. symlinked deploy: launchers exec a link such as
#      ~/bin/voicememo-bundler.sh, so the script must resolve its own location
#      through the link to find repo-relative files (topology.yaml). A control
#      run without topology.yaml proves the assertion can fail.
#
# HERMETIC + OFFLINE: every case builds a throwaway fake repo + HOME and copies
# the real script in fresh. The unreadable folder is simulated with chmod 000,
# which denies the listing the same way the platform denial does. Cases 2 and 3
# are skipped when running as root, because chmod does not deny root.
#
# Run:  bash skills/meeting-transcription/tests/test-voicememo-bundler.sh
#       (exits non-zero on any failure).

set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REAL_BUNDLER="$SKILL_DIR/scripts/voicememo-bundler.sh"

PASS=0
FAIL=0
TMPS=""
cleanup() { for d in $TMPS; do chmod -R u+rwx "$d" 2>/dev/null; rm -rf "$d"; done; }
trap cleanup EXIT

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
# Second argument, when given, is dumped indented under the FAIL line so a red
# run carries the script's own output instead of just the assertion name.
fail() {
  echo "  FAIL: $1"
  if [ -n "${2:-}" ]; then printf '%s\n' "$2" | sed 's/^/        /'; fi
  FAIL=$((FAIL + 1))
}

assert_eq() { if [ "$1" = "$2" ]; then pass "$3"; else fail "$3 (got '$1', want '$2')" "$OUT"; fi; }
assert_rc_nonzero() { if [ "$1" -ne 0 ]; then pass "$2"; else fail "$2 (rc=0)" "$OUT"; fi; }
assert_file() { if [ -f "$1" ]; then pass "$2"; else fail "$2 (missing: $1)" "$OUT"; fi; }
assert_absent() { if [ ! -e "$1" ]; then pass "$2"; else fail "$2 (still present: $1)" "$OUT"; fi; }
assert_contains() { case "$1" in *"$2"*) pass "$3";; *) fail "$3 (missing text: '$2')" "$1";; esac; }
assert_not_contains() { case "$1" in *"$2"*) fail "$3 (unexpected text: '$2')" "$1";; *) pass "$3";; esac; }

rec() { echo "$1/home/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"; }
state() { echo "$1/home/Library/Application Support/bridge-voicememo"; }
logtext() { cat "$1/home/Library/Logs/voicememo-bundler.log" 2>/dev/null; }

# mk_case [empty]: throwaway repo + HOME. Default: two pre-existing recordings,
# both listed in the baseline. "empty": no recordings and an empty baseline.
mk_case() {
  local r
  r="$(mktemp -d)"
  TMPS="$TMPS $r"
  mkdir -p "$r/skills/meeting-transcription/scripts" "$r/infra/transcriptions" "$(state "$r")" "$(rec "$r")"
  cp "$REAL_BUNDLER" "$r/skills/meeting-transcription/scripts/voicememo-bundler.sh"
  : > "$(state "$r")/baseline.txt"
  if [ "${1:-}" != empty ]; then
    for f in "20260101 120000-AAAA1111.m4a" "20260102 120000-BBBB2222.m4a"; do
      : > "$(rec "$r")/$f"
      printf '%s\n' "$f" >> "$(state "$r")/baseline.txt"
    done
  fi
  echo "$r"
}

run_bundler() {
  OUT="$(env -u TRANSCRIBE_WORKER HOME="$1/home" TRANSCRIBE_MODE=local \
    bash "$1/skills/meeting-transcription/scripts/voicememo-bundler.sh" 2>&1)"
  RC=$?
}

echo "1. healthy scan"
r=$(mk_case)
run_bundler "$r"
assert_eq "$RC" 0 "readable folder exits 0"
assert_file "$(state "$r")/last-scan-ok" "readable folder writes the heartbeat stamp"
assert_not_contains "$(logtext "$r")" "scan-blind" "readable folder logs no blind line"

echo "2. blind scan"
if [ "$(id -u)" -eq 0 ]; then
  echo "  SKIP: running as root, chmod 000 does not deny the listing"
else
  r=$(mk_case)
  chmod 000 "$(rec "$r")"
  run_bundler "$r"
  assert_rc_nonzero "$RC" "blind scan exits non-zero"
  assert_contains "$(logtext "$r")" "scan-blind" "blind scan logs a blind line"
  assert_absent "$(state "$r")/last-scan-ok" "blind scan writes no heartbeat stamp"
  assert_file "$(state "$r")/scan-blind-since" "blind scan records when the outage began"
  run_bundler "$r"
  assert_rc_nonzero "$RC" "a second blind run still exits non-zero"
  n=$(logtext "$r" | grep -c "scan-blind" || true)
  assert_eq "$n" 1 "a second blind run adds no second blind line"

  echo "3. recovery"
  chmod 755 "$(rec "$r")"
  run_bundler "$r"
  assert_eq "$RC" 0 "seeing run after an outage exits 0"
  assert_contains "$(logtext "$r")" "recovered" "seeing run logs the recovery"
  assert_absent "$(state "$r")/scan-blind-since" "recovery clears the outage marker"
  assert_file "$(state "$r")/last-scan-ok" "recovery writes the heartbeat stamp"
fi

echo "4. empty baseline"
r=$(mk_case empty)
run_bundler "$r"
assert_eq "$RC" 0 "empty folder with empty baseline exits 0"
assert_file "$(state "$r")/last-scan-ok" "empty folder with empty baseline writes the heartbeat stamp"
assert_not_contains "$(logtext "$r")" "scan-blind" "empty folder with empty baseline logs no blind line"

echo "5. symlinked deploy"
r=$(mk_case)
printf 'worker:\n  host: fake-worker\n' > "$r/infra/transcriptions/topology.yaml"
mkdir -p "$r/home/bin"
ln -s "$r/skills/meeting-transcription/scripts/voicememo-bundler.sh" "$r/home/bin/voicememo-bundler.sh"
OUT="$(env -u TRANSCRIBE_WORKER -u TRANSCRIBE_MODE HOME="$r/home" bash "$r/home/bin/voicememo-bundler.sh" 2>&1)"
assert_not_contains "$(logtext "$r")" "no transcription worker configured" "a symlinked script finds topology.yaml in its repo"

r=$(mk_case)
mkdir -p "$r/home/bin"
ln -s "$r/skills/meeting-transcription/scripts/voicememo-bundler.sh" "$r/home/bin/voicememo-bundler.sh"
OUT="$(env -u TRANSCRIBE_WORKER -u TRANSCRIBE_MODE HOME="$r/home" bash "$r/home/bin/voicememo-bundler.sh" 2>&1)"
assert_contains "$(logtext "$r")" "no transcription worker configured" "control: without topology.yaml the same run reports the missing worker"

# ---------------------------------------------------------------------------
echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
