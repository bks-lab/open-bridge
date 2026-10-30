#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Thin wrapper for the pytest suite of scripts/context-index.py.
#
# Run: bash scripts/tests/test-context-index.sh   (from repo root; non-zero on failure)
set -u
cd "$(dirname "$0")/../.."

# Smoke: --registries prints one card per registry, base first.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
printf 'org: base\ncustomers:\n  a:\n    description: base label\n' >"$tmp/ecosystem.yaml"
printf 'org: acme\ncustomers:\n  b:\n    description: acme label\n' >"$tmp/ecosystem.acme.yaml"
out=$(python3 scripts/context-index.py --repo-root "$tmp" --registries) || {
  echo "FAIL: --registries exited non-zero" >&2; exit 1; }
for header in "# ecosystem.yaml — index" "# ecosystem.acme.yaml — index"; do
  case "$out" in
    *"$header"*) ;;
    *) echo "FAIL: --registries output lacks '$header'" >&2; exit 1 ;;
  esac
done
echo "ok: --registries prints both registry cards"

python3 -m pytest scripts/tests/test_context_index.py -q
