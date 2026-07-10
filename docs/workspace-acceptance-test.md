---
summary: "Standalone acceptance-test playbook for the workspace feature — a zero-prior-context runbook an external tester (human or AI) executes to confirm the two engines (scripts/workspace.py + scripts/workspace_registry.py) and the shared registry behave exactly as documented: three green suites, source-level neutrality, an end-to-end walk, the provider seam, the fail-closed registry, the trust guard, and a docs cross-check."
type: guide
last_updated: 2026-07-10
related:
  - docs/workspaces.md
  - docs/schemas/workspace.schema.yaml
  - docs/schemas/workspaces-lock.schema.yaml
  - docs/schemas/workspaces-registry.schema.yaml
  - scripts/workspace.py
  - scripts/workspace_registry.py
---

# Workspace feature — standalone acceptance test

This is a **self-contained acceptance-test playbook**. An external tester — human
or AI — can run it end to end with **zero prior knowledge of the project**. Every
step lists the exact command and the exact result to expect. Nothing here needs a
second tool, a network service, or any private component.

## What is under test

| Piece | What it is |
|---|---|
| **Branch** | `feat/workspace-unification` of the open-bridge repository. |
| **Engine 1** | [`scripts/workspace.py`](../scripts/workspace.py) — the repo-local workspace engine: `create` / `list` / `validate` / `status` / `subscribe` / `unsubscribe`. |
| **Engine 2** | [`scripts/workspace_registry.py`](../scripts/workspace_registry.py) — a standalone, conformant reader/writer of the machine-global **shared identity registry**. |
| **Shared registry** | `$WORKSPACES_DIR/workspaces.json` — a tool-neutral JSON file (schema `version: 2`) that answers "which project is this directory in?", writable by several conformant co-writers. |

The design goal being verified: the workspace engines are **standalone** (they run
with no external tool present) and the shared registry is **multi-writer-safe and
fail-closed** (a bad or foreign file is never silently clobbered).

### Safety rules (read before you run anything)

1. **Always pin `WORKSPACES_DIR` to a throwaway directory** — `export
   WORKSPACES_DIR="$(mktemp -d)"`. Never let a test touch your real
   `~/.workspaces/`.
2. **Never run `git config --global`** (or `--system`). Set a throwaway commit
   identity per-repo instead — `git -c user.name=t -c user.email=t@example.com …`
   or `git config --local`.
3. **Work under a scratch directory** — `export SCRATCH="$(mktemp -d)"`; create the
   consumer repo and the member repo underneath it. Nothing here writes outside
   `$SCRATCH` and `$WORKSPACES_DIR`.
4. The mutating verbs only run on a `user/*` branch — that is by design; keep the
   consumer on `user/tester`.

## Setup

### Prerequisites

- `python3` (3.10+), with **PyYAML** importable (`python3 -c "import yaml"`).
  `workspace.py` needs it; `workspace_registry.py` is pure stdlib.
- `git` on `PATH`.
- Optional: `check-jsonschema` (if present, `validate` uses it; otherwise an
  in-engine structural fallback runs — both are acceptable).

### Clone the branch and record the SHA

```bash
git clone --branch feat/workspace-unification <repo-url> open-bridge
cd open-bridge
git rev-parse HEAD          # RECORD this SHA in your report
export WT="$PWD"            # worktree root — the scripts live under $WT/scripts/
```

### Lay down throwaway working dirs

```bash
export SCRATCH="$(mktemp -d)"
export WORKSPACES_DIR="$(mktemp -d)"      # the shared registry lives here
IDENT=(-c user.name=t -c user.email=t@example.com -c commit.gpgsign=false)
```

---

## Step 1 — the three test suites (expected 218/0, 70/0, 11/0)

Each suite pins its own temp `WORKSPACES_DIR` internally, but export a throwaway
one anyway for belt-and-suspenders.

```bash
WORKSPACES_DIR="$(mktemp -d)" bash "$WT/scripts/tests/test-workspace.sh"          | tail -3
WORKSPACES_DIR="$(mktemp -d)" bash "$WT/scripts/tests/test-workspace-registry.sh" | tail -3
WORKSPACES_DIR="$(mktemp -d)" bash "$WT/scripts/tests/test-workspace-skill.sh"    | tail -3
```

**Expected** — each ends in a `RESULT:` banner:

```
RESULT: 218 passed, 0 failed      # test-workspace.sh          (the repo-local engine)
RESULT: 70 passed, 0 failed       # test-workspace-registry.sh (the shared registry)
RESULT: 11 passed, 0 failed       # test-workspace-skill.sh    (skill/doc wording)
```

**PASS** iff all three show `0 failed` with those totals.

---

## Step 2 — source-level neutrality proof

The engines must not import, shell out to, or name any external product. Two
independent checks.

### 2a — import allowlist: no third-party or foreign-tool dependency

Instead of grepping for any particular product name, assert positively that every
top-level import of **both** engines is in a tiny allowlist — the standard library,
`yaml` (PyYAML), and the sibling engine module `workspace_registry` (repo-local).
Anything outside that set (a foreign tool package, a client SDK) fails.

```bash
python3 - "$WT/scripts/workspace.py" "$WT/scripts/workspace_registry.py" <<'PY'
import ast, sys
allowed = set(sys.stdlib_module_names) | {"yaml", "workspace_registry"}
bad = {}
for path in sys.argv[1:]:
    mods = set()
    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, ast.Import):
            for a in n.names: mods.add(a.name.split('.')[0])
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module.split('.')[0])
    extra = sorted(m for m in mods if m not in allowed)
    print(path.split('/')[-1], "→", sorted(mods))
    if extra: bad[path] = extra
print("outside allowlist:", bad if bad else "none")
sys.exit(1 if bad else 0)
PY
echo "exit=$?"
```

**Expected:** `outside allowlist: none`, exit `0` — the engines pull in only the
standard library and `yaml`; no external tool, no client SDK.

### 2b — AST import check: `workspace_registry.py` is stdlib-only

```bash
python3 - "$WT/scripts/workspace_registry.py" <<'PY'
import ast, sys
src = open(sys.argv[1]).read()
mods = set()
for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.Import):
        for a in n.names: mods.add(a.name.split('.')[0])
    elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
        mods.add(n.module.split('.')[0])
nonstd = sorted(m for m in mods if m not in sys.stdlib_module_names)
print("top-level imports:", sorted(mods))
print("non-stdlib:", nonstd)
PY
```

**Expected** (order may vary):

```
top-level imports: ['argparse', 'copy', 'datetime', 'fcntl', 'json', 'os', 're', 'sys', 'tempfile']
non-stdlib: []
```

**PASS** iff `non-stdlib: []`. (`workspace.py` additionally imports `yaml`, which
is expected — it is not part of this stdlib-only claim.)

---

## Step 3 — end-to-end walk

Build a consumer Bridge repo on a `user/*` branch and a local member repo, then
drive the full lifecycle. Every clone URL is a `file://` path, so no network is
needed.

### 3.0 — a member repo (subscribed via `file://`) and a consumer bridge

```bash
export MEMBER="$SCRATCH/member-code"
mkdir -p "$MEMBER"; ( cd "$MEMBER" && git init -q -b main && echo hello > a.txt \
  && git add -A && git "${IDENT[@]}" commit -qm init )

export CONSUMER="$SCRATCH/consumer"
mkdir -p "$CONSUMER"; ( cd "$CONSUMER" && git init -q -b main \
  && git checkout -q -b user/tester && mkdir -p workflow/workspaces \
  && echo seed > README.md && git add -A && git "${IDENT[@]}" commit -qm seed )

WS()  { python3 "$WT/scripts/workspace.py" --repo-root "$CONSUMER" "$@"; }
REG() { python3 "$WT/scripts/workspace_registry.py" "$@"; }
```

### 3.1 — `create` with `--dir`

```bash
WS create demo --dir "$CONSUMER/wd-demo" --title "Demo WS" --description "acceptance walk"
```

**Expected:** exit `0`, prints `created workflow/workspaces/demo.yaml`. The written
definition carries the `directory:` you passed:

```yaml
schema_version: 1
id: demo
title: Demo WS
description: acceptance walk
directory: <CONSUMER>/wd-demo
created_at: '…Z'
updated_at: '…Z'
overlays: []
repos: []
```

### 3.2 — `subscribe` a `file://` code member

```bash
WS subscribe demo "file://$MEMBER"
```

**Expected:** exit `0`, prints (the SHA is the member's `HEAD`):

```
added code member 'member-code' @ <40-hex sha> → .bridge/workspaces/demo/member-code
```

### 3.3 — `list` / `status` / `validate`

```bash
WS list
WS status demo
WS validate demo
```

**Expected:**

```
# list
ID    TITLE    #CODE  #OVERLAY  DIR
demo  Demo WS  1      0         <CONSUMER>/wd-demo

# status demo
■ demo — Demo WS
  code · member-code: clean
  overlays     : (none)

# validate demo
PASS — demo.yaml            # exit 0
```

Confirm the generated artifacts:

```bash
sed -n '1,40p' "$CONSUMER/workspaces.lock.yaml"     # role:code member pinned with resolved_sha
sed -n '1,40p' "$CONSUMER/.git/info/exclude"        # a "workspace:demo" marked block excluding the clone
```

**Expected** — the lock names the member with a `resolved_sha`, and the
`.git/info/exclude` file contains:

```
# >>> workspace:demo (managed by scripts/workspace.py — do not edit) >>>
…
/.bridge/workspaces/demo/member-code/
# <<< workspace:demo <<<
```

### 3.4 — `find-path` resolves the `--dir`

```bash
REG find-path "$CONSUMER/wd-demo"
REG find-path "$CONSUMER/wd-demo/nested/deeper"      # nested still resolves (longest match)
```

**Expected:** both print `ws_0001<TAB>Demo WS` and exit `0`. (The publish keyed
the row under an instance-qualified id inside `extensions["open-bridge"]["id"]`,
e.g. `<12-hex>:demo` — inspect with `REG read` if you like.)

### 3.5 — `unsubscribe` shrinks the lock and the registry

```bash
WS unsubscribe demo member-code
sed -n '1,40p' "$CONSUMER/workspaces.lock.yaml"      # repos: []  now
REG read | python3 -c 'import json,sys; w=json.load(sys.stdin)["workspaces"][0]; print("git_remotes:", w["git_remotes"]); print("dirs:", [d["path"] for d in w["directories"]])'
```

**Expected:** exit `0`, prints `removed code member 'member-code' from workspace
'demo'`. The lock's `repos:` is now empty, the `.git/info/exclude` `workspace:demo`
block is gone, and in the registry the member's remote and its `repo`-labelled
directory have been removed — `git_remotes: []`, and only the `wd-demo` primary
directory remains. The mirror **shrank**.

---

## Step 4 — provider seam (a bare name exits 3)

Passing a bare slug where a git URL is expected exercises the optional
external-provider seam, which is **absent** in a standalone checkout.

```bash
WS subscribe demo somename ; echo "exit=$?"
```

**Expected:** exit `3`, with a clear message on stderr:

```
'somename' is not a git URL. Resolving a workspace/provider name to repos needs an
external provider that is not available in this standalone Bridge. Pass an explicit
git URL, or install a provider.
```

No clone happens, no import is attempted.

---

## Step 5 — fail-closed shared registry

The registry never silently discards data. Each sub-check uses its **own** fresh
`WORKSPACES_DIR`.

### 5a — corrupt file: the local verb still succeeds; the file is untouched

```bash
WD="$(mktemp -d)"; export WORKSPACES_DIR="$WD"
printf 'this is not json {{{' > "$WD/workspaces.json"
before="$(shasum "$WD/workspaces.json")"
WS create ws2 --dir "$CONSUMER/wd2" ; echo "exit=$?"
after="$(shasum "$WD/workspaces.json")"
[ "$before" = "$after" ] && echo "file UNCHANGED (pass)" || echo "file changed (fail)"
```

**Expected:** the command exits **`0`** and prints `created
workflow/workspaces/ws2.yaml`, but first writes a warning to stderr:

```
workspace: shared-registry publish failed (local state unaffected): registry …/workspaces.json
is unreadable — inspect or remove it; refusing to guess (a write must not overwrite an unparseable file).
```

The corrupt file is **byte-for-byte unchanged** (`file UNCHANGED (pass)`) — the
additive registry mirror warns but never fails the local command, and never
overwrites an unreadable file.

### 5b — a *direct* registry write on the same corrupt file exits 1

```bash
REG upsert "X" --dir "$CONSUMER/wd3" ; echo "exit=$?"
```

**Expected:** exit `1` (`RegistryError`) — the direct writer refuses the corrupt
file outright, printing the same "unreadable — refusing to guess" message. (The
difference from 5a: the engine's mirror is *additive* and degrades to a warning;
the registry CLI itself fails closed.)

### 5c — `version: "2"` as a string proceeds and re-emits integer `2`

```bash
WD="$(mktemp -d)"; export WORKSPACES_DIR="$WD"
printf '{"version":"2","workspaces":[]}' > "$WD/workspaces.json"
REG upsert "StrVer" --dir "$CONSUMER/wds" ; echo "exit=$?"
python3 -c 'import json;d=json.load(open("'"$WD"'/workspaces.json"));print("version=",repr(d["version"]),type(d["version"]).__name__)'
```

**Expected:** exit `0`, `upserted ws_0001 (StrVer)`, then `version= 2 int` — the
string `"2"` is coerced to `2` on read and written back as the JSON integer `2`.

### 5d — `version: 1` rotates loudly to a timestamped backup

```bash
WD="$(mktemp -d)"; export WORKSPACES_DIR="$WD"
printf '{"version":1,"workspaces":[{"id":"ws_0001","name":"old"}]}' > "$WD/workspaces.json"
REG upsert "New" --dir "$CONSUMER/wdn" ; echo "exit=$?"
ls -1 "$WD" | grep bak
python3 -c 'import json;d=json.load(open("'"$WD"'/workspaces.json"));print("version=",d["version"],"rows=",len(d["workspaces"]))'
```

**Expected:** exit `0`, and a loud stderr notice before the upsert:

```
workspace-registry: rotated legacy v1 registry to …/workspaces.json.bak.<UTC yyyymmddThhmmssZ>
(1 workspace row(s) evacuated); started a fresh v2 registry.
```

A timestamped `workspaces.json.bak.<UTC>` now exists (the old bytes preserved), and
the live registry is a fresh `version= 2` with the new row.

> Optional extra (documents the ceiling): seed `{"version":3,"workspaces":[]}` and
> `REG upsert …` — the write is **refused with exit `4`** (`RegistryVersionError`,
> "understands at most 2"), while `REG read` still exits `0`. A newer file is
> read-only, never clobbered.

---

## Step 6 — trust-guard spot checks

`subscribe` refuses dangerous URL schemes and argv-injection **before any clone**.

```bash
WS subscribe demo "ext::sh -c id" ; echo "exit=$?"     # remote-helper transport
WS subscribe demo -- "-evil-path" ; echo "exit=$?"     # leading '-' (after -- so argparse forwards it)
```

**Expected:** both exit `1`, writing nothing:

```
workspace: refusing a git remote-helper transport in 'ext::sh -c id' — only https://, ssh://, file:// and scp-form user@host:path are trusted.
workspace: refusing an argument that begins with '-' (argv-injection guard): '-evil-path'. …
```

(Note: without the `--` separator, a leading-dash argument is caught earlier by the
CLI argument parser as a usage error, exit `2` — also a refusal, just at a
different layer.)

---

## Step 7 — docs cross-check

Confirm five concrete claims from [`docs/workspaces.md`](workspaces.md) against what
you observed. Each is a direct, testable statement.

| # | Claim in `docs/workspaces.md` | Observed in | Pass? |
|---|---|---|---|
| 1 | "Every verb … works end-to-end on a bare Bridge that has never heard of any external tool." | Steps 1, 3 — all verbs run green with no external tool present. | |
| 2 | "the engine prints a graceful message and **exits 3** — performing **no import and no path lookup** of any provider." | Step 4 — bare name → exit 3, graceful message. | |
| 3 | "`subscribe` accepts only `https://`, `ssh://`, scp-form … and `file://` … Every other scheme … and any argument starting with `-` … is **refused before any clone**." | Step 6 — `ext::` and leading `-` → exit 1, nothing written. | |
| 4 | "An unparseable file … **refuses the write** (`RegistryError`); the on-disk bytes are left exactly as found." | Step 5a/5b — direct upsert exits 1, file unchanged; the engine mirror warns but the local verb still exits 0. | |
| 5 | "an `unsubscribe` shrinks the mirror." | Step 3.5 — `git_remotes` and the `repo` directory drop from the registry row. | |

**PASS** iff all five observations match the quoted claims.

---

## Report template

Fill this in and return it as the test result.

```
Workspace acceptance test — report
Branch : feat/workspace-unification
SHA    : <git rev-parse HEAD>
Runner : <human | AI model> · <OS / python version>

| Step | What | Verdict | Evidence (paste the deciding line) |
|------|------|---------|-------------------------------------|
| 1  | Three suites 218/0, 70/0, 11/0        | PASS/FAIL | RESULT lines |
| 2a | grep neutrality (clean)               | PASS/FAIL | clean (pass) |
| 2b | AST stdlib-only registry              | PASS/FAIL | non-stdlib: [] |
| 3  | End-to-end walk (create→unsubscribe)  | PASS/FAIL | key command outputs |
| 4  | Provider seam → exit 3                 | PASS/FAIL | exit=3 + message |
| 5a | Corrupt file: verb exit 0, unchanged  | PASS/FAIL | file UNCHANGED |
| 5b | Direct upsert on corrupt → exit 1     | PASS/FAIL | exit=1 |
| 5c | version "2" → int 2                    | PASS/FAIL | version= 2 int |
| 5d | version 1 → timestamped backup        | PASS/FAIL | rotated … .bak.<UTC> |
| 6  | Trust guard (ext:: / leading -)       | PASS/FAIL | exit=1 refusals |
| 7  | Docs cross-check (5/5 claims)          | PASS/FAIL | table above |

Findings (bugs, deviations, surprises):
- …

Overall verdict: PASS / FAIL
```

## Related

- [Workspaces](workspaces.md) — the feature under test, in full.
- [`docs/schemas/workspace.schema.yaml`](schemas/workspace.schema.yaml),
  [`workspaces-lock.schema.yaml`](schemas/workspaces-lock.schema.yaml),
  [`workspaces-registry.schema.yaml`](schemas/workspaces-registry.schema.yaml) —
  the definition, lock, and registry schemas.
