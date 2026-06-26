#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Fixture test for the public-origin push guard (scripts/hooks/pre-push).
#
# The guard's job: a Bridge clone of a PUBLIC upstream must never push a
# user/* branch (or USER-scoped content) to that public remote — the
# 2026-06-24 leak vector. It must NOT over-block: feature/*, ci/*, promote-*
# and any push to a private/own remote pass through untouched, and an explicit
# BRIDGE_PUSH_GUARD=off bypass stays available for the deliberate case.
#
# Run: bash scripts/tests/test-push-guard.sh   (from repo root; exits non-zero on failure)
# Offline + deterministic: public detection comes from .bridge-origin + the
# built-in fallback list, never the network. gh is escalation-only for unknowns.
set -u
cd "$(dirname "$0")/../.."

HOOK="scripts/hooks/pre-push"
PASS=0
FAIL=0

# run_hook <remote_url> <ref-line> [env-prefix]
#   feeds git's pre-push stdin contract: "<local_ref> <local_sha> <remote_ref> <remote_sha>"
#   git calls the hook with argv: $1=remote-name $2=remote-url
run_hook() {
  local url="$1" refline="$2" envp="${3:-}"
  local sha="0000000000000000000000000000000000000000"
  # local_sha is a fake non-zero sha so the hook treats it as a real push
  local local_sha="1111111111111111111111111111111111111111"
  printf '%s %s %s %s\n' "$refline" "$local_sha" "$refline" "$sha" \
    | env ${envp} bash "$HOOK" origin "$url" >/dev/null 2>&1
  echo $?   # exit code
}

assert_block() { # <desc> <url> <ref> [env]
  local desc="$1" rc; rc=$(run_hook "$2" "$3" "${4:-}")
  if [ "$rc" -ne 0 ]; then echo "  PASS (blocked) — $desc"; PASS=$((PASS+1));
  else echo "  FAIL (should block, got exit 0) — $desc"; FAIL=$((FAIL+1)); fi
}
assert_allow() { # <desc> <url> <ref> [env]
  local desc="$1" rc; rc=$(run_hook "$2" "$3" "${4:-}")
  if [ "$rc" -eq 0 ]; then echo "  PASS (allowed) — $desc"; PASS=$((PASS+1));
  else echo "  FAIL (should allow, got exit $rc) — $desc"; FAIL=$((FAIL+1)); fi
}

# run_hook2 <remote_url> <local_ref> <remote_ref> [env]
#   like run_hook, but feeds DIFFERENT local and remote refs — the case `git push
#   origin HEAD` / `git push origin <sha>:refs/heads/user/x` / a detached-HEAD push
#   produce (local_ref=HEAD or a raw sha, remote_ref=the real destination). The guard
#   must decide on the DESTINATION (remote_ref), so these must still block.
run_hook2() {
  local url="$1" lref="$2" rref="$3" envp="${4:-}"
  local zero="0000000000000000000000000000000000000000"
  local local_sha="1111111111111111111111111111111111111111"
  printf '%s %s %s %s\n' "$lref" "$local_sha" "$rref" "$zero" \
    | env ${envp} bash "$HOOK" origin "$url" >/dev/null 2>&1
  echo $?
}
assert_block2() { # <desc> <url> <local_ref> <remote_ref> [env]
  local desc="$1" rc; rc=$(run_hook2 "$2" "$3" "$4" "${5:-}")
  if [ "$rc" -ne 0 ]; then echo "  PASS (blocked) — $desc"; PASS=$((PASS+1));
  else echo "  FAIL (should block, got exit 0) — $desc"; FAIL=$((FAIL+1)); fi
}

echo "== push-guard fixture =="

# Precondition: the hook must exist and be executable (RED until implemented).
if [ ! -x "$HOOK" ]; then
  echo "  FAIL — $HOOK does not exist or is not executable"
  echo ""
  echo "RESULT: 0 passed, 1 failed (hook missing)"
  exit 1
fi

PUB_HTTPS="https://github.com/bks-lab/open-bridge.git"
PUB_SSH="git@github.com:bks-lab/open-bridge.git"
PRIV="git@github.com:obfixture-nonexistent-owner/my-private-bridge.git"

# BLOCK: user/* to the public upstream (https + ssh forms — slug normalization)
assert_block "user/* → public upstream (https)" "$PUB_HTTPS" "refs/heads/user/alice"
assert_block "user/* → public upstream (ssh)"   "$PUB_SSH"   "refs/heads/user/alice"

# BLOCK (regression — 2026-06-26 P0): the leak forms where local_ref != destination.
# `git push origin HEAD` feeds local_ref=HEAD; a sha push feeds a raw sha; both land
# the private branch as refs/heads/user/*. Keying on local_ref let these through.
assert_block2 "git push origin HEAD (local_ref=HEAD) → user/* dest" "$PUB_HTTPS" "HEAD" "refs/heads/user/bob"
assert_block2 "sha push (<sha>:refs/heads/user/x) → user/* dest"    "$PUB_HTTPS" "1234567890123456789012345678901234567890" "refs/heads/user/carol"
assert_block2 "detached-HEAD push → user/* dest"                    "$PUB_SSH"   "HEAD" "refs/heads/user/dave"

# ALLOW: CORE-shaped refs to the public upstream are fine (that is what open-bridge is for)
assert_allow "feature/* → public upstream" "$PUB_HTTPS" "refs/heads/feature/onboard-mirror-guard"
assert_allow "ci/* → public upstream"      "$PUB_HTTPS" "refs/heads/ci/nightly"
assert_allow "promote-* → public upstream" "$PUB_HTTPS" "refs/heads/promote-open-bridge-2026-06-26"

# ALLOW: user/* to a private/own remote (your own origin) — no false-block
assert_allow "user/* → private own origin" "$PRIV" "refs/heads/user/alice"

# BYPASS: deliberate, visible, per-push override
assert_allow "BRIDGE_PUSH_GUARD=off bypass on the blocked case" "$PUB_HTTPS" "refs/heads/user/alice" "BRIDGE_PUSH_GUARD=off"

echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
