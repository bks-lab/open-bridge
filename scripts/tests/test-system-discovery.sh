#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Fixture test for the system-discovery scope-consent backstop.
#
# The guard's job: scripts/system-discovery.py must NOT scan the machine unless
# there is explicit consent — discovery.mode: broader in bridge-config.yaml, or
# the --broader / --force flag. A confined / unset / absent config makes the
# script REFUSE (no-op result, non-zero exit). This is the deterministic backstop
# behind PR #57's scope-consent promise ("default confined = no scan ever without
# explicit consent"), which previously lived only in the LLM wizard flow.
#
# It must NOT over-block: a broader config, or --broader/--force, must scan.
# --permissions selects WHICH sources to scan but is NOT consent on its own.
#
# Run: bash scripts/tests/test-system-discovery.sh   (from repo root; non-zero on failure)
# Offline + deterministic: the only scan source exercised is git_config, which
# reads local git config — never the network. The refuse paths run no scan at all.
set -u
cd "$(dirname "$0")/../.."

SCRIPT="scripts/system-discovery.py"
REFUSE_EXIT=3
PASS=0
FAIL=0

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'discovery:\n  mode: confined\n  permissions: []\n'   > "$TMP/confined.yaml"
printf 'discovery:\n  mode: broader\n  permissions: [git_config]\n' > "$TMP/broader.yaml"
printf 'theme: professional\n'                              > "$TMP/nomode.yaml"
ABSENT="$TMP/does-not-exist.yaml"

# run <config> [extra args...] → prints "<exit_code>\t<stdout>"
run() {
  local cfg="$1"; shift
  local out rc
  out="$(python3 "$SCRIPT" --config "$cfg" --output - "$@" 2>/dev/null)"
  rc=$?
  printf '%s\t%s' "$rc" "$out"
}

# assert_refuse <desc> <config> [extra args...]
assert_refuse() {
  local desc="$1"; shift
  local cfg="$1"; shift
  local res rc out
  res="$(run "$cfg" "$@")"
  rc="${res%%$'\t'*}"; out="${res#*$'\t'}"
  if [ "$rc" -eq "$REFUSE_EXIT" ] && printf '%s' "$out" | grep -q '"refused": true'; then
    echo "  PASS (refused) — $desc"; PASS=$((PASS+1))
  else
    echo "  FAIL (should refuse with exit $REFUSE_EXIT + refused:true, got exit $rc) — $desc"; FAIL=$((FAIL+1))
  fi
}

# assert_scan <desc> <config> [extra args...]
assert_scan() {
  local desc="$1"; shift
  local cfg="$1"; shift
  local res rc out
  res="$(run "$cfg" "$@")"
  rc="${res%%$'\t'*}"; out="${res#*$'\t'}"
  if [ "$rc" -eq 0 ] && printf '%s' "$out" | grep -q '"evidence"' && ! printf '%s' "$out" | grep -q '"refused"'; then
    echo "  PASS (scanned) — $desc"; PASS=$((PASS+1))
  else
    echo "  FAIL (should scan with exit 0 + evidence, got exit $rc) — $desc"; FAIL=$((FAIL+1))
  fi
}

echo "== system-discovery scope-consent fixture =="

# Precondition: the script must exist.
if [ ! -f "$SCRIPT" ]; then
  echo "  FAIL — $SCRIPT does not exist"
  echo ""
  echo "RESULT: 0 passed, 1 failed (script missing)"
  exit 1
fi

# REFUSE: confined / unset / absent config, no consent flag.
assert_refuse "confined config, no flag"                 "$TMP/confined.yaml"
assert_refuse "confined config + --permissions only (selection != consent)" \
                                                          "$TMP/confined.yaml" --permissions git_config
assert_refuse "config without a discovery.mode key"      "$TMP/nomode.yaml"
assert_refuse "absent config file (fresh CORE checkout)" "$ABSENT"

# SCAN: explicit consent via config or flag — no false-block.
assert_scan "broader config, no flag"      "$TMP/broader.yaml" --permissions git_config
assert_scan "confined config + --broader"  "$TMP/confined.yaml" --broader --permissions git_config
assert_scan "confined config + --force"    "$TMP/confined.yaml" --force --permissions git_config

echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
