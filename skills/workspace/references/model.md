# Workspace model — identity vs materialization, and the shared registry

Read this to understand *why* the pieces are split the way they are, how a
second tool can co-own the same workspace safely, and why the whole thing runs
standalone.

## Two disjoint halves

| Concern | Lives in | Written by | Kind |
|---|---|---|---|
| **Identity** — name, member roots, git remotes, our ext slice | `~/.workspaces/workspaces.json` (machine-global, shared) | the registry writer, via the publish hook | additive mirror, never the source of record |
| **Definition / intent** | `workflow/workspaces/<id>.yaml` (repo-local) | `create` / `subscribe` | source of record; `scope: user` (absent on a fresh public clone, which ships only `_template.yaml`) |
| **Resolved code pins** | `workspaces.lock.yaml` (repo root) | rebuilt on every code mutation | generated; `{name,url,ref,resolved_sha,path}` per member |
| **Code clones** | `.bridge/workspaces/<id>/<member>/` | `git clone` | ignored by `.gitignore` AND `.git/info/exclude` |
| **Config state** | `overlays.lock.yaml` + copies + `@import` | the overlay engine (delegated) | owned entirely by `overlay.py` |
| **Exclude guard** | `.git/info/exclude` (untracked) | on every code add/remove | the second, fork-proof guard |

The rule of thumb: **identity is a machine fact** (a set of projects on this
machine), so it is machine-global. **Materialization is a repo fact** (how *this*
checkout realises the project), so it is repo-local. The registry only
*references* identity; it holds no materialization. Deleting
`~/.workspaces/workspaces.json` loses no source of record — the next mutation
re-publishes it from the repo-local definition. Losing the definition/lock is the
real loss.

## The field mapping at the registry boundary

When the publish hook mirrors a workspace's identity:

| repo-local (definition) | shared registry (v2 row) |
|---|---|
| `title` | `name` |
| `role:code` member path (→ absolute) | `directories[] {path, label:"repo"}` |
| clone's `origin` remote (else member `url`) | `git_remotes[]` |
| `overlays[]` names + `repos[]` slices | `extensions["open-bridge"] = {overlays, repos, id}` |
| `.bridge/` clones, lockfiles, exclude block | — (never leaves the repo) |

The shared row carries only the two fields a co-writer's schema requires
(`id`, `name`) plus the identity fields and our own namespaced
`extensions["open-bridge"]` slice. It deliberately omits any fields private to
another tool — those are that tool's to fill.

## The multi-writer protocol (why co-writing is safe)

`~/.workspaces/workspaces.json` is a **tool-neutral, multi-writer** file. Any
conformant tool modifies it under one documented protocol:

1. Acquire an exclusive advisory lock on a **separate `.lock` file** in the same
   directory (blocks until the other writer releases).
2. Read the WHOLE file (every row, every foreign `extensions[<tool>]` slice,
   every unknown key retained in memory).
3. Version-guard: refuse to write a file whose `version` is newer than supported
   (never downgrade-clobber); rotate a corrupt/older file to `.bak` before
   starting fresh.
4. Modify ONLY your own row's own fields (this writer matches strictly by
   `extensions["open-bridge"]["id"]`, so it can never resolve onto another
   tool's row).
5. Atomic replace: write `…json.tmp` → `flush` → `fsync` → `os.replace` (a rename
   on the same filesystem); a failure before the rename leaves the live file
   untouched (no torn write).
6. Release the lock.

The invariants that make this safe — whole-file read inside the lock,
preserve-unknown-fields-and-foreign-slices, disjoint match keys, version
max-monotonic — are locked by `scripts/tests/test-workspace-registry.sh`
(including a k2a-conformance guard that every emitted row meets a co-writer's
required-field contract, and mutation-checks that give each safety assert teeth).

## Standalone guarantee

The workspace engine has **zero dependency on any external launcher or tool**:

- It never imports or shells out to a launcher; a member's provider-name seam is
  inert (exit 3) rather than resolved.
- The shared-registry write is a post-success side-effect that **warns, never
  fails**: no `~/.workspaces/`, a registry hiccup, or a missing writer module all
  leave the local workspace command succeeding.
- So a Bridge with no other workspace-aware tool installed is fully functional;
  the shared registry is simply where identity is *offered* for any tool that
  wants to read it. The interop is a file contract, not a runtime coupling.

The reference co-writer of this file today is reinvent-lab's `k2a` (which
published the tool-neutral `~/.workspaces/` layout and `SCHEMA.md`); it is an
*example* of a conformant tool, not a requirement — the contract stands on its
own.
