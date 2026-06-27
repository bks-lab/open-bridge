#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test harness for the org-overlay engine (scripts/overlay.py).
#
# Deterministic + model-free. Drives the REAL scripts/overlay.py against a
# THROWAWAY COPY of the open-bridge tree (extracted via `git archive` into a
# temp dir) so the real working tree is never mutated. The overlay SOURCE repos
# are local git fixtures: a clean one derived from examples/overlay-example/
# (prompt_fields stripped for deterministic, non-interactive materialize) and
# the deliberate violation fixtures under fixtures/overlay/.
#
# Coverage (each an assert with a clear PASS/FAIL line):
#   - idempotent re-apply (2nd apply writes nothing; lock byte-identical)
#   - subscribe + materialize (every dest exists; inline scope:org; lock hashes)
#   - conflict no-clobber (edited managed dest, unchanged source → file intact)
#   - 3-way merge clean (disjoint) AND conflict (same line → preserved)
#   - dry-run writes nothing (add/sync --dry-run → no dest/lock; plan on stdout)
#   - remove restores clean tree; --keep-files; refuse-modified
#   - leak gate refuses a raw-secret overlay; clean siblings still materialize
#   - CORE-refusal (_template + wrapper README dests hard-refused)
#   - path-traversal refusal (escaping dest refused pre-write) + unit check
#   - multi-overlay precedence (higher wins; lock owner) + CORE-only separation
#   - schema validation (malformed manifest aborts add; example validates)
#   - effective scope classifier coverage (every example dest → org/user)
#   - prompt-field override survives a re-sync — source-unchanged (skip) AND
#     source-changed (re-materialize): no silent clobber, lock keeps PATHS only
#   - leak gate refuses a real ALL-CAPS secret (base32 TOTP / uppercase-hex) at a
#     covered key; URI / ${var} / comment / prose pass (security-regression unit)
#
# Run:  bash scripts/tests/test-overlay.sh        (exits non-zero on any failure)
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OVERLAY="$ROOT/scripts/overlay.py"
FIXROOT="$ROOT/scripts/tests/fixtures/overlay"
EXAMPLE="$ROOT/examples/overlay-example"

PASS=0
FAIL=0
OUT=""
RC=0

pass() { echo "  PASS — $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL — $1"; [ -n "${2:-}" ] && echo "$2" | sed 's/^/      /'; FAIL=$((FAIL + 1)); }

assert_rc() {        # <desc> <expected_rc>
  if [ "$RC" -eq "$2" ]; then pass "$1 (exit $RC)"; else fail "$1 — expected exit $2, got $RC" "$OUT"; fi
}
assert_out() {       # <desc> <needle>
  if printf '%s' "$OUT" | grep -qF -- "$2"; then pass "$1"; else fail "$1 — output missing: $2" "$OUT"; fi
}
assert_file() {      # <desc> <path>
  if [ -f "$2" ]; then pass "$1"; else fail "$1 — file absent: $2"; fi
}
assert_absent() {    # <desc> <path>
  if [ ! -e "$2" ]; then pass "$1"; else fail "$1 — path unexpectedly present: $2"; fi
}
assert_grep() {      # <desc> <path> <needle>
  if [ -f "$2" ] && grep -qF -- "$3" "$2"; then pass "$1"; else fail "$1 — '$3' not in $2"; fi
}
assert_nogrep() {    # <desc> <path> <needle>
  if [ -f "$2" ] && grep -qF -- "$3" "$2"; then fail "$1 — '$3' unexpectedly in $2"; else pass "$1"; fi
}
assert_eq() {        # <desc> <a> <b>
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 — '$2' != '$3'"; fi
}

# run_overlay <consumer> <overlay args...> — feeds `yes y` on stdin so the
# behavioural [y] gates and any prompt are satisfied; captures $OUT + $RC.
run_overlay() {
  local con="$1"; shift
  OUT="$(yes y | python3 "$OVERLAY" --repo-root "$con" "$@" 2>&1)"
  RC=$?
}

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# --- pristine consumer template (tracked tree only, no .git / .bridge) -------
PRISTINE="$TMP/pristine"
mkdir -p "$PRISTINE"
git -C "$ROOT" archive --format=tar HEAD | ( cd "$PRISTINE" && tar -xf - )

mkcon() {  # echoes a fresh consumer dir on a user/test branch
  # mktemp -d for a UNIQUE dir — a counter incremented inside the $(mkcon)
  # command-substitution subshell would not persist, silently reusing one dir.
  local c; c="$(mktemp -d "$TMP/con.XXXXXX")"
  cp -R "$PRISTINE/." "$c/"
  git -C "$c" init -q
  git -C "$c" checkout -q -b user/test
  git -C "$c" add -A
  git -C "$c" -c user.email=t@t -c user.name=t commit -qm init >/dev/null 2>&1
  echo "$c"
}

git_overlay() {  # init + commit a dir as a local overlay repo
  git -C "$1" init -q
  git -C "$1" add -A
  git -C "$1" -c user.email=t@t -c user.name=t commit -qm "$2" >/dev/null 2>&1
}

mk_clean_overlay() {  # echoes a clean overlay repo derived from the example
  local o; o="$(mktemp -d "$TMP/ovclean.XXXXXX")"
  cp -R "$EXAMPLE/." "$o/"
  # Strip prompt_fields so materialize is fully non-interactive + leaves the
  # example placeholders untouched (deterministic hashes, valid YAML).
  python3 - "$o/overlay.manifest.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p))
for f in d.get("files", []):
    f.pop("prompt_fields", None)
yaml.safe_dump(d, open(p, "w"), sort_keys=False, allow_unicode=True)
PY
  git_overlay "$o" init
  echo "$o"
}

mk_fixture_overlay() {  # <fixture-name> — echoes a fresh git overlay repo
  local o; o="$(mktemp -d "$TMP/ovfix.XXXXXX")"
  cp -R "$FIXROOT/$1/." "$o/"
  git_overlay "$o" init
  echo "$o"
}

# in-place single-line replace (portable: no BSD/GNU sed -i divergence)
edit_line() { python3 -c 'import sys; p,a,b=sys.argv[1:4]; t=open(p).read(); open(p,"w").write(t.replace(a,b))' "$1" "$2" "$3"; }

# Canonical materialized dests of the example overlay.
EX_DESTS=".claude/agents/example-org-coordinator.md identity/accounts/example-cloud.yaml identity/mandants/example-team.yaml rules/org/example-routing.md skills/example-org-coordinator/SKILL.md workflow/contexts/example-docs.yaml workflow/projects/example-board.yaml"

echo "════════════════════════════════════════════════════════════════"
echo "  overlay engine — test harness"
echo "════════════════════════════════════════════════════════════════"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 1. subscribe + materialize ──────────────────────────────────"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org
assert_rc "add succeeds" 0
assert_out "add reports clean materialize" "added example-org"
allok=1
for d in $EX_DESTS; do [ -f "$CON/$d" ] || { allok=0; echo "      missing dest: $d"; }; done
assert_eq "every example dest materialized" "$allok" 1
assert_file "ecosystem fragment copied" "$CON/ecosystem.example-org.yaml"
assert_grep "@import wired into CLAUDE.md" "$CON/CLAUDE.md" "@ecosystem.example-org.yaml"
# inline scope:org survives on each materialized dest
scopeok=1
for d in $EX_DESTS; do grep -qF "scope: org" "$CON/$d" || { scopeok=0; echo "      no scope:org in $d"; }; done
assert_eq "each dest carries inline scope: org" "$scopeok" 1
assert_file "lock written" "$CON/overlays.lock.yaml"
# lock lists all 7 dests, and live file hashes match the lock's materialized_sha
hashok=1; lockcount=0
for d in $EX_DESTS; do
  lh="$(python3 -c 'import sys,yaml;d=yaml.safe_load(open(sys.argv[1]));print(next((f["materialized_sha256"] for f in d["overlays"]["example-org"]["files"] if f["dest"]==sys.argv[2]),""))' "$CON/overlays.lock.yaml" "$d")"
  fh="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$CON/$d")"
  [ -n "$lh" ] && lockcount=$((lockcount + 1))
  [ "$lh" = "$fh" ] || { hashok=0; echo "      hash mismatch $d: lock=$lh live=$fh"; }
done
assert_eq "lock lists all 7 dests" "$lockcount" 7
assert_eq "lock materialized hashes match live files" "$hashok" 1

# ───────────────────────────────────────────────────────────────────
echo
echo "── 2. idempotent re-apply (lock byte-identical) ────────────────"
cp "$CON/overlays.lock.yaml" "$TMP/lock.before"
run_overlay "$CON" apply --yes
assert_rc "first apply succeeds" 0
cp "$CON/overlays.lock.yaml" "$TMP/lock.after1"
run_overlay "$CON" apply --yes
assert_rc "second apply succeeds" 0
cp "$CON/overlays.lock.yaml" "$TMP/lock.after2"
if cmp -s "$TMP/lock.after1" "$TMP/lock.after2"; then pass "lock byte-identical across re-applies"; else fail "lock changed across re-applies" "$(diff "$TMP/lock.after1" "$TMP/lock.after2")"; fi
# second apply must write nothing new — all 7 managed files report skipped, and
# the per-write counters (clean=/conflict=/upstream-ahead=) never appear.
assert_out "re-apply writes nothing (all 7 skipped)" "skipped=7"
if printf '%s' "$OUT" | grep -qE 'clean=[0-9]|conflict=[0-9]|upstream-ahead=[0-9]'; then
  fail "re-apply recorded a fresh write" "$OUT"
else
  pass "re-apply recorded no fresh write"
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 3. conflict no-clobber (edit managed dest, source unchanged) ─"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
TARGET="$CON/workflow/contexts/example-docs.yaml"
edit_line "$TARGET" "id: example-docs" "id: example-docs  # LOCAL-EDIT-MARKER"
run_overlay "$CON" sync --yes
assert_rc "sync over a locally-edited dest succeeds" 0
assert_out "sync reports locally-modified" "locally-modified"
assert_grep "local edit preserved (no clobber)" "$TARGET" "LOCAL-EDIT-MARKER"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 4. 3-way merge — clean (disjoint lines) ─────────────────────"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
TARGET="$CON/workflow/contexts/example-docs.yaml"
# consumer edits one line; overlay v2 edits a DISJOINT line.
edit_line "$TARGET" "default_mandant: example-team" "default_mandant: example-team  # CONSUMER-LINE"
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" 'description: "Documentation + routing context for the example-org engagement"' 'description: "UPSTREAM-LINE — documentation + routing context"'
git -C "$OV" add -A; git -C "$OV" -c user.email=t@t -c user.name=t commit -qm v2 >/dev/null 2>&1
run_overlay "$CON" sync --yes
assert_rc "sync with disjoint upstream change succeeds" 0
assert_grep "consumer's disjoint edit kept" "$TARGET" "CONSUMER-LINE"
assert_grep "upstream's disjoint edit merged in" "$TARGET" "UPSTREAM-LINE"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 5. 3-way merge — conflict (same line) ───────────────────────"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
TARGET="$CON/workflow/contexts/example-docs.yaml"
edit_line "$TARGET" 'description: "Documentation + routing context for the example-org engagement"' 'description: "LOCAL-CONFLICT"'
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" 'description: "Documentation + routing context for the example-org engagement"' 'description: "UPSTREAM-CONFLICT"'
git -C "$OV" add -A; git -C "$OV" -c user.email=t@t -c user.name=t commit -qm v2 >/dev/null 2>&1
run_overlay "$CON" sync --yes
assert_rc "sync with conflicting upstream change succeeds" 0
assert_out "sync reports a conflict" "conflict"
assert_grep "local side preserved on conflict" "$TARGET" "LOCAL-CONFLICT"
assert_nogrep "conflicting file left intact (no merge markers)" "$TARGET" "<<<<<<<"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 6. dry-run writes nothing ───────────────────────────────────"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org --dry-run
assert_rc "add --dry-run succeeds" 0
assert_out "add --dry-run prints a plan" "clean-new"
assert_out "add --dry-run states no writes" "no files written"
assert_absent "add --dry-run wrote no lock" "$CON/overlays.lock.yaml"
assert_absent "add --dry-run wrote no dest" "$CON/workflow/contexts/example-docs.yaml"
# now a real add, then sync --dry-run must not touch lock/dests
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
cp "$CON/overlays.lock.yaml" "$TMP/lock.predry"
run_overlay "$CON" sync --dry-run
assert_rc "sync --dry-run succeeds" 0
assert_out "sync --dry-run states no writes" "no files written"
if cmp -s "$CON/overlays.lock.yaml" "$TMP/lock.predry"; then pass "sync --dry-run left lock untouched"; else fail "sync --dry-run mutated lock"; fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 7. remove restores a clean tree ─────────────────────────────"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
run_overlay "$CON" remove example-org
assert_rc "remove succeeds" 0
gone=1; for d in $EX_DESTS; do [ -e "$CON/$d" ] && { gone=0; echo "      still present: $d"; }; done
assert_eq "all clean managed files deleted" "$gone" 1
assert_absent "ecosystem fragment deleted" "$CON/ecosystem.example-org.yaml"
assert_nogrep "@import removed from CLAUDE.md" "$CON/CLAUDE.md" "@ecosystem.example-org.yaml"
assert_absent "cache dir removed" "$CON/.bridge/overlays/example-org"
emptylock="$(python3 -c 'import yaml,sys;d=yaml.safe_load(open(sys.argv[1]));print(len((d or {}).get("overlays") or {}))' "$CON/overlays.lock.yaml" 2>/dev/null || echo 0)"
assert_eq "lock entry dropped" "$emptylock" 0
# nothing else touched: remove strips only the overlay @import, the core
# @ecosystem.yaml import survives (CLAUDE.md is otherwise intact).
assert_grep "core @ecosystem.yaml import survives remove" "$CON/CLAUDE.md" "@ecosystem.yaml"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 8. remove --keep-files / refuse-modified ────────────────────"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
run_overlay "$CON" remove example-org --keep-files
assert_rc "remove --keep-files succeeds" 0
assert_file "kept file remains after --keep-files" "$CON/workflow/contexts/example-docs.yaml"
keptlock="$(python3 -c 'import yaml,sys;d=yaml.safe_load(open(sys.argv[1]));print(len((d or {}).get("overlays") or {}))' "$CON/overlays.lock.yaml" 2>/dev/null || echo 0)"
assert_eq "subscription dropped (lock empty) but files kept" "$keptlock" 0
# refuse-modified: a locally-edited managed file is preserved by plain remove
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
edit_line "$CON/workflow/contexts/example-docs.yaml" "id: example-docs" "id: example-docs  # KEEP-ME"
run_overlay "$CON" remove example-org
assert_rc "remove (with a modified file) succeeds" 0
assert_out "remove keeps the locally-modified file" "KEEP"
assert_file "modified file preserved on remove" "$CON/workflow/contexts/example-docs.yaml"
assert_grep "preserved file still carries its edit" "$CON/workflow/contexts/example-docs.yaml" "KEEP-ME"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 9. leak gate refuses a raw-secret overlay ───────────────────"
CON="$(mkcon)"; OV="$(mk_fixture_overlay secret-overlay)"
run_overlay "$CON" add "file://$OV" --name secret-overlay
assert_rc "add (with a leaky file) still succeeds for clean siblings" 0
assert_out "leak gate refused the secret file" "leak-refused"
assert_absent "secret file NOT materialized" "$CON/identity/accounts/leaky.yaml"
assert_file "clean sibling still materialized" "$CON/workflow/contexts/clean-sibling.yaml"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 10. CORE-refusal (_template + wrapper README) ───────────────"
CON="$(mkcon)"; OV="$(mk_fixture_overlay core-refusal-overlay)"
run_overlay "$CON" add "file://$OV" --name core-refusal-overlay
assert_rc "add (with CORE dests) succeeds for clean siblings" 0
assert_out "engine reports core-refused" "core-refused"
assert_absent "_-prefixed dest hard-refused (never written)" "$CON/workflow/projects/_fixture.yaml"
assert_absent "wrapper README dest hard-refused" "$CON/identity/mandants/README.md"
# the pre-existing CORE _template.yaml in the consumer is never clobbered
assert_nogrep "pre-existing CORE _template not overwritten" "$CON/workflow/projects/_template.yaml" "id: _fixture"
assert_file "clean sibling still materialized" "$CON/workflow/contexts/clean.yaml"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 11. path-traversal refusal ──────────────────────────────────"
CON="$(mkcon)"; OV="$(mk_fixture_overlay traversal-overlay)"
run_overlay "$CON" add "file://$OV" --name traversal-overlay
assert_rc "add (with an escaping dest) succeeds for clean siblings" 0
assert_out "engine refuses the escaping dest" "escapes repo root"
assert_absent "escaping dest NOT written outside repo root" "$(dirname "$CON")/escaped.yaml"
assert_absent "escaping dest NOT written inside repo either" "$CON/escaped.yaml"
assert_file "clean in-tree sibling still materialized" "$CON/workflow/contexts/ok.yaml"
# unit: dest_refusal must reject the literal ../../etc/x before any write
UNIT="$(python3 - "$ROOT" "$CON" <<'PY'
import importlib.util, os, sys
repo, con = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("ov", os.path.join(repo, "scripts", "overlay.py"))
ov = importlib.util.module_from_spec(spec); spec.loader.exec_module(ov)
c = ov.Consumer(con)
r = ov.dest_refusal("../../etc/x", b"scope: org\nid: x\n", c, {"overlays": {}}, "t", 0)
print(r or "ALLOWED")
PY
)"
assert_eq "dest_refusal rejects literal ../../etc/x" "$UNIT" "escapes repo root"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 12. multi-overlay precedence + ownership ────────────────────"
CON="$(mkcon)"; OVA="$(mk_fixture_overlay overlay-a)"; OVB="$(mk_fixture_overlay overlay-b)"
run_overlay "$CON" add "file://$OVA" --name overlay-a --precedence 5
assert_rc "add overlay-a (precedence 5) succeeds" 0
assert_grep "shared dest owned by overlay-a" "$CON/workflow/contexts/shared.yaml" "owner: overlay-a"
run_overlay "$CON" add "file://$OVB" --name overlay-b --precedence 1
assert_rc "add overlay-b (precedence 1) succeeds" 0
assert_out "lower-precedence overlay refused on owned dest" "owned by overlay 'overlay-a'"
assert_grep "higher-precedence content wins (unchanged)" "$CON/workflow/contexts/shared.yaml" "owner: overlay-a"
assert_nogrep "lower-precedence content did NOT overwrite" "$CON/workflow/contexts/shared.yaml" "owner: overlay-b"
OWNER="$(python3 -c 'import yaml,sys;d=yaml.safe_load(open(sys.argv[1]));print(next((n for n,e in d["overlays"].items() for f in e.get("files",[]) if f["dest"]=="workflow/contexts/shared.yaml"),""))' "$CON/overlays.lock.yaml")"
assert_eq "lock records the dest owner as overlay-a" "$OWNER" "overlay-a"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 13. CORE-only separation (no org-overlay → no-op) ───────────"
CON="$(mkcon)"
# a consumer whose only upstream is a CORE upstream (role != org-overlay)
cat > "$CON/bridge-config.yaml" <<'EOF'
upstreams:
  - name: open-bridge
    repo: example/open-bridge
    role: upstream
EOF
git -C "$CON" add -A; git -C "$CON" -c user.email=t@t -c user.name=t commit -qm cfg >/dev/null 2>&1
run_overlay "$CON" sync
assert_rc "sync with no org-overlay subscribed succeeds" 0
assert_out "CORE-only consumer is a no-op" "No org overlays subscribed"
assert_absent "no lock written for a CORE-only consumer" "$CON/overlays.lock.yaml"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 14. schema validation ───────────────────────────────────────"
CON="$(mkcon)"; OVM="$(mk_fixture_overlay malformed-overlay)"
run_overlay "$CON" add "file://$OVM" --name malformed-overlay
assert_rc "add aborts on a malformed manifest" 1
assert_out "abort cites schema validation" "schema"
assert_absent "nothing materialized from a malformed overlay" "$CON/workflow/contexts/x.yaml"
assert_absent "no lock written for a malformed overlay" "$CON/overlays.lock.yaml"
# the real example manifest validates against the published schema
OUT="$(check-jsonschema --schemafile "$ROOT/docs/schemas/overlay-manifest.schema.yaml" "$EXAMPLE/overlay.manifest.yaml" 2>&1)"; RC=$?
assert_rc "example manifest schema-validates" 0
# validate-bridge over a consumer that materialized the example mandant passes
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
OUT="$(python3 "$CON/scripts/validate-bridge.py" --surface mandant 2>&1)"; RC=$?
assert_rc "validate-bridge passes over the materialized example mandant" 0

# ───────────────────────────────────────────────────────────────────
echo
echo "── 15. effective scope classifier coverage ─────────────────────"
# Every example-org dest must resolve (inline scope tripwire, else path
# classify) to org/user — NEVER core. This is exactly the classification the
# engine's dest_refusal uses, so a 'core' here would mean a misrouted overlay
# file.
CLS="$(python3 - "$ROOT" "$EXAMPLE/tree" <<'PY'
import importlib.util, os, sys
repo, tree = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("ov", os.path.join(repo, "scripts", "overlay.py"))
ov = importlib.util.module_from_spec(spec); spec.loader.exec_module(ov)
os.chdir(tree)
dests = [
    ".claude/agents/example-org-coordinator.md",
    "identity/accounts/example-cloud.yaml",
    "identity/mandants/example-team.yaml",
    "rules/org/example-routing.md",
    "skills/example-org-coordinator/SKILL.md",
    "workflow/contexts/example-docs.yaml",
    "workflow/projects/example-board.yaml",
]
bad = []
for d in dests:
    b = open(d, "rb").read()
    eff = ov.staged_scope(b) or ov.classify_file(d)
    if eff not in ("org", "user"):
        bad.append(f"{d}={eff}")
print("OK" if not bad else "BAD:" + ",".join(bad))
PY
)"
assert_eq "every example dest classifies org/user (never core)" "$CLS" "OK"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 16. prompt-field override survives a re-sync (no silent clobber) ─"
CON="$(mkcon)"
OV="$(mktemp -d "$TMP/ovpf.XXXXXX")"
mkdir -p "$OV/tree/workflow/projects"
cat > "$OV/overlay.manifest.yaml" <<'YAML'
schema_version: 1
overlay:
  name: pf
  org: pf
defaults:
  scope: org
  source_root: "tree/"
  on_conflict: prompt
selection:
  include: ["**"]
  exclude: ["**/_*.yaml", "**/README.md"]
files:
  - dest: workflow/projects/pf.yaml
    kind: config
    prompt_fields:
      - path: "$.project.number"
        reason: "board number (org/instance-specific)"
YAML
cat > "$OV/tree/workflow/projects/pf.yaml" <<'YAML'
scope: org
project:
  number: 1
  name: PF
YAML
git_overlay "$OV" pf-init
# interactive add — a teammate overrides the board number to 999
OUT="$(printf '999\n' | python3 "$OVERLAY" --repo-root "$CON" add "file://$OV" --name pf 2>&1)"; RC=$?
assert_rc "add with an interactive override succeeds" 0
assert_grep "override 999 materialized" "$CON/workflow/projects/pf.yaml" "999"
assert_grep "lock records the prompted PATH" "$CON/overlays.lock.yaml" "project.number"
assert_nogrep "lock never stores the override VALUE" "$CON/overlays.lock.yaml" "999"
# re-sync, source unchanged, non-interactive — must NOT revert to the default
run_overlay "$CON" sync pf --yes
assert_rc "re-sync (source unchanged) succeeds" 0
assert_out "unchanged source is a skip, not upstream-ahead" "skipped=1"
assert_grep "override 999 PRESERVED across the re-sync" "$CON/workflow/projects/pf.yaml" "999"
assert_nogrep "did NOT revert to the source default" "$CON/workflow/projects/pf.yaml" "number: 1"
assert_grep "lock still records the prompted PATH" "$CON/overlays.lock.yaml" "project.number"
# source changes a DIFFERENT field — the override must survive the re-materialize
sed -i.bak 's/name: PF/name: PF-RENAMED/' "$OV/tree/workflow/projects/pf.yaml" && rm -f "$OV/tree/workflow/projects/pf.yaml.bak"
git -C "$OV" add -A; git -C "$OV" -c user.email=t@t -c user.name=t commit -qm v2 >/dev/null 2>&1
run_overlay "$CON" sync pf --yes
assert_rc "re-sync after a source change succeeds" 0
assert_grep "source change (rename) applied" "$CON/workflow/projects/pf.yaml" "PF-RENAMED"
assert_grep "override 999 STILL preserved across a source change" "$CON/workflow/projects/pf.yaml" "999"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 17. leak gate — real all-caps secret refused (security unit) ────"
SECCHK="$(python3 - "$OVERLAY" <<'PY'
import importlib.util, sys
s = importlib.util.spec_from_file_location("o", sys.argv[1])
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
chk = lambda b: bool(m.leak_check(b, "org"))
refused = (
    chk(b"  secret: JBSWY3DPEHPK3PXP\n")            # base32 TOTP seed — all-caps
    and chk(b"  password: A1B2C3D4E5F6A7B8C9D0\n")  # uppercase-hex key
    and chk(b"  api_key: aB3xK9mNpQrS\n")           # mixed-case secret
)
passes = (
    not chk(b'  api_key: "${ELASTIC_API_KEY}"\n')   # ${var} reference
    and not chk(b"  token: keychain://acct/x\n")        # URI reference
    and not chk(b"  # secret: SOME_NAME in a comment\n") # comment, not an assignment
    and not chk(b"  note: see Token: ephemeral zone\n")  # prose, not an assignment
)
print("OK" if (refused and passes) else "FAIL")
PY
)"
assert_eq "all-caps secrets refused; URI/\${}/comment/prose pass" "$SECCHK" "OK"

# ───────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════"
echo "RESULT: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
