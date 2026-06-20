#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test harness for scripts/tracker-sync.py.
#
# Runs the deterministic `diff` and `plan` subcommands against an offline
# fixture root (a miniature Bridge tree with a snapshot + STATUS.md files)
# and asserts the delta classification. No `gh` / network needed — the
# `pull` subcommand is integration-only and not covered here.
#
# Usage: bash scripts/tests/test-tracker-sync.sh
# Exit:  0 — all tests pass, 1 — at least one failure.

set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$ROOT/scripts/tracker-sync.py"
FIXROOT="$ROOT/scripts/tests/fixtures/tracker-sync"

PASS=0
FAIL=0

# assert_exit <name> <expected_exit> <cmd...>
# captures output into $OUT for follow-up substring assertions.
OUT=""
assert_exit() {
  local name="$1" expected="$2"; shift 2
  OUT=$("$@" 2>&1)
  local actual=$?
  if [ "$actual" -ne "$expected" ]; then
    echo "FAIL  $name"
    echo "  cmd:           $*"
    echo "  expected exit: $expected"
    echo "  actual exit:   $actual"
    echo "$OUT" | sed 's/^/    /'
    FAIL=$((FAIL + 1)); return 1
  fi
  echo "PASS  $name (exit $actual)"
  PASS=$((PASS + 1)); return 0
}

assert_contains() {
  local name="$1" needle="$2"
  if echo "$OUT" | grep -qF "$needle"; then
    echo "PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $name — output missing: $needle"
    echo "$OUT" | sed 's/^/    /'
    FAIL=$((FAIL + 1))
  fi
}

assert_absent() {
  local name="$1" needle="$2"
  if echo "$OUT" | grep -qF "$needle"; then
    echo "FAIL  $name — output unexpectedly contains: $needle"
    echo "$OUT" | sed 's/^/    /'
    FAIL=$((FAIL + 1))
  else
    echo "PASS  $name"
    PASS=$((PASS + 1))
  fi
}

echo "── selftest (pure-function: state normalization + classify) ─"
assert_exit "selftest passes" 0 python3 "$SCRIPT" selftest

echo "── diff (table) ────────────────────────────────────────────"
assert_exit "diff runs" 0 python3 "$SCRIPT" diff --root "$FIXROOT"
assert_contains "in_sync #10"        "in_sync | #10"
assert_contains "remote_ahead #11"   "remote_ahead | #11"
assert_contains "local_ahead #12"    "local_ahead | #12"
assert_contains "state_mismatch #13" "state_mismatch | #13"
assert_contains "orphan_local #99"   "orphan_local | #99"
assert_contains "orphan_remote #14"  "orphan_remote | #14"
assert_absent   "bridge_only hidden" "task-bridgeonly"
# Cross-repo collision regression: #10 exists in demo-org/demo (in_progress)
# AND other-org/other (done). They must NOT cross-match on bare number —
# task-insync(doing) stays in_sync with the in_progress one, task-otherrepo
# (done) stays in_sync with the done one. A number-only index would have
# flipped task-insync to remote_ahead.
assert_contains "collision repo shown"   "other-org/other"
assert_absent   "no cross-repo mismatch" "remote_ahead | #10"
# Issue lifecycle vs board Status field: a CLOSED issue whose card never moved
# off New must surface as board_stale (unlinked) or remote_ahead (linked) —
# NOT as an open orphan_remote.
assert_contains "board_stale #15"        "board_stale | #15"
assert_absent   "closed not orphaned"    "orphan_remote | #15"
assert_contains "closed-linked ahead #16" "remote_ahead | #16"

echo "── diff --exit-code (drift present → 2) ────────────────────"
assert_exit "exit-code signals drift" 2 python3 "$SCRIPT" diff --root "$FIXROOT" --exit-code

echo "── plan (push local→remote for local_ahead) ───────────────"
assert_exit "plan runs" 0 python3 "$SCRIPT" plan --root "$FIXROOT"
assert_contains "plan targets #12"  "#12"
assert_contains "plan maps to Done" "Done"
assert_absent   "plan skips in_sync #10" "#10"

echo
echo "Results: $PASS passed, $FAIL failed."
[ "$FAIL" -eq 0 ]
