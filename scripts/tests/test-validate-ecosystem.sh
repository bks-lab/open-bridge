#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test harness for scripts/validate-ecosystem.py.
#
# Runs the validator against each fixture and checks expected exit code
# and that the output mentions the expected issue. Zero dependencies
# beyond Python 3 + PyYAML (same as the validator itself).
#
# Usage: bash scripts/tests/test-validate-ecosystem.sh
# Exit:  0 — all tests pass, 1 — at least one failure.

set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VALIDATOR="$ROOT/scripts/validate-ecosystem.py"
FIXTURES="$ROOT/scripts/tests/fixtures"

PASS=0
FAIL=0

run_case() {
  local name="$1" fixture="$2" expected_exit="$3" expected_substring="$4"
  local output
  output=$(python3 "$VALIDATOR" "$FIXTURES/$fixture" 2>&1)
  local actual_exit=$?

  if [ "$actual_exit" -ne "$expected_exit" ]; then
    echo "FAIL  $name"
    echo "  fixture:       $fixture"
    echo "  expected exit: $expected_exit"
    echo "  actual exit:   $actual_exit"
    echo "  output:"
    echo "$output" | sed 's/^/    /'
    FAIL=$((FAIL + 1))
    return
  fi

  if [ -n "$expected_substring" ] && ! echo "$output" | grep -qF "$expected_substring"; then
    echo "FAIL  $name"
    echo "  fixture:   $fixture"
    echo "  expected output to contain: $expected_substring"
    echo "  actual output:"
    echo "$output" | sed 's/^/    /'
    FAIL=$((FAIL + 1))
    return
  fi

  echo "PASS  $name"
  PASS=$((PASS + 1))
}

run_case "valid minimal passes"                 valid-minimal.yaml              0 ""
run_case "broken workspace ref fails"            broken-workspace-ref.yaml       1 "nonexistent-repo"
run_case "broken depends_on fails"               broken-depends-on.yaml          1 "missing-package"
run_case "broken wiki_ref fails"                 broken-wiki-ref.yaml            1 "wiki.areas.nonexistent"
run_case "malformed issue_repo fails"            broken-issue-repo.yaml          1 "issue_repo"
run_case "archived in workspace warns not fails" warn-archived-in-workspace.yaml 0 "status=archived"

# Regression guard: the SHIPPED example template must validate clean. Neither CI
# nor the pre-commit hook validate it (both key on ecosystem.yaml, which is
# gitignored), so this is the only gate that covers ecosystem.example.yaml.
example_out=$(python3 "$VALIDATOR" "$ROOT/ecosystem.example.yaml" 2>&1)
if [ $? -eq 0 ]; then
  echo "PASS  shipped ecosystem.example.yaml validates clean"
  PASS=$((PASS + 1))
else
  echo "FAIL  shipped ecosystem.example.yaml validates clean"
  echo "$example_out" | sed 's/^/    /'
  FAIL=$((FAIL + 1))
fi

echo
echo "Results: $PASS passed, $FAIL failed."
[ "$FAIL" -eq 0 ]
