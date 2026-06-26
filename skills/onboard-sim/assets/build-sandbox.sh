#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# onboard-sim — build a leak-SAFE sandbox reproducing a fresh PUBLIC-origin clone
# of open-bridge with the push guard armed.
#
# The sandbox's "public upstream" is a LOCAL bare repo. The newcomer clone's
# `origin` is set to the public URL (so the guard's slug detection sees the real
# public slug) but ALL transport is redirected to the local bare repo via
# insteadOf — so even if the guard fails, a simulated leaky push lands in the
# local bare repo, never on the real public internet. Testing for a leak can
# never cause one.
#
# Prints the sandbox dir on stdout.
set -euo pipefail

CORE_SRC="${1:?usage: build-sandbox.sh <open-bridge-checkout> [sandbox-dir]}"
SANDBOX="${2:-$(mktemp -d "${TMPDIR:-/tmp}/obsim.XXXXXX")}"
rm -rf "$SANDBOX"; mkdir -p "$SANDBOX"
PUBLIC_BARE="$SANDBOX/public-open-bridge.git"
NEWCOMER="$SANDBOX/newcomer"
PUBLIC_URL="https://github.com/bks-lab/open-bridge.git"

slug_of() {
  printf '%s' "$1" \
    | sed -E 's#^git@[^:]+:##; s#^ssh://git@[^/]+/##; s#^https?://[^/]+/##; s#/$##; s#\.git$##' \
    | tr '[:upper:]' '[:lower:]'
}

# 1) fake "public" upstream = a local bare repo
git init -q --bare "$PUBLIC_BARE"

# 2) newcomer working copy = the live CORE (tracked + new-untracked, minus ignored)
mkdir -p "$NEWCOMER"
( cd "$CORE_SRC" && git ls-files -co --exclude-standard ) > "$SANDBOX/.filelist"
rsync -a --files-from="$SANDBOX/.filelist" "$CORE_SRC"/ "$NEWCOMER"/
cd "$NEWCOMER"
git init -q -b main
git add -A
git -c user.email=sim@example.com -c user.name="OB Sim" commit -q -m "open-bridge CORE baseline (sim)"

# 3) origin LOOKS like the public repo; transport redirected to the local bare (leak-safe)
git remote add origin "$PUBLIC_URL"
git config "url.${PUBLIC_BARE}.insteadOf" "$PUBLIC_URL"
git config "url.${PUBLIC_BARE}.pushInsteadOf" "$PUBLIC_URL"

# 4) arm the guard exactly as bin/setup would
git config core.hooksPath scripts/hooks
[ -f scripts/hooks/pre-push ] && chmod +x scripts/hooks/pre-push

# 5) belt-and-suspenders: the guard must recognize the target as public whether git
#    hands the hook the spoof URL or the rewritten bare path
cat > bridge-config.yaml <<YAML
# sandbox-only (gitignored in real clones)
push_guard:
  public_upstreams: ["bks-lab/open-bridge", "$(slug_of "$PUBLIC_BARE")"]
  private_remotes: []
YAML

echo "$SANDBOX"
