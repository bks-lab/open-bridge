---
scope: core
description: The fail-closed contract overlay.py enforces when materializing an org overlay's scope:org content into a consumer Bridge — CORE-refusal, merge-not-clobber, scope tripwire, leak gate, reversibility, opt-in by structure.
---

# Org Overlays — the materialization contract

The `/overlay` skill and its engine ([`scripts/overlay.py`](../scripts/overlay.py))
pull an org's `scope:org` content **down** into a consumer Bridge — the
downstream inverse of `/promote`. This rule is the hard contract the engine
enforces on every `add` / `sync` / `apply`. Concept, CLI reference, and the
"why copy not submodule/subtree/symlink" rationale: [`docs/org-overlays.md`](../docs/org-overlays.md).

**The engine refuses rather than guesses. Every gate below is fail-closed** —
when a check cannot pass cleanly the engine declines that file (or the whole
operation) and surfaces why; it never writes on doubt.

## Gate 0 — never materialize off a user branch

Materialization writes into the live tree, so it runs **only on `user/*`**. On
any CORE branch (`main`, the non-default of `main`/`development`, `feature/*`)
every verb is a no-op with a CORE-only message. A CORE branch never carries a
materialized overlay file — that is precisely what keeps the weekly
`git merge main` conflict-free for every consumer.

## Gate 1 — CORE-refusal list (hard, non-overridable)

A destination is refused outright — no prompt, no `overlay-wins`, no precedence
override — when `classify_file` ([`scripts/categorize-commits.py`](../scripts/categorize-commits.py))
routes it `core`, **or** it is:

- a `_`-prefixed file (`_template.yaml` / `_schema.yaml`),
- a cluster-wrapper `README.md`,
- a path that escapes the repo tree (`../`, absolute).

An overlay ships only org-tier **instance** files; it can never replace a CORE
mechanism. It is also refused a `dest` already owned by **another** overlay
unless it has equal-or-higher `precedence` (single owner per path — Gate 3).

## Gate 2 — merge, never clobber

Default `on_conflict` is `prompt`. The engine compares live-on-disk vs the
lock-recorded value vs the new source, and:

- **absent from lock but present on disk** ⇒ USER-owned ⇒ `on_conflict` (prompt
  default) — never silently overwrite a user's file;
- **in lock, live == materialized, source unchanged** ⇒ skip (idempotent);
- **in lock, live == materialized, source changed** ⇒ re-materialize cleanly;
- **in lock, live != materialized** ⇒ **local edit** ⇒ 3-way merge against the
  reconstructed base; conflict or GC'd base ⇒ prompt (keep-local / take-upstream
  / manual).

**A local edit is never clobbered.** `on_conflict: overlay-wins` does not apply
to behavioural kinds on first materialize (Gate 8).

## Gate 3 — precedence: one owner per path

Each overlay carries an integer `precedence`; **higher wins** a destination
collision. A lower-precedence overlay may not write a path another overlay owns.
The owner is recorded in the lock, so ownership is deterministic across syncs.

## Gate 4 — scope:org tripwire on every materialized file

Every materialized instance file must carry an inline `scope: org`
(`metadata.scope` for skills; top-level for agents, project configs, and
cluster-wrapper YAML). The engine **verifies or injects** it. This is what makes
the leak model structural: `classify_file` then routes the file org-overlay-only
and `/promote` can never carry it to open-bridge.

> `standing-order` is the exception: its `scope:` field is a dispatch mode, not
> a tier, so a flat org standing order has no clean tier signal. The kind is
> engine-recognized but its tiering is an open framework question — see
> [`docs/org-overlays.md`](../docs/org-overlays.md) § scope-leak model. The
> `example-org` fixture ships none.

## Gate 5 — leak gate BEFORE write

Before any file is written, run [`scripts/no-scrub-leak.py`](../scripts/no-scrub-leak.py)
plus a raw-secret regex on the **staged temp file**. A hit refuses **that** file,
surfaces it, and continues with the rest — one poisoned file never aborts the
whole sync, and a poisoned file never reaches disk.

## Gate 6 — no raw secrets

Account files carry **only** `azure-keyvault://` / `keychain://` /
`1password://` URI references. Any raw secret (token, key, password) is refused
at the file boundary. Real values live in the vault, never in a materialized
file or the lock.

## Gate 7 — PII paths only, never values

`prompt_fields` inject local values where the shipped placeholder is still in
place. The lockfile records the **JSONPath of each prompted field, never the
value** (the value may be PII). The `materialized_sha256` ≠ `source_sha256`
inequality is the only record that a prompt happened.

## Gate 8 — behavioural files need an explicit `[y]`

A `kind` of `skill`, `agent`, or `standing-order` is behavioural: it requires an
explicit **per-file `[y]`** at first materialize (shown in the preview).
`config` and `rule` files batch-confirm. `--yes` is valid non-interactively
**only** for non-behavioural files.

## Gate 9 — copies, never symlinks

Write a **copy**, atomically; `materialized_sha256` is the hash **as written**.
Never symlink the consumer path onto the cache — a symlink dangles when the
cache is pruned and lets an edit write through into the shared cache (see
[`docs/org-overlays.md`](../docs/org-overlays.md) § Not a symlink farm).

## Gate 10 — reversibility discipline

`remove` hash-verifies each lock-recorded file and deletes **only** the clean
managed ones; it prompts on any locally-modified file and never touches an
unmanaged one. It then drops the cache, the `materialize` block, the lock entry,
and the ecosystem `@import`. `--keep-files` ends the subscription but leaves the
files. Removal must be as clean as the add — no orphaned files, no dangling
config.

## Gate 11 — opt-in, structurally

Overlay capability is **opt-in by structure, never a flag to forget**. A
consumer with no `materialize` block under a `role: org-overlay` upstream — or
an instance whose `infra/instances/<slug>.yaml` has `subscribes_overlays: []`
or omits it — is **overlay-incapable**: the engine has no work and reports
CORE-only. You opt in by `/overlay add` (which writes the materialize block);
there is nothing to disable.

## See also

- [`docs/org-overlays.md`](../docs/org-overlays.md) — concept, CLI, lock and
  conflict models, the "why not submodule/subtree/symlink" rationale.
- [`rules/promote-safety.md`](promote-safety.md) — the *outbound* leak gate;
  this rule is its inbound mirror (same classifier, same scope tripwire).
- [`rules/operations.md`](operations.md) § Scope-Routing — how folder + inline
  scope decides which upstream a file can reach.
- [`docs/schemas/overlay-manifest.schema.yaml`](../docs/schemas/overlay-manifest.schema.yaml)
  · [`docs/schemas/overlays-lock.schema.yaml`](../docs/schemas/overlays-lock.schema.yaml).
