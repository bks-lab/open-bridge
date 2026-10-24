#!/bin/sh
# SPDX-License-Identifier: MIT
# Contract for the pre-commit ALWAYS-ON gate (f).
#
# The gate is a shell `&&`/`||` chain with three branches per guard: guard
# present and passing (silent), present and failing (warn), absent (silent, and
# NOT a warning about a file this fork never took). A chain like that is exactly
# what reads correct and behaves otherwise, so each branch is exercised rather
# than argued.
set -e
HOOK=$(cd "$(dirname "$0")/../.." && pwd)/scripts/hooks/pre-commit
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }

setup() {
  rm -rf "$TMP/r"; mkdir -p "$TMP/r/scripts"; cd "$TMP/r"
  git init -q . && git checkout -q -b user/test
  git config user.email t@e.st && git config user.name t
  mkdir -p work/tasks && echo "x" > work/board.md
  git add -A && git commit -qm init --no-verify
}

# 1. a failing guard warns
setup
printf 'import sys\nsys.exit(1)\n' > scripts/check-edges.py
printf 'a: 1\n' > ecosystem.yaml
git add ecosystem.yaml scripts/check-edges.py
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "EDGES" || fail "a failing guard produced no warning"

# 2. a passing guard is silent
setup
printf 'import sys\nsys.exit(0)\n' > scripts/check-edges.py
printf 'a: 1\n' > ecosystem.yaml
git add ecosystem.yaml scripts/check-edges.py
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "EDGES" && fail "a passing guard still warned"

# 3. an absent guard is silent — not a complaint about a file this fork never took
setup
printf 'a: 1\n' > ecosystem.yaml
git add ecosystem.yaml
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "EDGES" && fail "an absent guard produced a warning"

# 4. the gate does not fire for a commit that touches no always-on surface
setup
printf 'import sys\nsys.exit(1)\n' > scripts/check-edges.py
mkdir -p work/tasks/x && echo "note" > work/tasks/x/STATUS.md
git add work/tasks/x/STATUS.md
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "EDGES" && fail "the gate fired for a commit outside the surface"

# 5. warn-only: the hook still exits 0 with a failing guard
setup
printf 'import sys\nsys.exit(1)\n' > scripts/check-edges.py
printf 'a: 1\n' > ecosystem.yaml
git add ecosystem.yaml scripts/check-edges.py
sh "$HOOK" >/dev/null 2>&1 || fail "the hook blocked; this gate is warn-only"

# 6. the cockpit gate (i): a drifted demo copy warns when the page's code is staged
setup
printf 'import sys\nsys.exit(1)\n' > scripts/build-cockpit-demo.py
mkdir -p scripts/web && echo "x" > scripts/web/x.js
git add scripts/web/x.js scripts/build-cockpit-demo.py
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "COCKPIT" || fail "a failing cockpit check produced no warning"

# 7. ... and stays silent when the checks pass or the cockpit is not staged
setup
printf 'import sys\nsys.exit(0)\n' > scripts/build-cockpit-demo.py
mkdir -p scripts/web && echo "x" > scripts/web/x.js
git add scripts/web/x.js scripts/build-cockpit-demo.py
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "COCKPIT" && fail "a passing cockpit check still warned"
setup
printf 'import sys\nsys.exit(1)\n' > scripts/build-cockpit-demo.py
mkdir -p work/tasks/x && echo "note" > work/tasks/x/STATUS.md
git add work/tasks/x/STATUS.md
out=$(GIT_DIR=.git sh "$HOOK" 2>&1 || true)
echo "$out" | grep -q "COCKPIT" && fail "the cockpit gate fired for a commit outside the cockpit"

echo "test-precommit-guards: 7 assertions pass"
