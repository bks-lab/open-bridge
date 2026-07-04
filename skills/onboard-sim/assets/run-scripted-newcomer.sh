#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# onboard-sim — model-free naive newcomer (for CI / deterministic runs).
# Does the canonical leaky thing: write USER data, commit to user/*, push.
# The realistic variant drives the same flow with a cheap LLM (see SKILL.md);
# this scripted variant needs no model, so it gates in CI for free.
set -uo pipefail
NEWCOMER="${1:?usage: run-scripted-newcomer.sh <sandbox>/newcomer}"
cd "$NEWCOMER"

git config user.name "Sim Newcomer"
git config user.email "sim@example.com"

mkdir -p identity/agent work/tasks/acme-migration
cat > identity/agent/IDENTITY.md <<'M'
# IDENTITY
Name: Sim Newcomer — freelance IT consultant.
Client in flight: ACME Financial Services (day rate documented internally).
M
cat > identity/agent/SOUL.md <<'M'
# SOUL
Pragmatic, terse. Works for ACME this quarter.
M
printf '| 2026-06-24 09:00 | Decision | acme | Pinned the ACME contract rate; migration kickoff. |\n' > work/log.md
printf 'status: doing\ncontext: acme\nnext: finish the ACME migration, then invoice.\n' > work/tasks/acme-migration/STATUS.md

git checkout -q -b user/sim
git add -A
git commit -q -m "personal setup: identity + ACME work"

echo "--- attempt 1: push user/sim by name to origin (the guard should block this) ---"
git push -u origin user/sim
echo "push exit: $?   (non-zero = guard blocked, as intended)"

# Regression (2026-06-26 P0): the same private branch via `git push origin HEAD` —
# the muscle-memory form and what the auto-end-of-work autopilot uses. git feeds the
# hook local_ref=HEAD, which once slipped past the user/* check. Must also be blocked.
echo "--- attempt 2: same private branch via 'git push origin HEAD' (must also block) ---"
git push origin HEAD
echo "push exit: $?   (non-zero = guard blocked, as intended)"

# Positive control: a CORE-only sanctioned branch MUST be able to reach the upstream.
# If it can't, the sandbox transport is dead and the no-leak assertion is vacuous —
# assert-no-leak.sh fails loudly when this probe is missing from the bare.
echo "--- positive control: push CORE-only ci/probe (the guard must ALLOW this) ---"
git checkout -q main
git checkout -q -b ci/probe
: > .onboard-sim-probe
git add .onboard-sim-probe
git commit -q -m "ci: onboard-sim transport probe (CORE-only, no USER content)"
git push -u origin ci/probe
echo "probe push exit: $?   (zero = transport works + CORE push allowed, as intended)"
exit 0
