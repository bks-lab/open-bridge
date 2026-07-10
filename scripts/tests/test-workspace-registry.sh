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
#   -  foreign-extension preservation — another tool's extensions["cowriter"] slice
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
#   -  standalone — the module source names no specific co-writer tool
#   -  CLI — version-guard exits non-zero, read still exits 0
#   -  guarded structural adopt (publish, §C.3 rule 3) — a peer tool's row with
#      NO open-bridge slice is ADOPTED (merge semantics, foreign fields preserved,
#      name kept unless empty/auto-generated) on a shared remote OR path; two
#      ambiguous candidates or a foreign open-bridge id → mint instead
#   -  fail-closed anomaly path — a corrupt file / missing-version REFUSES the
#      write (bytes untouched, no .bak); version "2"/2.0 coerce and proceed; a
#      genuine v1 file rotates LOUDLY to a TIMESTAMPED .bak (a second rotation
#      never clobbers the first)
#   -  TEETH — a real concurrency case (12 parallel writers, all rows + unique ids
#      survive) with a no-flock mutant that must LOSE updates; a real atomicity
#      case (a concurrent reader parses every snapshot during rapid writes) with a
#      non-atomic-write mutant that must produce a torn read
#   -  MUTATION-CHECKS on the safety-critical asserts (preserve-unknown,
#      foreign-ext, de-dup, version-guard, publish, adopt, flock, atomic-replace):
#      break a COPY of the engine, confirm the corresponding assert now FAILS (has
#      teeth), discard the copy (original never touched).
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
ws = reg.upsert_workspace("cowriter",
        directories=["/tmp/wsr/cowriter"],
        git_remotes=["https://github.com/acme/cowriter.git"],
        open_bridge_ext={"overlays": ["o"], "repos": ["r"]})
d = reg.read_registry()
w = d["workspaces"][0]
ok = (d["version"] == 2 and len(d["workspaces"]) == 1
      and w["name"] == "cowriter" and w["id"] == "ws_0001" and w["archived"] is False
      and w["directories"][0]["path"] == os.path.realpath("/tmp/wsr/cowriter")
      and "https://github.com/acme/cowriter.git" in w["git_remotes"]
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
    "extensions": {"cowriter": {"state": {"panes": 2}, "flags": ["--a"]}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.upsert_workspace("proj", git_remotes=["https://github.com/acme/proj.git"],
                     open_bridge_ext={"overlays": ["o1"]})
after = json.load(open(reg.path))
w = after["workspaces"][0]
ok = (len(after["workspaces"]) == 1                                       # de-dup held
      and w["extensions"]["cowriter"] == {"state": {"panes": 2}, "flags": ["--a"]}  # foreign slice intact
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
    "extensions": {"cowriter": {"state": {"p": 1}},
                   "open-bridge": {"id": "mine", "overlays": []}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("mine", "Renamed", directories=["/tmp/wsr/m"], git_remotes=[],
                      open_bridge_ext={"overlays": ["o"], "repos": []})
after = json.load(open(reg.path)); w = after["workspaces"][0]
ok = (len(after["workspaces"]) == 1                       # matched our id, no new row
      and w["extensions"]["cowriter"] == {"state": {"p": 1}}   # foreign slice preserved
      and w.get("unknown_ws") == {"keep": 1}              # unknown per-ws key preserved
      and w["name"] == "Renamed"                          # our identity replace applied
      and w["extensions"]["open-bridge"]["overlays"] == ["o"])
print("PASS-PUBLISH-FOREIGN" if ok else f"FAIL-PUBLISH-FOREIGN ext={w.get('extensions')} unk={w.get('unknown_ws')}")
PY

# CO-WRITER CONFORMANCE — every row WE write must satisfy a conformant co-writer's
# required-field contract so another tool can parse the shared file at all. Per the
# external tool-neutral design: the workspace struct requires ONLY top-level string
# `id` + `name`; every other field defaults (state/session_ns/… all fill from
# defaults). A row we emit that lacks id or name would fail a co-writer's parse for
# the WHOLE file. Rows we author must ALSO omit co-writer-private fields (state,
# session_ns) — those are a co-writer's to fill. A pre-seeded co-writer-style row
# (carrying `state`) must survive untouched alongside ours. This pins our output to
# the PUBLISHED neutral schema, NOT to any one tool.
S_CONFORM="$TMP/s_conform.py"; printf '%s' "$HDR" > "$S_CONFORM"
cat >> "$S_CONFORM" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0003", "name": "cowriter-owned",
    "directories": [{"path": "/tmp/wsr/cowriter", "aliases": []}],
    "git_remotes": [], "state": {"panes": []}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.upsert_workspace("up", directories=["/tmp/wsr/up"],
                     git_remotes=["https://h/x/up.git"],
                     open_bridge_ext={"overlays": [], "repos": []})
reg.publish_workspace("pub-id", "Published", directories=["/tmp/wsr/pub"],
                      git_remotes=[], open_bridge_ext={"overlays": ["o"], "repos": []})
rows = reg.read_registry()["workspaces"]
req = all(isinstance(w.get("id"), str) and w["id"]
          and isinstance(w.get("name"), str) and w["name"] for w in rows)   # cowriter's 2 required fields
dirs = all(isinstance(d.get("path"), str) and d["path"]
           for w in rows for d in w.get("directories", []))                 # WorkspaceDirectory.path
ours = [w for w in rows if "open-bridge" in w.get("extensions", {})]
noprivate = all("state" not in w and "session_ns" not in w for w in ours)   # leave cowriter-private to defaults
foreign = [w for w in rows if w["id"] == "ws_0003"][0]
foreign_ok = foreign.get("state") == {"panes": []}                          # cowriter row untouched
ok = req and dirs and noprivate and foreign_ok and len(ours) == 2
print("PASS-CONFORM" if ok else f"FAIL-CONFORM req={req} dirs={dirs} noprivate={noprivate} foreign={foreign_ok} nours={len(ours)}")
PY

# publish → guarded structural ADOPT (§C.3 rule 3): a peer tool's row that carries
# NO open-bridge slice is ADOPTED with MERGE semantics when EXACTLY one row shares
# our identity — foreign fields survive, the name is kept unless empty/generated.

# 16a. adopt by shared normalized remote (scp≡https); merge unions remotes.
S_ADOPT_REMOTE="$TMP/s_adopt_remote.py"; printf '%s' "$HDR" > "$S_ADOPT_REMOTE"
cat >> "$S_ADOPT_REMOTE" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0007", "name": "cowriter-native", "name_generated": False,
    "directories": [{"path": "/tmp/wsr/cowriter", "aliases": []}],
    "git_remotes": ["git@github.com:acme/cowriter.git"],   # scp form
    "state": {"panes": 3}, "session_ns": "abc",
    "resource_refs": [{"kind": "doc", "id": "d1"}],
    "extensions": {"cowriter": {"flags": ["--x"]}},
    "weird": {"keep": 1}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("abc123def456:cowriter", "OB Name",
                      directories=["/tmp/wsr/cowriter"],
                      git_remotes=["https://github.com/acme/cowriter.git",   # SAME repo (deduped)
                                   "https://github.com/acme/extra.git"],  # NEW (merged in)
                      open_bridge_ext={"overlays": ["o1"], "repos": []})
after = json.load(open(reg.path)); w = after["workspaces"][0]
ok = (len(after["workspaces"]) == 1                                       # adopted, no new row
      and w["id"] == "ws_0007"                                           # SAME row
      and w["name"] == "cowriter-native"                                      # name kept (not generated)
      and w["state"] == {"panes": 3} and w["session_ns"] == "abc"        # cowriter-private preserved
      and w["resource_refs"] == [{"kind": "doc", "id": "d1"}]            # resource_refs preserved
      and w["extensions"]["cowriter"] == {"flags": ["--x"]}                   # foreign ext preserved
      and w.get("weird") == {"keep": 1}                                  # unknown key preserved
      and w["extensions"]["open-bridge"]["id"] == "abc123def456:cowriter"     # our slice parked
      and w["extensions"]["open-bridge"]["overlays"] == ["o1"]
      and w["git_remotes"] == ["git@github.com:acme/cowriter.git",            # MERGE: kept + deduped + added
                               "https://github.com/acme/extra.git"]
      and len(w["directories"]) == 1)
print("PASS-ADOPT-REMOTE" if ok else f"FAIL-ADOPT-REMOTE w={w}")
PY

# 16b. adopt by shared canonical directory; merge unions directories.
S_ADOPT_PATH="$TMP/s_adopt_path.py"; printf '%s' "$HDR" > "$S_ADOPT_PATH"
cat >> "$S_ADOPT_PATH" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0004", "name": "native", "name_generated": False,
    "directories": [{"path": "/tmp/wsr/shared", "aliases": []}],
    "git_remotes": [], "extensions": {"cowriter": {"s": 1}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("h:shared", "OB",
                      directories=["/tmp/wsr/shared/", "/tmp/wsr/shared/code"],  # trailing-slash ≡ same
                      git_remotes=[], open_bridge_ext={"overlays": [], "repos": []})
after = json.load(open(reg.path)); w = after["workspaces"][0]
paths = [d["path"] for d in w["directories"]]
ok = (len(after["workspaces"]) == 1 and w["id"] == "ws_0004"
      and w["name"] == "native"                              # name kept
      and w["extensions"]["cowriter"] == {"s": 1}                 # foreign ext preserved
      and w["extensions"]["open-bridge"]["id"] == "h:shared"
      and len(w["directories"]) == 2                          # merged, not replaced
      and "/tmp/wsr/shared" in paths                          # existing entry preserved as-is
      and os.path.realpath("/tmp/wsr/shared/code") in paths)  # new dir merged in (canonical)
print("PASS-ADOPT-PATH" if ok else f"FAIL-ADOPT-PATH w={w}")
PY

# 16c. name overwrite rules — empty OR name_generated → overwrite; curated → keep.
S_ADOPT_NAME="$TMP/s_adopt_name.py"; printf '%s' "$HDR" > "$S_ADOPT_NAME"
cat >> "$S_ADOPT_NAME" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [
    {"id": "ws_0001", "name": "", "name_generated": False,
     "directories": [], "git_remotes": ["https://h/x/empty.git"], "extensions": {"cowriter": {}}},
    {"id": "ws_0002", "name": "auto", "name_generated": True,
     "directories": [], "git_remotes": ["https://h/x/gen.git"], "extensions": {"cowriter": {}}},
    {"id": "ws_0003", "name": "curated", "name_generated": False,
     "directories": [], "git_remotes": ["https://h/x/keep.git"], "extensions": {"cowriter": {}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("h:empty", "FromEmpty", git_remotes=["https://h/x/empty.git"], open_bridge_ext={"overlays": []})
reg.publish_workspace("h:gen", "FromGen", git_remotes=["https://h/x/gen.git"], open_bridge_ext={"overlays": []})
reg.publish_workspace("h:keep", "ShouldNotApply", git_remotes=["https://h/x/keep.git"], open_bridge_ext={"overlays": []})
rows = {w["id"]: w for w in json.load(open(reg.path))["workspaces"]}
ok = (len(rows) == 3                                          # all adopted, none minted
      and rows["ws_0001"]["name"] == "FromEmpty"             # empty name → overwritten
      and rows["ws_0002"]["name"] == "FromGen"               # name_generated → overwritten
      and rows["ws_0003"]["name"] == "curated"               # curated name → preserved
      and rows["ws_0001"]["extensions"]["open-bridge"]["id"] == "h:empty"
      and rows["ws_0003"]["extensions"]["open-bridge"]["id"] == "h:keep")
print("PASS-ADOPT-NAME" if ok else "FAIL-ADOPT-NAME n1=%r n2=%r n3=%r count=%d" % (
      rows.get("ws_0001", {}).get("name"), rows.get("ws_0002", {}).get("name"),
      rows.get("ws_0003", {}).get("name"), len(rows)))
PY

# 16d. two ambiguous structural candidates → mint (adopt NEITHER).
S_ADOPT_AMBIG="$TMP/s_adopt_ambig.py"; printf '%s' "$HDR" > "$S_ADOPT_AMBIG"
cat >> "$S_ADOPT_AMBIG" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [
    {"id": "ws_0001", "name": "A", "directories": [], "git_remotes": ["https://h/x/one.git"], "extensions": {"cowriter": {}}},
    {"id": "ws_0002", "name": "B", "directories": [], "git_remotes": ["https://h/x/two.git"], "extensions": {"cowriter": {}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("h:both", "Both", directories=[],
                      git_remotes=["https://h/x/one.git", "https://h/x/two.git"],  # matches BOTH
                      open_bridge_ext={"overlays": []})
after = json.load(open(reg.path))
minted = [w for w in after["workspaces"] if w.get("extensions", {}).get("open-bridge", {}).get("id") == "h:both"]
ok = (len(after["workspaces"]) == 3                                              # ambiguous → new row minted
      and after["workspaces"][0]["name"] == "A" and "open-bridge" not in after["workspaces"][0]["extensions"]
      and after["workspaces"][1]["name"] == "B" and "open-bridge" not in after["workspaces"][1]["extensions"]
      and len(minted) == 1)
print("PASS-ADOPT-AMBIG" if ok else f"FAIL-ADOPT-AMBIG n={len(after['workspaces'])} minted={len(minted)}")
PY

# 16e. a structurally-matching row carrying a FOREIGN open-bridge id → never adopt → mint.
S_ADOPT_FOREIGNID="$TMP/s_adopt_foreignid.py"; printf '%s' "$HDR" > "$S_ADOPT_FOREIGNID"
cat >> "$S_ADOPT_FOREIGNID" <<'PY'
reg = m.Registry()
seed = {"version": 2, "workspaces": [{
    "id": "ws_0006", "name": "theirs", "directories": [],
    "git_remotes": ["https://h/x/shared.git"],
    "extensions": {"open-bridge": {"id": "other-instance:foo", "overlays": []}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
reg.publish_workspace("me:foo", "Mine", directories=[],
                      git_remotes=["https://h/x/shared.git"],   # SAME remote as the foreign-id row
                      open_bridge_ext={"overlays": ["o"]})
after = json.load(open(reg.path))
ok = (len(after["workspaces"]) == 2                                                       # NOT adopted → minted
      and after["workspaces"][0]["extensions"]["open-bridge"]["id"] == "other-instance:foo"  # untouched
      and after["workspaces"][0]["name"] == "theirs"
      and after["workspaces"][1]["extensions"]["open-bridge"]["id"] == "me:foo")
print("PASS-ADOPT-FOREIGNID" if ok else f"FAIL-ADOPT-FOREIGNID n={len(after['workspaces'])}")
PY

# 16f. adopt-then-republish (the create→subscribe flow): after a structural ADOPT
# parks our id on a peer row, the NATURALLY-following id-match publish must MERGE
# (not wholesale-REPLACE) — the peer's curated name + peer-only dirs/remotes + its
# private/foreign fields survive, and only OUR own contributed subset can shrink.
S_ADOPT_REPUBLISH="$TMP/s_adopt_republish.py"; printf '%s' "$HDR" > "$S_ADOPT_REPUBLISH"
cat >> "$S_ADOPT_REPUBLISH" <<'PY'
reg = m.Registry()
# A peer tool (cowriter) row — curated name, a peer-only extra dir + remote, private
# state/session, a foreign extension slice: the exact shape create→subscribe hits.
seed = {"version": 2, "workspaces": [{
    "id": "ws_0011", "name": "cowriter-native", "name_generated": False,
    "directories": [{"path": "/tmp/wsr/cowriter", "aliases": []},
                    {"path": "/tmp/wsr/cowriter-only-extra", "aliases": []}],
    "git_remotes": ["git@github.com:acme/cowriter.git",                 # shared identity (scp form)
                    "https://github.com/acme/cowriter-only.git"],        # peer-only extra remote
    "state": {"panes": 4}, "session_ns": "s9",
    "resource_refs": [{"kind": "doc", "id": "d1"}],
    "extensions": {"cowriter": {"flags": ["--z"]}}}]}
os.makedirs(reg.dir, exist_ok=True); json.dump(seed, open(reg.path, "w"))
REF = "abc123abc123:demo"
# publish #1 = the `create` publish → structural ADOPT (shared remote), our clone
# dir + slice parked onto the peer row (peer curation kept).
reg.publish_workspace(REF, "demo", directories=["/tmp/wsr/ours-clone"],
                      git_remotes=["https://github.com/acme/cowriter.git"],  # ≡ the scp remote
                      open_bridge_ext={"overlays": [], "repos": []})
# publish #2 = the `subscribe` publish that NATURALLY follows create — id-match.
# THIS is the regression: on an adopted row it must MERGE, keeping the name guard.
reg.publish_workspace(REF, "demo", directories=["/tmp/wsr/ours-clone"],
                      git_remotes=["https://github.com/acme/cowriter.git"],
                      open_bridge_ext={"overlays": ["o"], "repos": []})
w = json.load(open(reg.path))["workspaces"]; rows = w; w = rows[0]
paths = [d["path"] for d in w["directories"]]
merged = (len(rows) == 1                                            # still ONE row
          and w["id"] == "ws_0011"                                 # adopted row, not re-minted
          and w["name"] == "cowriter-native"                            # peer name KEPT (not 'demo')
          and "/tmp/wsr/cowriter-only-extra" in paths                   # peer-only dir survived #2 (as-seeded)
          and os.path.realpath("/tmp/wsr/ours-clone") in paths     # our clone present (canonicalized)
          and "https://github.com/acme/cowriter-only.git" in w["git_remotes"]  # peer-only remote survived
          and w["state"] == {"panes": 4} and w["session_ns"] == "s9"      # cowriter-private preserved
          and w["resource_refs"] == [{"kind": "doc", "id": "d1"}]
          and w["extensions"]["cowriter"] == {"flags": ["--z"]}         # foreign ext preserved
          and w["extensions"]["open-bridge"]["id"] == REF
          and w["extensions"]["open-bridge"]["overlays"] == ["o"]) # our slice refreshed
# publish #3 drops OUR clone dir → only OUR contribution shrinks; peer fields stay.
reg.publish_workspace(REF, "demo", directories=[],
                      git_remotes=["https://github.com/acme/cowriter.git"],
                      open_bridge_ext={"overlays": ["o"], "repos": []})
w3 = json.load(open(reg.path))["workspaces"][0]
p3 = [d["path"] for d in w3["directories"]]
shrink = (os.path.realpath("/tmp/wsr/ours-clone") not in p3        # our clone pruned (shrink)
          and "/tmp/wsr/cowriter-only-extra" in p3                      # peer dir untouched (as-seeded)
          and "/tmp/wsr/cowriter" in p3                                 # peer dir untouched (as-seeded)
          and "https://github.com/acme/cowriter-only.git" in w3["git_remotes"])  # peer remote untouched
ok = merged and shrink
print("PASS-ADOPT-REPUBLISH" if ok else f"FAIL-ADOPT-REPUBLISH merged={merged} shrink={shrink} w={w} w3={w3}")
PY

# fail-closed anomaly path (S3): corrupt / missing-version REFUSE the write untouched;
# "2"/2.0 coerce; a genuine v1 file rotates LOUDLY to a timestamped .bak.

S_CORRUPT="$TMP/s_corrupt.py"; printf '%s' "$HDR" > "$S_CORRUPT"
cat >> "$S_CORRUPT" <<'PY'
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
open(reg.path, "wb").write(b'{ this is not valid json ')
before = open(reg.path, "rb").read()
refused = False; msg = ""
try:
    reg.upsert_workspace("x", directories=["/tmp/wsr/x"])
except m.RegistryError as e:
    refused = True; msg = str(e)
except Exception as e:
    msg = "WRONG:" + repr(e)
after = open(reg.path, "rb").read()
baks = [f for f in os.listdir(reg.dir) if ".bak" in f]
ok = refused and after == before and not baks and "refusing to guess" in msg
print("PASS-CORRUPT" if ok else f"FAIL-CORRUPT refused={refused} same={after == before} baks={baks} msg={msg!r}")
PY

S_VER_STR="$TMP/s_ver_str.py"; printf '%s' "$HDR" > "$S_VER_STR"
cat >> "$S_VER_STR" <<'PY'
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
open(reg.path, "w").write('{"version": "2", "workspaces": []}')   # string version
reg.upsert_workspace("x", directories=["/tmp/wsr/x"])
d = json.load(open(reg.path))
baks = [f for f in os.listdir(reg.dir) if ".bak" in f]
ok = (d["version"] == 2 and isinstance(d["version"], int)         # re-emitted as int 2
      and len(d["workspaces"]) == 1 and not baks)                 # proceeded, NOT rotated
print("PASS-VER-STR" if ok else f"FAIL-VER-STR d={d} baks={baks}")
PY

S_VER_FLOAT="$TMP/s_ver_float.py"; printf '%s' "$HDR" > "$S_VER_FLOAT"
cat >> "$S_VER_FLOAT" <<'PY'
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
open(reg.path, "w").write('{"version": 2.0, "workspaces": []}')   # float version
reg.upsert_workspace("x", directories=["/tmp/wsr/x"])
d = json.load(open(reg.path))
baks = [f for f in os.listdir(reg.dir) if ".bak" in f]
ok = (d["version"] == 2 and isinstance(d["version"], int)
      and len(d["workspaces"]) == 1 and not baks)
print("PASS-VER-FLOAT" if ok else f"FAIL-VER-FLOAT d={d} baks={baks}")
PY

S_VER_MISSING="$TMP/s_ver_missing.py"; printf '%s' "$HDR" > "$S_VER_MISSING"
cat >> "$S_VER_MISSING" <<'PY'
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
open(reg.path, "w").write('{"workspaces": [{"id": "ws_0001", "name": "keep"}]}')  # no version
before = open(reg.path, "rb").read()
refused = False; msg = ""
try:
    reg.upsert_workspace("x", directories=["/tmp/wsr/x"])
except m.RegistryError as e:
    refused = True; msg = str(e)
except Exception as e:
    msg = "WRONG:" + repr(e)
after = open(reg.path, "rb").read()
baks = [f for f in os.listdir(reg.dir) if ".bak" in f]
ok = refused and after == before and not baks
print("PASS-VER-MISSING" if ok else f"FAIL-VER-MISSING refused={refused} same={after == before} baks={baks} msg={msg!r}")
PY

S_VER_ONE="$TMP/s_ver_one.py"; printf '%s' "$HDR" > "$S_VER_ONE"
cat >> "$S_VER_ONE" <<'PY'
import io, contextlib, re as _re
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
json.dump({"version": 1, "workspaces": [{"id": "ws_0001", "name": "legacy-a"},
                                        {"id": "ws_0002", "name": "legacy-b"}]}, open(reg.path, "w"))
err = io.StringIO()
with contextlib.redirect_stderr(err):
    reg.upsert_workspace("fresh", directories=["/tmp/wsr/fresh"])
stderr = err.getvalue()
d = json.load(open(reg.path))
baks = [f for f in os.listdir(reg.dir) if f.startswith("workspaces.json.bak.")]
pat = _re.compile(r"^workspaces\.json\.bak\.\d{8}T\d{6}Z(\.\d+)?$")
bak_ok = len(baks) == 1 and pat.match(baks[0]) is not None
old = json.load(open(os.path.join(reg.dir, baks[0]))) if bak_ok else {}
loud = bool(baks) and baks[0] in stderr and "2 workspace row(s) evacuated" in stderr   # bak path + row count LOUD
fresh_v2 = d.get("version") == 2 and len(d.get("workspaces", [])) == 1 and d["workspaces"][0]["name"] == "fresh"
old_ok = old.get("version") == 1 and len(old.get("workspaces", [])) == 2               # bak holds the OLD bytes
ok = bak_ok and loud and fresh_v2 and old_ok
print("PASS-VER-ONE" if ok else f"FAIL-VER-ONE baks={baks} bak_ok={bak_ok} loud={loud} fresh_v2={fresh_v2} old_ok={old_ok} stderr={stderr!r}")
PY

S_VER_ONE_TWICE="$TMP/s_ver_one_twice.py"; printf '%s' "$HDR" > "$S_VER_ONE_TWICE"
cat >> "$S_VER_ONE_TWICE" <<'PY'
import io, contextlib
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
json.dump({"version": 1, "workspaces": [{"id": "ws_0001", "name": "first-legacy"}]}, open(reg.path, "w"))
with contextlib.redirect_stderr(io.StringIO()):
    reg.upsert_workspace("a", directories=["/tmp/wsr/a"])
json.dump({"version": 1, "workspaces": [{"id": "ws_0009", "name": "second-legacy"}]}, open(reg.path, "w"))
with contextlib.redirect_stderr(io.StringIO()):
    reg.upsert_workspace("b", directories=["/tmp/wsr/b"])
baks = sorted(f for f in os.listdir(reg.dir) if f.startswith("workspaces.json.bak."))
names = []
for b in baks:
    try:
        names.append(json.load(open(os.path.join(reg.dir, b)))["workspaces"][0]["name"])
    except Exception:
        names.append(None)
distinct = len(baks) == 2 and len(set(baks)) == 2                 # two DISTINCT bak files
ok = distinct and "first-legacy" in names and "second-legacy" in names  # neither rotation clobbered the other
print("PASS-VER-ONE-TWICE" if ok else f"FAIL-VER-ONE-TWICE baks={baks} names={names} distinct={distinct}")
PY

# TEETH — a REAL concurrency case: 12 writers upsert DISTINCT workspaces into one
# registry, all released together by a barrier so their read-modify-write windows
# overlap. Under flock all 12 rows + strictly-unique ids survive (deterministic —
# flock queues them); the no-flock mutant (§19) must lose updates. `fcntl.flock`
# is per-open-description, so it excludes across threads too (each _Lock opens its
# own fd). Fat rows widen the write window so the unlocked race reliably collides.
S_CONCURRENCY="$TMP/s_concurrency.py"; printf '%s' "$HDR" > "$S_CONCURRENCY"
cat >> "$S_CONCURRENCY" <<'PY'
import threading
os.makedirs(os.environ["WORKSPACES_DIR"], exist_ok=True)
N = 12
pad = "y" * 20000                       # fat rows → a wider RMW window for the unlocked race
barrier = threading.Barrier(N)
errors = []
def worker(i):
    try:
        barrier.wait()                  # all writers enter the RMW together
        m.Registry().upsert_workspace(
            f"ws{i}", git_remotes=[f"https://h/x/repo{i}.git"],
            directories=[f"/tmp/wsr/conc/{i}"], description=pad)
    except Exception as e:              # a mutant may raise under the race; that is a loss too
        errors.append(repr(e))
ths = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
for t in ths:
    t.start()
for t in ths:
    t.join()
rows = m.Registry().read_registry()["workspaces"]
ids = [w.get("id") for w in rows]
ok = (not errors) and len(rows) == N and len(set(ids)) == N and all(ids)  # no lost update, ids unique
print("PASS-CONCURRENCY" if ok else f"FAIL-CONCURRENCY rows={len(rows)} uniq={len(set(ids))} err={errors[:2]}")
PY

# The concurrent reader worker (§20). Engine-agnostic: it only json-parses the
# raw registry file in a tight loop, counting any snapshot that fails to parse.
# Under an atomic os.replace it must NEVER see a torn read; the truncate-write
# mutant must produce at least one.
S_READER="$TMP/s_reader.py"
cat > "$S_READER" <<'PY'
import json, os, time
d = os.environ["WORKSPACES_DIR"]
path = os.path.join(d, "workspaces.json")
open(os.path.join(d, ".reader-ready"), "w").close()   # handshake: writer waits for this
deadline = time.time() + float(os.environ.get("READER_SECONDS", "3.0"))
reads = 0; fails = 0
while time.time() < deadline:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        json.loads(raw.decode("utf-8"))   # empty/partial → raises → a torn read
        reads += 1
    except FileNotFoundError:
        pass                              # not created yet — not a torn read
    except Exception:
        fails += 1
print(f"{reads} {fails}")
PY

S_ATOMICITY="$TMP/s_atomicity.py"; printf '%s' "$HDR" > "$S_ATOMICITY"
cat >> "$S_ATOMICITY" <<'PY'
import subprocess, sys, time
reg = m.Registry()
os.makedirs(reg.dir, exist_ok=True)
reader = os.environ["READER_SCRIPT"]
env = dict(os.environ); env["READER_SECONDS"] = "3.0"
p = subprocess.Popen([sys.executable, reader], env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
ready = os.path.join(reg.dir, ".reader-ready")
t0 = time.time()
while not os.path.exists(ready) and time.time() - t0 < 5:
    time.sleep(0.005)                     # ensure the reader is live during writes
pad = "x" * 8000                          # fat rows → multi-chunk writes widen any torn window
for i in range(30):
    reg.upsert_workspace(f"ws{i}", directories=[f"/tmp/wsr/at/{i}"], description=pad)
out, _ = p.communicate(timeout=30)
parts = out.split()
reads = int(parts[0]) if len(parts) == 2 else -1
fails = int(parts[1]) if len(parts) == 2 else -1
ok = fails == 0 and reads > 0            # every snapshot parsed; the reader did run
print("PASS-ATOMICITY" if ok else f"FAIL-ATOMICITY reads={reads} fails={fails} out={out!r}")
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
assert_out "another tool's extensions[cowriter] survives our upsert; our slice written" "PASS-FOREIGN-EXT"

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
echo "── 10. standalone — no named co-writer tool in the module ──────"
if [ -f "$REGISTRY" ]; then
  if grep -iqE 'cowriter' "$REGISTRY"; then
    fail "scripts/workspace_registry.py names a specific co-writer tool (not standalone)" "$(grep -inE 'cowriter' "$REGISTRY")"
  else
    pass "scripts/workspace_registry.py names no specific co-writer tool"
  fi
else
  fail "scripts/workspace_registry.py absent — cannot assert it is tool-neutral"
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
  'if version > MAX_SUPPORTED_VERSION:' \
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
echo "── 15. cowriter-conformance — every row we write meets cowriter's contract ─"
run_scen "$S_CONFORM" "$(wsdir)"
assert_notrace "conformance scenario did not crash"
assert_out "our rows carry top-level str id+name, dirs as [{path}], omit cowriter-private state/session_ns; foreign cowriter row untouched" "PASS-CONFORM"
# teeth: a writer that emits a non-string id → cowriter would reject the whole file
MUT="$TMP/mut_conform_id.py"
mutate "$MUT" '"id": _next_id(workspaces),' '"id": 12345,'
run_scen "$S_CONFORM" "$(wsdir)" "$MUT"
assert_noout "a non-string-id writer FAILS the conformance assert (teeth)" "PASS-CONFORM"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 16. publish — guarded structural adopt (§C.3 rule 3) ────────"
run_scen "$S_ADOPT_REMOTE" "$(wsdir)"
assert_notrace "adopt-by-remote scenario did not crash"
assert_out "shared remote → ADOPT a slice-less peer row; merge remotes, keep name+foreign fields" "PASS-ADOPT-REMOTE"
run_scen "$S_ADOPT_PATH" "$(wsdir)"
assert_notrace "adopt-by-path scenario did not crash"
assert_out "shared canonical directory → ADOPT + merge directories; foreign ext preserved" "PASS-ADOPT-PATH"
run_scen "$S_ADOPT_NAME" "$(wsdir)"
assert_out "adopt overwrites name only when empty OR name_generated; curated name kept" "PASS-ADOPT-NAME"
run_scen "$S_ADOPT_AMBIG" "$(wsdir)"
assert_out "two ambiguous candidates → mint (adopt neither); both left untouched" "PASS-ADOPT-AMBIG"
run_scen "$S_ADOPT_FOREIGNID" "$(wsdir)"
assert_out "a candidate carrying a FOREIGN open-bridge id is never adopted → mint (instance isolation)" "PASS-ADOPT-FOREIGNID"
run_scen "$S_ADOPT_REPUBLISH" "$(wsdir)"
assert_notrace "adopt-then-republish scenario did not crash"
assert_out "adopt→id-match republish MERGEs (peer name+dirs+remotes kept); only our subset shrinks" "PASS-ADOPT-REPUBLISH"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 17. MUTATION-CHECKS on guarded adopt (teeth) ────────────────"
# 17a. no-adopt — the candidate finder returns nothing → publish mints a duplicate
MUT="$TMP/mut_no_adopt.py"
mutate "$MUT" 'return hits' 'return []'
run_scen "$S_ADOPT_REMOTE" "$(wsdir)" "$MUT"
assert_noout "an engine that never adopts FAILS the ONE-row adopt assert (teeth)" "PASS-ADOPT-REMOTE"
# 17b. exclude-ours disabled — a foreign open-bridge row becomes adoptable (instance clobber)
MUT="$TMP/mut_adopt_ours.py"
mutate "$MUT" \
  'continue  # a row already ours / another instance'"'"'s — never adopt' \
  'pass      # a row already ours / another instance'"'"'s — never adopt'
run_scen "$S_ADOPT_FOREIGNID" "$(wsdir)" "$MUT"
assert_noout "an engine that adopts a foreign-id row FAILS the mint assert (teeth)" "PASS-ADOPT-FOREIGNID"
# 17c. replace-not-merge — adopt clobbers remotes instead of unioning them
MUT="$TMP/mut_adopt_replace.py"
mutate "$MUT" 'self._merge_remotes(ws, remotes)' 'ws["git_remotes"] = remotes'
run_scen "$S_ADOPT_REMOTE" "$(wsdir)" "$MUT"
assert_noout "an engine that replaces (not merges) remotes FAILS the merge assert (teeth)" "PASS-ADOPT-REMOTE"
# 17d. clobber-on-republish — the id-match branch treats an ADOPTED row as minted
# (never MERGEs) → the subscribe publish reverts the peer's curation (review fix #1)
MUT="$TMP/mut_republish_clobber.py"
mutate "$MUT" 'if isinstance(old_mirror, dict):' 'if False and isinstance(old_mirror, dict):'
run_scen "$S_ADOPT_REPUBLISH" "$(wsdir)" "$MUT"
assert_noout "an engine that REPLACEs (not merges) an adopted row FAILS the republish assert (teeth)" "PASS-ADOPT-REPUBLISH"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 18. fail-closed anomaly path (corrupt / version) ────────────"
run_scen "$S_CORRUPT" "$(wsdir)"
assert_notrace "corrupt-file scenario did not crash"
assert_out "a corrupt file REFUSES the write untouched, no .bak, 'refusing to guess'" "PASS-CORRUPT"
run_scen "$S_VER_STR" "$(wsdir)"
assert_out "version as the string \"2\" coerces → write proceeds, re-emits int 2, no rotation" "PASS-VER-STR"
run_scen "$S_VER_FLOAT" "$(wsdir)"
assert_out "version as the float 2.0 coerces → write proceeds, re-emits int 2, no rotation" "PASS-VER-FLOAT"
run_scen "$S_VER_MISSING" "$(wsdir)"
assert_out "a missing version REFUSES the write untouched, no .bak" "PASS-VER-MISSING"
run_scen "$S_VER_ONE" "$(wsdir)"
assert_notrace "v1-rotation scenario did not crash"
assert_out "a genuine v1 file rotates LOUDLY to a timestamped .bak (path+row-count on stderr); fresh v2" "PASS-VER-ONE"
run_scen "$S_VER_ONE_TWICE" "$(wsdir)"
assert_out "a second v1-rotation writes a DISTINCT bak — the first backup is not clobbered" "PASS-VER-ONE-TWICE"
# CLI-level fail-closed: corrupt → exit non-zero + stderr, file bytes untouched, no .bak
CORRDIR="$(wsdir)"
printf 'not json at all' > "$CORRDIR/workspaces.json"
BSUM_BEFORE="$(shasum "$CORRDIR/workspaces.json" | awk '{print $1}')"
OUT="$(WORKSPACES_DIR="$CORRDIR" python3 "$REGISTRY" upsert x --dir /tmp/wsr/x 2>&1)"; RC=$?
assert_rc_nonzero "CLI upsert on a corrupt file exits non-zero (fail-closed)"
assert_notrace "CLI corrupt refusal is a clean error, not a crash"
assert_out "CLI corrupt refusal refuses to guess" "refusing to guess"
assert_eq "the corrupt file bytes were NOT rotated/changed" \
  "$(shasum "$CORRDIR/workspaces.json" | awk '{print $1}')" "$BSUM_BEFORE"
if ls "$CORRDIR"/workspaces.json.bak* >/dev/null 2>&1; then
  fail "corrupt file must NOT be rotated to a .bak (fail-closed)"
else
  pass "corrupt file left in place — no .bak rotation"
fi

# ───────────────────────────────────────────────────────────────────
echo
echo "── 19. TEETH — flock: parallel writers keep every row ──────────"
run_scen "$S_CONCURRENCY" "$(wsdir)"
assert_out "12 parallel writers → all 12 rows + strictly-unique ids survive (flock holds)" "PASS-CONCURRENCY"
# mutant: strip the exclusive flock → the SAME parallel case must lose updates
MUT="$TMP/mut_noflock.py"
mutate "$MUT" 'fcntl.flock(self.fd, fcntl.LOCK_EX)' 'pass'
run_scen "$S_CONCURRENCY" "$(wsdir)" "$MUT"
assert_noout "a no-flock engine LOSES updates under the parallel case (teeth)" "PASS-CONCURRENCY"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 20. TEETH — atomic replace: no torn read for a concurrent reader ─"
export READER_SCRIPT="$S_READER"
run_scen "$S_ATOMICITY" "$(wsdir)"
assert_out "a reader parses EVERY snapshot during ~30 rapid writes (os.replace is atomic)" "PASS-ATOMICITY"
# mutant: replace the atomic os.replace with a non-atomic truncate-in-place copy
MUT="$TMP/mut_nonatomic.py"
mutate "$MUT" 'os.replace(tmp, dest)' '__import__("shutil").copyfile(tmp, dest)'
run_scen "$S_ATOMICITY" "$(wsdir)" "$MUT"
assert_noout "a non-atomic-write engine produces a torn read (teeth)" "PASS-ATOMICITY"

# ───────────────────────────────────────────────────────────────────
echo
echo "── 21. real ~/.workspaces/ untouched across the entire run ─────"
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
