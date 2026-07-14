#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test suite for the local/remote TRANSPORT logic in the meeting-transcription
# skill's shell scripts (scripts/debrief_sync.sh + scripts/add_context.sh),
# introduced when the pipeline gained a topology `mode: local|remote`.
#
# What it locks down:
#   1. mode resolution — TRANSCRIBE_MODE wins; an invalid mode hard-fails with a
#      clear message; best-effort inference (worker host ⇒ remote, else local).
#   2. local transport round-trip for debrief_sync.sh (push / pull / voiceprints
#      pull) using plain filesystem cp/mv — no SSH.
#   3. add_context.sh local branch — bootstraps local dirs + deploys the runtime
#      context yaml WITHOUT requiring a worker host (the old script hard-required it).
#   4. remote-arm regression guard — the frozen set of ssh/rsync command lines in
#      the CURRENT debrief_sync.sh, so the remote path can't silently drift.
#
# HERMETIC + OFFLINE: every behavioural test runs against a throwaway fake bridge
# repo (the real scripts are copied in fresh at runtime, so there is no drift and
# the real repo / real ~/Transcripts / real config are never touched). Mode is
# forced with TRANSCRIBE_MODE / env overrides; the one remote-inference case uses
# an `ssh` stub that always fails, so no network and no real worker are needed.
#
# Run:  bash skills/meeting-transcription/tests/test-transport-modes.sh
#       (exits non-zero on any failure).
#
# NOTE: `launchctl kickstart` prints a non-fatal "WARN could not kickstart worker"
# in these tests (no such launchd job in the sandbox / not macOS in CI) — the push
# still exits 0. That WARN is expected.

set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$SKILL_DIR/scripts"
REAL_DEBRIEF="$SCRIPTS/debrief_sync.sh"
REAL_ADDCTX="$SCRIPTS/add_context.sh"

PASS=0
FAIL=0
TMPS=""
cleanup() { for d in $TMPS; do rm -rf "$d"; done; }
trap cleanup EXIT

pass() { echo "  PASS — $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL — $1"; FAIL=$((FAIL + 1)); }

# assert_file <path> <desc>
assert_file() { if [ -f "$1" ]; then pass "$2"; else fail "$2 (missing: $1)"; fi; }
# assert_absent <path> <desc>
assert_absent() { if [ ! -e "$1" ]; then pass "$2"; else fail "$2 (still present: $1)"; fi; }
# assert_contains <haystack> <needle> <desc>
assert_contains() { case "$1" in *"$2"*) pass "$3";; *) fail "$3 (missing text: '$2')";; esac; }
# assert_not_contains <haystack> <needle> <desc>
assert_not_contains() { case "$1" in *"$2"*) fail "$3 (unexpected text: '$2')";; *) pass "$3";; esac; }
# assert_rc_zero <rc> <desc>
assert_rc_zero() { if [ "$1" -eq 0 ]; then pass "$2"; else fail "$2 (rc=$1)"; fi; }
# assert_rc_nonzero <rc> <desc>
assert_rc_nonzero() { if [ "$1" -ne 0 ]; then pass "$2"; else fail "$2 (rc=0, expected failure)"; fi; }

# run <cmd...>  →  sets OUT (stdout+stderr) and RC
run() { OUT="$("$@" 2>&1)"; RC=$?; }

# mk_repo — a throwaway fake bridge repo with the CURRENT scripts copied in.
# Echoes its path. Caller writes bridge-config.yaml / topology.yaml / context
# fixtures as each test needs. REPO_ROOT inside the copied script resolves to
# this dir (scripts/ → skill → skills/ → repo), so all config reads are hermetic.
mk_repo() {
  local d; d=$(mktemp -d); TMPS="$TMPS $d"
  mkdir -p "$d/skills/meeting-transcription/scripts" \
           "$d/infra/transcriptions" \
           "$d/workflow/contexts" \
           "$d/work/imports" \
           "$d/identity/voiceprints" \
           "$d/home"
  cp "$SCRIPTS/debrief_sync.sh" "$SCRIPTS/add_context.sh" \
     "$SCRIPTS/extract_runtime_contexts.py" \
     "$d/skills/meeting-transcription/scripts/"
  chmod +x "$d/skills/meeting-transcription/scripts/debrief_sync.sh" \
           "$d/skills/meeting-transcription/scripts/add_context.sh"
  echo "$d"
}

# ssh stub dir — an `ssh` that always fails (offline remote probe). Prepend to PATH.
mk_ssh_stub() {
  local s; s=$(mktemp -d); TMPS="$TMPS $s"
  printf '#!/bin/sh\nexit 1\n' > "$s/ssh"; chmod +x "$s/ssh"
  echo "$s"
}

D_SYNC() { echo "$1/skills/meeting-transcription/scripts/debrief_sync.sh"; }
D_ADDCTX() { echo "$1/skills/meeting-transcription/scripts/add_context.sh"; }

echo "== meeting-transcription transport modes =="

# Precondition: the scripts under test must exist.
[ -f "$REAL_DEBRIEF" ] || { echo "  FAIL — $REAL_DEBRIEF missing"; echo "RESULT: 0 passed, 1 failed"; exit 1; }
[ -f "$REAL_ADDCTX" ]  || { echo "  FAIL — $REAL_ADDCTX missing";  echo "RESULT: 0 passed, 1 failed"; exit 1; }

# ---------------------------------------------------------------------------
echo ""
echo "-- 1. mode resolution --"

# 1a. TRANSCRIBE_MODE=local resolves local (no SSH probe, clean exit).
r=$(mk_repo)
run env HOME="$r/home" TRANSCRIBE_MODE=local TRANSCRIBE_CONTEXTS=demo \
    BRIDGE_IMPORTS="$r/work/imports" BRIDGE_VOICEPRINTS="$r/identity/voiceprints" \
    bash "$(D_SYNC "$r")" pull
assert_rc_zero "$RC" "TRANSCRIBE_MODE=local → resolves local (pull exits 0)"
assert_contains "$OUT" "pull done" "local pull reaches the local branch"
assert_not_contains "$OUT" "unreachable" "local mode skips the SSH reachability probe"

# 1b. An invalid TRANSCRIBE_MODE hard-fails with a clear message.
r=$(mk_repo)
run env HOME="$r/home" TRANSCRIBE_MODE=locl TRANSCRIBE_CONTEXTS=demo \
    BRIDGE_IMPORTS="$r/work/imports" bash "$(D_SYNC "$r")" pull
assert_rc_nonzero "$RC" "invalid TRANSCRIBE_MODE=locl exits non-zero"
assert_contains "$OUT" "invalid transcription mode" "invalid mode prints a clear message"

# 1c. Inference (best-effort): a worker host present (legacy bridge-config location,
# no topology mode, no TRANSCRIBE_MODE) ⇒ remote. Proven by the SSH probe firing
# (an ssh stub makes it fail deterministically → the remote-only 'unreachable' line).
r=$(mk_repo)
cat > "$r/bridge-config.yaml" <<'YAML'
integrations:
  transcription:
    contexts:
      demo: {}
    worker:
      host: fakehost-unreachable
YAML
stub=$(mk_ssh_stub)
run env PATH="$stub:$PATH" HOME="$r/home" TRANSCRIBE_CONTEXTS=demo \
    BRIDGE_IMPORTS="$r/work/imports" bash "$(D_SYNC "$r")" pull
assert_rc_nonzero "$RC" "inference: worker host present ⇒ remote (probe fails, exits non-zero)"
assert_contains "$OUT" "unreachable" "inferred remote reaches the SSH reachability probe"

# 1d. Inference: no worker host anywhere ⇒ local (clean exit, no SSH).
r=$(mk_repo)
cat > "$r/bridge-config.yaml" <<'YAML'
integrations:
  transcription:
    contexts:
      demo: {}
YAML
run env HOME="$r/home" TRANSCRIBE_CONTEXTS=demo \
    BRIDGE_IMPORTS="$r/work/imports" bash "$(D_SYNC "$r")" pull
assert_rc_zero "$RC" "inference: no worker host ⇒ local (pull exits 0)"
assert_contains "$OUT" "pull done" "inferred local reaches the local branch"

# ---------------------------------------------------------------------------
echo ""
echo "-- 2. local transport round-trip (debrief_sync.sh) --"

r=$(mk_repo)
H="$r/home"
CTX=demo
IMPORTS="$r/work/imports"
VP="$r/identity/voiceprints"
# Seed the worker's conventional LOCAL dirs (mode: local defaults to $HOME/...).
mkdir -p "$H/transcribe-inbox/$CTX"
mkdir -p "$H/Transcripts/$CTX"
printf '# transcript\nnaked transcript body\n' > "$H/Transcripts/$CTX/meeting-notes.md"
mkdir -p "$H/transcribe-pipeline/speaker-library/$CTX"
printf 'NPYDATA' > "$H/transcribe-pipeline/speaker-library/$CTX/axel.npy"
printf 'fake-audio-bytes' > "$r/sample.mp3"

# push <audio> <ctx>
run env HOME="$H" TRANSCRIBE_MODE=local TRANSCRIBE_CONTEXTS="$CTX" \
    BRIDGE_IMPORTS="$IMPORTS" BRIDGE_VOICEPRINTS="$VP" \
    bash "$(D_SYNC "$r")" push "$r/sample.mp3" "$CTX"
assert_rc_zero "$RC" "push exits 0 (local)"
mp3=$(find "$H/transcribe-inbox/$CTX" -mindepth 2 -name meeting.mp3 2>/dev/null | head -1)
assert_file "$mp3" "push drops <ts>/meeting.mp3 into the local inbox"
tsdir=$(dirname "$mp3" 2>/dev/null || echo "$H/transcribe-inbox/$CTX/_none")
assert_file "$tsdir/manifest.yaml" "push writes <ts>/manifest.yaml"
assert_file "$tsdir/.READY" "push touches <ts>/.READY"
manifest=$(cat "$tsdir/manifest.yaml" 2>/dev/null || echo "")
assert_contains "$manifest" "context: $CTX" "manifest records the context"
assert_contains "$manifest" "tracks: single" "manifest forces tracks: single"

# pull
run env HOME="$H" TRANSCRIBE_MODE=local TRANSCRIBE_CONTEXTS="$CTX" \
    BRIDGE_IMPORTS="$IMPORTS" BRIDGE_VOICEPRINTS="$VP" \
    bash "$(D_SYNC "$r")" pull
assert_rc_zero "$RC" "pull exits 0 (local)"
assert_file "$IMPORTS/${CTX}-meeting-notes.md" "pull copies transcript → imports with ctx prefix"
assert_file "$H/Transcripts/$CTX/_debriefed/meeting-notes.md" "pull moves source into _debriefed/"
assert_absent "$H/Transcripts/$CTX/meeting-notes.md" "pull removes the source from the transcripts dir (moved once)"

# voiceprints pull
run env HOME="$H" TRANSCRIBE_MODE=local TRANSCRIBE_CONTEXTS="$CTX" \
    BRIDGE_IMPORTS="$IMPORTS" BRIDGE_VOICEPRINTS="$VP" \
    bash "$(D_SYNC "$r")" voiceprints pull
assert_rc_zero "$RC" "voiceprints pull exits 0 (local)"
assert_file "$VP/$CTX/axel.npy" "voiceprints pull copies .npy into the bridge voiceprint dir"

# ---------------------------------------------------------------------------
echo ""
echo "-- 3. add_context.sh local branch --"

r=$(mk_repo)
H="$r/home"
NAME=demo-test
cat > "$r/workflow/contexts/$NAME.yaml" <<YAML
schema_version: 1
scope: user
id: $NAME
description: "temp transcription context (test fixture)"
integrations:
  transcription:
    language: de
    library: $NAME
    output: $NAME
    notify: false
YAML

# local mode, NO TRANSCRIBE_WORKER → must succeed and bootstrap local dirs + yaml.
run env HOME="$H" TRANSCRIBE_MODE=local bash "$(D_ADDCTX "$r")" "$NAME"
assert_rc_zero "$RC" "add_context local exits 0 WITHOUT a worker host"
assert_not_contains "$OUT" "no worker host" "add_context local never demands a worker host"
if [ -d "$H/transcribe-inbox/$NAME" ]; then pass "add_context creates the local inbox dir"; else fail "add_context creates the local inbox dir (missing)"; fi
if [ -d "$H/transcribe-pipeline/speaker-library/$NAME" ]; then pass "add_context creates the local speaker-library dir"; else fail "add_context creates the local speaker-library dir (missing)"; fi
assert_file "$H/transcribe-pipeline/contexts/$NAME.yaml" "add_context deploys the runtime context yaml locally"
runtime=$(cat "$H/transcribe-pipeline/contexts/$NAME.yaml" 2>/dev/null || echo "")
assert_contains "$runtime" "language" "deployed runtime yaml carries the flattened fields"

# Contrast: remote mode with NO worker host STILL hard-fails (guards the split).
r2=$(mk_repo)
cat > "$r2/workflow/contexts/$NAME.yaml" <<YAML
schema_version: 1
scope: user
id: $NAME
description: "temp transcription context (test fixture)"
integrations:
  transcription:
    language: de
    library: $NAME
    output: $NAME
    notify: false
YAML
run env HOME="$r2/home" TRANSCRIBE_MODE=remote bash "$(D_ADDCTX "$r2")" "$NAME"
assert_rc_nonzero "$RC" "add_context remote WITHOUT a worker host still hard-fails"
assert_contains "$OUT" "no worker host" "remote-without-worker prints a clear message"

# ---------------------------------------------------------------------------
echo ""
echo "-- 4. remote-arm regression snapshot (debrief_sync.sh) --"

# The frozen set of ssh/rsync command lines in the current debrief_sync.sh.
# If the remote transport is edited, this diff fails LOUD — update the snapshot
# deliberately (and re-review the remote path) rather than let it drift silently.
expected_remote_snapshot() {
  cat <<'SNAP'
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$WORKER" 'true' 2>/dev/null; then
ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/Transcripts/$ctx/_debriefed" 2>/dev/null || true
mapfile -t files < <(ssh -o BatchMode=yes "$WORKER" "find ~/Transcripts/$ctx -maxdepth 1 -name '*.md' 2>/dev/null" || true)
if rsync -av "$WORKER:$f" "$IMPORTS/${ctx}-${bn}" >/dev/null 2>&1; then
ssh -o BatchMode=yes "$WORKER" "mv ~/Transcripts/$ctx/$bn ~/Transcripts/$ctx/_debriefed/" 2>/dev/null || true
if ! ssh -o BatchMode=yes "$WORKER" "test -d ~/transcribe-inbox/$ctx" 2>/dev/null; then
ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-inbox/$ctx/$ts"
rsync -av "$audio" "$WORKER:~/transcribe-inbox/$ctx/$ts/meeting.mp3" >/dev/null
ssh -o BatchMode=yes "$WORKER" "printf 'recorded_at: %s\nduration_s: 0\ncontext: %s\ntracks: single\nsource: debrief-handoff\n' \
ssh -o BatchMode=yes "$WORKER" "launchctl kickstart gui/\$(id -u)/$KICK_LABEL" >/dev/null 2>&1 \
if ! ssh -o BatchMode=yes "$WORKER" "test -d ~/transcribe-pipeline/speaker-library/$ctx" 2>/dev/null; then
n=$(rsync -av --include='*.npy' --exclude='*' \
n=$(rsync -av --include='*.npy' --exclude='*' \
ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-pipeline/speaker-library/$ctx" 2>/dev/null || true
n=$(rsync -av --include='*.npy' --exclude='*' \
n=$(rsync -av --include='*.npy' --exclude='*' \
SNAP
}
actual_remote_snapshot() {
  grep -E 'ssh -o|rsync -av' "$REAL_DEBRIEF" | sed 's/^[[:space:]]*//'
}
if diff <(expected_remote_snapshot) <(actual_remote_snapshot) > /tmp/.tx_snap_diff.$$ 2>&1; then
  pass "remote ssh/rsync command set matches the frozen snapshot"
else
  fail "remote ssh/rsync command set DRIFTED from the frozen snapshot"
  echo "    --- diff (expected vs actual) ---"
  sed 's/^/    /' /tmp/.tx_snap_diff.$$
fi
rm -f /tmp/.tx_snap_diff.$$

# ---------------------------------------------------------------------------
echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
