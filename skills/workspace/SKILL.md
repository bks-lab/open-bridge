---
name: workspace
description: >-
  Bind code repos AND config overlays into a named WORKSPACE — a project
  container with a machine-global identity (shared with any conformant tool via
  ~/.workspaces/) and repo-local materialization (clones under .bridge/, lockfiles,
  a public-fork-safe exclude guard). `workspace create <name>` seeds the
  definition; `subscribe … --role code` clones a member repo; `subscribe …
  --role config` delegates a config overlay to the /overlay engine; `list` /
  `status` / `validate` inspect; `unsubscribe` removes. Standalone — zero
  dependency on any external launcher; the shared identity write is additive and
  warns-never-fails. Trigger: "/workspace", "workspace", "create a workspace",
  "add a repo to my workspace", "bind repos", "workspace status", "list
  workspaces", "subscribe repo to workspace", "unsubscribe from workspace",
  "workspace members", "project container".
metadata:
  scope: core
---

# Workspace — bind repos + config into one named project container

A **workspace** is a named project identity that pulls together the code repos
and config overlays you work on as one unit. It has two disjoint halves:

- **Identity** (*which project is this*) — name, member roots, git remotes —
  lives in the **machine-global shared registry** `~/.workspaces/workspaces.json`,
  a tool-neutral file any conformant tool can read/write under a documented
  lock + atomic-replace protocol. This is how a workspace means the same thing
  across tools on the machine.
- **Materialization** (*how does THIS repo realise it*) — the actual clones, the
  resolved-SHA lockfile, the fork-safety exclude block — is **repo-local** and
  never leaves the repo.

The engine is `scripts/workspace.py` (standalone, stdlib-only). This skill is the
`/workspace` surface over it. **Run the referenced file ONLY when the decision
tree sends you there.**

`/workspace` is the **umbrella**; for the deep *org-overlay* subscription flow
(manifest validation, per-file plan, 3-way merge, sync/diff) it delegates to and
cross-references **`/overlay`** (the `bridge-overlay` skill). Binding a config
overlay via `workspace subscribe … --role config` calls that same engine
(`overlay.py`) under the hood.

## When to use

- "Make a workspace for project X" → `create`
- "Add this repo to the workspace" / "bind these repos together" → `subscribe … --role code`
- "Pull the org's shared config into this workspace" → `subscribe … --role config` (delegates to `/overlay`)
- "What workspaces do I have / are the members drifted?" → `list` / `status`
- "Drop a repo / overlay from the workspace" → `unsubscribe`

**NOT** for:
- Managing an org overlay subscription on its own (manifest, sync, diff, authoring) → **`/overlay`** (`bridge-overlay`)
- Pushing YOUR changes upstream → `/promote`, `/bridge-sync`
- A knowledge-base index over a folder → a provider skill, if your instance ships one (unrelated to this "workspace")

## Command surface (the real engine CLI)

All commands run through `scripts/workspace.py`. Mutating verbs (`create`,
`subscribe`, `unsubscribe`) require a `user/*` branch (see Safety).

| Intent | Command |
|---|---|
| Create a workspace | `workspace create <name> [--dir <path>] [--title <label>] [--description <text>]` |
| Bind a code member repo | `workspace subscribe <name> <git-url> --role code [--ref <branch>]` |
| Bind a config overlay | `workspace subscribe <name> <git-url> --role config [--precedence <N>]` |
| Remove a member (code or overlay) | `workspace unsubscribe <name> <member>` |
| List all workspaces | `workspace list` |
| Validate definition(s) | `workspace validate [<name>]` |
| Member drift status (read-only) | `workspace status [<name>]` |

`add-repo` / `remove-repo` are accepted aliases for `subscribe` / `unsubscribe`.
`--role` defaults to `code`. Run any subcommand with `-h` for its exact flags.

Decision tree:

- **create / subscribe / unsubscribe** (a mutating verb) → read
  [`references/mechanics.md`](references/mechanics.md) for the exact per-flow
  steps, guards, and exit codes before running.
- **understand the model** (identity vs materialization, the shared registry,
  standalone guarantee, how a second tool co-writes safely) → read
  [`references/model.md`](references/model.md).
- **list / validate / status** (read-only) → just run it; no reference needed.

## What each mutating verb produces

- `create <name>` → writes the source-of-record definition
  `workflow/workspaces/<name>.yaml` (`schema_version`, `id`, `title`,
  `overlays: []`, `repos: []`), then additively mirrors the (thin) identity into
  the shared registry.
- `subscribe … --role code` → clones the member into
  `.bridge/workspaces/<name>/<member>/`, records it in the definition +
  `workspaces.lock.yaml` (resolved SHA), refreshes the `.git/info/exclude` guard,
  and re-publishes the grown identity (`directories[]`, `git_remotes[]`).
- `subscribe … --role config` → **delegates to `overlay.py`** (subprocess, never
  imported), then indexes the newly-materialized overlay name(s) in the
  definition's `overlays[]` and the identity's `extensions["open-bridge"]`.
- `unsubscribe <name> <member>` → code-first dispatch: removes the clone +
  lock entry (rebuilding the exclude guard, or dropping it when no code members
  remain), or delegates overlay removal to `overlay.py`; then re-publishes the
  shrunken identity.

## Safety (never bypass)

- **Branch gate** — every mutating verb refuses unless on a `user/*` branch
  (`require_user_branch`), so CORE/definition data never lands on a shared
  branch. Read-only verbs (`list`/`validate`/`status`) are always allowed.
- **Trust guard** — a member `git-url` is refused before any network access if it
  uses a scheme outside `{https, ssh, file}`, a `::` remote-helper transport, or
  a leading `-` (argv injection). A bare provider name is an inert seam → exit 3,
  no lookup (this Bridge is standalone).
- **Public-fork safety** — foreign code clones live under `.bridge/` and are
  masked by BOTH the tracked `.gitignore` and an untracked, per-workspace
  `.git/info/exclude` block — two independent guards, so a public fork can never
  `git add -A`-publish someone else's repo.
- **Warns-never-fails** — the shared-registry write is a post-success side-effect;
  if it fails (registry newer than supported, I/O error, module absent) the local
  workspace command STILL succeeds. The identity mirror is additive, never the
  source of record.

Exit codes: `0` ok · `1` guard refusal (branch/trust/not-found/conflict) · `2`
usage · `3` provider-name seam (no standalone resolver) · `4` registry version
too new (at the registry CLI only; swallowed to a warning here).

## Relationship to /overlay and to other tools

- **`/overlay`** (`bridge-overlay`) owns the org-overlay subscription lifecycle
  end-to-end. `/workspace` uses that same engine to bind a config overlay *into a
  named workspace*; for standalone overlay management (sync, diff, authoring) use
  `/overlay` directly.
- **Any conformant co-writer** (e.g. a launcher or file manager that reads
  `~/.workspaces/` — see the descriptive
  [`docs/schemas/workspaces-registry.schema.yaml`](../../docs/schemas/workspaces-registry.schema.yaml))
  shares the identity: it sees this workspace's row, and its own data lives
  untouched in its own `extensions[<tool>]` slice. `/workspace` never imports
  or requires such a tool — the interop is a file contract, not a dependency.
