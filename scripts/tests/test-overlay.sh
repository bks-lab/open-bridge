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
#     source-changed (re-materialize) for SCALAR paths: no silent clobber, lock
#     keeps PATHS only
#   - leak gate refuses a real ALL-CAPS secret (base32 TOTP / uppercase-hex),
#     totp_secret/mfa_seed keys, and an Azure AccountKey= conn-string; URI /
#     ${var} / comment / prose pass; CODE files skip the assignment heuristic
#     (api_key=get()) but still get the format scan (AKIA in a .py caught)
#   - a wildcard [*] override NEVER cross-wires to the wrong list element on a
#     roster reorder (positional restore is refused for multi-valued paths)
#   - a scope:org SKILL ships COMPLETE — its scripts inherit the SKILL.md tier
#     and materialize, never CORE-refused (§19)
#   - the overlay excludes its managed dests via the UNTRACKED .git/info/exclude
#     (skills/agents land in tracked paths) so a public fork can't `git add -A`-
#     publish org content OR its filenames; .gitignore is untouched; dropped on
#     remove (§20)
#   - the LARGE PRUNE GUARD — a `select:` narrowed by mistake (dropping many
#     already-materialized files out of scope at once) never silently mass-
#     deletes: --dry-run surfaces an aggregate warning, non-interactive/--yes
#     refuses the whole batch outright (lock keeps every entry, nothing on
#     disk touched), interactive gates it behind one explicit confirmation
#     that can decline (kept) or confirm (deletes) — a lone real orphan below
#     the threshold is unaffected either way (§24)
#   - the ecosystem fragment is a managed file (§25): the lock records it, diff
#     and --dry-run list it, a local edit survives a sync AND the next one that
#     carries an upstream change (a merged edit is never laundered into
#     materialized_sha256, for tree files too), a conflict keeps the local side,
#     remove keeps an edited fragment, a lock from the pre-fix engine is adopted
#     without clobbering (also with its pinned blob gone), a consumer's own
#     registry from before the subscription is never merged into or removed, a
#     fragment also shipped under tree/ still gets its @import, and a fragment
#     the overlay stops shipping is pruned
#     together with its @import
#   - unattended sync (§26, #218): new files and updates apply; a conflict or a
#     planned deletion HOLDS the whole overlay (nothing written, pin unchanged,
#     still held on the next run); a clean merge applies; a new behavioural file
#     stays pending; pull_interval_days is honoured; a failure exits 1; status
#     shows the last run; the wrapper reports and notifies on change only; the
#     installer renders the --overlays job under --print, sandboxed
#   - the behavioural gate asks once per skill folder, all or none (§27): a
#     non-interactive or declined run withholds the whole folder (no SKILL.md
#     without its new reference), one [y] writes all of it, and `status` counts
#     what waits as pending-confirm and never as upstream-ahead=0
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

assert_neq() {       # <desc> <a> <b>
  if [ "$2" != "$3" ]; then pass "$1"; else fail "$1 — both are '$2'"; fi
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
# bridge-config.yaml and overlays.lock.yaml are both gitignored in open-bridge
# itself, so `git archive` never includes them there — but a downstream instance
# may deliberately TRACK either one (a private repo has no reason to gitignore
# its own config or its own overlay subscription state; both are documented,
# intentional exceptions in such an instance's own .gitignore). Strip both
# unconditionally rather than relying on that being absent: every consumer must
# start with a genuinely clean slate (only the overlay(s) each test explicitly
# subscribes, with no pre-existing lock entries), never inheriting a real
# instance's actual upstreams or subscriptions into an "isolated" test fixture.
PRISTINE="$TMP/pristine"
mkdir -p "$PRISTINE"
# The fixture is copied once PER CONSUMER, so its size multiplies by the number
# of consumers in the suite. Upstream the tree is small and this is invisible;
# on a downstream instance `work/` fills with deliverables and the copies stop
# being free. Measured on one such instance: 334 of 356 MB were `work/`, one
# finished consumer 728 MB, peak ~15.7 GB against the ~14 GB free on a GitHub
# ubuntu-latest runner. The runner then dies mid-step, which surfaces as a
# failed job with the step stuck `in_progress`, every later step `pending` and
# NO logs uploaded (BlobNotFound) — never as a test failure, so it reads like a
# broken assertion and is not one. No test or engine reads a byte of `work/`;
# excluding it left 22 MB. Quoted array, not word splitting: agents whose shell
# is zsh do not split an unquoted list at all.
FIXTURE_PATHS=()
while IFS= read -r _p; do FIXTURE_PATHS+=("$_p"); done \
  < <(git -C "$ROOT" ls-tree --name-only HEAD | grep -vxE 'work|imports')
[ "${#FIXTURE_PATHS[@]}" -gt 0 ] || { echo "fixture path list is empty — refusing to build an empty pristine tree" >&2; exit 1; }
git -C "$ROOT" archive --format=tar HEAD -- "${FIXTURE_PATHS[@]}" | ( cd "$PRISTINE" && tar -xf - )
rm -f "$PRISTINE/bridge-config.yaml" "$PRISTINE/overlays.lock.yaml"

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
# ADJACENT to the core import, not appended at the end of the file. The wiring
# anchors on a literal line, and an anchor nobody asserts on rots in silence:
# the insert falls through to its end-of-file fallback, the import still works,
# and nothing says the placement changed. That is exactly how this assertion
# came to be — the anchor was `@ecosystem.yaml` and outlived that line.
IMPLINE="$(grep -n '@ecosystem.example-org.yaml' "$CON/CLAUDE.md" | head -1 | cut -d: -f1)"
assert_eq "@import sits next to the core import, not at EOF" "$([ "${IMPLINE:-99}" -le 4 ] && echo yes || echo no)" "yes"
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
# 7 tree files plus the ecosystem fragment, which is a managed file (§25).
assert_out "re-apply writes nothing (7 files + the fragment skipped)" "skipped=8"
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

# The lock must not LAUNDER that kept edit. `materialized_sha256` means "the
# bytes the overlay wrote"; recording the consumer's own bytes under that name
# turns a hand-edited file into a pristine one, and `remove` deletes a pristine
# file without asking (cmd_remove: clean = sha256(dest) == materialized_sha256).
# One routine conflict-then-keep was enough to arm that.
livesha="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$TARGET")"
locksha="$(python3 - "$CON/overlays.lock.yaml" <<'PYEOF'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
for ov in (d.get("overlays") or {}).values():
    for f in ov.get("files") or []:
        if f.get("dest", "").endswith("example-docs.yaml"):
            print(f.get("materialized_sha256") or "")
            break
PYEOF
)"
assert_neq "kept local edit is not laundered into the lock" "$locksha" "$livesha"
run_overlay "$CON" remove example-org --yes >/dev/null 2>&1
assert_file "a kept local edit survives overlay remove" "$TARGET"
assert_grep "and it is still the consumer's version" "$TARGET" "LOCAL-CONFLICT"

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
# @AGENTS.md import survives (CLAUDE.md is otherwise intact). The canary used
# to be @ecosystem.yaml, which stopped being an import when the registry
# became an index (docs/context-index.md); @AGENTS.md is the import that is
# always there.
assert_grep "core @AGENTS.md import survives remove" "$CON/CLAUDE.md" "@AGENTS.md"

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
# interactive add — a teammate overrides the board number to 31415926
OUT="$(printf '31415926\n' | python3 "$OVERLAY" --repo-root "$CON" add "file://$OV" --name pf 2>&1)"; RC=$?
assert_rc "add with an interactive override succeeds" 0
assert_grep "override 31415926 materialized" "$CON/workflow/projects/pf.yaml" "31415926"
assert_grep "lock records the prompted PATH" "$CON/overlays.lock.yaml" "project.number"
assert_nogrep "lock never stores the override VALUE" "$CON/overlays.lock.yaml" "31415926"
# re-sync, source unchanged, non-interactive — must NOT revert to the default
run_overlay "$CON" sync pf --yes
assert_rc "re-sync (source unchanged) succeeds" 0
assert_out "unchanged source is a skip, not upstream-ahead" "skipped=1"
assert_grep "override 31415926 PRESERVED across the re-sync" "$CON/workflow/projects/pf.yaml" "31415926"
assert_nogrep "did NOT revert to the source default" "$CON/workflow/projects/pf.yaml" "number: 1"
assert_grep "lock still records the prompted PATH" "$CON/overlays.lock.yaml" "project.number"
# source changes a DIFFERENT field — the override must survive the re-materialize
sed -i.bak 's/name: PF/name: PF-RENAMED/' "$OV/tree/workflow/projects/pf.yaml" && rm -f "$OV/tree/workflow/projects/pf.yaml.bak"
git -C "$OV" add -A; git -C "$OV" -c user.email=t@t -c user.name=t commit -qm v2 >/dev/null 2>&1
run_overlay "$CON" sync pf --yes
assert_rc "re-sync after a source change succeeds" 0
assert_grep "source change (rename) applied" "$CON/workflow/projects/pf.yaml" "PF-RENAMED"
assert_grep "override 31415926 STILL preserved across a source change" "$CON/workflow/projects/pf.yaml" "31415926"

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
    and chk(b"  totp_secret: JBSWY3DPEHPK3PXP\n")   # totp_secret key (widened dict)
    and chk(b"  mfa_seed: ABCDEF1234567890\n")      # mfa_seed key (widened dict)
    and chk(b"  conn: Endpoint=x;AccountKey=A1B2C3D4E5F6+/aBcD1234eFgH==;\n")  # Azure conn-string
)
passes = (
    not chk(b'  api_key: "${ELASTIC_API_KEY}"\n')   # ${var} reference
    and not chk(b"  token: keychain://acct/x\n")        # URI reference
    and not chk(b"  # secret: SOME_NAME in a comment\n") # comment, not an assignment
    and not chk(b"  note: see Token: ephemeral zone\n")  # prose, not an assignment
)
# code-aware: the key=value heuristic does not run on code files (it would
# false-positive on `api_key = get_key()`), but the format scan still does.
codechk = lambda b, d: bool(m.leak_check(b, "org", d))
code_ok = (
    not codechk(b"api_key = os.environ.get('X')\n", "s.py")        # code: function call
    and not codechk(b"token = fetch_token(args.hf_token)\n", "s.py")  # code: function call
    and codechk(b'aws = "AKIA1234567890ABCDEF"\n', "s.py")         # format secret in CODE still caught
    and codechk(b"api_key: realLiteralValue123\n", "c.yaml")       # config literal still caught
)
print("OK" if (refused and passes and code_ok) else "FAIL")
PY
)"
assert_eq "all-caps secrets refused; URI/\${}/comment/prose pass" "$SECCHK" "OK"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 18. wildcard [*] override never cross-wires on a roster reorder ──"
CON="$(mkcon)"
OV="$(mktemp -d "$TMP/ovwild.XXXXXX")"
mkdir -p "$OV/tree/identity/mandants"
cat > "$OV/overlay.manifest.yaml" <<'YAML'
schema_version: 1
overlay:
  name: wl
  org: wl
defaults:
  scope: org
  source_root: "tree/"
  on_conflict: prompt
selection:
  include: ["**"]
  exclude: ["**/_*.yaml", "**/README.md"]
files:
  - dest: identity/mandants/team.yaml
    kind: config
    prompt_fields:
      - path: "$.persons[*].channels.email"
        reason: "recipient emails"
        pii: true
YAML
cat > "$OV/tree/identity/mandants/team.yaml" <<'YAML'
scope: org
persons:
  - name: Lead
    channels:
      email: lead-SRC@org.test
  - name: Dev
    channels:
      email: dev-SRC@org.test
YAML
git_overlay "$OV" wl-init
# interactive add overrides BOTH emails (PII wildcard → one prompt per person)
OUT="$(printf 'lead-REAL@org.test\ndev-REAL@org.test\n' | python3 "$OVERLAY" --repo-root "$CON" add "file://$OV" --name wl 2>&1)"; RC=$?
assert_rc "add with wildcard PII overrides succeeds" 0
assert_grep "Lead override materialized" "$CON/identity/mandants/team.yaml" "lead-REAL@org.test"
# upstream REORDERS the roster (Dev first), then a non-interactive re-sync
cat > "$OV/tree/identity/mandants/team.yaml" <<'YAML'
scope: org
persons:
  - name: Dev
    channels:
      email: dev-SRC@org.test
  - name: Lead
    channels:
      email: lead-SRC@org.test
YAML
git -C "$OV" add -A; git -C "$OV" -c user.email=t@t -c user.name=t commit -qm reorder >/dev/null 2>&1
run_overlay "$CON" sync wl --yes
assert_rc "re-sync after a roster reorder succeeds" 0
# the override must NEVER land on the wrong person (no positional cross-wire)
XW="$(python3 - "$CON/identity/mandants/team.yaml" <<'PY'
import yaml, sys
d = yaml.safe_load(open(sys.argv[1]))
by = {p["name"]: p["channels"]["email"] for p in d["persons"]}
print("CROSS-WIRED" if ("lead-REAL" in by.get("Dev", "") or "dev-REAL" in by.get("Lead", "")) else "SAFE")
PY
)"
assert_eq "wildcard override never cross-wires to the wrong person" "$XW" "SAFE"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 19. a scope:org skill ships COMPLETE (scripts inherit SKILL.md) ─"
CON="$(mkcon)"
OV="$(mktemp -d "$TMP/ovskill.XXXXXX")"
mkdir -p "$OV/tree/skills/demo-skill/scripts"
cat > "$OV/overlay.manifest.yaml" <<'YAML'
schema_version: 1
overlay:
  name: sk
  org: sk
defaults:
  scope: org
  source_root: "tree/"
  on_conflict: prompt
selection:
  include: ["**"]
  exclude: ["**/_*.yaml", "**/README.md"]
YAML
cat > "$OV/tree/skills/demo-skill/SKILL.md" <<'MD'
---
name: demo-skill
description: A demo skill for overlay testing.
metadata:
  scope: org
---
# Demo
MD
# a script with NO inline scope + a line that LOOKS like a secret assignment but
# is a function call (the leak gate must not false-positive on code).
cat > "$OV/tree/skills/demo-skill/scripts/run.py" <<'PY'
import os
api_key = os.environ.get("DEMO_API_KEY")
token = fetch_token(args.hf_token)
print(api_key, token)
PY
git_overlay "$OV" sk-init
run_overlay "$CON" add "file://$OV" --name sk
assert_rc "add a skill-with-scripts succeeds" 0
assert_out "add reports no refusals" "clean=2"
assert_file "SKILL.md materialized" "$CON/skills/demo-skill/SKILL.md"
assert_file "the skill SCRIPT materialized (inherits SKILL.md tier, not core-refused)" "$CON/skills/demo-skill/scripts/run.py"
assert_grep "script recorded in the lock" "$CON/overlays.lock.yaml" "skills/demo-skill/scripts/run.py"
assert_grep "skill carries scope:org" "$CON/skills/demo-skill/SKILL.md" "scope: org"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 20. overlay excludes managed dests via UNTRACKED .git/info/exclude ─"
CON="$(mkcon)"
OV="$(mktemp -d "$TMP/ovgi.XXXXXX")"
mkdir -p "$OV/tree/skills/demo-skill/scripts"
cat > "$OV/overlay.manifest.yaml" <<'YAML'
schema_version: 1
overlay:
  name: gi
  org: gi
defaults:
  scope: org
  source_root: "tree/"
  on_conflict: prompt
selection:
  include: ["**"]
  exclude: ["**/_*.yaml", "**/README.md"]
YAML
cat > "$OV/tree/skills/demo-skill/SKILL.md" <<'MD'
---
name: demo-skill
description: A demo skill.
metadata:
  scope: org
---
# Demo
MD
echo 'print("x")' > "$OV/tree/skills/demo-skill/scripts/run.py"
git_overlay "$OV" gi-init
run_overlay "$CON" add "file://$OV" --name gi
assert_rc "add succeeds" 0
assert_grep ".git/info/exclude carries the managed block" "$CON/.git/info/exclude" "overlay:gi"
assert_grep ".git/info/exclude lists the skill SKILL.md dest" "$CON/.git/info/exclude" "/skills/demo-skill/SKILL.md"
assert_grep ".git/info/exclude lists the skill SCRIPT dest" "$CON/.git/info/exclude" "/skills/demo-skill/scripts/run.py"
# git must ACTUALLY ignore the materialized skill → git add -A cannot stage it
if ( cd "$CON" && git check-ignore -q skills/demo-skill/scripts/run.py ); then
  pass "git ignores the materialized skill script (add -A can't publish org content)"
else
  fail "git does NOT ignore the materialized skill script — public-fork leak"
fi
# the guard touches NO tracked file: .gitignore is unchanged (no filename leak)
# AND the managed dests don't even show as untracked → add -A can't publish them
assert_nogrep ".gitignore (tracked) was NOT modified — no filename leak" "$CON/.gitignore" "overlay:gi"
if [ -z "$(cd "$CON" && git status --porcelain skills/ .claude/ 2>/dev/null)" ]; then
  pass "materialized skill/agent dests are excluded (git status shows nothing under them)"
else
  fail "materialized dests NOT excluded — would be staged: $(cd "$CON" && git status --porcelain skills/ | head -2 | tr '\n' '|')"
fi
# remove drops the managed block
run_overlay "$CON" remove gi
assert_rc "remove succeeds" 0
assert_nogrep "exclude block removed on remove" "$CON/.git/info/exclude" "overlay:gi"

# ───────────────────────────────────────────────────────────────────
echo
# ───────────────────────────────────────────────────────────────────
echo
echo "── 21. CORE-refusal is path-authoritative (inline scope can't smuggle CORE) ──"
# Unit-drive dest_refusal: a CORE-path dest carrying an inline `scope: org` line
# must STILL be refused — otherwise an overlay overwrites rules/, docs/, scripts/,
# CLAUDE.md, …  Frontmatter-bearing paths (skills/agents/identity) stay rescuable
# so a real org skill/agent still ships (skill-completeness, §19).
refusal() {  # <dest> <content> → prints the refusal reason, or ALLOWED
  python3 - "$ROOT" "$1" "$2" <<'PY'
import importlib.util, os, sys, tempfile
repo, dest, content = sys.argv[1], sys.argv[2], sys.argv[3].encode()
spec = importlib.util.spec_from_file_location("ov", os.path.join(repo, "scripts", "overlay.py"))
ov = importlib.util.module_from_spec(spec); spec.loader.exec_module(ov)
c = ov.Consumer(tempfile.mkdtemp())
print(ov.dest_refusal(dest, content, c, {"overlays": {}}, "t", 0) or "ALLOWED")
PY
}
CORE_REASON="classifies CORE (org overlays never ship CORE files)"
ORGFM="---
scope: org
---
x"
assert_eq "inline scope:org cannot smuggle a rules/ CORE file" "$(refusal "rules/git-hygiene.md" "$ORGFM")" "$CORE_REASON"
assert_eq "inline scope:org cannot smuggle CLAUDE.md"          "$(refusal "CLAUDE.md" "$ORGFM")"           "$CORE_REASON"
assert_eq "inline scope:org cannot smuggle the engine itself"  "$(refusal "scripts/overlay.py" "$ORGFM")"   "$CORE_REASON"
assert_eq "a scope:org SKILL.md still ships (carve-out, not over-refused)" "$(refusal "skills/bks-coordinator/SKILL.md" "---
metadata:
  scope: org
---
x")" "ALLOWED"
assert_eq "a scope:org sub-agent still ships (carve-out, not over-refused)" "$(refusal ".claude/agents/bks-coordinator.md" "$ORGFM")" "ALLOWED"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 22. ecosystem_fragment name guarded in-engine (no check-jsonschema dep) ──"
# The ^ecosystem.<org>.yaml$ name must be enforced even on a consumer WITHOUT the
# optional check-jsonschema — else a bad-named fragment is written at repo root and
# @import-wired into CLAUDE.md (instruction injection).
fragcheck() {  # <fragment-name> → REFUSED | OK
  python3 - "$ROOT" "$1" <<'PY'
import importlib.util, os, sys, tempfile
repo, frag = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("ov", os.path.join(repo, "scripts", "overlay.py"))
ov = importlib.util.module_from_spec(spec); spec.loader.exec_module(ov)
ov.shutil.which = lambda *_a, **_k: None   # simulate a consumer WITHOUT check-jsonschema
d = tempfile.mkdtemp()
with open(os.path.join(d, ov.MANIFEST_FILE), "w") as fh:
    fh.write("schema_version: 1\noverlay: {name: x, org: x}\n"
             f"ecosystem_fragment: {frag}\n")
try:
    ov.validate_manifest(d); print("OK")
except ov.OverlayError:
    print("REFUSED")
PY
}
assert_eq "a bad ecosystem_fragment name aborts even without check-jsonschema" "$(fragcheck "NOT-an-ecosystem.yaml")" "REFUSED"
assert_eq "a traversal ecosystem_fragment aborts even without check-jsonschema" "$(fragcheck "../escape.yaml")" "REFUSED"
assert_eq "a valid ecosystem.<org>.yaml fragment name still passes" "$(fragcheck "ecosystem.acme.yaml")" "OK"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 23. track_managed_dests opt-in — default off vs explicit on ─"
# 23a. default (unset) — byte-identical to today: exclude block written,
# managed dests git-ignored.
CON="$(mkcon)"
OV="$(mktemp -d "$TMP/ovtrk.XXXXXX")"
mkdir -p "$OV/tree/skills/demo-skill/scripts"
cat > "$OV/overlay.manifest.yaml" <<'YAML'
schema_version: 1
overlay:
  name: trk
  org: trk
defaults:
  scope: org
  source_root: "tree/"
  on_conflict: prompt
selection:
  include: ["**"]
  exclude: ["**/_*.yaml", "**/README.md"]
YAML
cat > "$OV/tree/skills/demo-skill/SKILL.md" <<'MD'
---
name: demo-skill
description: A demo skill.
metadata:
  scope: org
---
# Demo
MD
echo 'print("x")' > "$OV/tree/skills/demo-skill/scripts/run.py"
git_overlay "$OV" trk-init
run_overlay "$CON" add "file://$OV" --name trk
assert_rc "add (default, no flag) succeeds" 0
assert_grep ".git/info/exclude carries the managed block by default" "$CON/.git/info/exclude" "overlay:trk"
if ( cd "$CON" && git check-ignore -q skills/demo-skill/scripts/run.py ); then
  pass "default: git ignores the managed dest (byte-identical to prior behaviour)"
else
  fail "default: git unexpectedly does NOT ignore the managed dest"
fi

# 23b. --track-managed-dests at add time — no exclude block, dests are
# normal trackable files.
CON2="$(mkcon)"
run_overlay "$CON2" add "file://$OV" --name trk --track-managed-dests
assert_rc "add --track-managed-dests succeeds" 0
assert_nogrep ".git/info/exclude carries NO block when opted into tracking" "$CON2/.git/info/exclude" "overlay:trk"
if ( cd "$CON2" && git check-ignore -q skills/demo-skill/scripts/run.py ); then
  fail "opted-in: git still ignores the managed dest — switch had no effect"
else
  pass "opted-in: git does NOT ignore the managed dest (trackable)"
fi
if [ -n "$(cd "$CON2" && git status --porcelain skills/demo-skill/scripts/run.py 2>/dev/null)" ]; then
  pass "opted-in: managed dest shows as a normal untracked/addable file to git status"
else
  fail "opted-in: managed dest invisible to git status — still excluded"
fi
assert_grep "bridge-config.yaml records track_managed_dests: true" "$CON2/bridge-config.yaml" "track_managed_dests: true"

# 23c. flipping the switch on for an EXISTING (already-excluded) subscription
# cleans up the previously-written exclude block on the next sync — no manual
# .git/info/exclude edit required.
CON3="$(mkcon)"
run_overlay "$CON3" add "file://$OV" --name trk
assert_rc "add (default) for flip-test succeeds" 0
assert_grep "flip-test: exclude block present before the flip" "$CON3/.git/info/exclude" "overlay:trk"
python3 -c "
import yaml
p = '$CON3/bridge-config.yaml'
d = yaml.safe_load(open(p))
for u in d['upstreams']:
    if u.get('name') == 'trk':
        u['materialize']['track_managed_dests'] = True
yaml.safe_dump(d, open(p, 'w'), sort_keys=False, allow_unicode=True)
"
run_overlay "$CON3" sync trk --yes
assert_rc "sync after flipping track_managed_dests on succeeds" 0
assert_nogrep "flip-test: sync removed the stale exclude block" "$CON3/.git/info/exclude" "overlay:trk"
if ( cd "$CON3" && git check-ignore -q skills/demo-skill/scripts/run.py ); then
  fail "flip-test: dest still ignored after flipping the switch on"
else
  pass "flip-test: dest is trackable after flipping the switch on + sync"
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 24. large-prune guard — narrowed select never silently mass-deletes ─"
# Incident this codifies: narrowing bridge-config.yaml's materialize.select to
# isolate one new glob dropped every OTHER already-materialized file out of
# scope in the same edit — every one of them then reads as a clean orphan and
# (pre-fix) was unconditionally os.remove()'d, in BOTH interactive and --yes
# runs, with zero confirmation. Caught live only because a human read the
# config diff before the write landed. EX_DESTS has 7 files across 6 globs;
# narrowing select to just "skills/**" leaves 1 in scope and orphans the
# other 6 — one more than LARGE_PRUNE_THRESHOLD (5), so every path below must
# route through the guard, not the old unconditional-delete branch.
narrow_select() {  # <consumer-dir> <overlay-name> <glob>
  python3 -c "
import yaml
p = '$1/bridge-config.yaml'
d = yaml.safe_load(open(p))
for u in d['upstreams']:
    if u.get('name') == '$2':
        u['materialize']['select'] = ['$3']
yaml.safe_dump(d, open(p, 'w'), sort_keys=False, allow_unicode=True)
"
}

CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org
assert_rc "24 setup: add (full select) succeeds" 0
for d in $EX_DESTS; do assert_file "24 setup: $d materialized before narrowing" "$CON/$d"; done
narrow_select "$CON" example-org "skills/**"

# 24a. --dry-run surfaces the aggregate warning (no writes either way).
OUT="$(python3 "$OVERLAY" --repo-root "$CON" sync example-org --dry-run 2>&1)"; RC=$?
assert_rc "24a: dry-run with narrowed select succeeds" 0
assert_out "24a: dry-run warns about the large prune batch" "would be pruned as orphans"
for d in $EX_DESTS; do assert_file "24a: dry-run wrote nothing — $d still present" "$CON/$d"; done

# 24b. non-interactive (--yes) REFUSES the batch outright — nothing deleted.
run_overlay "$CON" sync example-org --yes
assert_rc "24b: non-interactive sync (narrowed select) still succeeds" 0
assert_out "24b: engine reports the batch as blocked" "BLOCKED"
for d in $EX_DESTS; do assert_file "24b: non-interactive sync kept $d (not deleted)" "$CON/$d"; done
lockcount="$(python3 -c 'import yaml,sys;d=yaml.safe_load(open(sys.argv[1]));print(len((d.get("overlays") or {}).get("example-org",{}).get("files") or []))' "$CON/overlays.lock.yaml")"
# 7 tree files plus the ecosystem fragment: `select:` narrows the tree, not the
# fragment, so its entry stays alongside the six blocked orphans (§25).
assert_eq "24b: lock still carries all 7 file entries + the fragment (identity preserved)" "$lockcount" 8

# 24c. interactive + decline ("n") — same as 24b, nothing deleted.
OUT="$(printf 'n\n' | python3 "$OVERLAY" --repo-root "$CON" sync example-org 2>&1)"; RC=$?
assert_rc "24c: interactive sync (declined) succeeds" 0
assert_out "24c: engine reports the batch kept" "KEPT"
for d in $EX_DESTS; do assert_file "24c: declined confirmation kept $d" "$CON/$d"; done

# 24d. interactive + confirm ("y") — the batch, and ONLY the batch, deletes.
OUT="$(printf 'y\n' | python3 "$OVERLAY" --repo-root "$CON" sync example-org 2>&1)"; RC=$?
assert_rc "24d: interactive sync (confirmed) succeeds" 0
assert_file "24d: in-scope file survives (still selected)" "$CON/skills/example-org-coordinator/SKILL.md"
for d in $EX_DESTS; do
  case "$d" in
    skills/example-org-coordinator/SKILL.md) ;;
    *) assert_absent "24d: confirmed prune removed $d" "$CON/$d" ;;
  esac
done

# ───────────────────────────────────────────────────────────────────
echo
echo "── 25. ecosystem fragment is a managed file, local edits survive ──"
# Codifies a live loss: a consumer had added one repo to its
# ecosystem.<org>.yaml by hand, and the next routine sync rewrote the file from
# the overlay. Step 13 copied the fragment verbatim on every run, with no lock
# entry, no 3-way merge and no line in diff or --dry-run, and `remove` deleted it
# without a hash check. The fragment now runs through the same plan as every
# other managed file.
FRAG="ecosystem.example-org.yaml"
sha_of() { python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }
lock_sha() {  # <consumer> <dest> → materialized_sha256 in the example-org lock entry, NONE, or ABSENT
  python3 - "$1/overlays.lock.yaml" "$2" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1])) or {}
files = (d.get("overlays") or {}).get("example-org", {}).get("files") or []
f = next((f for f in files if f.get("dest") == sys.argv[2]), None)
print("NONE" if f is None else (f.get("materialized_sha256") or "ABSENT"))
PY
}
plan_line() { printf '%s\n' "$OUT" | grep -F " $1" | head -1; }   # <dest> → its line in a rendered plan
commit_ov() { git -C "$1" add -A; git -C "$1" -c user.email=t@t -c user.name=t commit -qm "$2" >/dev/null 2>&1; }
drop_frag_from_lock() {  # <consumer>: rewrite the lock the way the pre-fix engine left it
  python3 - "$1/overlays.lock.yaml" "$FRAG" <<'PY'
import sys, yaml
p, frag = sys.argv[1], sys.argv[2]
d = yaml.safe_load(open(p))
e = d["overlays"]["example-org"]
e.pop("fragment_managed", None)
e["files"] = [f for f in e["files"] if f.get("dest") != frag]
yaml.safe_dump(d, open(p, "w"), sort_keys=False, allow_unicode=True)
PY
}
LOCAL_OLD='display_name: "Example Org"'
LOCAL_NEW='display_name: "Example Org"  # LOCAL-FRAGMENT-EDIT'
UP_OLD='description: "Example storefront"'
UP_NEW='description: "UPSTREAM-FRAGMENT-EDIT"'

# 25a. add copies the fragment byte for byte and records it in the lock. The
# example's header mentions `scope: org`, which would hide an injected scope
# line from this check, so that mention is stripped from the source first.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
edit_line "$OV/$FRAG" "(scope: org)" ""; commit_ov "$OV" frag-no-scope-mention
run_overlay "$CON" add "file://$OV" --name example-org
assert_rc "25a: add succeeds" 0
assert_eq "25a: the fragment arrives byte for byte (no scope tripwire, no prompt-fields)" "$(sha_of "$CON/$FRAG")" "$(sha_of "$OV/$FRAG")"
assert_eq "25a: the lock carries the fragment with the hash as written" "$(lock_sha "$CON" "$FRAG")" "$(sha_of "$CON/$FRAG")"

# 25b. a local edit is visible to diff and --dry-run, and a sync keeps it.
edit_line "$CON/$FRAG" "$LOCAL_OLD" "$LOCAL_NEW"
OUT="$(python3 "$OVERLAY" --repo-root "$CON" diff example-org 2>&1)"
case "$(plan_line "$FRAG")" in *local-edit*) pass "25b: diff lists the edited fragment as local-edit" ;; *) fail "25b: diff does not list the edited fragment as local-edit" "$OUT" ;; esac
OUT="$(python3 "$OVERLAY" --repo-root "$CON" sync example-org --dry-run 2>&1)"
case "$(plan_line "$FRAG")" in *local-edit*) pass "25b: sync --dry-run lists it as well" ;; *) fail "25b: sync --dry-run does not list the edited fragment" "$OUT" ;; esac
touch -t 202001010000 "$CON/$FRAG"
run_overlay "$CON" sync example-org --yes
assert_rc "25b: sync over an edited fragment succeeds" 0
assert_grep "25b: the local fragment edit survives the sync" "$CON/$FRAG" "LOCAL-FRAGMENT-EDIT"
# The merge changed nothing, so the file must not be rewritten: an untouched
# mtime is the observable difference between "kept" and "written again".
fmtime="$(python3 -c 'import os,sys,time;print(time.strftime("%Y",time.localtime(os.stat(sys.argv[1]).st_mtime)))' "$CON/$FRAG")"
assert_eq "25b: a merge that changes nothing does not rewrite the file" "$fmtime" "2020"

# 25c. ... and the NEXT sync, when the overlay changes a different line. The
# trap: recording the merged bytes as `materialized_sha256` makes the edited
# file look pristine, so the next upstream change lands as a clean overwrite.
# NONE/ABSENT count as failures: a fragment missing from the lock is not
# "not laundered", it is not tracked at all, and must not pass this row.
fl_sha="$(lock_sha "$CON" "$FRAG")"; live_sha="$(sha_of "$CON/$FRAG")"
if [ "$fl_sha" = "NONE" ] || [ "$fl_sha" = "ABSENT" ]; then fail "25c: the fragment has no lock hash to compare ($fl_sha)"
elif [ "$fl_sha" = "$live_sha" ]; then fail "25c: the merged edit was laundered into the lock"
else pass "25c: the merged edit is not laundered into the lock"; fi
edit_line "$OV/$FRAG" "$UP_OLD" "$UP_NEW"; commit_ov "$OV" frag-v2
run_overlay "$CON" sync example-org --yes
assert_rc "25c: sync with an upstream fragment change succeeds" 0
assert_grep "25c: the local edit survives the second sync" "$CON/$FRAG" "LOCAL-FRAGMENT-EDIT"
assert_grep "25c: the upstream change is merged in" "$CON/$FRAG" "UPSTREAM-FRAGMENT-EDIT"

# 25d. the same rule for a tree file: a merged edit survives the next upstream change.
TARGET="$CON/workflow/contexts/example-docs.yaml"
edit_line "$TARGET" "default_mandant: example-team" "default_mandant: example-team  # TREE-LOCAL"
run_overlay "$CON" sync example-org --yes
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" 'description: "Documentation + routing context for the example-org engagement"' 'description: "TREE-UPSTREAM"'
commit_ov "$OV" tree-v2
run_overlay "$CON" sync example-org --yes
assert_rc "25d: second sync over a merged tree edit succeeds" 0
assert_grep "25d: a tree file's local edit survives two syncs" "$TARGET" "TREE-LOCAL"
assert_grep "25d: and the later upstream change is merged in" "$TARGET" "TREE-UPSTREAM"

# 25e. a same-line conflict keeps the local side, without markers.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
edit_line "$CON/$FRAG" "$UP_OLD" 'description: "LOCAL-FRAGMENT-CONFLICT"'
edit_line "$OV/$FRAG" "$UP_OLD" 'description: "UPSTREAM-FRAGMENT-CONFLICT"'; commit_ov "$OV" frag-conflict
run_overlay "$CON" sync example-org --yes
assert_rc "25e: sync with a conflicting fragment change succeeds" 0
assert_out "25e: the conflict is reported" "conflict"
assert_grep "25e: the local side of the fragment is kept" "$CON/$FRAG" "LOCAL-FRAGMENT-CONFLICT"
assert_nogrep "25e: no merge markers land in the fragment" "$CON/$FRAG" "<<<<<<<"

# 25f. remove keeps an edited fragment (a clean one is deleted, §7).
run_overlay "$CON" remove example-org
assert_rc "25f: remove succeeds" 0
assert_grep "25f: remove keeps a locally-edited fragment" "$CON/$FRAG" "LOCAL-FRAGMENT-CONFLICT"

# 25g. a lock written by the pre-fix engine has no fragment entry. The first
# sync adopts the fragment without clobbering an edit made under that lock.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
drop_frag_from_lock "$CON"
edit_line "$CON/$FRAG" "$LOCAL_OLD" "$LOCAL_NEW"
edit_line "$OV/$FRAG" "$UP_OLD" "$UP_NEW"; commit_ov "$OV" frag-v2
run_overlay "$CON" sync example-org --yes
assert_rc "25g: sync over a pre-fix lock succeeds" 0
assert_grep "25g: an edit under the pre-fix lock survives adoption" "$CON/$FRAG" "LOCAL-FRAGMENT-EDIT"
assert_grep "25g: the upstream change still arrives" "$CON/$FRAG" "UPSTREAM-FRAGMENT-EDIT"
assert_neq "25g: the fragment is in the lock afterwards" "$(lock_sha "$CON" "$FRAG")" "NONE"

# 25h. an untouched fragment under a pre-fix lock simply takes the upstream change.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
drop_frag_from_lock "$CON"
edit_line "$OV/$FRAG" "$UP_OLD" "$UP_NEW"; commit_ov "$OV" frag-v2
OUT="$(python3 "$OVERLAY" --repo-root "$CON" sync example-org --dry-run 2>&1)"
case "$(plan_line "$FRAG")" in *upstream-ahead*) pass "25h: the adopted fragment plans as upstream-ahead" ;; *) fail "25h: the adopted fragment does not plan as upstream-ahead" "$OUT" ;; esac
run_overlay "$CON" sync example-org --yes
assert_rc "25h: sync over a pre-fix lock (untouched fragment) succeeds" 0
assert_grep "25h: an untouched fragment takes the upstream change" "$CON/$FRAG" "UPSTREAM-FRAGMENT-EDIT"

# 25i. remove under a pre-fix lock keeps an edited fragment as well.
edit_line "$CON/$FRAG" "$LOCAL_OLD" "$LOCAL_NEW"
drop_frag_from_lock "$CON"
run_overlay "$CON" remove example-org
assert_rc "25i: remove under a pre-fix lock succeeds" 0
assert_grep "25i: remove under a pre-fix lock keeps an edited fragment" "$CON/$FRAG" "LOCAL-FRAGMENT-EDIT"
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
drop_frag_from_lock "$CON"
run_overlay "$CON" remove example-org
assert_rc "25i: remove under a pre-fix lock (clean fragment) succeeds" 0
assert_absent "25i: remove under a pre-fix lock deletes a clean fragment" "$CON/$FRAG"

# 25k. the pinned blob can be gone (a force-pushed overlay, a re-cloned cache).
# Adoption must still not fall back to user-owned, which a non-interactive sync
# skips on every run, so the fragment would never be updated again.
zero_pin() {  # <consumer>: point the lock at a commit the cache does not have
  python3 - "$1/overlays.lock.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p))
d["overlays"]["example-org"]["resolved_sha"] = "0" * 40
yaml.safe_dump(d, open(p, "w"), sort_keys=False, allow_unicode=True)
PY
}
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
drop_frag_from_lock "$CON"; zero_pin "$CON"
OUT="$(python3 "$OVERLAY" --repo-root "$CON" sync example-org --dry-run 2>&1)"
case "$(plan_line "$FRAG")" in *" skip "*) pass "25k: an untouched fragment plans as skip without the pinned blob" ;; *) fail "25k: an untouched fragment does not plan as skip without the pinned blob" "$OUT" ;; esac
run_overlay "$CON" sync example-org --yes
assert_rc "25k: sync with the pinned blob gone succeeds" 0
assert_neq "25k: and it is in the lock afterwards" "$(lock_sha "$CON" "$FRAG")" "NONE"
drop_frag_from_lock "$CON"; zero_pin "$CON"
edit_line "$CON/$FRAG" "$LOCAL_OLD" "$LOCAL_NEW"
edit_line "$OV/$FRAG" "$UP_OLD" "$UP_NEW"; commit_ov "$OV" frag-v2
OUT="$(python3 "$OVERLAY" --repo-root "$CON" sync example-org --dry-run 2>&1)"
case "$(plan_line "$FRAG")" in *local-edit*) pass "25k: an edited fragment plans as local-edit without the pinned blob" ;; *) fail "25k: an edited fragment does not plan as local-edit without the pinned blob" "$OUT" ;; esac
run_overlay "$CON" sync example-org --yes
assert_rc "25k: sync over an edited fragment without the pinned blob succeeds" 0
assert_out "25k: and the unresolvable merge is reported" "conflict"
assert_grep "25k: the edit is kept, never overwritten" "$CON/$FRAG" "LOCAL-FRAGMENT-EDIT"
# The kept fragment needs a hash in the lock (the schema requires one), and it
# must not be the live file's, or the edit would read as pristine.
fl_sha="$(lock_sha "$CON" "$FRAG")"; live_sha="$(sha_of "$CON/$FRAG")"
if [ "$fl_sha" = "NONE" ] || [ "$fl_sha" = "ABSENT" ]; then fail "25k: the kept fragment has no lock hash ($fl_sha)"
elif [ "$fl_sha" = "$live_sha" ]; then fail "25k: the kept fragment was laundered into the lock"
else pass "25k: the kept fragment carries a lock hash that is not the live file's"; fi
OUT="$(check-jsonschema --schemafile "$ROOT/docs/schemas/overlays-lock.schema.yaml" "$CON/overlays.lock.yaml" 2>&1)"; RC=$?
assert_rc "25k: the lock after adoption schema-validates" 0
# Not stuck: a later upstream change on another line merges in, the edit stays.
edit_line "$OV/$FRAG" "number: 1" "number: 7  # UPSTREAM-THIRD-EDIT"; commit_ov "$OV" frag-v3
run_overlay "$CON" sync example-org --yes
assert_rc "25k: the next sync after adoption succeeds" 0
assert_grep "25k: the next upstream change arrives" "$CON/$FRAG" "UPSTREAM-THIRD-EDIT"
assert_grep "25k: and the edit is still kept" "$CON/$FRAG" "LOCAL-FRAGMENT-EDIT"

# 25j. an overlay that stops shipping its fragment prunes a clean copy and drops
# the @import, so CLAUDE.md never points at a file that is gone.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
python3 - "$OV/overlay.manifest.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p))
d.pop("ecosystem_fragment", None)
yaml.safe_dump(d, open(p, "w"), sort_keys=False, allow_unicode=True)
PY
git -C "$OV" rm -q "$FRAG"; commit_ov "$OV" drop-fragment
run_overlay "$CON" sync example-org --yes
assert_rc "25j: sync after the overlay drops its fragment succeeds" 0
assert_absent "25j: the clean fragment is pruned" "$CON/$FRAG"
assert_nogrep "25j: and its @import is dropped from CLAUDE.md" "$CON/CLAUDE.md" "@$FRAG"

# 25l. a registry the consumer had before subscribing stays the consumer's. The
# lock then has no fragment entry, exactly like a pre-fix lock, and adopting it
# would merge overlay lines into the consumer's own file. The overlay says
# on_conflict: skip, so add leaves the existing file alone (run_overlay answers
# every prompt with y, which would otherwise take the overlay's copy).
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
edit_line "$OV/overlay.manifest.yaml" "on_conflict: prompt" "on_conflict: skip"; commit_ov "$OV" skip-policy
printf 'own_registry:\n  note: OWN-REGISTRY\n' > "$CON/$FRAG"
own_sha="$(sha_of "$CON/$FRAG")"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
edit_line "$OV/$FRAG" "$UP_OLD" "$UP_NEW"; commit_ov "$OV" frag-v2
OUT="$(python3 "$OVERLAY" --repo-root "$CON" sync example-org --dry-run 2>&1)"
case "$(plan_line "$FRAG")" in *user-owned*) pass "25l: the consumer's own registry plans as user-owned" ;; *) fail "25l: the consumer's own registry does not plan as user-owned" "$OUT" ;; esac
run_overlay "$CON" sync example-org --yes
assert_rc "25l: sync over the consumer's own registry succeeds" 0
assert_eq "25l: the consumer's own registry is untouched by the sync" "$(sha_of "$CON/$FRAG")" "$own_sha"
run_overlay "$CON" remove example-org
assert_rc "25l: remove succeeds" 0
assert_eq "25l: remove leaves the consumer's own registry alone" "$(sha_of "$CON/$FRAG")" "$own_sha"
# an own copy identical to the overlay's is still the consumer's: remove keeps it
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
edit_line "$OV/overlay.manifest.yaml" "on_conflict: prompt" "on_conflict: skip"; commit_ov "$OV" skip-policy
cp "$OV/$FRAG" "$CON/$FRAG"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
run_overlay "$CON" remove example-org
assert_file "25l: remove leaves an own copy identical to the overlay's alone" "$CON/$FRAG"

# 25m. an overlay that also ships the fragment under tree/ plans it as a tree
# file, and the @import must still be wired.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
cp "$OV/$FRAG" "$OV/tree/$FRAG"; commit_ov "$OV" frag-in-tree
run_overlay "$CON" add "file://$OV" --name example-org
assert_rc "25m: add with the fragment also under tree/ succeeds" 0
assert_grep "25m: the @import is wired" "$CON/CLAUDE.md" "@$FRAG"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 26. unattended sync (#218) ──────────────────────────────────"
# `sync --unattended` is what the scheduled job runs. It applies an overlay only
# when the whole plan needs nobody: a predicted conflict or a planned deletion
# HOLDS the overlay (nothing written, lock pin unchanged), because a plain
# `sync --yes` keeps the local side of a conflict AND advances the pin, and from
# the next run on the file reads as an ordinary local edit: the upstream change
# is lost and no signal says so any more. New behavioural files stay pending
# (never auto-approved), the rest applies. `status` shows the last run.
lock_pin() { python3 - "$1/overlays.lock.yaml" <<'PY'
import sys, yaml
print(((yaml.safe_load(open(sys.argv[1])) or {}).get("overlays") or {}).get("example-org", {}).get("resolved_sha", ""))
PY
}
set_interval() { python3 - "$1/bridge-config.yaml" "$2" <<'PY'
import sys, yaml
p, n = sys.argv[1], int(sys.argv[2])
d = yaml.safe_load(open(p))
for u in d.get("upstreams") or []:
    if u.get("role") == "org-overlay":
        u["pull_interval_days"] = n
yaml.safe_dump(d, open(p, "w"), sort_keys=False, allow_unicode=True)
PY
}
unattended() { OUT="$(python3 "$OVERLAY" --repo-root "$1" sync --unattended </dev/null 2>&1)"; RC=$?; }
CTX_OLD='description: "Documentation + routing context for the example-org engagement"'
NEWCTX=workflow/contexts/example-new.yaml

# 26a. a new file and an upstream change arrive unattended.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
run_overlay "$CON" status example-org
assert_out "26a: status before any unattended run says never" "last unattended: never"
sed 's/id: example-docs/id: example-new/' "$OV/tree/workflow/contexts/example-docs.yaml" > "$OV/tree/$NEWCTX"
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "UPSTREAM-V2"'
commit_ov "$OV" v2
unattended "$CON"
assert_rc "26a: unattended sync succeeds" 0
assert_out "26a: reports applied" "unattended example-org: applied"
assert_file "26a: the new file is materialized" "$CON/$NEWCTX"
assert_grep "26a: the upstream change is applied" "$CON/workflow/contexts/example-docs.yaml" "UPSTREAM-V2"
assert_eq "26a: the lock pin advances to the overlay HEAD" "$(lock_pin "$CON")" "$(git -C "$OV" rev-parse HEAD)"
run_overlay "$CON" status example-org
assert_out "26a: status shows the last unattended run and its outcome" "applied"

# 26b. an interval that has not elapsed: nothing is fetched or written.
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" 'description: "UPSTREAM-V2"' 'description: "UPSTREAM-V3"'
commit_ov "$OV" v3
unattended "$CON"
assert_rc "26b: a run inside the interval succeeds" 0
assert_out "26b: reports not-due" "unattended example-org: not-due"
assert_nogrep "26b: nothing applied inside the interval" "$CON/workflow/contexts/example-docs.yaml" "UPSTREAM-V3"
run_overlay "$CON" status example-org
assert_out "26b: a not-due run does not replace the last real outcome" "applied"
set_interval "$CON" 0
unattended "$CON"
assert_out "26b: interval 0 makes every run due" "unattended example-org: applied"
assert_grep "26b: and the change lands" "$CON/workflow/contexts/example-docs.yaml" "UPSTREAM-V3"

# 26c. a conflict with a local edit holds the WHOLE overlay and stays held.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
set_interval "$CON" 0
pin0="$(lock_pin "$CON")"
T="$CON/workflow/contexts/example-docs.yaml"
edit_line "$T" "$CTX_OLD" 'description: "LOCAL-CONFLICT"'
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "UPSTREAM-CONFLICT"'
sed 's/id: example-docs/id: example-new/' "$OV/tree/workflow/contexts/example-docs.yaml" > "$OV/tree/$NEWCTX"
commit_ov "$OV" conflict
unattended "$CON"
assert_rc "26c: a held run is not a failure" 0
assert_out "26c: reports held" "unattended example-org: held"
assert_out "26c: names the conflicting file" "conflict: workflow/contexts/example-docs.yaml"
assert_grep "26c: the local edit is intact" "$T" "LOCAL-CONFLICT"
assert_nogrep "26c: no conflict markers written" "$T" "<<<<<<<"
assert_absent "26c: nothing else from the held overlay is applied either" "$CON/$NEWCTX"
assert_eq "26c: the lock pin does not advance" "$(lock_pin "$CON")" "$pin0"
unattended "$CON"
assert_out "26c: the next run is still held (the conflict is not laundered away)" "conflict: workflow/contexts/example-docs.yaml"
run_overlay "$CON" status example-org
assert_out "26c: status shows the held run" "held"

# 26d. a local edit that merges cleanly is not a reason to hold.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
T="$CON/workflow/contexts/example-docs.yaml"
edit_line "$T" "default_mandant: example-team" "default_mandant: example-team  # CONSUMER-LINE"
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "UPSTREAM-LINE"'
commit_ov "$OV" disjoint
unattended "$CON"
assert_out "26d: a clean merge applies" "unattended example-org: applied"
assert_grep "26d: the consumer's line is kept" "$T" "CONSUMER-LINE"
assert_grep "26d: the upstream line is merged in" "$T" "UPSTREAM-LINE"

# 26e. a new behavioural file is never approved unattended; the rest applies.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
mkdir -p "$OV/tree/skills/example-new-skill"
sed 's/example-org-coordinator/example-new-skill/' "$OV/tree/skills/example-org-coordinator/SKILL.md" > "$OV/tree/skills/example-new-skill/SKILL.md"
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "UPSTREAM-BESIDE-SKILL"'
commit_ov "$OV" new-skill
unattended "$CON"
assert_out "26e: applies the rest" "unattended example-org: applied"
# on the summary line, not anywhere: the engine's own SKIP line names the file too
case "$(printf '%s\n' "$OUT" | grep '^unattended example-org:')" in
  *"pending: skills/example-new-skill/SKILL.md"*) pass "26e: the summary names the pending behavioural file" ;;
  *) fail "26e: the summary does not name the pending behavioural file" "$OUT" ;;
esac
assert_absent "26e: the new skill is not installed" "$CON/skills/example-new-skill/SKILL.md"
assert_grep "26e: the config change beside it is applied" "$CON/workflow/contexts/example-docs.yaml" "UPSTREAM-BESIDE-SKILL"

# 26f. a planned deletion holds the overlay; the file stays.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
git -C "$OV" rm -q tree/identity/mandants/example-team.yaml; commit_ov "$OV" drop-mandant
unattended "$CON"
assert_out "26f: a planned deletion holds" "unattended example-org: held"
assert_out "26f: names the file it would delete" "identity/mandants/example-team.yaml"
assert_file "26f: the file stays" "$CON/identity/mandants/example-team.yaml"

# 26g. an unreachable overlay is a failure, recorded, and exits non-zero.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
rm -rf "$CON/.bridge/overlays/example-org" "$OV"
unattended "$CON"
assert_rc "26g: an unreachable overlay fails" 1
assert_out "26g: reports failed" "unattended example-org: failed"
run_overlay "$CON" status example-org
assert_out "26g: status shows the failed run" "failed"

# 26h. the scheduled wrapper: report, notification on change only.
# The consumer fixture is `git archive HEAD`, so copy the WORKING-TREE engine
# and wrapper in; otherwise this section tests the last commit.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
cp "$ROOT/scripts/overlay.py" "$ROOT/scripts/overlay-autosync.sh" "$CON/scripts/"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
set_interval "$CON" 0
FAKEBIN="$TMP/fakebin"; mkdir -p "$FAKEBIN"; SENT="$TMP/signal-sent.log"; : > "$SENT"
printf '#!/bin/sh\necho "$@" >> "%s"\n' "$SENT" > "$FAKEBIN/signal-cli"; chmod +x "$FAKEBIN/signal-cli"
autosync() { OUT="$(PATH="$FAKEBIN:$PATH" SIGNAL_ACCOUNT=+1 SIGNAL_RECIPIENT=+2 bash "$CON/scripts/overlay-autosync.sh" </dev/null 2>&1)"; RC=$?; }
edit_line "$CON/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "LOCAL-CONFLICT"'
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "UPSTREAM-CONFLICT"'
commit_ov "$OV" conflict
autosync
assert_rc "26h: the wrapper exits 0 on a held overlay" 0
assert_grep "26h: the report says held" "$CON/work/overlay-status.md" "held"
assert_grep "26h: the report names the conflict" "$CON/work/overlay-status.md" "workflow/contexts/example-docs.yaml"
assert_grep "26h: a held overlay notifies" "$SENT" "held"
n1="$(wc -l < "$SENT" | tr -d ' ')"
autosync
assert_eq "26h: the same held outcome does not notify again" "$(wc -l < "$SENT" | tr -d ' ')" "$n1"
edit_line "$CON/workflow/contexts/example-docs.yaml" 'description: "LOCAL-CONFLICT"' 'description: "UPSTREAM-CONFLICT"'
autosync
assert_grep "26h: once resolved the report says applied" "$CON/work/overlay-status.md" "applied"

# 26i. one install step schedules it (rendered, not loaded: no launchd in CI).
# Sandboxed twice over: HOME points into $TMP and `launchctl` is a recorder, so
# an installer that ignored --print could still never register a real job.
# (The first red run of this section did exactly that against the real HOME.)
mkdir -p "$TMP/home"; LREC="$TMP/launchctl.log"; : > "$LREC"
printf '#!/bin/sh\necho "$@" >> "%s"\n' "$LREC" > "$FAKEBIN/launchctl"; chmod +x "$FAKEBIN/launchctl"
installer() { OUT="$(HOME="$TMP/home" PATH="$FAKEBIN:$PATH" bash "$ROOT/scripts/install-upstream-autoupdate.sh" "$@" </dev/null 2>&1)"; RC=$?; }
installer --overlays --print
assert_rc "26i: installer --overlays --print succeeds" 0
assert_out "26i: the job runs overlay-autosync.sh" "scripts/overlay-autosync.sh"
assert_out "26i: under its own label" "com.openbridge.overlay-autosync"
installer --print
assert_out "26i: without --overlays the CORE job is unchanged" "scripts/upstream-autoupdate.sh"
assert_eq "26i: --print never calls launchctl" "$(wc -c < "$LREC" | tr -d ' ')" "0"
assert_absent "26i: --print writes no plist" "$TMP/home/Library/LaunchAgents"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 27. the behavioural gate is one answer per skill folder ─────"
# A skill is a folder, not a file: SKILL.md routes into its references/. The
# gate used to ask per file, so a run without a person skipped a NEW reference
# while it applied the SKILL.md that points at it, leaving a half skill, and
# `status` reported upstream-ahead=0 because a never-written file is in no
# count. Now the folder is confirmed all or none, a non-interactive run holds
# back the WHOLE folder, and `status` counts what waits as pending-confirm.
SK=skills/example-org-coordinator
REF="$SK/references/costs.md"
run_overlay_n() {  # like run_overlay, but answers every prompt with n
  local con="$1"; shift
  OUT="$(yes n | python3 "$OVERLAY" --repo-root "$con" "$@" 2>&1)"
  RC=$?
}
mk_ref_change() {  # <overlay>: a new reference plus the SKILL.md line routing to it
  mkdir -p "$1/tree/$SK/references"
  printf '# Costs\n\nRead this when costs come up.\n' > "$1/tree/$REF"
  printf '\nCosts: see references/costs.md (UPSTREAM-ROUTE).\n' >> "$1/tree/$SK/SKILL.md"
  commit_ov "$1" ref-change
}

# 27a. non-interactive: the whole folder is withheld, the rest applies.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
mk_ref_change "$OV"
edit_line "$OV/tree/workflow/contexts/example-docs.yaml" "$CTX_OLD" 'description: "UPSTREAM-BESIDE-REF"'
commit_ov "$OV" ctx-beside-ref
run_overlay "$CON" sync example-org --yes
assert_rc "27a: sync --yes succeeds" 0
assert_absent "27a: the new reference is not written" "$CON/$REF"
assert_nogrep "27a: the SKILL.md routing to it is held back too" "$CON/$SK/SKILL.md" "UPSTREAM-ROUTE"
assert_out "27a: the folder is named as withheld" "WITHHELD $SK/"
assert_out "27a: the summary counts the withheld files" "withheld=2"
assert_grep "27a: the config change beside it is applied" "$CON/workflow/contexts/example-docs.yaml" "UPSTREAM-BESIDE-REF"

# 27b. status says so: never upstream-ahead=0 while something waits.
run_overlay "$CON" status example-org
assert_out "27b: status counts the files waiting for [y]" "pending-confirm=2"
assert_out "27b: and they are upstream-ahead, not invisible" "upstream-ahead=2"
assert_out "27b: status names the withheld folder" "$SK/"
JSON="$(python3 "$OVERLAY" --repo-root "$CON" status example-org --json 2>/dev/null)"
case "$JSON" in
  *'"withheld"'*"$SK/"*) pass "27b: --json carries the withheld folder" ;;
  *) fail "27b: --json lacks the withheld folder" "$JSON" ;;
esac

# 27c. a declined folder writes none of its files.
run_overlay_n "$CON" sync example-org
assert_absent "27c: declined: the reference is not written" "$CON/$REF"
assert_nogrep "27c: declined: SKILL.md is not updated either" "$CON/$SK/SKILL.md" "UPSTREAM-ROUTE"
assert_out "27c: declined is reported for the folder" "declined at behavioural gate"

# 27d. one [y] for the folder writes all of it, and status is clear again.
run_overlay "$CON" sync example-org
n_prompts="$(printf '%s' "$OUT" | grep -c 'Materialize skill folder')" || true
assert_eq "27d: one prompt for the whole folder" "$n_prompts" "1"
assert_file "27d: confirmed: the reference is written" "$CON/$REF"
assert_grep "27d: confirmed: SKILL.md is updated" "$CON/$SK/SKILL.md" "UPSTREAM-ROUTE"
run_overlay "$CON" status example-org
assert_out "27d: nothing waits after the confirm" "pending-confirm=0"

# 27e. the reported case: only a new reference, SKILL.md unchanged.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
mkdir -p "$OV/tree/$SK/references"
printf '# Costs\n' > "$OV/tree/$REF"; commit_ov "$OV" ref-only
run_overlay "$CON" sync example-org --yes
assert_absent "27e: the lone new reference is withheld" "$CON/$REF"
run_overlay "$CON" status example-org
assert_out "27e: status counts it" "pending-confirm=1"
assert_out "27e: and does not claim upstream-ahead=0" "upstream-ahead=1"

# 27f. unattended: the folder stays pending as a whole, SKILL.md untouched.
CON="$(mkcon)"; OV="$(mk_clean_overlay)"
run_overlay "$CON" add "file://$OV" --name example-org >/dev/null 2>&1
mk_ref_change "$OV"
unattended "$CON"
assert_out "27f: unattended still applies" "unattended example-org: applied"
case "$(printf '%s\n' "$OUT" | grep '^unattended example-org:')" in
  *"pending: "*"$SK/SKILL.md"*) pass "27f: the summary lists the held SKILL.md as pending" ;;
  *) fail "27f: the summary does not list the held SKILL.md" "$OUT" ;;
esac
assert_absent "27f: the reference is not written" "$CON/$REF"
assert_nogrep "27f: SKILL.md is not updated" "$CON/$SK/SKILL.md" "UPSTREAM-ROUTE"

# ───────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════"
echo "RESULT: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
