---
summary: "Workspaces — two halves: a machine-global SHARED identity registry (~/.workspaces/workspaces.json, v2, multi-writer, written by the standalone workspace_registry.py) and a repo-local materialization engine (workspace.py) that binds config overlays[] + member repos[] with a lock, public-fork-safe code checkout, and delegation to the overlay engine."
type: guide
last_updated: 2026-07-08
related:
  - docs/org-overlays.md
  - docs/multi-instance.md
  - docs/structure.md
  - docs/schemas/workspace.schema.yaml
  - docs/schemas/workspaces-lock.schema.yaml
  - scripts/workspace_registry.py
  - scripts/workspace.py
---

# Workspaces

A **workspace** is the instance container that binds together the pieces a
Bridge needs to work on one thing: the **config overlays** it subscribes to, the
**member repos** it clones into its working set, and an opaque **session**
pointer. Each workspace is one file — `workflow/workspaces/<id>.yaml` — and the
engine that reads and mutates it is [`scripts/workspace.py`](../scripts/workspace.py).

A workspace does not replace the overlay mechanism; it sits **above** it. Config
overlays are still materialized by the existing, test-locked overlay engine
([`scripts/overlay.py`](../scripts/overlay.py)) — the workspace layer just
delegates to it and records the overlay by name. What the workspace layer adds on
its own is the second membership dimension the overlay engine never had: **code
repos**, cloned into an ignored, public-fork-safe location and pinned in a lock.

```
workflow/workspaces/<id>.yaml        ← the workspace definition (what you author)
        │
        ▼
scripts/workspace.py                 ← the workspace engine (this layer)
   ├── role: code    ─▶ git clone → .bridge/workspaces/<id>/<member>/   (ignored)
   │                     pin {url, ref, resolved_sha, path} in workspaces.lock.yaml
   └── role: config  ─▶ subprocess → scripts/overlay.py   (UNCHANGED, delegated)
                         materializes tracked copies, owns overlays.lock.yaml
```

## Two halves: shared identity + repo-local materialization (Option 3)

A workspace has **two separable halves**, and open-bridge implements both:

- **Identity** — *which* project this is: its name, the directories it roots at,
  and its `git_remotes[]`. A *set of projects* is a fact about the **machine**, not
  about one repo or one tool, so identity is **shared** and lives in a tool-neutral
  registry **outside** any single tool — `$WORKSPACES_DIR/workspaces.json` (else
  `~/.workspaces/workspaces.json`), schema `version: 2`. It is read/written by the
  standalone [`scripts/workspace_registry.py`](../scripts/workspace_registry.py).
- **Materialization** — *how* this instance realises the workspace locally: the
  `role: code` clones under `.bridge/`, the `.git/info/exclude` block, and the
  generated `workspaces.lock.yaml`. A clone location and a generated lock are
  implementation details of **one instance**, so this half stays **repo-local** —
  it is the engine documented in the rest of this page
  ([`scripts/workspace.py`](../scripts/workspace.py)).

The shared registry is **multi-writer** by design — other tools (a knowledge tool
such as k2a, a cmux importer, an editor or agent hook, and this Bridge) all conform
to one documented protocol and write the *same* file — so the identity writer is
held to strict multi-writer discipline (see
[The shared identity registry](#the-shared-identity-registry-workspaces) below).
This follows the reconcile decision in
`work/tasks/workspace-unification/deliverables/RECONCILE-ANALYSIS.md` (Option 3):
adopt the shared identity registry, keep materialization repo-local.

## Standalone-first — zero k2a required

The workspace engine is **standalone**. It runs with **no k2a present** — no
import of k2a, no shelling out to a `k2a` binary, no k2a path assumption. Every
verb (`create`, `list`, `validate`, `status`, `subscribe`, `unsubscribe`) works
end-to-end on a bare Bridge that has never heard of any external tool.

This is a hard invariant, not a nicety. The only provider hooks in the whole
design are two **inert** seams: the schema's `x-provider` extension bag (which
CORE never reads) and the `subscribe` name-resolution seam (which prints a
graceful "provider not available" and exits when no provider is installed). Both
are described under [The optional external-provider seam](#the-optional-external-provider-seam)
and neither does anything on a standalone Bridge. A future knowledge/workspace
tool (for example, k2a) **may** attach through them later; nothing here waits on
it, and nothing here breaks without it.

## The model — overlays[] + repos[] + a session pointer

A workspace definition (`workflow/workspaces/<id>.yaml`, schema:
[`docs/schemas/workspace.schema.yaml`](schemas/workspace.schema.yaml)) is a small,
generic YAML file. Its required core is just identity —
`schema_version`, `id`, `title` — and everything else is optional:

| Field | Meaning |
|---|---|
| `schema_version` | Contract version (`1`). |
| `id` | Workspace slug (`^[a-z][a-z0-9-]*$`); must equal the filename basename. |
| `title` | Human label. |
| `description` | One-line purpose. |
| `directory` | Working directory the workspace maps to (`${var}` / leading `~` allowed). **Informational only** — a workspace does *not* fold in instance-lifecycle; see the multi-instance note below. |
| `created_at` / `updated_at` | Engine-stamped ISO-8601 UTC timestamps. |
| `overlays[]` | The config-overlay subscriptions this workspace pulls (an index; materialization is delegated — see below). |
| `repos[]` | The member repos (each `role: code` or `role: config`). |
| `session_ref` | An **opaque** resume pointer — reserved. The engine treats it as a typed, meaningless string; it is never a semantically shared session concept, and this layer neither reads nor writes it. |
| `x-provider` | The generic extension point — a namespaced bag an optional external provider may attach to. CORE never reads it; extra keys never fail validation (forward-compat). |

The three ingredients are orthogonal:

- **`overlays[]`** — *shared config* pulled from org-overlay repos. These are the
  same overlays described in [Org Overlays](org-overlays.md); the workspace is
  just a place to group a subscription set.
- **`repos[]`** — *member repos*. A `role: code` member is source you want in the
  working set (cloned locally, ignored by git). A `role: config` member is an
  overlay expressed as a repo URL, which is normalized and handed to the overlay
  engine.
- **`session_ref`** — an opaque pointer, reserved for a future resume story. It is
  deliberately *not* interpreted here, because "session" means different things in
  different tools and a shared field must not imply a shared concept.

> **Not an instance re-architecture.** `directory` is informational and the
> workspace never owns instance provisioning, installers, or the multi-instance
> lifecycle. Several Bridges side by side is still the domain of
> [multi-instance](multi-instance.md); a workspace is a binding *inside* one
> instance, not a new instance model.

## Config overlays delegate to the overlay engine

The workspace layer is **never a second materializer** for config. When you add a
`role: config` member, `workspace.py` **delegates to `overlay.py` as a
subprocess** — it does not import the overlay engine and does not reimplement any
of its logic:

```
subscribe <ws> <git-url> --role config
        │
        ▼
subprocess: scripts/overlay.py --repo-root <root> add <git-url> --ref <ref> …
        │  (overlay.py's own branch gate, leak gate, conflict/precedence
        │   handling, per-file [y] prompts, and exit codes run UNCHANGED)
        ▼
overlay.py writes the tracked copies + owns overlays.lock.yaml
        │
        ▼
workspace.py records only the overlay NAME in the definition overlays[]
```

Subprocess (not import) is a deliberate boundary. `overlay.py` is mature and
test-locked ([`scripts/tests/test-overlay.sh`](../scripts/tests/test-overlay.sh)),
so the workspace layer must sit **above** it and leave it byte-for-byte untouched.
Shelling out preserves the overlay engine's exact gates and exit codes, keeps the
workspace engine standalone (no packaging), and means all the guarantees in
[Org Overlays](org-overlays.md) — merge-never-clobber, precedence, CORE-refusal,
the scope-leak model, prompted-paths-only — apply verbatim to config members.

Consequently the two locks stay cleanly separated:

- **Config state** lives in `overlays.lock.yaml`, owned by `overlay.py`.
- The workspace lock references those overlays **by name only** — a
  back-reference, never a re-pin. There is no duplicated config state.

Unsubscribing a `role: config` member likewise delegates (`overlay.py remove
<name>`) and then drops the name from the workspace's `overlays[]`.

## Repo membership + public-fork safety

`role: code` members are the new capability, and cloning arbitrary source into a
working tree is a **security surface** — a fork of a public repo is itself public,
so a careless `git add -A` could publish foreign code. The engine treats this the
same disciplined way `overlay.py` treats its cache:

- **Clone into an ignored location.** Code members clone to
  `.bridge/workspaces/<id>/<member>/`, under the already-gitignored `.bridge/`
  tree (mirroring `.bridge/overlays/<name>/`). The member slug defaults to the
  last URL path segment, `.git` stripped and lowercased.
- **Belt-and-suspenders `.git/info/exclude` block.** On every `subscribe` /
  `unsubscribe`, the engine rewrites a per-workspace **marked block** in the
  untracked local exclude file:

  ```
  # >>> workspace:<id> (managed by scripts/workspace.py — do not edit) >>>
  /.bridge/workspaces/<id>/<member>/
  # <<< workspace:<id> <<<
  ```

  It is idempotent, rebuilt on each mutation, and dropped entirely when the
  workspace has no code members. Because `.git/info/exclude` is local and
  untracked, neither the code nor the member filenames can be published — even on
  a public fork. The tracked `.gitignore` is never touched by this block.
- **Git-URL trust guard.** `subscribe` accepts only `https://`, `ssh://`, scp-form
  `user@host:path`, and `file://` (the last for local fixtures/tests). Every other
  scheme (`http://`, `git://`, `ext::`, `fd::`, …) and any argument starting with
  `-` (argv-injection guard) is **refused before any clone** — it writes nothing.
- **Deterministic pin.** Each code member is recorded in the lock as
  `{name, url, ref, resolved_sha, path}`, with `resolved_sha` the clone's
  `HEAD` — so `status` can detect drift and `unsubscribe` can prune deterministically.

`subscribe` is idempotent: re-adding a member with the same `url` + `ref` is a
no-op (no re-clone, no lock churn); a *different* url/ref at the same slug is
refused.

## The lock model

`workspaces.lock.yaml` is a **generated** root file (`scope: user`), parallel to
`overlays.lock.yaml` and validated by
[`docs/schemas/workspaces-lock.schema.yaml`](schemas/workspaces-lock.schema.yaml).
It records the **resolved reality** of `role: code` member clones so the engine
can tell intent (the definition) from what is actually on disk:

```yaml
schema_version: 1
workspaces:
  <workspace-id>:
    updated_at: <iso-8601-utc>
    repos:                       # role=code members only
      - name: <slug>
        url:  <uri>
        ref:  <string>
        resolved_sha: <40-hex>   # immutable pin, HEAD at clone/update
        path: <string>          # clone path, relative to repo root
    overlays: [<name>, ...]      # back-reference to overlays.lock.yaml entries;
                                 # NOT re-pinned here — overlay.py owns that state
```

Like its sibling, the lock is `scope: user`: **gitignored in a public fork**
(it names local material paths) and un-ignored only in a private instance, exactly
as `overlays.lock.yaml` is handled. The `.bridge/workspaces/` clones are always
ignored (covered by `/.bridge/`). The workspace **definitions** themselves are
user instances too — tracked in a private instance, absent on a fresh public clone
which ships only `_template.yaml` (the same policy as `workflow/contexts/*.yaml`).

## State-file locations

| Artifact | Location | Tier |
|---|---|---|
| Workspace **definition** | `workflow/workspaces/<id>.yaml` | scope:user instance |
| Definition **template** | `workflow/workspaces/_template.yaml` | core (`_`-prefixed, excluded from discovery) |
| Definition **schema** | `docs/schemas/workspace.schema.yaml` | core |
| Generated **lock** | `workspaces.lock.yaml` (repo root) | scope:user, generated |
| Lock **schema** | `docs/schemas/workspaces-lock.schema.yaml` | core |
| `role: code` member **clones** | `.bridge/workspaces/<id>/<member>/` | ignored |

The definition lives under the `workflow/` cluster-wrapper because a workspace
binds *what happens when* — repos + overlays for a unit of work. It gets its own
`<types>` folder per the **Default-to-Folder** rule (see
[structure](structure.md)) and is found by the standard discovery glob
`workflow/workspaces/*.yaml` (skipping `_`-prefixed files).

## The workspace command surface

> **Increment status.** What is documented here is the **engine + model**:
> `scripts/workspace.py` and the two schemas. The ergonomic **`/workspace`
> slash-command skill** that will wrap this engine — the way the `bridge-overlay`
> skill wraps `overlay.py` — is a **later increment** and does not exist yet.
> Likewise the `bridge-overlay` → `/workspace` rename, an `/overlay` alias, and the
> `ecosystem.yaml workspaces:` cleanup are out of scope for now. Until the skill
> lands, drive the engine directly via `scripts/workspace.py`.

The engine CLI:

```
workspace [--repo-root R] <subcommand> …

create       <name> [--dir DIR] [--title T] [--description D]
list
validate     [name]
status       [name]
subscribe    <name> <git-url> [--ref R] [--role code|config]   # alias: add-repo   (--role default: code)
unsubscribe  <name> <member>                                   # alias: remove-repo
```

`subscribe` / `unsubscribe` are the **canonical** verb names; `add-repo` /
`remove-repo` are retained **aliases** that dispatch to the identical handlers
(same behaviour, same branch gate) so older scripts and vocabulary keep working.

- **`create`** — scaffold a new `workflow/workspaces/<name>.yaml` from the
  template (`schema_version`, `id`, `title`, timestamps, empty `overlays[]` /
  `repos[]`). Refuses an invalid slug or an existing file.
- **`list`** — read-only table of workspaces and their code/overlay counts.
- **`validate [name]`** — validate one or all definitions against the schema
  (preferring `check-jsonschema` when available, with an in-engine fallback
  otherwise). An `x-provider` bag never fails validation.
- **`status [name]`** — read-only drift report: for each `role: code` member,
  whether the clone is present and whether its `HEAD` matches the lock's
  `resolved_sha` (`clean` / `ahead` / `missing`); config overlays are listed by
  name.
- **`subscribe`** (alias `add-repo`) — clone a `role: code` member (§ public-fork
  safety) or delegate a `role: config` member to `overlay.py` (§ config delegation).
- **`unsubscribe`** (alias `remove-repo`) — remove a code member (delete clone, drop
  the lock entry, refresh the exclude block) or a config overlay (delegate
  `overlay.py remove`).

### Branch gate

The **mutating** verbs — `create`, `subscribe`, `unsubscribe` (and their aliases
`add-repo` / `remove-repo`) — refuse to run unless the current branch is `user/*`
(or detached / non-repo). This is the same
gate `overlay.py` enforces and it honours the same env escape
(`BRIDGE_OVERLAY_ALLOW_ANY_BRANCH=1`) so a shared test harness works. The
**read-only** verbs (`list`, `validate`, `status`) run on any branch.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | `WorkspaceError` — branch gate, validation failure, trust-guard refusal, not-found, or a delegated `overlay.py` non-zero |
| `2` | usage / repo-root / chdir error (argparse default) |
| `3` | the optional provider-name seam fired but no provider is available (see below) |

## The optional external-provider seam

Two inert extension points let a future external provider attach to the workspace
model **without CORE ever depending on it**. Both are **non-normative** and do
nothing on a standalone Bridge.

1. **`x-provider` (schema).** A namespaced bag on the workspace definition
   (`propertyNames` are provider slugs). An external provider may stash its own
   data there; CORE never reads it, and unknown keys never fail validation. No
   k2a-specific field is ever a *required* CORE field — the required core stays
   generic.

2. **The `subscribe` name seam.** The second positional of `subscribe` (alias
   `add-repo`) is normally a git URL. If instead it is a bare slug
   (`^[a-z][a-z0-9-]*$`, no scheme, no `/`), the
   engine treats it as a **workspace/provider name** that only an external provider
   could resolve to a set of repos. On a standalone Bridge no provider is present,
   so the engine prints a graceful message and **exits 3** — performing **no
   import and no path lookup** of any provider:

   ```
   '<x>' is not a git URL. Resolving a workspace/provider name to repos needs an
   external provider (e.g. k2a) that is not available in this standalone Bridge.
   Pass an explicit git URL, or install the provider.
   ```

The intent, non-normatively: a knowledge/workspace tool that maintains its own
workspace registry (k2a being the concrete example) **could**, in a later
increment, register as that provider and resolve a workspace name to the repos it
knows about — because both sides read the same open, versioned workspace schema.
That is a documented *seam*, capability-detected and graceful when absent — never
a build dependency, and explicitly not built here.

## The shared identity registry (`~/.workspaces/`)

The **identity half** (above) is a conformant reader/writer of the tool-neutral
registry, implemented standalone in
[`scripts/workspace_registry.py`](../scripts/workspace_registry.py) — pure stdlib,
with **no external tool imported, shelled out to, or assumed present**. It is a
first-class **writer**, not merely a reader: a standalone Bridge registers a
workspace's identity itself, without waiting on any other tool.

### Location + resolution

`$WORKSPACES_DIR` if set, else `~/.workspaces/` — one predictable, cross-OS path,
deliberately no XDG special-casing. The directory is created on first write. The
registry's `SCHEMA.md` (published beside the file so any tool can conform) is
authored by the registry's schema owner; this writer conforms to that format and
does not overwrite it.

### Multi-writer protocol (safety-critical)

Because other tools write the **same** `workspaces.json`, a bug that drops a field
corrupts *their* registry, not just ours. Every mutation follows one protocol,
exactly:

> take the advisory lock (`<dir>/.lock`, `flock`) → read → modify in memory →
> **atomic replace** (`workspaces.json.tmp` + `os.replace`) → release the lock.

with these invariants — all test-locked in
[`scripts/tests/test-workspace-registry.sh`](../scripts/tests/test-workspace-registry.sh),
whose mutation-checks break the engine to prove each assert has teeth:

- **Preserve unknown fields** — unrecognized top-level keys and unrecognized
  per-workspace keys round-trip untouched.
- **Never touch another tool's slice** — a writer edits only the shared identity
  fields plus its own `extensions["open-bridge"]`; every other
  `extensions["<tool>"]` slice is left byte-for-byte.
- **`version` is max-monotonic** — this writer understands at most `version: 2`
  and always writes `2`; a file whose on-disk version is higher may be **read** but
  is **refused for write** (a clean non-zero error, never a clobber).
- **De-dup on create by identity** — a shared normalized `git_remotes` entry or a
  shared canonical directory path attributes to the existing workspace instead of
  appending a duplicate (§ Path identity below).
- **Never lose data** — an unreadable or older-versioned file is rotated to
  `workspaces.json.bak` before a fresh `version: 2` registry is started.

Reads (`read_registry`, `list_workspaces`, `find_by_path`) are lockless — the
atomic replace guarantees a reader always sees a whole file, never a torn one.

### Path identity + matching

Paths are **canonicalized** (symlinks resolved, `~` expanded) and
**alias-expanded** for the macOS File-Provider spellings
(`~/Dropbox` ↔ `~/Library/CloudStorage/Dropbox`; the same shape generalizes to
OneDrive / Google Drive). `find_by_path` matches a query equal-to or nested-under
a workspace directory, and the **longest matching directory wins** (the most
specific workspace). Both spellings are stored in `directories[].aliases` so cheap
string-prefix consumers match without canonicalizing.

### Writer API

| Call | What |
|---|---|
| `upsert_workspace(name, directories=[…], git_remotes=[…], open_bridge_ext={…})` | Create-or-update by **structural** identity (shared path / git remote), MERGING — the generic cross-tool converge path. |
| `publish_workspace(ref, name, directories=[…], git_remotes=[…], open_bridge_ext={…})` | The **owning mirror**: create-or-update by a stable open-bridge id (`ref`, parked in `extensions["open-bridge"]["id"]`), REPLACING the mirrored identity so a removal shrinks it. Used by the engine write-through. |
| `read_registry()` / `list_workspaces()` | Read the whole registry / the workspace rows. |
| `find_by_path(p)` | Longest-match workspace for a path, else `None`. |
| `archive_workspace(id)` | Soft-delete (`archived: true`). |

### Automatic write-through from the repo-local engine

The repo-local engine ([`scripts/workspace.py`](../scripts/workspace.py)) **publishes
identity automatically**: after a `create` / `subscribe` / `unsubscribe` succeeds, it
mirrors the workspace into the shared registry via `publish_workspace` — `title` → `name`,
each `role: code` member's clone directory (label `repo`) + its origin remote, and the
overlays/repos under `extensions["open-bridge"]`, keyed by the workspace slug as the stable
id. Successive publishes converge on **one** entry, and an `unsubscribe` shrinks the mirror.
This is **additive**: the repo-local definition, lock, and materialization stay the source of
record, and a shared-registry hiccup (a version-guarded newer file, an unreadable registry)
**warns but never fails** the local command — local materialization is already done. The
publish target resolves the usual way (`$WORKSPACES_DIR` else `~/.workspaces/`), so an
instance's tests must pin `$WORKSPACES_DIR` to a temp dir (both suites do).

### How our model maps onto the shared schema

open-bridge keeps its own vocabulary internally and maps it **at the registry
boundary** — it does not rename load-bearing fields:

| open-bridge (repo-local) | shared registry (v2) | mapping |
|---|---|---|
| `title` | `name` | mapped on write (the shared schema keeps a `title` read-alias) |
| `schema_version` | `version` | same envelope pattern |
| code members (`repos[] role: code`) | `directories[]` + `git_remotes[]` | shared identity |
| config overlays (`overlays[]`) + repo config | `extensions["open-bridge"]` | our namespaced slice |
| materialization (`.bridge/` clones, `workspaces.lock.yaml`, exclude block) | — | stays repo-local; the registry only *references* identity |

### open-bridge defaults (documented, adjustable)

These are open-bridge's **chosen defaults** for the shared model — written down so
they are explicit and easy to revisit, **not** hard invariants:

1. **Config overlays + member-repo config live under `extensions["open-bridge"]`,
   not as shared fields.** The shared core is kept deliberately small: code members
   map onto the shared `directories[]` / `git_remotes[]`, while config-overlay
   subscriptions are open-bridge-specific and stay in our extension slice (they may
   later be proposed as shared fields).
2. **`title` stays the internal name and is mapped to `name` on write.** open-bridge
   does not rename its internal `title` (load-bearing in the lock + template).
3. **This Bridge is a full conformant WRITER, not only a reader** — standalone
   operation requires registering identity with no other tool present.
4. **The registry is machine-global; materialization is repo/branch-scoped.**
   Overlay materialization applies only to a workspace whose `directories[0]` is a
   Bridge repo; for a non-Bridge workspace the `extensions["open-bridge"]` slice is
   simply empty.

> **Engine, not a skill.** This is the registry *engine* — the reader/writer and
> its protocol. There is no `/workspace` slash-command skill wrapping it yet (the
> same status as the repo-local engine above); drive it via
> `scripts/workspace_registry.py` or the library API until a skill lands.

## Schema reference

- [`docs/schemas/workspace.schema.yaml`](schemas/workspace.schema.yaml) — the
  workspace **definition** (JSON Schema Draft 2020-12 in YAML). Field-by-field
  constraints, the `OverlayRef` / `RepoMember` `$defs`, and the `x-provider`
  extension point.
- [`docs/schemas/workspaces-lock.schema.yaml`](schemas/workspaces-lock.schema.yaml)
  — the generated **lock** (`scope: user`) recording resolved `role: code` member
  clones and the by-name back-reference to `overlays.lock.yaml`.

The definition template ships at `workflow/workspaces/_template.yaml`; read it and
the matching schema before authoring a workspace by hand (per
[file-creation](../rules/file-creation.md)).

## Related

- [Org Overlays](org-overlays.md) — the config-overlay mechanism a workspace
  delegates to for every `role: config` member, and the source of the
  merge/precedence/leak guarantees that apply to those members.
- [Multi-instance](multi-instance.md) — several Bridges side by side; a workspace
  is a binding *inside* one instance and does not own the instance lifecycle.
- [Structure](structure.md) — the Default-to-Folder layout that places workspace
  definitions under `workflow/workspaces/`.
- [`scripts/overlay.py`](../scripts/overlay.py) · [`scripts/workspace.py`](../scripts/workspace.py)
  — the overlay engine (delegated to, unchanged) and the workspace engine (this
  layer).
