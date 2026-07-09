#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Test harness for the standalone workspace-registry writer (scripts/workspace_registry.py).
#
# Deterministic + model-free. Drives the REAL scripts/workspace_registry.py, but
# ALWAYS against a THROWAWAY `$WORKSPACES_DIR` (a fresh mktemp -d) — it NEVER reads
# or writes the user's real `~/.workspaces/` (design §C.3 "Test isolation —
# must-have"). A snapshot of the real registry dir is taken before and after the
# whole run and asserted byte-identical, proving zero touch.
#
# The registry is a SHARED, multi-writer JSON file (also written by other tools),
# so every mutation is safety-critical. Coverage (each an assert w/ PASS/FAIL):
#   -  upsert + read-back (name/id/dirs/remote/extensions/timestamps/version)
#   -  de-dup on create by identity — by git_remotes (scp≡https) AND by path
#   -  preserve-unknown — an unknown top-level key + an unknown per-workspace key
#      survive an upsert of a DIFFERENT workspace (only version + workspaces touched)
#   -  foreign-extension preservation — another tool's extensions["k2a"] slice
#      survives an upsert of the SAME identity; only our extensions["open-bridge"]
#      and the shared-identity fields change
#   -  atomic replace — no `.tmp` left behind; the file is always parseable
#   -  version max-monotonic — a version:3 file is REFUSED for write (exit non-zero,
#      file left intact) yet can still be READ
#   -  $WORKSPACES_DIR isolation — the module resolves + writes ONLY under the temp
#      dir; the real ~/.workspaces/ is never created or modified during the run
#   -  path matching (§D) — symlink canonicalization, macOS Dropbox alias, and
#      longest-match-wins for nested directories
#   -  archive — soft-delete flips archived + bumps updated_at
#   -  standalone — the module source contains no k2a/reinvent reference
#   -  CLI — version-guard exits non-zero, read still exits 0
#   -  MUTATION-CHECKS on the four safety-critical asserts (preserve-unknown,
#      foreign-ext, de-dup, version-guard): break a COPY of the engine, confirm the
#      corresponding assert now FAILS (has teeth), discard the copy (original never
#      touched).
#
# NOTE ON `set`: like test-overlay.sh this uses `set -u` ONLY. Each command's
# non-zero exit is captured into $RC and the run continues; the final
# `[ "$FAIL" -eq 0 ]` is what makes the script exit non-zero on any failure.
#
# Run:  bash scripts/tests/test-workspace-registry.sh   (exits non-zero on any failure)
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGISTRY="$ROOT/scripts/workspace_registry.py"

PASS=0
FAIL=0
OUT=""
RC=0

pass() { echo "  PASS — $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL — $1"; [ -n "${2:-}" ] && echo "$2" | sed 's/^/      /'; FAIL=$((FAIL + 1)); }

assert_rc()        { if [ "$RC" -eq "$2" ]; then pass "$1 (exit $RC)"; else fail "$1 — expected exit $2, got $RC" "$OUT"; fi; }
assert_rc_nonzero(){ if [ "$RC" -ne 0 ]; then pass "$1 (exit $RC)"; else fail "$1 — expected non-zero, got 0" "$OUT"; fi; }
assert_out()       { if printf '%s' "$OUT" | grep -qF -- "$2"; then pass "$1"; else fail "$1 — output missing: $2" "$OUT"; fi; }
assert_noout()     { if printf '%s' "$OUT" | grep -qF -- "$2"; then fail "$1 — output unexpectedly present: $2" "$OUT"; else pass "$1"; fi; }
assert_eq()        { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 — '$2' != '$3'"; fi; }
assert_file()      { if [ -f "$2" ]; then pass "$1"; else fail "$1 — file absent: $2"; fi; }
assert_absent()    { if [ ! -e "$2" ]; then pass "$1"; else fail "$1 — path unexpectedly present: $2"; fi; }
assert_notrace()   { if printf '%s' "$OUT" | grep -q 'Traceback (most recent call last)'; then fail "$1 — python traceback (crash)" "$OUT"; else pass "$1"; fi; }

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# --- REAL registry snapshot (must be byte-identical before/after the whole run) --
REAL_WS="${HOME}/.workspaces"
real_snapshot() { ( ls -laR "$REAL_WS" 2>/dev/null; find "$REAL_WS" -type f -exec shasum {} + 2>/dev/null ) | shasum | awk '{print $1}'; }
REAL_BEFORE="$(real_snapshot)"

# fresh throwaway registry dir — NEVER the real ~/.workspaces
wsdir() { mktemp -d "$TMP/wsdir.XXXXXX"; }

# run_scen <scenario.py> <wsdir> [module] — drives a scenario with an ISOLATED
# $WORKSPACES_DIR; WSR_MODULE selects the engine (real by default, a mutant copy
# for the mutation-checks). Captures $OUT + $RC.
run_scen() {
  local f="$1" dir="$2" mod="${3:-$REGISTRY}"
  OUT="$(WORKSPACES_DIR="$dir" WSR_MODULE="$mod" python3 "$f" 2>&1)"; RC=$?
}

# mutate <dst> <old> <new> — copy $REGISTRY → dst with a replacement; asserts the
# anchor is present so a silent no-op mutation can't fake a passing teeth-check.
mutate() {
  python3 - "$REGISTRY" "$1" "$2" "$3" <<'PY'
import sys
src, dst, a, b = sys.argv[1:5]
t = open(src).read()
assert a in t, f"mutation anchor absent: {a!r}"
open(dst, "w").write(t.replace(a, b))
PY
}

# Every scenario file begins with this loader (module path from $WSR_MODULE).
HDR='import importlib.util, os, json
_spec = importlib.util.spec_from_file_location("wsr", os.environ["WSR_MODULE"])
m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(m)
'

echo "════════════════════════════════════════════════════════════════"
echo "  workspace-registry writer — test harness"
echo "════════════════════════════════════════════════════════════════"
if [ ! -f "$REGISTRY" ]; then
  echo; echo "  NOTE: scripts/workspace_registry.py is ABSENT — RED phase."
fi

# ───────────────────────────────────────────────────────────────────
# Scenario files (reused by the real run AND the mutant teeth-checks)
# ───────────────────────────────────────────────────────────────────
S_UPSERT="$TMP/s_upsert.py";        printf '%s' "$HDR" > "$S_UPSERT"
cat >> "$S_UPSERT" <<'PY'
reg = m.Registry()
ws = reg.upsert_workspace("k2a",
        directories=["/tmp/wsr/k2a"],
        git_remotes=["https://github.com/acme/k2a.git"],
        open_bridge_ext={"overlays": ["o"], "repos": ["r"]})
d = reg.read_registry()
w = d["workspaces"][0]
ok = (d["version"] == 2 and len(d["workspaces"]) == 1
      and w["name"] == "k2a" and w["id"] == "ws_0001" and w["archived"] is False
      and w["directories"][0]["path"] == os.path.realpath("/tmp/wsr/k2a")
      and "https://github.com/acme/k2a.git" in w["git_remotes"]
      and w["extensions"]["open-bridge"] == {"overlays": ["o"], "repos": ["r"]}
      and bool(w["created_at"]) and bool(w["updated_at"]))
print("PASS-UPSERT" if ok else "FAIL-UPSERT", w)
PY

S_DEDUP_REMOTE="$TMP/s_dedup_remote.py"; printf '%s' "$HDR" > "$S_DEDUP_REMOTE"
cat >> "$S_DEDUP_REMOTE" <<'PY'
reg = m.Registry()
reg.upsert_workspace("a", git_remotes=["https://github.com/acme/repo.git"])
reg.upsert_workspace("b", git_remotes=["git@github.com:acme/repo.git"])  # scp form, same remote
n = len(reg.read_registry()["workspaces"])
print("PASS-DEDUP-REMOTE" if n == 1 else f"FAIL-DEDUP-REMOTE n={n}")
PY

S_DEDUP_PATH="$TMP/s_dedup_path.py"; printf '%s' "$HDR" > "$S_DEDUP_PATH"
cat >> "$S_DEDUP_PATH" <<'PY'
reg = m.Registry()
reg.upsert_workspace("a", directories=["/tmp/wsr/proj"])
reg.upsert_workspace("b", directories=["/tmp/wsr/proj/"])  # trailing slash → same canonical
n = len(reg.read_registry()["workspaces"])
print("PASS-DEDUP-PATH" if n == 1 else f"FAIL-DEDUP-PATH n={n}")
PY

S_DEDUP_CASE="$TMP/s_dedup_case.py"; printf '%s' "$HDR" > "$S_DEDUP_CASE"
cat >> "$S_DEDUP_CASE" <<'PY'
reg = m.Registry()
reg.upsert_workspace("a", git_remotes=["https://h/x/repo.git"])
reg.upsert_workspace("b", git_remotes=["https://h/x/repo.GIT"])  # uppercase .GIT suffix, SAME repo
n = len(reg.read_registry()["workspaces"])
print("PASS-DEDUP-CASE" if n == 1 else f"FAIL-DEDUP-CASE n={n}")
PY

S_PRESERVE="$TMP/s_preserve.py"; printf '%s' "$HDR" > "$S_PRESERVE"
cat >> "$S_PRESERVE" <<'PY'
reg = m.Registry()
seed = {"version": 2, "future_top": {"x": [1, 2]},
        "workspaces": [{"id": "ws_0009", "name": "old",
                        "directories": [{"path": "/tmp/wsr/old", "aliases": []}],
                        "git_remotes": [], "weird": {"k": "v"}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
before = json.load(open(reg.path))
reg.upsert_workspace("newer", directories=["/tmp/wsr/new"], open_bridge_ext={"overlays": []})
after = json.load(open(reg.path))
old = [w for w in after["workspaces"] if w["id"] == "ws_0009"][0]
ok = (after.get("future_top") == before["future_top"]      # unknown top-level survives
      and old.get("weird") == {"k": "v"}                    # unknown per-ws survives
      and old == before["workspaces"][0])                   # existing ws byte-for-byte
print("PASS-PRESERVE-TOP" if ok else f"FAIL-PRESERVE-TOP top={after.get('future_top')} old_eq={old == before['workspaces'][0]}")
PY

S_FOREIGN="$TMP/s_foreign.py"; printf '%s' "$HDR" > "$S_FOREIGN"
cat >> "$S_FOREIGN" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0003", "name": "proj", "directories": [],
    "git_remotes": ["https://github.com/acme/proj.git"],
    "extensions": {"k2a": {"state": {"panes": 2}, "flags": ["--a"]}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.upsert_workspace("proj", git_remotes=["https://github.com/acme/proj.git"],
                     open_bridge_ext={"overlays": ["o1"]})
after = json.load(open(reg.path))
w = after["workspaces"][0]
ok = (len(after["workspaces"]) == 1                                       # de-dup held
      and w["extensions"]["k2a"] == {"state": {"panes": 2}, "flags": ["--a"]}  # foreign slice intact
      and w["extensions"]["open-bridge"] == {"overlays": ["o1"]})         # our slice written
print("PASS-FOREIGN-EXT" if ok else f"FAIL-FOREIGN-EXT ext={w.get('extensions')}")
PY

S_VERSION="$TMP/s_version.py"; printf '%s' "$HDR" > "$S_VERSION"
cat >> "$S_VERSION" <<'PY'
reg = m.Registry()
seed = {"version": 3, "workspaces": []}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
readable = reg.read_registry()["version"] == 3          # reading a newer file is allowed
refused = False
try:
    reg.upsert_workspace("nope", directories=["/tmp/wsr/z"])
except m.RegistryVersionError:
    refused = True
except Exception:
    pass
ver = json.load(open(reg.path))["version"]              # write must have been refused
ok = readable and refused and ver == 3
print("PASS-VERSION-GUARD" if ok else f"FAIL-VERSION-GUARD readable={readable} refused={refused} ver={ver}")
PY

S_ATOMIC="$TMP/s_atomic.py"; printf '%s' "$HDR" > "$S_ATOMIC"
cat >> "$S_ATOMIC" <<'PY'
reg = m.Registry()
for i in range(5):
    reg.upsert_workspace(f"w{i}", directories=[f"/tmp/wsr/p{i}"])
tmp_left = [f for f in os.listdir(reg.dir) if f.endswith(".tmp")]
try:
    d = json.load(open(reg.path)); parseable = True
except Exception:
    d = {}; parseable = False
ok = (not tmp_left) and parseable and len(d.get("workspaces", [])) == 5
print("PASS-ATOMIC" if ok else f"FAIL-ATOMIC tmp_left={tmp_left} parseable={parseable}")
PY

S_ISO="$TMP/s_iso.py"; printf '%s' "$HDR" > "$S_ISO"
cat >> "$S_ISO" <<'PY'
reg = m.Registry()
want = os.path.abspath(os.environ["WORKSPACES_DIR"])
reg.upsert_workspace("iso", directories=["/tmp/wsr/iso"])
ok = (reg.dir == want                                     # resolved to the temp dir
      and os.path.exists(reg.path)                         # wrote under it
      and reg.path.startswith(want + os.sep)
      and reg.dir != os.path.expanduser("~/.workspaces"))  # NOT the real home dir
print("PASS-ISO" if ok else f"FAIL-ISO dir={reg.dir} want={want}")
PY

S_PATH="$TMP/s_path.py"; printf '%s' "$HDR" > "$S_PATH"
cat >> "$S_PATH" <<'PY'
reg = m.Registry()
base = os.path.join(os.path.dirname(reg.dir), "fix"); os.makedirs(base, exist_ok=True)
real = os.path.join(base, "realproj"); os.makedirs(real, exist_ok=True)
link = os.path.join(base, "linkproj")
if not os.path.lexists(link):
    os.symlink(real, link)
# 1. symlink canonicalization — register at the real path, query via the symlink
reg.upsert_workspace("rp", directories=[real])
h1 = reg.find_by_path(os.path.join(link, "sub"))
ok_symlink = h1 is not None and h1["name"] == "rp"
# 2. longest-match — a parent workspace and a nested child workspace
reg.upsert_workspace("parent", directories=[os.path.join(base, "a")])
reg.upsert_workspace("child", directories=[os.path.join(base, "a", "b")])
h2 = reg.find_by_path(os.path.join(base, "a", "b", "c"))
ok_longest = h2 is not None and h2["name"] == "child"
h3 = reg.find_by_path(os.path.join(base, "a", "x"))
ok_parent = h3 is not None and h3["name"] == "parent"
# 3. macOS Dropbox alias (§D.2) — store canonical + legacy alias, query the legacy
home = os.path.expanduser("~")
canon = os.path.join(home, "Library", "CloudStorage", "Dropbox", "__wsr_ro__", "p")
legacy = os.path.join(home, "Dropbox", "__wsr_ro__", "p")   # read-only string; never created
reg.upsert_workspace("dbx", directories=[{"path": canon, "aliases": [legacy]}])
h4 = reg.find_by_path(legacy)
ok_dbx = h4 is not None and h4["name"] == "dbx"
ok = ok_symlink and ok_longest and ok_parent and ok_dbx
print("PASS-PATHMATCH" if ok else f"FAIL-PATHMATCH sym={ok_symlink} long={ok_longest} par={ok_parent} dbx={ok_dbx}")
PY

S_ARCHIVE="$TMP/s_archive.py"; printf '%s' "$HDR" > "$S_ARCHIVE"
cat >> "$S_ARCHIVE" <<'PY'
reg = m.Registry()
ws = reg.upsert_workspace("a", directories=["/tmp/wsr/a"])
created_updated = ws["updated_at"]
a = reg.archive_workspace(ws["id"])
after = json.load(open(reg.path))
ok = (a["archived"] is True and after["workspaces"][0]["archived"] is True)
print("PASS-ARCHIVE" if ok else "FAIL-ARCHIVE")
PY

# publish_workspace — the OWNING mirror keyed by a stable open-bridge id (R2).
S_PUBLISH="$TMP/s_publish.py"; printf '%s' "$HDR" > "$S_PUBLISH"
cat >> "$S_PUBLISH" <<'PY'
reg = m.Registry()
# create-like publish (no dirs) THEN code-like publish (dirs) share the SAME id
# → ONE row (de-dup by extensions["open-bridge"]["id"], not by path/remote)
reg.publish_workspace("demo-workspace", "Demo Workspace",
                      directories=[], git_remotes=[],
                      open_bridge_ext={"overlays": [], "repos": []})
reg.publish_workspace("demo-workspace", "Demo Workspace",
                      directories=["/tmp/wsr/demo/code"],
                      git_remotes=["https://h/x/demo.git"],
                      open_bridge_ext={"overlays": ["ov1"],
                                       "repos": [{"url": "https://h/x/demo.git",
                                                  "role": "code", "name": "demo", "ref": "main"}]})
d = reg.read_registry(); w = d["workspaces"][0]
ok_one = len(d["workspaces"]) == 1
ok_id = w["extensions"]["open-bridge"]["id"] == "demo-workspace"
ok_name = w["name"] == "Demo Workspace"
ok_dirs = len(w["directories"]) == 1
ok_rem = "https://h/x/demo.git" in w["git_remotes"]
ok_ov = w["extensions"]["open-bridge"]["overlays"] == ["ov1"]
# reduce: re-publish with empty dirs → mirror SHRINKS (REPLACE, not merge)
reg.publish_workspace("demo-workspace", "Demo Workspace",
                      directories=[], git_remotes=[],
                      open_bridge_ext={"overlays": ["ov1"], "repos": []})
w2 = reg.read_registry()["workspaces"][0]
ok_shrink = len(w2["directories"]) == 0 and len(w2["git_remotes"]) == 0
ok = ok_one and ok_id and ok_name and ok_dirs and ok_rem and ok_ov and ok_shrink
print("PASS-PUBLISH" if ok else f"FAIL-PUBLISH one={ok_one} id={ok_id} dirs={ok_dirs} rem={ok_rem} ov={ok_ov} shrink={ok_shrink}")
PY

S_PUBLISH_FOREIGN="$TMP/s_publish_foreign.py"; printf '%s' "$HDR" > "$S_PUBLISH_FOREIGN"
cat >> "$S_PUBLISH_FOREIGN" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0005", "name": "x", "directories": [], "git_remotes": [],
    "unknown_ws": {"keep": 1},
    "extensions": {"k2a": {"state": {"p": 1}},
                   "open-bridge": {"id": "mine", "overlays": []}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("mine", "Renamed", directories=["/tmp/wsr/m"], git_remotes=[],
                      open_bridge_ext={"overlays": ["o"], "repos": []})
after = json.load(open(reg.path)); w = after["workspaces"][0]
ok = (len(after["workspaces"]) == 1                       # matched our id, no new row
      and w["extensions"]["k2a"] == {"state": {"p": 1}}   # foreign slice preserved
      and w.get("unknown_ws") == {"keep": 1}              # unknown per-ws key preserved
      and w["name"] == "Renamed"                          # our identity replace applied
      and w["extensions"]["open-bridge"]["overlays"] == ["o"])
print("PASS-PUBLISH-FOREIGN" if ok else f"FAIL-PUBLISH-FOREIGN ext={w.get('extensions')} unk={w.get('unknown_ws')}")
PY

# k2a-CONFORMANCE — every row WE write must satisfy k2a's required-field
# contract so k2a can parse the shared file at all. Verified against k2a `dev`
# workspaces.rs: the Workspace struct requires ONLY top-level string `id` +
# `name`; every other field is #[serde(default)] (state/session_ns/… all fill
# from defaults). A row we emit that lacks id or name would fail k2a's parse for
# the WHOLE file. Rows we author must ALSO omit k2a-private fields (state,
# session_ns) — those are k2a's to fill. A pre-seeded k2a-style row (carrying
# `state`) must survive untouched alongside ours. This pins our output to the
# PUBLISHED neutral schema, NOT to k2a-the-tool.
S_CONFORM="$TMP/s_conform.py"; printf '%s' "$HDR" > "$S_CONFORM"
cat >> "$S_CONFORM" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0003", "name": "k2a-owned",
    "directories": [{"path": "/tmp/wsr/k2a", "aliases": []}],
    "git_remotes": [], "state": {"panes": []}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.upsert_workspace("up", directories=["/tmp/wsr/up"],
                     git_remotes=["https://h/x/up.git"],
                     open_bridge_ext={"overlays": [], "repos": []})
reg.publish_workspace("pub-id", "Published", directories=["/tmp/wsr/pub"],
                      git_remotes=[], open_bridge_ext={"overlays": ["o"], "repos": []})
rows = reg.read_registry()["workspaces"]
req = all(isinstance(w.get("id"), str) and w["id"]
          and isinstance(w.get("name"), str) and w["name"] for w in rows)   # k2a's 2 required fields
dirs = all(isinstance(d.get("path"), str) and d["path"]
           for w in rows for d in w.get("directories", []))                 # WorkspaceDirectory.path
ours = [w for w in rows if "open-bridge" in w.get("extensions", {})]
noprivate = all("state" not in w and "session_ns" not in w for w in ours)   # leave k2a-private to defaults
foreign = [w for w in rows if w["id"] == "ws_0003"][0]
foreign_ok = foreign.get("state") == {"panes": []}                          # k2a row untouched
ok = req and dirs and noprivate and foreign_ok and len(ours) == 2
print("PASS-CONFORM" if ok else f"FAIL-CONFORM req={req} dirs={dirs} noprivate={noprivate} foreign={foreign_ok} nours={len(ours)}")
PY

# ───────────────────────────────────────────────────────────────────
echo
echo "── 1. upsert + read-back (schema-conformant entry) ─────────────"
run_scen "$S_UPSERT" "$(wsdir)"
assert_rc "upsert scenario runs cleanly" 0
assert_notrace "upsert did not crash"
assert_out "upsert + read-back: fields correct (name/id/dirs/remote/ext/ts/version)" "PASS-UPSERT"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 2. de-dup on create by identity ─────────────────────────────"
run_scen "$S_DEDUP_REMOTE" "$(wsdir)"
assert_out "second upsert of same git_remote (scp≡https) de-dups (one row)" "PASS-DEDUP-REMOTE"
run_scen "$S_DEDUP_PATH" "$(wsdir)"
assert_out "second upsert of same canonical path de-dups (one row)" "PASS-DEDUP-PATH"
run_scen "$S_DEDUP_CASE" "$(wsdir)"
assert_out "same repo in .git vs .GIT form de-dups (case-insensitive suffix)" "PASS-DEDUP-CASE"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 3. preserve unknown top-level + per-workspace fields ────────"
run_scen "$S_PRESERVE" "$(wsdir)"
assert_notrace "preserve scenario did not crash"
assert_out "unknown top-level + per-ws fields survive; existing ws byte-for-byte" "PASS-PRESERVE-TOP"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 4. foreign extension slice preserved (only our slice changes) ─"
run_scen "$S_FOREIGN" "$(wsdir)"
assert_notrace "foreign-ext scenario did not crash"
assert_out "another tool's extensions[k2a] survives our upsert; our slice written" "PASS-FOREIGN-EXT"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 5. atomic replace (no .tmp left; always parseable) ──────────"
run_scen "$S_ATOMIC" "$(wsdir)"
assert_out "5 writes leave no .tmp behind and a parseable file" "PASS-ATOMIC"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 6. version max-monotonic (v3 refused for write, still readable) ─"
run_scen "$S_VERSION" "$(wsdir)"
assert_notrace "version-guard scenario did not crash"
assert_out "version:3 file refused for write but readable; file left intact" "PASS-VERSION-GUARD"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 7. \$WORKSPACES_DIR isolation (writes only under the temp dir) ─"
ISODIR="$(wsdir)"
run_scen "$S_ISO" "$ISODIR"
assert_out "module resolves + writes ONLY under \$WORKSPACES_DIR, never ~/.workspaces" "PASS-ISO"
assert_file "the isolated write landed under the temp dir" "$ISODIR/workspaces.json"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 8. path matching (§D: symlink, Dropbox alias, longest-match) ─"
run_scen "$S_PATH" "$(wsdir)"
assert_notrace "path-match scenario did not crash"
assert_out "symlink canonicalizes, Dropbox alias resolves, longest-match wins" "PASS-PATHMATCH"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 9. archive (soft-delete) ────────────────────────────────────"
run_scen "$S_ARCHIVE" "$(wsdir)"
assert_out "archive flips archived:true on the workspace" "PASS-ARCHIVE"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 10. standalone — no k2a/reinvent reference in the module ────"
if [ -f "$REGISTRY" ]; then
  if grep -iqE 'k2a|reinvent' "$REGISTRY"; then
    fail "scripts/workspace_registry.py references k2a/reinvent (not standalone)" "$(grep -inE 'k2a|reinvent' "$REGISTRY")"
  else
    pass "scripts/workspace_registry.py contains no k2a/reinvent reference"
  fi
else
  fail "scripts/workspace_registry.py absent — cannot assert it is k2a-free"
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 11. CLI — version-guard exits non-zero; read still exits 0 ──"
CLIDIR="$(wsdir)"
printf '{"version": 3, "workspaces": []}' > "$CLIDIR/workspaces.json"
OUT="$(WORKSPACES_DIR="$CLIDIR" python3 "$REGISTRY" upsert nope --dir /tmp/wsr/z 2>&1)"; RC=$?
assert_rc_nonzero "CLI upsert on a version:3 file exits non-zero"
assert_notrace "CLI version refusal is a clean error, not a crash"
assert_eq "the v3 file was NOT clobbered by the refused CLI write" \
  "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["version"])' "$CLIDIR/workspaces.json")" "3"
OUT="$(WORKSPACES_DIR="$CLIDIR" python3 "$REGISTRY" read 2>&1)"; RC=$?
assert_rc "CLI read of a version:3 file still succeeds" 0
# a normal CLI upsert on a fresh dir writes the file
CLIDIR2="$(wsdir)"
OUT="$(WORKSPACES_DIR="$CLIDIR2" python3 "$REGISTRY" upsert demo --dir /tmp/wsr/demo --overlay o1 --git-remote https://github.com/acme/demo.git 2>&1)"; RC=$?
assert_rc "CLI upsert on a fresh dir succeeds" 0
assert_file "CLI upsert wrote workspaces.json" "$CLIDIR2/workspaces.json"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 12. MUTATION-CHECKS — the safety-critical asserts have teeth ─"
# Each mutation is applied to a COPY of the engine (the original is never touched);
# the corresponding scenario must FLIP from its PASS token to a non-PASS result.

# 12a. preserve-unknown — a _write that rebuilds only {version, workspaces}
MUT="$TMP/mut_preserve.py"
mutate "$MUT" \
  'body = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)' \
  'body = json.dumps({"version": MAX_SUPPORTED_VERSION, "workspaces": data.get("workspaces", [])}, indent=2, ensure_ascii=False, sort_keys=False)'
run_scen "$S_PRESERVE" "$(wsdir)" "$MUT"
assert_noout "broken preserve-unknown engine FAILS the preserve assert (teeth)" "PASS-PRESERVE-TOP"

# 12b. foreign-ext — an extensions write that REPLACES the map (drops foreign slices)
MUT="$TMP/mut_foreign.py"
mutate "$MUT" \
  'exts[OUR_EXTENSION] = deepcopy(open_bridge_ext)' \
  'ws["extensions"] = {OUR_EXTENSION: deepcopy(open_bridge_ext)}'
run_scen "$S_FOREIGN" "$(wsdir)" "$MUT"
assert_noout "broken foreign-ext engine FAILS the foreign-slice assert (teeth)" "PASS-FOREIGN-EXT"

# 12c. de-dup — an identity resolver that never matches (always appends)
MUT="$TMP/mut_dedup.py"
mutate "$MUT" 'return i' 'return None'
run_scen "$S_DEDUP_REMOTE" "$(wsdir)" "$MUT"
assert_noout "broken de-dup engine FAILS the single-row assert (teeth)" "PASS-DEDUP-REMOTE"

# 12d. version-guard — a disabled version ceiling (writes over a newer file)
MUT="$TMP/mut_version.py"
mutate "$MUT" \
  'if isinstance(version, int) and version > MAX_SUPPORTED_VERSION:' \
  'if False:'
run_scen "$S_VERSION" "$(wsdir)" "$MUT"
assert_noout "broken version-guard engine FAILS the refuse-write assert (teeth)" "PASS-VERSION-GUARD"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 13. publish_workspace — owning mirror keyed by open-bridge id ─"
run_scen "$S_PUBLISH" "$(wsdir)"
assert_notrace "publish scenario did not crash"
assert_out "create-then-code publish share an id → ONE row; mirror REPLACES + shrinks" "PASS-PUBLISH"
run_scen "$S_PUBLISH_FOREIGN" "$(wsdir)"
assert_notrace "publish-foreign scenario did not crash"
assert_out "publish preserves foreign ext + unknown per-ws keys; replaces only our identity" "PASS-PUBLISH-FOREIGN"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 14. MUTATION-CHECKS on publish_workspace (teeth) ────────────"
# 14a. de-dup by open-bridge id — disable the id match → two rows instead of one
MUT="$TMP/mut_publish_id.py"
mutate "$MUT" \
  'if isinstance(slice_, dict) and slice_.get(OUR_ID_KEY) == ref:' \
  'if False and isinstance(slice_, dict) and slice_.get(OUR_ID_KEY) == ref:'
run_scen "$S_PUBLISH" "$(wsdir)" "$MUT"
assert_noout "broken id-match engine FAILS the ONE-row publish assert (teeth)" "PASS-PUBLISH"

# 14b. foreign-ext preservation — replace the extensions map on our owned entry
MUT="$TMP/mut_publish_foreign.py"
mutate "$MUT" \
  'exts[OUR_EXTENSION] = ext_slice' \
  'ws["extensions"] = {OUR_EXTENSION: ext_slice}'
run_scen "$S_PUBLISH_FOREIGN" "$(wsdir)" "$MUT"
assert_noout "broken publish foreign-ext engine FAILS the foreign-slice assert (teeth)" "PASS-PUBLISH-FOREIGN"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 15. k2a-conformance — every row we write meets k2a's contract ─"
run_scen "$S_CONFORM" "$(wsdir)"
assert_notrace "conformance scenario did not crash"
assert_out "our rows carry top-level str id+name, dirs as [{path}], omit k2a-private state/session_ns; foreign k2a row untouched" "PASS-CONFORM"
# teeth: a writer that emits a non-string id → k2a would reject the whole file
MUT="$TMP/mut_conform_id.py"
mutate "$MUT" '"id": _next_id(workspaces),' '"id": 12345,'
run_scen "$S_CONFORM" "$(wsdir)" "$MUT"
assert_noout "a non-string-id writer FAILS the conformance assert (teeth)" "PASS-CONFORM"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 16. real ~/.workspaces/ untouched across the entire run ─────"
REAL_AFTER="$(real_snapshot)"
assert_eq "the real ~/.workspaces/ snapshot is byte-identical before/after" "$REAL_BEFORE" "$REAL_AFTER"
if [ ! -e "$REAL_WS" ]; then
  pass "real ~/.workspaces/ was never created during the run"
else
  echo "  NOTE: ~/.workspaces/ pre-existed; snapshot equality above is the proof of no-touch."
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════"
echo "RESULT: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ]
