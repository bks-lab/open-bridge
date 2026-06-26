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
ABS_HOOK="$(pwd)/$HOOK"   # absolute: the fixture runs cd into a temp repo
PASS=0
FAIL=0

# Fixtures + a gh stub let the three-state classifier be tested deterministically,
# offline, without touching the repo's real .bridge-origin (is_public:true).
TMPS=""
cleanup() { for d in $TMPS; do rm -rf "$d"; done; }
trap cleanup EXIT

# make_fixture → echoes a fresh temp GIT repo path; `$ROOT` for the hook resolves
# there (via git rev-parse), so a bridge-config.yaml / .bridge-origin dropped in it
# is what the classifier reads — never the repo's real markers.
make_fixture() {
  local d; d=$(mktemp -d); TMPS="$TMPS $d"; git -C "$d" init -q; echo "$d"
}

# gh_stub_path → a dir holding a `gh` that always fails (simulates offline / gh
# unavailable). Prepend to PATH so `command -v gh` finds it but every call errors,
# leaving the target classified `unknown`.
GH_STUB=""
gh_stub_path() {
  [ -n "$GH_STUB" ] && { echo "$GH_STUB"; return; }
  GH_STUB=$(mktemp -d); TMPS="$TMPS $GH_STUB"
  printf '#!/bin/sh\nexit 1\n' > "$GH_STUB/gh"; chmod +x "$GH_STUB/gh"
  echo "$GH_STUB"
}

# run_hook_at <fixture_dir> <remote_url> <local_ref> <remote_ref> [env]
#   runs the hook with cwd = the fixture repo (so its markers are read), feeding the
#   stdin push contract. remote_sha = zero (new branch) so commit inspection no-ops.
run_hook_at() {
  local dir="$1" url="$2" lref="$3" rref="$4" envp="${5:-}"
  local zero="0000000000000000000000000000000000000000"
  local local_sha="1111111111111111111111111111111111111111"
  ( cd "$dir" && printf '%s %s %s %s\n' "$lref" "$local_sha" "$rref" "$zero" \
      | env ${envp} bash "$ABS_HOOK" origin "$url" >/dev/null 2>&1 )
  echo $?
}
assert_block_at() { # <desc> <dir> <url> <local_ref> <remote_ref> [env]
  local desc="$1" rc; rc=$(run_hook_at "$2" "$3" "$4" "$5" "${6:-}")
  if [ "$rc" -ne 0 ]; then echo "  PASS (blocked) — $desc"; PASS=$((PASS+1));
  else echo "  FAIL (should block, got exit 0) — $desc"; FAIL=$((FAIL+1)); fi
}
assert_allow_at() { # <desc> <dir> <url> <local_ref> <remote_ref> [env]
  local desc="$1" rc; rc=$(run_hook_at "$2" "$3" "$4" "$5" "${6:-}")
  if [ "$rc" -eq 0 ]; then echo "  PASS (allowed) — $desc"; PASS=$((PASS+1));
  else echo "  FAIL (should allow, got exit $rc) — $desc"; FAIL=$((FAIL+1)); fi
}

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

PRIV_SLUG="obfixture-nonexistent-owner/my-private-bridge"   # slug_of "$PRIV"

# ALLOW: user/* to a CONFIRMED-private own origin — no false-block. Under the
# three-state guard, "your own origin" must be PROVEN private deterministically;
# gh-fails-⇒-allow is gone. Two deterministic, offline private signals:
#   (a) bridge-config.yaml push_guard.private_remotes
fix_cfg=$(make_fixture)
printf 'push_guard:\n  private_remotes: [%s]\n' "$PRIV_SLUG" > "$fix_cfg/bridge-config.yaml"
assert_allow_at "user/* → private own origin (private_remotes)" \
  "$fix_cfg" "$PRIV" "refs/heads/user/alice" "refs/heads/user/alice"
#   (b) .bridge-origin marker: is_public:false with a MATCHING repo: slug
fix_org=$(make_fixture)
printf 'repo: %s\nis_public: false\n' "$PRIV_SLUG" > "$fix_org/.bridge-origin"
assert_allow_at "user/* → private own origin (.bridge-origin is_public:false)" \
  "$fix_org" "$PRIV" "refs/heads/user/alice" "refs/heads/user/alice"

# BLOCK (2026-06-26 P2-a leak): user/* to an UNKNOWN, not-confirmed-private remote
# with gh forced unavailable. The old fail-OPEN allowed this (is_public stayed `no`
# ⇒ exit 0); the new fail-CLOSED-for-sensitive default blocks it. A stale
# .bridge-origin from a previous origin (repo != target) must NOT vouch for it.
fix_leak=$(make_fixture)
printf 'repo: %s\nis_public: false\n' "some-old-owner/previous-bridge" > "$fix_leak/.bridge-origin"
assert_block_at "user/* → UNKNOWN remote, gh unavailable (stale .bridge-origin) → BLOCK" \
  "$fix_leak" "$PRIV" "refs/heads/user/erin" "refs/heads/user/erin" "PATH=$(gh_stub_path):$PATH"

# NO FALSE-BLOCK: a CORE-clean push (no user/* dest, no USER content) to that same
# UNKNOWN remote must STILL be ALLOWED — /promote forks + feature/* to arbitrary
# remotes keep working. Fail-closed applies ONLY to sensitive payloads.
fix_core=$(make_fixture)
assert_allow_at "CORE-clean feature/* → UNKNOWN remote, gh unavailable → ALLOW" \
  "$fix_core" "$PRIV" "refs/heads/feature/core-fix" "refs/heads/feature/core-fix" "PATH=$(gh_stub_path):$PATH"

# BYPASS: deliberate, visible, per-push override
assert_allow "BRIDGE_PUSH_GUARD=off bypass on the blocked case" "$PUB_HTTPS" "refs/heads/user/alice" "BRIDGE_PUSH_GUARD=off"

echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
