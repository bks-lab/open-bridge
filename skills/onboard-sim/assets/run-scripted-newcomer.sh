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
printf '| 09:00 | Decision | acme | Pinned the ACME contract rate; migration kickoff. |\n' > work/log.md
printf 'status: doing\ncontext: acme\nnext: finish the ACME migration, then invoice.\n' > work/tasks/acme-migration/STATUS.md

git checkout -q -b user/sim
git add -A
git commit -q -m "personal setup: identity + ACME work"

echo "--- attempting push of user/sim to origin (the guard should block this) ---"
git push -u origin user/sim
echo "push exit: $?   (non-zero = guard blocked, as intended)"
exit 0
