# Workspace mechanics — per-verb operational guide

Read this before running a **mutating** verb (`create`, `subscribe`,
`unsubscribe`). Every step maps to real behaviour in `scripts/workspace.py`;
read-only verbs (`list`, `validate`, `status`) need nothing from here — just run
them.

All mutating verbs first assert a `user/*` branch (`require_user_branch`) and
publish an identity mirror to the shared registry **after** the local step
succeeds (post-success side-effect; `list`/`validate`/`status` never publish).

## `create <name> [--dir D] [--title T] [--description D]`

1. Branch gate → slug guard (`^[a-z][a-z0-9-]*$`) → exists guard
   (`workflow/workspaces/<name>.yaml` must not already exist).
2. Build the definition from the template scalar seeds: `schema_version: 1`,
   `id`, `title` (= `--title` or the id), optional `description`/`directory`,
   `created_at`/`updated_at`, empty `overlays: []` + `repos: []`.
3. Atomic-write `workflow/workspaces/<name>.yaml` (the source of record).
4. Post-hook: publish a thin identity row — `directories[0]` = the given
   `--dir` (canonicalized) when one was passed, else no code members yet →
   empty `directories`/`git_remotes`.

Refusals (bad branch / bad slug / already exists) → exit 1, nothing written.

## `subscribe <name> <git-url> --role code [--ref R]`

Default role is `code`. This clones a member repo into the workspace.

1. Branch gate.
2. **Trust guard** on the URL (before any network): refuse a scheme outside
   `{https, ssh, file}`, a `::` remote-helper transport, or a leading `-`. A bare
   provider name (no `/`) is an inert seam → **exit 3**, no lookup.
3. Derive the member slug (last path segment, `.git` stripped, lowercased).
4. Idempotency: same slug + same url + same ref → "already a member", exit 0;
   same slug + different url/ref → error ("remove it first"), exit 1.
5. Clone into `.bridge/workspaces/<name>/<member>/`
   (`git clone --recurse-submodules [--branch R]`), record resolved HEAD SHA.
6. Ordering matters here (exclude armed BEFORE the tracked definition records the
   clone, closing the crash window where a public fork could `git add -A`-publish
   freshly cloned foreign code): refresh the `.git/info/exclude` marked block with
   every code member path (including the new one) FIRST; then append
   `{url, role: code, name, ref, path}` to the definition's `repos[]` and write it;
   THEN rebuild `workspaces.lock.yaml[<name>]` from ALL live code clones (full
   rewrite, not append).
7. Post-hook: re-publish the grown identity (`directories[0]` = the workspace's
   own `directory:` when set, followed by each clone's abs path labelled
   `repo`; `git_remotes[]` = each clone's `origin`).

## `subscribe <name> <git-url> --role config [--precedence N]`

Binds an org config overlay into the workspace by **delegating to the overlay
engine** — this is the same machinery `/overlay` drives.

1. Branch gate + trust guard (as above).
2. Snapshot the overlay universe *before* (keys of `overlays.lock.yaml` ∪ dirs
   under `.bridge/overlays/`).
3. Run `overlay.py add <url> --ref <ref|main> [--precedence N]` as a subprocess
   (never imported — its prompts, gates and exit codes pass through verbatim).
   overlay.py runs its own CORE-refusal, leak-check, 3-way-merge and per-file
   `[y]` gates and writes atomic COPIES + `overlays.lock.yaml` + the ecosystem
   `@import`.
4. If overlay.py exits non-zero → error, exit 1.
5. Snapshot *after*; the new overlay name(s) = the set difference. Index each new
   name in the definition's `overlays[]` (config members are indexed by NAME
   only — they are not added to `repos[]`).
6. Post-hook: `extensions["open-bridge"]["overlays"]` now carries the names.

The workspace layer learns the overlay name by **diffing the universe**, not by
parsing overlay.py's stdout — one `add` may surface zero, one, or several names
(idempotent re-add surfaces zero → "(no new overlay)", still exit 0).

## `unsubscribe <name> <member>`

Code-first dispatch: if `<member>` is a code member → remove code; else if it is
an indexed overlay name → remove config; else error (exit 1).

- **Code member:** metadata FIRST, clone deletion LAST — filter the member out of
  `repos[]` and write the definition, rebuild `workspaces.lock.yaml[<name>]` from
  the survivors, rebuild the exclude block with the remaining code paths (or drop
  the whole marked block when no code members remain, preserving any unrelated
  exclude lines) — only then `rmtree` the clone. If the rmtree is interrupted, the
  definition/lock/exclude are already consistent (member already gone); a stray
  clone directory is inert (unreferenced, still excluded).
- **Config overlay:** delegate `overlay.py remove <name>` (it hash-verifies and
  deletes clean managed files, drops the `@import` + lock entry + its own exclude
  block), then filter the name out of the definition's `overlays[]`.

Both paths re-publish the shrunken identity (a REPLACE mirror, so removal
actually shrinks the shared row).

## Guard / exit-code reference

| Guard | Result |
|---|---|
| Branch gate (mutating verbs; `BRIDGE_OVERLAY_ALLOW_ANY_BRANCH=1` bypasses) | exit 1, nothing mutated |
| Trust guard (bad scheme / `::` / leading `-` / unrecognized) | exit 1, before any clone |
| Provider-name seam (bare name, no standalone resolver) | exit 3, graceful, no lookup |
| Delegated overlay.py non-zero | exit 1 |
| Not-found / dup-conflict / invalid slug | exit 1 |
| Usage / repo-root / chdir | exit 2 |
| Registry version newer than supported | exit 4 at the registry CLI; via the publish hook it is warned and the workspace command still exits 0 |
| Any publish failure | stderr warning, never changes the exit code ("warns, never fails") |
| Atomic-write failure before `os.replace` | tmp unlinked; live file unchanged (no torn write) |
