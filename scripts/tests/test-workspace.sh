#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test harness for the standalone workspace engine (scripts/workspace.py).
#
# Deterministic + model-free. Drives the REAL scripts/workspace.py against a
# THROWAWAY COPY of the tree (extracted via `git archive HEAD` into a temp dir)
# so the real working tree is never mutated. Fixtures are LOCAL git repos
# consumed through `file://` URLs:
#   - a tiny throwaway `role: code` member repo whose basename → slug `demo-code`
#   - the worked example overlay (examples/overlay-example/, prompt_fields
#     stripped) for the `--role config` delegation-to-overlay.py case.
# The user/* branch is simulated INSIDE each throwaway consumer (checkout -b),
# so both the branch gate and the clone are fully hermetic.
#
# Implements the SPEC test matrix (work/tasks/workspace-unification/deliverables/
# SPEC-increment-1.md §5), cases 1–12 + the optional hardening:
#    1  schema-validate PASS            (a hand-written valid def validates)
#    2  schema-validate FAIL            (missing title / bad role enum → non-zero, no crash)
#    3  create + list                   (writes <id>.yaml with id+created_at; list shows row)
#    4  validate created                (the just-created def validates)
#    5  add-repo (code)                 (clone dir + exclude block + lock pin + def repos[])
#    6  add-repo idempotent             (re-run → already-a-member, lock byte-identical)
#    7  remove-repo (code)              (clone gone, exclude block gone, lock+def pruned)
#    8  refuse off user branch          (create/add-repo refused on a non-user/* branch)
#    9  STANDALONE / no-k2a             (all verbs run; provider-name seam degrades exit 3)
#   10  config delegation               (--role config → overlay.py writes overlays.lock.yaml)
#   11  no-k2a-reference grep           (workspace.py source contains no k2a/reinvent)
#   12  trust guard                     (ext:: / git:// / http:// schemes + leading-dash refused)
#   13  optional hardening              (status read-only off-branch; x-provider bag accepted)
#   14  exclude block is the REAL guard (isolation: strip /.bridge/ .gitignore mask → info/exclude alone must ignore)
#   15  remove-repo branch gate         (remove-repo refused off a user/* branch, mutates nothing)
#   16  exclude drop preserves content  (a pre-existing unrelated info/exclude line survives the block drop)
#   17  multi-member exclude rebuild    (remove one of two members; the survivor's path stays excluded)
#   18  per-workspace lock prune        (removing a member from ws A leaves ws B's lock entry intact)
#   19  canonical subscribe/unsubscribe (canonical verbs work; add-repo/remove-repo retained as aliases; gate + config delegation hold)
#  + case  2 splits FAIL per-file (missing-title AND role:bogus each fail alone)
#  + case 10 adds config-overlay remove-repo (overlay.py delegation + def overlays[] prune)
#  + case 12 adds git:// + http:// scheme refusals
#
# NOTE ON `set`: like test-overlay.sh this uses `set -u` ONLY — NOT `-e`/`pipefail`.
# The harness deliberately captures each command's non-zero exit into $RC and keeps
# going so every section runs and the final summary is authoritative; `set -e` would
# abort on the first expected-non-zero verb, and `pipefail` would let the `yes y`
# SIGPIPE corrupt $RC. Non-zero exit on ANY failure is enforced by the final
# `[ "$FAIL" -eq 0 ]`, not by `-e`.
#
# Run:  bash scripts/tests/test-workspace.sh        (exits non-zero on any failure)
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORKSPACE="$ROOT/scripts/workspace.py"
EXAMPLE="$ROOT/examples/overlay-example"

# The branch gate must be able to FIRE — never let an ambient escape hatch mask it.
unset BRIDGE_OVERLAY_ALLOW_ANY_BRANCH 2>/dev/null || true

PASS=0
FAIL=0
OUT=""
RC=0

pass() { echo "  PASS — $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL — $1"; [ -n "${2:-}" ] && echo "$2" | sed 's/^/      /'; FAIL=$((FAIL + 1)); }

assert_rc() {        # <desc> <expected_rc>
  if [ "$RC" -eq "$2" ]; then pass "$1 (exit $RC)"; else fail "$1 — expected exit $2, got $RC" "$OUT"; fi
}
assert_rc_nonzero() { # <desc>
  if [ "$RC" -ne 0 ]; then pass "$1 (exit $RC)"; else fail "$1 — expected non-zero, got 0" "$OUT"; fi
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
assert_notrace() {   # <desc> — current $OUT carries no python traceback (graceful, not a crash)
  if printf '%s' "$OUT" | grep -q 'Traceback (most recent call last)'; then
    fail "$1 — python traceback in output (engine crashed)" "$OUT"
  else pass "$1"; fi
}

# run_workspace <consumer> <args...> — feeds `yes y` on stdin so any behavioural
# [y] gate (incl. the delegated overlay.py prompts) is satisfied; captures $OUT + $RC.
#
# SAFETY: the mutating verbs now ALSO publish workspace identity into the shared
# registry ($WORKSPACES_DIR else ~/.workspaces/). We pin $WORKSPACES_DIR to a
# per-consumer THROWAWAY dir (`<con>.wsreg`, a sibling under $TMP, OUTSIDE the
# consumer git tree) for EVERY run, so the suite NEVER touches the user's real
# ~/.workspaces/ (asserted absent/unchanged at the end).
run_workspace() {
  local con="$1"; shift
  OUT="$(yes y | WORKSPACES_DIR="${con}.wsreg" python3 "$WORKSPACE" --repo-root "$con" "$@" 2>&1)"
  RC=$?
}

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# --- REAL registry snapshot (must be byte-identical before/after the whole run) --
REAL_WS="${HOME}/.workspaces"
real_snapshot() { ( ls -laR "$REAL_WS" 2>/dev/null; find "$REAL_WS" -type f -exec shasum {} + 2>/dev/null ) | shasum | awk '{print $1}'; }
REAL_BEFORE="$(real_snapshot)"

# --- shared-registry (Option 3 write-through) readers -------------------------
reg_count() {   # <wsreg-dir> → number of entries (0 if absent/unreadable)
python3 - "$1" <<'PY' 2>/dev/null
import json, os, sys
try: print(len(json.load(open(os.path.join(sys.argv[1], "workspaces.json")))["workspaces"]))
except Exception: print(0)
PY
}
reg_version() { python3 -c 'import json,os,sys;print(json.load(open(os.path.join(sys.argv[1],"workspaces.json")))["version"])' "$1" 2>/dev/null || echo ""; }
reg_get() {     # <wsreg-dir> <python-expr over w=workspaces[0]> → printed value
python3 - "$1" "$2" <<'PY' 2>/dev/null
import json, os, sys
try:
    ws = json.load(open(os.path.join(sys.argv[1], "workspaces.json")))["workspaces"]
    w = ws[0] if ws else {}
    print(eval(sys.argv[2]))
except Exception:
    print("")
PY
}

# --- pristine consumer template (tracked tree only, no .git / .bridge) -------
PRISTINE="$TMP/pristine"
mkdir -p "$PRISTINE"
git -C "$ROOT" archive --format=tar HEAD | ( cd "$PRISTINE" && tar -xf - )

mkcon() {  # echoes a fresh consumer dir on a user/test branch (mutating verbs allowed)
  local c; c="$(mktemp -d "$TMP/con.XXXXXX")"
  cp -R "$PRISTINE/." "$c/"
  git -C "$c" init -q
  git -C "$c" checkout -q -b user/test
  git -C "$c" add -A
  git -C "$c" -c user.email=t@t -c user.name=t commit -qm init >/dev/null 2>&1
  echo "$c"
}

mkcon_core() {  # echoes a consumer on a NON-user/* branch (branch gate must refuse)
  local c; c="$(mktemp -d "$TMP/core.XXXXXX")"
  cp -R "$PRISTINE/." "$c/"
  git -C "$c" init -q
  git -C "$c" checkout -q -b not-a-user-branch
  git -C "$c" add -A
  git -C "$c" -c user.email=t@t -c user.name=t commit -qm init >/dev/null 2>&1
  echo "$c"
}

git_init_commit() {  # <dir> <msg> — init + commit a dir as a local git repo
  git -C "$1" init -q
  git -C "$1" add -A
  git -C "$1" -c user.email=t@t -c user.name=t commit -qm "$2" >/dev/null 2>&1
}

mk_code_fixture() {  # echoes the path to a throwaway code repo; basename → slug `demo-code`
  local parent; parent="$(mktemp -d "$TMP/codefix.XXXXXX")"
  local repo="$parent/demo-code"           # stable final segment → deterministic member slug
  mkdir -p "$repo"
  printf 'print("member")\n' > "$repo/main.py"
  printf '# demo-code — throwaway role:code member fixture\n' > "$repo/README.md"
  git_init_commit "$repo" "code-fixture init"
  echo "$repo"
}

mk_code_fixture2() {  # echoes a SECOND throwaway code repo; basename → slug `demo-lib`
  local parent; parent="$(mktemp -d "$TMP/codefix2.XXXXXX")"
  local repo="$parent/demo-lib"            # distinct final segment → distinct member slug
  mkdir -p "$repo"
  printf 'def lib():\n    return 2\n' > "$repo/lib.py"
  printf '# demo-lib — second throwaway role:code member fixture\n' > "$repo/README.md"
  git_init_commit "$repo" "code-fixture2 init"
  echo "$repo"
}

mk_clean_overlay() {  # echoes a clean overlay repo derived from the worked example
  local o; o="$(mktemp -d "$TMP/ovclean.XXXXXX")"
  cp -R "$EXAMPLE/." "$o/"
  # Strip prompt_fields so the delegated overlay.py materialize is non-interactive
  # and deterministic (placeholders untouched, valid YAML, stable hashes).
  python3 - "$o/overlay.manifest.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p))
for f in d.get("files", []):
    f.pop("prompt_fields", None)
yaml.safe_dump(d, open(p, "w"), sort_keys=False, allow_unicode=True)
PY
  git_init_commit "$o" init
  echo "$o"
}

# --- YAML readers (tolerant: print a sentinel on a missing/malformed file) ----
lock_repos_count() {  # <lockfile> <ws-id> → integer
python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, yaml
try:
    d = yaml.safe_load(open(sys.argv[1])) or {}
    ws = (d.get("workspaces") or {}).get(sys.argv[2]) or {}
    print(len(ws.get("repos") or []))
except Exception:
    print(0)
PY
}
lock_field() {        # <lockfile> <ws-id> <field> → first-repo field ("" if none)
python3 - "$1" "$2" "$3" <<'PY' 2>/dev/null
import sys, yaml
try:
    d = yaml.safe_load(open(sys.argv[1])) or {}
    r = ((d.get("workspaces") or {}).get(sys.argv[2]) or {}).get("repos") or []
    print(r[0].get(sys.argv[3], "") if r else "")
except Exception:
    print("")
PY
}
def_repos_count() {   # <deffile> → integer
python3 - "$1" <<'PY' 2>/dev/null
import sys, yaml
try:
    print(len((yaml.safe_load(open(sys.argv[1])) or {}).get("repos") or []))
except Exception:
    print(0)
PY
}
def_repo_field() {    # <deffile> <index> <field>
python3 - "$1" "$2" "$3" <<'PY' 2>/dev/null
import sys, yaml
try:
    r = (yaml.safe_load(open(sys.argv[1])) or {}).get("repos") or []
    print(r[int(sys.argv[2])].get(sys.argv[3], ""))
except Exception:
    print("")
PY
}
def_field() {         # <deffile> <key>
python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, yaml
try:
    print((yaml.safe_load(open(sys.argv[1])) or {}).get(sys.argv[2], ""))
except Exception:
    print("")
PY
}
def_has_overlay() {   # <deffile> <name> → YES|NO
python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, yaml
try:
    ov = (yaml.safe_load(open(sys.argv[1])) or {}).get("overlays") or []
    names = [(o.get("name") if isinstance(o, dict) else o) for o in ov]
    print("YES" if sys.argv[2] in names else "NO")
except Exception:
    print("NO")
PY
}
overlays_lock_has() { # <overlays.lock.yaml> <name> → YES|NO  (the private instance ships a
                      # tracked overlays.lock.yaml, so mere existence proves nothing — a fresh
                      # entry for <name> is what proves overlay.py actually delegated.)
python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, yaml
try:
    ov = (yaml.safe_load(open(sys.argv[1])) or {}).get("overlays") or {}
    print("YES" if sys.argv[2] in ov else "NO")
except Exception:
    print("NO")
PY
}

echo "════════════════════════════════════════════════════════════════"
echo "  workspace engine — test harness"
echo "════════════════════════════════════════════════════════════════"
if [ ! -f "$WORKSPACE" ]; then
  echo
  echo "  NOTE: scripts/workspace.py is ABSENT — this is the RED phase."
  echo "        Every section that drives the engine will FAIL until it is built."
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 1. schema-validate PASS (hand-written valid def) ────────────"
CONV="$(mkcon)"
mkdir -p "$CONV/workflow/workspaces"
cat > "$CONV/workflow/workspaces/valid-ws.yaml" <<'YAML'
schema_version: 1
id: valid-ws
title: A Valid Workspace
description: Hand-written, minimal, schema-conformant.
overlays: []
repos: []
YAML
run_workspace "$CONV" validate valid-ws
assert_rc "validate a valid def exits 0" 0
assert_out "validate prints PASS for the valid def" "PASS"
assert_notrace "validate did not crash"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 2. schema-validate FAIL (missing title / bad role enum) ─────"
# a def missing the REQUIRED `title`
cat > "$CONV/workflow/workspaces/no-title.yaml" <<'YAML'
schema_version: 1
id: no-title
overlays: []
repos: []
YAML
# a def with an out-of-enum role
cat > "$CONV/workflow/workspaces/bad-role.yaml" <<'YAML'
schema_version: 1
id: bad-role
title: Has A Bad Role
repos:
  - url: "file:///tmp/nowhere"
    role: bogus
overlays: []
YAML
run_workspace "$CONV" validate
assert_rc "validate over an invalid set exits 1" 1
assert_out "validate prints FAIL for an invalid def" "FAIL"
assert_notrace "validate reported failure without a crash"
# Aggregate FAIL can be carried by EITHER file — validate each ALONE so neither the
# missing-title nor the role-enum check can be masked by the other.
run_workspace "$CONV" validate no-title
assert_rc "missing-title def fails validation ALONE" 1
assert_out "missing-title def prints FAIL on its own" "FAIL"
assert_notrace "missing-title validate did not crash"
run_workspace "$CONV" validate bad-role
assert_rc "bad-role-enum def fails validation ALONE" 1
assert_out "bad-role def prints FAIL on its own" "FAIL"
assert_notrace "bad-role validate did not crash"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 3. create + list ────────────────────────────────────────────"
CON="$(mkcon)"
DEF="$CON/workflow/workspaces/demo-workspace.yaml"
LOCK="$CON/workspaces.lock.yaml"
EXCL="$CON/.git/info/exclude"
run_workspace "$CON" create demo-workspace
assert_rc "create succeeds on a user/* branch" 0
assert_file "create wrote the definition file" "$DEF"
assert_eq "definition id == basename" "$(def_field "$DEF" id)" "demo-workspace"
CREATED="$(def_field "$DEF" created_at)"
if [ -n "$CREATED" ]; then pass "create stamped created_at ($CREATED)"; else fail "create left created_at empty"; fi
run_workspace "$CON" list
assert_rc "list succeeds" 0
assert_out "list shows the new workspace row" "demo-workspace"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 4. validate the just-created def ────────────────────────────"
run_workspace "$CON" validate demo-workspace
assert_rc "validate the created def exits 0" 0
assert_out "validate prints PASS for the created def" "PASS"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 5. add-repo (role: code) → clone + exclude + lock + def ─────"
CODEFIX="$(mk_code_fixture)"
FIXSHA="$(git -C "$CODEFIX" rev-parse HEAD)"
CLONE="$CON/.bridge/workspaces/demo-workspace/demo-code"
run_workspace "$CON" add-repo demo-workspace "file://$CODEFIX" --role code
assert_rc "add-repo (code) succeeds" 0
assert_file "clone landed under .bridge/workspaces/<id>/<member>/" "$CLONE/main.py"
# belt-and-suspenders: the UNTRACKED .git/info/exclude carries the managed block
assert_grep "exclude carries the workspace marked block" "$EXCL" "workspace:demo-workspace"
assert_grep "exclude lists the member clone path" "$EXCL" "/.bridge/workspaces/demo-workspace/demo-code/"
assert_nogrep "tracked .gitignore was NOT touched (no filename leak)" "$CON/.gitignore" "workspace:demo-workspace"
# git must actually ignore the clone → a public fork's `git add -A` can't publish it
if ( cd "$CON" && git check-ignore -q .bridge/workspaces/demo-workspace/demo-code/main.py ); then
  pass "git ignores the cloned member (add -A cannot publish foreign code)"
else
  fail "git does NOT ignore the cloned member — public-fork code leak"
fi
# lock records the resolved reality
assert_file "workspaces.lock.yaml written" "$LOCK"
assert_eq "lock records the member name" "$(lock_field "$LOCK" demo-workspace name)" "demo-code"
LURL="$(lock_field "$LOCK" demo-workspace url)"
if printf '%s' "$LURL" | grep -q '^file://' && printf '%s' "$LURL" | grep -q 'demo-code'; then
  pass "lock records the member url"
else fail "lock member url wrong: $LURL"; fi
LREF="$(lock_field "$LOCK" demo-workspace ref)"
if [ -n "$LREF" ]; then pass "lock records a ref ($LREF)"; else fail "lock ref empty"; fi
LSHA="$(lock_field "$LOCK" demo-workspace resolved_sha)"
if printf '%s' "$LSHA" | grep -qE '^[0-9a-f]{40}$'; then pass "lock resolved_sha is a 40-hex pin"; else fail "lock resolved_sha not a 40-hex pin" "$LSHA"; fi
assert_eq "lock resolved_sha == the clone's actual HEAD" "$LSHA" "$FIXSHA"
LPATH="$(lock_field "$LOCK" demo-workspace path)"
if printf '%s' "$LPATH" | grep -q '\.bridge/workspaces/demo-workspace/demo-code'; then pass "lock records the clone path"; else fail "lock path wrong: $LPATH"; fi
# the definition now carries exactly one role:code member
assert_eq "definition repos[] has one entry" "$(def_repos_count "$DEF")" "1"
assert_eq "definition repos[0].role == code" "$(def_repo_field "$DEF" 0 role)" "code"
assert_eq "definition repos[0].name == demo-code" "$(def_repo_field "$DEF" 0 name)" "demo-code"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 6. add-repo idempotent (identical re-run is a no-op) ────────"
cp "$LOCK" "$TMP/wlock.before"
cp "$EXCL" "$TMP/wexcl.before"
run_workspace "$CON" add-repo demo-workspace "file://$CODEFIX" --role code
assert_rc "identical re-add succeeds" 0
assert_out "identical re-add reports already-a-member" "already a member"
if cmp -s "$LOCK" "$TMP/wlock.before"; then pass "lock byte-identical across the re-add"; else fail "lock changed on an idempotent re-add" "$(diff "$TMP/wlock.before" "$LOCK" 2>&1)"; fi
if cmp -s "$EXCL" "$TMP/wexcl.before"; then pass "exclude unchanged across the re-add"; else fail "exclude changed on an idempotent re-add"; fi
assert_eq "definition repos[] still length 1 (no second member)" "$(def_repos_count "$DEF")" "1"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 7. remove-repo (code member) restores a clean state ─────────"
run_workspace "$CON" remove-repo demo-workspace demo-code
assert_rc "remove-repo (code) succeeds" 0
assert_absent "clone dir deleted" "$CLONE"
assert_nogrep "exclude block dropped (no code members remain)" "$EXCL" "workspace:demo-workspace"
assert_eq "lock repos pruned to empty" "$(lock_repos_count "$LOCK" demo-workspace)" "0"
assert_eq "definition repos[] emptied" "$(def_repos_count "$DEF")" "0"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 8. refuse mutating verbs off a user/* branch ────────────────"
CORE="$(mkcon_core)"
run_workspace "$CORE" create off-branch-ws
assert_rc "create refused off a user/* branch" 1
assert_out "create refusal names the user/* gate" "user/"
assert_absent "nothing written for the refused create" "$CORE/workflow/workspaces/off-branch-ws.yaml"
run_workspace "$CORE" add-repo off-branch-ws "file://$CODEFIX" --role code
assert_rc "add-repo refused off a user/* branch" 1
assert_out "add-repo refusal names the user/* gate" "user/"
assert_absent "no clone written for the refused add-repo" "$CORE/.bridge/workspaces/off-branch-ws"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 9. STANDALONE — every verb runs with no k2a; name-seam degrades ─"
CON9="$(mkcon)"
DEF9="$CON9/workflow/workspaces/demo-workspace.yaml"
run_workspace "$CON9" create demo-workspace ;        assert_rc "standalone: create" 0
run_workspace "$CON9" list ;                          assert_rc "standalone: list" 0
run_workspace "$CON9" validate demo-workspace ;       assert_rc "standalone: validate" 0
run_workspace "$CON9" status demo-workspace ;         assert_rc "standalone: status" 0
run_workspace "$CON9" add-repo demo-workspace "file://$CODEFIX" --role code ; assert_rc "standalone: add-repo (code)" 0
run_workspace "$CON9" status demo-workspace ;         assert_rc "standalone: status after add" 0
run_workspace "$CON9" remove-repo demo-workspace demo-code ; assert_rc "standalone: remove-repo" 0
# provider-name seam: a bare slug (no scheme, no `/`) needs an external provider that
# is not present → graceful exit 3, no traceback, nothing written.
cp "$DEF9" "$TMP/def9.before"
run_workspace "$CON9" add-repo demo-workspace someprovider
assert_rc "provider-name seam degrades with exit 3" 3
assert_out "seam says the arg is not a git URL" "not a git URL"
assert_out "seam says the provider is not available" "not available"
assert_notrace "provider-name seam degraded gracefully (no traceback)"
assert_absent "no clone attempted for a provider name" "$CON9/.bridge/workspaces/demo-workspace/someprovider"
if cmp -s "$DEF9" "$TMP/def9.before"; then pass "provider-name attempt wrote nothing to the definition"; else fail "provider-name attempt mutated the definition"; fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 10. config delegation → overlay.py owns overlays.lock.yaml ──"
CON10="$(mkcon)"
DEF10="$CON10/workflow/workspaces/demo-workspace.yaml"
OV="$(mk_clean_overlay)"
run_workspace "$CON10" create demo-workspace ; assert_rc "create (for delegation case)" 0
run_workspace "$CON10" add-repo demo-workspace "file://$OV" --role config
assert_rc "add-repo (config) succeeds" 0
assert_file "overlays.lock.yaml present" "$CON10/overlays.lock.yaml"
assert_eq "overlay.py recorded the overlay in overlays.lock.yaml (real delegation, not a stub)" "$(overlays_lock_has "$CON10/overlays.lock.yaml" example-org)" "YES"
assert_eq "definition overlays[] records the resolved overlay name" "$(def_has_overlay "$DEF10" example-org)" "YES"
assert_file "at least one example dest materialized by overlay.py" "$CON10/workflow/contexts/example-docs.yaml"
assert_eq "config member NOT kept in repos[] (increment-1 rule)" "$(def_repos_count "$DEF10")" "0"
# remove-repo of a config overlay must DELEGATE to overlay.py (dropping the entry
# from overlays.lock.yaml + the cache) AND prune the name from the def overlays[].
run_workspace "$CON10" remove-repo demo-workspace example-org
assert_rc "remove-repo (config overlay) succeeds" 0
assert_notrace "config remove-repo did not crash"
assert_eq "overlay.py dropped the entry from overlays.lock.yaml (real delegation, not a stub)" "$(overlays_lock_has "$CON10/overlays.lock.yaml" example-org)" "NO"
assert_eq "definition overlays[] no longer lists the overlay" "$(def_has_overlay "$DEF10" example-org)" "NO"
assert_absent "overlay cache dropped by overlay.py remove" "$CON10/.bridge/overlays/example-org"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 11. no-k2a-reference grep (source-level standalone) ─────────"
if [ -f "$WORKSPACE" ]; then
  if grep -iqE 'k2a|reinvent' "$WORKSPACE"; then
    fail "scripts/workspace.py references k2a/reinvent (not standalone)" "$(grep -inE 'k2a|reinvent' "$WORKSPACE")"
  else
    pass "scripts/workspace.py contains no k2a/reinvent reference"
  fi
else
  fail "scripts/workspace.py absent — cannot assert it is k2a-free"
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 12. git-URL trust guard (refuse dangerous schemes / injection) ─"
CON12="$(mkcon)"
DEF12="$CON12/workflow/workspaces/demo-workspace.yaml"
run_workspace "$CON12" create demo-workspace ; assert_rc "create (for trust-guard case)" 0
cp "$DEF12" "$TMP/def12.before"
# ext:: is a remote-code-execution transport → must be refused before any clone
run_workspace "$CON12" add-repo demo-workspace 'ext::sh -c id' --role code
assert_rc "ext:: scheme refused (exit 1)" 1
assert_notrace "ext:: refusal is a clean error, not a crash"
# an argument that begins with '-' (argv-injection); `--` forces it positional
run_workspace "$CON12" add-repo demo-workspace -- '-rf'
assert_rc "leading-dash arg refused (exit 1)" 1
assert_notrace "leading-dash refusal is a clean error, not a crash"
# neither refusal touched the tree
assert_absent "trust guard cloned nothing" "$CON12/.bridge/workspaces/demo-workspace"
assert_eq "trust guard left repos[] empty" "$(def_repos_count "$DEF12")" "0"
if cmp -s "$DEF12" "$TMP/def12.before"; then pass "trust guard wrote nothing to the definition"; else fail "trust guard mutated the definition"; fi
assert_absent "trust guard wrote no lock" "$CON12/workspaces.lock.yaml"
# scheme allowlist: only https/ssh/file/scp are trusted → git:// and http:// (a
# supply-chain hole if the allowlist is ever widened) must be REFUSED pre-clone.
run_workspace "$CON12" add-repo demo-workspace 'git://evil.example/repo.git' --role code
assert_rc "git:// scheme refused (exit 1)" 1
assert_out "git:// refusal cites the scheme allowlist" "scheme"
assert_notrace "git:// refusal is a clean error, not a crash"
run_workspace "$CON12" add-repo demo-workspace 'http://evil.example/repo.git' --role code
assert_rc "http:// scheme refused (exit 1)" 1
assert_out "http:// refusal cites the scheme allowlist" "scheme"
assert_notrace "http:// refusal is a clean error, not a crash"
assert_absent "no clone dir from any refused scheme" "$CON12/.bridge/workspaces/demo-workspace"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 13. optional hardening (read-only off-branch; x-provider bag) ─"
# status is read-only → it runs even on a non-user/* branch
CORE2="$(mkcon_core)"
run_workspace "$CORE2" status
assert_rc "status runs read-only on a non-user/* branch" 0
assert_notrace "status did not crash off-branch"
# a def carrying an x-provider bag with provider-specific data must still validate
CON13="$(mkcon)"
mkdir -p "$CON13/workflow/workspaces"
cat > "$CON13/workflow/workspaces/prov-ws.yaml" <<'YAML'
schema_version: 1
id: prov-ws
title: Workspace With A Provider Bag
overlays: []
repos: []
x-provider:
  someprovider:
    workspace: demo
    anything: [1, 2, 3]
YAML
run_workspace "$CON13" validate prov-ws
assert_rc "x-provider extension data does not fail validation (forward-compat)" 0

# ───────────────────────────────────────────────────────────────────
echo
echo "── 14. exclude block is the REAL guard (info/exclude in isolation) ─"
# Case 5's git check-ignore is MASKED: the tracked `.gitignore` line `/.bridge/`
# already ignores the clone path, so the belt-and-suspenders `.git/info/exclude`
# block is only checked TEXTUALLY there, never proven to actually protect. Here we
# STRIP `/.bridge/` from `.gitignore` so ONLY the untracked info/exclude block can
# keep the member clone out of git — a broken/no-op ensure_git_exclude_block
# (wrong path, missing block) now FAILS this case.
CONISO="$(mkcon)"
python3 - "$CONISO/.gitignore" <<'PY'
import sys
p = sys.argv[1]
out = [ln for ln in open(p).read().splitlines(keepends=True)
       if ln.strip().strip('/') != '.bridge']   # drop the `/.bridge/` cover only
open(p, "w").writelines(out)
PY
git -C "$CONISO" add .gitignore
git -C "$CONISO" -c user.email=t@t -c user.name=t commit -qm "drop /.bridge/ ignore (isolation)" >/dev/null 2>&1
# premise: with `/.bridge/` gone, `.gitignore` alone must NOT ignore the clone path
if ( cd "$CONISO" && git check-ignore -q .bridge/workspaces/demo-workspace/demo-code/main.py ); then
  fail "premise broken — .gitignore still ignores .bridge/ (isolation not achieved)"
else
  pass "premise: .gitignore no longer covers the clone path (isolation achieved)"
fi
run_workspace "$CONISO" create demo-workspace ; assert_rc "create (isolation case)" 0
run_workspace "$CONISO" add-repo demo-workspace "file://$CODEFIX" --role code
assert_rc "add-repo (code) succeeds (isolation case)" 0
# with no .gitignore cover, ONLY the info/exclude block can be ignoring the clone
if ( cd "$CONISO" && git check-ignore -q .bridge/workspaces/demo-workspace/demo-code/main.py ); then
  pass "member clone ignored with NO .gitignore cover → info/exclude is the active guard"
else
  fail "member clone NOT ignored once the .gitignore mask is gone — exclude block broken"
fi
# -v attribution: the deciding rule source must be the untracked info/exclude
CIV="$( cd "$CONISO" && git check-ignore -v .bridge/workspaces/demo-workspace/demo-code/main.py 2>/dev/null )"
if printf '%s' "$CIV" | grep -q 'info/exclude'; then
  pass ".git/info/exclude is the deciding ignore rule (git check-ignore -v)"
else
  fail "the deciding ignore rule is NOT info/exclude" "$CIV"
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 15. remove-repo is gated off a user/* branch ────────────────"
# cmd_remove_repo must call require_user_branch() FIRST — prove it refuses (exit 1)
# and mutates NOTHING even when a real member exists to be removed.
CORER="$(mkcon_core)"
mkdir -p "$CORER/workflow/workspaces"
cat > "$CORER/workflow/workspaces/gated-ws.yaml" <<'YAML'
schema_version: 1
id: gated-ws
title: Gated Workspace
overlays: []
repos:
  - url: "file:///tmp/nowhere"
    role: code
    name: demo-code
    ref: main
    path: .bridge/workspaces/gated-ws/demo-code
YAML
mkdir -p "$CORER/.bridge/workspaces/gated-ws/demo-code"
printf 'print("member")\n' > "$CORER/.bridge/workspaces/gated-ws/demo-code/main.py"
cp "$CORER/workflow/workspaces/gated-ws.yaml" "$TMP/gated.before"
run_workspace "$CORER" remove-repo gated-ws demo-code
assert_rc "remove-repo refused off a user/* branch" 1
assert_out "remove-repo refusal names the user/* gate" "user/"
assert_notrace "remove-repo refusal is a clean error, not a crash"
assert_file "the member clone SURVIVED the refused remove-repo" "$CORER/.bridge/workspaces/gated-ws/demo-code/main.py"
if cmp -s "$CORER/workflow/workspaces/gated-ws.yaml" "$TMP/gated.before"; then pass "remove-repo off-branch mutated no definition"; else fail "remove-repo off-branch mutated the definition"; fi
assert_absent "remove-repo off-branch wrote no lock" "$CORER/workspaces.lock.yaml"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 16. exclude-block drop preserves unrelated info/exclude content ─"
# remove-repo drops only the WORKSPACE block. A naive os.remove of the whole
# info/exclude would still pass assert_nogrep (an absent file also 'passes') yet
# destroy a user's own unrelated excludes. Seed one and prove it survives.
CONX="$(mkcon)"
printf '# my own local excludes\n/scratch-notes.txt\n' >> "$CONX/.git/info/exclude"
run_workspace "$CONX" create demo-workspace ; assert_rc "create (preserve-unrelated case)" 0
run_workspace "$CONX" add-repo demo-workspace "file://$CODEFIX" --role code
assert_rc "add-repo (code) succeeds (preserve-unrelated case)" 0
assert_grep "workspace block sits alongside the pre-existing line" "$CONX/.git/info/exclude" "workspace:demo-workspace"
assert_grep "unrelated line still present before remove" "$CONX/.git/info/exclude" "/scratch-notes.txt"
run_workspace "$CONX" remove-repo demo-workspace demo-code
assert_rc "remove-repo succeeds (preserve-unrelated case)" 0
assert_nogrep "workspace block dropped on remove" "$CONX/.git/info/exclude" "workspace:demo-workspace"
assert_grep "pre-existing UNRELATED exclude line SURVIVES the block drop" "$CONX/.git/info/exclude" "/scratch-notes.txt"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 17. multi-member exclude rebuild (partial remove keeps survivor) ─"
CODEFIX2="$(mk_code_fixture2)"          # basename → slug `demo-lib`
CONM="$(mkcon)"
DEFM="$CONM/workflow/workspaces/demo-workspace.yaml"
EXCLM="$CONM/.git/info/exclude"
run_workspace "$CONM" create demo-workspace ; assert_rc "create (multi-member case)" 0
run_workspace "$CONM" add-repo demo-workspace "file://$CODEFIX"  --role code ; assert_rc "add member one (demo-code)" 0
run_workspace "$CONM" add-repo demo-workspace "file://$CODEFIX2" --role code ; assert_rc "add member two (demo-lib)" 0
assert_grep "exclude lists member one's path"  "$EXCLM" "/.bridge/workspaces/demo-workspace/demo-code/"
assert_grep "exclude lists member two's path"  "$EXCLM" "/.bridge/workspaces/demo-workspace/demo-lib/"
assert_eq "definition carries two members" "$(def_repos_count "$DEFM")" "2"
run_workspace "$CONM" remove-repo demo-workspace demo-code ; assert_rc "remove member one succeeds" 0
assert_nogrep "removed member's path dropped from exclude"          "$EXCLM" "/.bridge/workspaces/demo-workspace/demo-code/"
assert_grep  "SURVIVING member's path STILL excluded after remove"  "$EXCLM" "/.bridge/workspaces/demo-workspace/demo-lib/"
assert_grep  "workspace block still present (one member remains)"    "$EXCLM" "workspace:demo-workspace"
assert_eq "definition down to one member" "$(def_repos_count "$DEFM")" "1"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 18. removing a member prunes one workspace, spares another ──"
# A second workspace's lock entry must SURVIVE a member removal in the first —
# proves remove rebuilds only the target ws entry, never destroys the whole lock.
CONW="$(mkcon)"
LOCKW="$CONW/workspaces.lock.yaml"
run_workspace "$CONW" create demo-workspace  ; assert_rc "create demo-workspace"  0
run_workspace "$CONW" create other-workspace ; assert_rc "create other-workspace" 0
run_workspace "$CONW" add-repo demo-workspace  "file://$CODEFIX" --role code ; assert_rc "add member to demo-workspace"  0
run_workspace "$CONW" add-repo other-workspace "file://$CODEFIX" --role code ; assert_rc "add member to other-workspace" 0
assert_eq "other-workspace has one locked member before the prune" "$(lock_repos_count "$LOCKW" other-workspace)" "1"
run_workspace "$CONW" remove-repo demo-workspace demo-code ; assert_rc "remove member from demo-workspace succeeds" 0
assert_eq "demo-workspace lock pruned to empty" "$(lock_repos_count "$LOCKW" demo-workspace)" "0"
assert_eq "OTHER workspace's lock entry SURVIVES (no whole-lock destroy)" "$(lock_repos_count "$LOCKW" other-workspace)" "1"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 19. canonical subscribe/unsubscribe (add-repo/remove-repo aliases) ─"
# subscribe/unsubscribe are the CANONICAL verb names; add-repo/remove-repo are
# retained aliases. Both must dispatch to the same handlers — incl. the branch
# gate and config delegation — so Axel's command vocabulary works unchanged.
CONS="$(mkcon)"
DEFS="$CONS/workflow/workspaces/demo-workspace.yaml"
LOCKS="$CONS/workspaces.lock.yaml"
EXCLS="$CONS/.git/info/exclude"
CLONES="$CONS/.bridge/workspaces/demo-workspace/demo-code"
run_workspace "$CONS" create demo-workspace ; assert_rc "create (verb-rename case)" 0
# subscribe (canonical) behaves exactly like add-repo
run_workspace "$CONS" subscribe demo-workspace "file://$CODEFIX" --role code
assert_rc "subscribe (canonical) adds a code member" 0
assert_file "subscribe cloned the member" "$CLONES/main.py"
assert_grep "subscribe wrote the exclude block" "$EXCLS" "workspace:demo-workspace"
assert_eq "subscribe recorded the lock member" "$(lock_field "$LOCKS" demo-workspace name)" "demo-code"
assert_eq "subscribe added one repos[] entry" "$(def_repos_count "$DEFS")" "1"
# unsubscribe (canonical) behaves exactly like remove-repo
run_workspace "$CONS" unsubscribe demo-workspace demo-code
assert_rc "unsubscribe (canonical) removes the code member" 0
assert_absent "unsubscribe deleted the clone" "$CLONES"
assert_nogrep "unsubscribe dropped the exclude block" "$EXCLS" "workspace:demo-workspace"
assert_eq "unsubscribe emptied repos[]" "$(def_repos_count "$DEFS")" "0"
# the OLD alias names still route identically (alias contract locked)
run_workspace "$CONS" add-repo demo-workspace "file://$CODEFIX" --role code
assert_rc "add-repo alias still adds a code member" 0
assert_eq "add-repo alias added one repos[] entry" "$(def_repos_count "$DEFS")" "1"
run_workspace "$CONS" remove-repo demo-workspace demo-code
assert_rc "remove-repo alias still removes the code member" 0
assert_eq "remove-repo alias emptied repos[]" "$(def_repos_count "$DEFS")" "0"
# the user/* branch gate fires under the canonical verbs too
CORES="$(mkcon_core)"
run_workspace "$CORES" subscribe off-branch-ws "file://$CODEFIX" --role code
assert_rc "subscribe refused off a user/* branch" 1
assert_out "subscribe refusal names the user/* gate" "user/"
run_workspace "$CORES" unsubscribe off-branch-ws demo-code
assert_rc "unsubscribe refused off a user/* branch" 1
assert_out "unsubscribe refusal names the user/* gate" "user/"
# subscribe --role config delegates to overlay.py (canonical verb, config path)
CONSC="$(mkcon)"
DEFSC="$CONSC/workflow/workspaces/demo-workspace.yaml"
OVS="$(mk_clean_overlay)"
run_workspace "$CONSC" create demo-workspace ; assert_rc "create (subscribe-config case)" 0
run_workspace "$CONSC" subscribe demo-workspace "file://$OVS" --role config
assert_rc "subscribe --role config delegates to overlay.py" 0
assert_file "subscribe --role config wrote overlays.lock.yaml (real delegation)" "$CONSC/overlays.lock.yaml"
assert_eq "overlay.py recorded the overlay via the canonical verb" "$(overlays_lock_has "$CONSC/overlays.lock.yaml" example-org)" "YES"
assert_eq "definition overlays[] records the overlay name" "$(def_has_overlay "$DEFSC" example-org)" "YES"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 20. shared-registry write-through (Option 3 identity publish) ─"
# After create/subscribe/unsubscribe SUCCEED, the engine publishes the workspace's
# IDENTITY into the shared registry (name from title, code-member directories +
# git_remotes, and extensions[open-bridge].overlays/.repos) — additively, keyed by
# a stable open-bridge id, so the three ops collapse to ONE entry and unsubscribe
# shrinks the mirror. The repo-local definition/lock/exclude stay the record.
CONP="$(mkcon)"
WSREG="${CONP}.wsreg"
CODEFIXP="$(mk_code_fixture)"        # basename → slug demo-code
OVP="$(mk_clean_overlay)"
run_workspace "$CONP" create demo-workspace --title "Demo Workspace"
assert_rc "create (write-through)" 0
assert_file "shared registry written on the create publish" "$WSREG/workspaces.json"
assert_eq "registry envelope is version 2" "$(reg_version "$WSREG")" "2"
assert_eq "ONE entry after create" "$(reg_count "$WSREG")" "1"
assert_eq "name mapped from title (title→name)" "$(reg_get "$WSREG" 'w["name"]')" "Demo Workspace"
assert_eq "our open-bridge id == the workspace slug" "$(reg_get "$WSREG" 'w["extensions"]["open-bridge"]["id"]')" "demo-workspace"
# subscribe code → still ONE entry (de-dup by our id), directories + git_remotes published
run_workspace "$CONP" subscribe demo-workspace "file://$CODEFIXP" --role code
assert_rc "subscribe code (write-through)" 0
assert_eq "still ONE entry after code subscribe (de-dup by open-bridge id)" "$(reg_count "$WSREG")" "1"
assert_eq "directories[] carries the one code member" "$(reg_get "$WSREG" 'len(w["directories"])')" "1"
assert_eq "code directory is labelled 'repo'" "$(reg_get "$WSREG" 'w["directories"][0].get("label")')" "repo"
PUBDIR="$(reg_get "$WSREG" 'w["directories"][0]["path"]')"
if printf '%s' "$PUBDIR" | grep -q '\.bridge/workspaces/demo-workspace/demo-code'; then pass "published directory points at the member clone"; else fail "published dir wrong: $PUBDIR"; fi
assert_eq "git_remotes[] populated from the member origin" "$(reg_get "$WSREG" 'len(w["git_remotes"])')" "1"
PUBREMOTE="$(reg_get "$WSREG" 'w["git_remotes"][0]')"
if printf '%s' "$PUBREMOTE" | grep -q 'demo-code'; then pass "git_remotes carries the member origin URL"; else fail "git_remote wrong: $PUBREMOTE"; fi
assert_eq "extensions[open-bridge].repos[] published" "$(reg_get "$WSREG" 'len(w["extensions"]["open-bridge"]["repos"])')" "1"
# subscribe config → still ONE entry, overlays published under our extension
run_workspace "$CONP" subscribe demo-workspace "file://$OVP" --role config
assert_rc "subscribe config (write-through)" 0
assert_eq "still ONE entry after config subscribe" "$(reg_count "$WSREG")" "1"
assert_eq "extensions[open-bridge].overlays[] carries the overlay" "$(reg_get "$WSREG" '"example-org" in w["extensions"]["open-bridge"]["overlays"]')" "True"
assert_eq "code directory still present after config subscribe" "$(reg_get "$WSREG" 'len(w["directories"])')" "1"
# unsubscribe code → the mirror SHRINKS (reduced state re-published)
run_workspace "$CONP" unsubscribe demo-workspace demo-code
assert_rc "unsubscribe code (write-through)" 0
assert_eq "still ONE entry after unsubscribe (updated in place)" "$(reg_count "$WSREG")" "1"
assert_eq "directories[] reduced to zero (mirror shrank, not merged)" "$(reg_get "$WSREG" 'len(w["directories"])')" "0"
assert_eq "git_remotes[] reduced to zero" "$(reg_get "$WSREG" 'len(w["git_remotes"])')" "0"
assert_eq "overlays survive the code unsubscribe" "$(reg_get "$WSREG" '"example-org" in w["extensions"]["open-bridge"]["overlays"]')" "True"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 21. real ~/.workspaces/ untouched across the entire suite ───"
REAL_AFTER="$(real_snapshot)"
assert_eq "the real ~/.workspaces/ snapshot is byte-identical before/after" "$REAL_BEFORE" "$REAL_AFTER"
if [ ! -e "$REAL_WS" ]; then
  pass "real ~/.workspaces/ was never created by the suite (all writes went to <con>.wsreg)"
else
  echo "  NOTE: ~/.workspaces/ pre-existed; snapshot equality above is the proof of no-touch."
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════"
echo "RESULT: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
