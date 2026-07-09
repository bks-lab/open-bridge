#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# test-workspace-skill.sh — conformance guard for the /workspace skill.
#
# A skill that documents commands the engine does not have is a broken example.
# This suite pins skills/workspace/SKILL.md (+ references) to the REAL CLI of
# scripts/workspace.py: every `workspace <verb>` the skill documents must be a
# real subcommand, every `--flag` it names must exist, the references must be
# present + linked, and the frontmatter scope must be `core`. Model-free.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$ROOT/skills/workspace/SKILL.md"
MECH="$ROOT/skills/workspace/references/mechanics.md"
MODEL="$ROOT/skills/workspace/references/model.md"
ENGINE="$ROOT/scripts/workspace.py"

PASS=0; FAIL=0
pass() { echo "  PASS — $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL — $1"; [ -n "${2:-}" ] && echo "$2" | sed 's/^/      /'; FAIL=$((FAIL + 1)); }
assert_file() { if [ -f "$2" ]; then pass "$1"; else fail "$1 — absent: $2"; fi; }

echo "════════════════════════════════════════════════════════════════"
echo "  /workspace skill — conformance guard"
echo "════════════════════════════════════════════════════════════════"

# ── 1. files present ────────────────────────────────────────────────
echo; echo "── 1. skill files present ──────────────────────────────────────"
assert_file "SKILL.md present" "$SKILL"
assert_file "references/mechanics.md present" "$MECH"
assert_file "references/model.md present" "$MODEL"
assert_file "engine present" "$ENGINE"

# ── 2. frontmatter scope: core ──────────────────────────────────────
echo; echo "── 2. frontmatter declares scope: core ─────────────────────────"
SCOPE="$(python3 - "$SKILL" <<'PY'
import sys, re
t = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'metadata:\s*\n(?:.*\n)*?\s*scope:\s*(\S+)', t)
print(m.group(1) if m else "MISSING")
PY
)"
if [ "$SCOPE" = "core" ]; then pass "metadata.scope is core"; else fail "metadata.scope != core (got: $SCOPE)"; fi

# ── 3. engine's REAL subcommand set (parsed live from --help) ───────
echo; echo "── 3. documented verbs are all real engine subcommands ─────────"
ENGINE_VERBS="$(python3 - "$ENGINE" <<'PY'
import subprocess, sys, re
out = subprocess.run([sys.executable, sys.argv[1], "--help"],
                     capture_output=True, text=True).stdout
m = re.search(r'\{([a-z,\-]+)\}', out)
print("\n".join(sorted(set(m.group(1).split(",")))) if m else "")
PY
)"
# documented verbs = second token of every `workspace <verb>` code span in the skill
DOC_VERBS="$(python3 - "$SKILL" "$MECH" <<'PY'
import sys, re
verbs = set()
for p in sys.argv[1:]:
    t = open(p, encoding="utf-8").read()
    for m in re.finditer(r'`workspace ([a-z][a-z-]*)', t):
        verbs.add(m.group(1))
print("\n".join(sorted(verbs)))
PY
)"
BAD=""
for v in $DOC_VERBS; do
  echo "$ENGINE_VERBS" | grep -qxF "$v" || BAD="$BAD $v"
done
if [ -z "$BAD" ]; then
  pass "every documented verb is a real subcommand ($(echo $DOC_VERBS | tr '\n' ' '))"
else
  fail "skill documents non-existent verb(s):$BAD" "engine has: $(echo $ENGINE_VERBS | tr '\n' ' ')"
fi

# ── 4. documented flags all exist in the engine ─────────────────────
# Only the SKILL.md command-surface flags are the conformance target — the
# `--flag`s that appear inside a `workspace …` code span. Flags named purely to
# describe an internal call (e.g. the `git clone --recurse-submodules` line in
# mechanics.md) are NOT workspace flags and are intentionally out of scope.
echo; echo "── 4. documented flags exist in the engine ─────────────────────"
ENGINE_FLAGS="$(python3 - "$ENGINE" <<'PY'
import subprocess, sys, re
flags = set()
subs = ["create","list","validate","status","subscribe","unsubscribe"]
for s in ["--help"] + list(subs):
    args = [sys.executable, sys.argv[1]] + ([s] if s == "--help" else [s, "--help"])
    out = subprocess.run(args, capture_output=True, text=True).stdout
    for m in re.finditer(r'(--[a-z][a-z-]+)', out):
        flags.add(m.group(1))
print("\n".join(sorted(flags)))
PY
)"
DOC_FLAGS="$(python3 - "$SKILL" <<'PY'
import sys, re
flags = set()
# command-surface rows are single lines; each `workspace …` invocation line
# contributes its --flags (line-scoped → no fragile whole-doc backtick pairing).
for line in open(sys.argv[1], encoding="utf-8"):
    if "`workspace " in line:
        for m in re.finditer(r'(--[a-z][a-z-]+)', line):
            flags.add(m.group(1))
print("\n".join(sorted(flags)))
PY
)"
BADF=""
for f in $DOC_FLAGS; do
  echo "$ENGINE_FLAGS" | grep -qxF -- "$f" || BADF="$BADF $f"
done
if [ -z "$BADF" ]; then
  pass "every documented flag exists ($(echo $DOC_FLAGS | tr '\n' ' '))"
else
  fail "skill documents non-existent flag(s):$BADF" "engine has: $(echo $ENGINE_FLAGS | tr '\n' ' ')"
fi

# ── 5. references linked from SKILL.md ──────────────────────────────
echo; echo "── 5. references are linked from SKILL.md ──────────────────────"
grep -qF "references/mechanics.md" "$SKILL" && pass "mechanics.md linked" || fail "mechanics.md not linked in SKILL.md"
grep -qF "references/model.md" "$SKILL" && pass "model.md linked" || fail "model.md not linked in SKILL.md"

# ── 6. cross-link to /overlay (delegation is documented) ────────────
echo; echo "── 6. /overlay delegation documented ───────────────────────────"
grep -qF "/overlay" "$SKILL" && pass "cross-links /overlay (config-overlay delegation)" || fail "no /overlay cross-link"

# ── 7. TEETH — a bogus verb in a copy must be caught ────────────────
echo; echo "── 7. mutation-check — the verb guard has teeth ────────────────"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
cp "$SKILL" "$TMP"; printf '\n`workspace frobnicate <x>`\n' >> "$TMP"
BOGUS="$(python3 - "$TMP" <<'PY'
import sys, re
t = open(sys.argv[1], encoding="utf-8").read()
print("\n".join(sorted({m.group(1) for m in re.finditer(r'`workspace ([a-z][a-z-]*)', t)})))
PY
)"
if echo "$BOGUS" | grep -qxF "frobnicate"; then
  pass "injected bogus verb IS extracted (guard would flag it)"
else
  fail "guard blind to an injected bogus verb (no teeth)"
fi

echo
echo "════════════════════════════════════════════════════════════════"
echo "RESULT: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
