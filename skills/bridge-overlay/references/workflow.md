# /overlay — Operator Runbook

Subscribe a Bridge to an **org overlay** and keep the materialized files in
sync. The deterministic implementation is `scripts/overlay.py`; this file is
the reference the skill follows when it drives that engine (and the spec the
engine implements). Schemas are authoritative:

- `docs/schemas/overlay-manifest.schema.yaml` — the org's `overlay.manifest.yaml`
- `docs/schemas/overlays-lock.schema.yaml` — the generated `overlays.lock.yaml`

> **Layer model in one line:** an overlay is the **lower** layer, your user
> files are the **upper** layer. The overlay never wins a collision with a file
> you edited — the 3-way merge protects your edit, and a behavioural file always
> stops for your `[y]`.

## What lives where

| Thing | Path | Owner | Tracked? |
|---|---|---|---|
| Subscription declaration | `bridge-config.yaml.upstreams[]` entry (`role: org-overlay`) + its `materialize:` sub-block | user | yes |
| Overlay cache (sparse clone) | `.bridge/overlays/<name>/` | engine | **no** (gitignored) |
| Lockfile (audit + drift) | `overlays.lock.yaml` (repo root) | engine (generated) | scope:user — gitignored in public forks |
| Materialized files | their real dest paths (e.g. `workflow/contexts/example-org-billing.yaml`) | engine, written as COPIES | yes (they're your USER files now) |
| Ecosystem fragment | `ecosystem.<org>.yaml` at root (a managed file, in the lock) + an `@import` line in `CLAUDE.md` | engine materializes / wires | yes |
| Fleet record | `infra/instances/<this-instance>.yaml` `subscribes_overlays` | engine updates | yes |

The subscription entry (representative shape — schema-light; the engine owns
the exact keys):

```yaml
upstreams:
  - name: example-org              # overlay slug (= manifest overlay.name = lock key)
    repo: example-org/bridge-overlay
    branch: main
    role: org-overlay              # what makes list/sync treat it as an overlay
    contribute: false              # an overlay is pull-only by default
    pull_interval_days: 7          # status warns past this; the unattended sync waits this long
    materialize:                   # presence of THIS block = a subscription
      url: https://github.com/example-org/bridge-overlay.git
      ref: main                    # branch or tag requested (resolves to resolved_sha)
      select: ['**']               # consumer-side narrowing, intersected with manifest.selection
      precedence: 10               # higher wins a dest collision BETWEEN overlays
      cache: .bridge/overlays/example-org/
```

A `role: org-overlay` entry **without** a `materialize:` block is a push-only
org target (for `/promote` of `scope: org` commits) — `/overlay` treats it as
**no-op** and prints a CORE-only message.

---

## SYNC ALGORITHM (the 17 steps)

`add`, `sync`, `apply`, and `diff` all run this pipeline; they differ only in
where they stop and whether the network is touched:

- `add` — Steps 1–17, network on, writes the subscription first
- `sync` — Steps 1–17, network on (fetch + pull)
- `apply` — Steps 1·3–17 **offline** (skips Step 2's network; uses the cache as-is)
- `diff` — Steps 1–11, **stops before Step 12** (plan only, no writes)
- `--dry-run` — any of the above, **stops before Step 12**

### 1 — Branch + subscription gate

Refuse off `user/*` (a CORE branch — `main`/`development` — **never**
materializes). Load `upstreams[]` and, for the requested overlay (or all),
its `materialize:` block. **No `materialize:` block ⇒ no-op** with a
"CORE-only / not a subscription" message.

### 2 — Cache (network; skipped by `apply`)

```bash
# absent → sparse cone clone restricted to the manifest's source_root
git clone --filter=blob:none --sparse <url> .bridge/overlays/<name>/
git -C .bridge/overlays/<name>/ sparse-checkout set <source_root>
# fall back to a FULL clone if the server rejects partial-clone
# present → refresh
git -C <cache> fetch --quiet && git -C <cache> checkout <ref> && git -C <cache> pull --ff-only
```

`resolved_sha = git -C <cache> rev-parse HEAD`. `apply` skips this entirely and
trusts whatever is already in the cache (offline).

### 3 — Validate the manifest

```bash
check-jsonschema --schemafile docs/schemas/overlay-manifest.schema.yaml \
                 <cache>/overlay.manifest.yaml
```

Record `manifest_sha256`. **Lint the org's hygiene** (warn, don't hard-fail
unless noted):

- Slugs MUST be **org-namespaced** (`<org>-*`) — a bare `<slug>.yaml` risks
  flat-discovery collision with the user's own files. Warn loudly.
- Discoverable instances (contexts / projects / mandants / …) MUST be **flat**
  `<slug>.yaml` — a nested-folder context `discover()` can't see. Warn.

### 4 — Build the file plan

Expand `selection.include` minus `selection.exclude` over `<cache>/<source_root>`,
**intersect** with `materialize.select` (the consumer-side narrowing), then
**union** the `files[]` exception list. Map `src → dest` by stripping
`source_root` (so `tree/workflow/contexts/x.yaml` → `workflow/contexts/x.yaml`).

### 5 — Classify + HARD-REFUSE each dest

`classify_file(dest)` via the categorize-commits logic. **HARD-REFUSE** (drop
the file from the plan, surface why) any dest that is:

- `core`-classified (an overlay may never write a CORE-tier file)
- `_`-prefixed (`_template.yaml` / `_schema.yaml` / any `_*`)
- a cluster-wrapper `README.md`
- a `_template` / `_schema` companion
- a path that **escapes the tree** (`..`, absolute, symlink target outside repo)

Also refuse a dest **owned by ANOTHER overlay** in the lock **unless** this
overlay's precedence is **≥** the owner's (higher precedence wins; equal is
allowed as a takeover with a note; lower is refused). See *Precedence model*.

### 6 — Merge-not-clobber decision (vs the lock)

For each surviving `dest`, decide against `overlays.lock.yaml`:

| Case | Condition | Action |
|---|---|---|
| (a) **USER-owned** | absent from lock but present on disk | a file you own collided — run `on_conflict` (default `prompt`) |
| (b) **idempotent skip** | in lock, `live == materialized_sha256`, src unchanged | SKIP — nothing to do |
| (c) **upstream-ahead** | in lock, `live == materialized_sha256`, src **changed** | re-materialize (clean upstream update) |
| (d) **local edit** | in lock, `live != materialized_sha256` | LOCAL EDIT → Step 7 (3-way) |

### 7 — 3-way merge (local-edit recovery)

```bash
base=$(git -C <cache> show <old_resolved_sha>:<src>)   # the version we last shipped
git merge-file <live> <base> <new>                      # in-place 3-way
```

- Clean merge ⇒ write the merged result.
- Conflict markers, **or a GC'd base** (old SHA unreachable in the cache) ⇒
  fall back to a **2-way diff** and **prompt**:
  `[k] keep-local · [u] take-upstream · [m] manual`. **Never clobber a local
  edit** without that choice.

### 8 — Prompt-fields (placeholders → real values)

For each `prompt_fields[]` in the manifest, resolve the JSONPath-lite
(`$.a.b`, `$.arr[*].c`) into the **staged** YAML. **Where the value still equals
the shipped placeholder**, prompt for the real value (mask the input when
`pii: true`). The lock records the **PATHS only** (`prompted_fields[]`) — never
the supplied value.

### 9 — Per-file leak gate (BEFORE write)

A **raw-secret regex** runs on the staged temp (accounts must carry **only**
`azure-keyvault://` / `keychain://` / `1password://` URI references). The
`no-scrub-leak.py` CORE-boundary scan runs **only when the materialize target is
itself `core`** — an org overlay writes `scope:org`, never core, so it is not
run there (core-leak protection lives at the consumer's push boundary):

```bash
# only when target == core (never reached for an org overlay):
python3 scripts/no-scrub-leak.py <staged-temp-file>
```

A hit **refuses THAT file**, surfaces it, and **continues** with the rest of the
plan. One poisoned file never aborts the whole sync.

### 10 — Scope tripwire

Verify (and inject if missing) the inline `scope: org` marker so a later
genericization/promote sweep classifies the file correctly:

- skills → `metadata.scope: org`
- agents / standing-orders / project-config / cluster-wrapper YAML →
  top-level `scope: org`

### 11 — Behavioural gate

`kind ∈ {skill, agent, standing-order}` ⇒ an **explicit `[y]`** when a file
arrives for the **first** time (shown in the preview, with what it changes).
The gate asks once per **unit**: a skill folder `skills/<name>/` is one unit,
an agent or standing-order file is its own. All or none: a declined or
unanswered unit writes none of its changed files, updates to files already in
the lock included, so no skill is left with a SKILL.md that routes to a
missing `references/` file. config / rule files **batch-confirm**. `--yes` is
honoured **only** for non-behavioural files; with `--yes` or no TTY a gated
unit is **withheld + reported** (`WITHHELD skills/<name>/`, count `withheld=`),
never auto-applied. Its lock entries stay as they were, so the next run and
`status` see it again.

The one answer covers the whole unit. A file upstream removed from a withheld
folder is not pruned (Step 14 keeps it and its lock entry), since the unchanged
SKILL.md may still route to it. A file the consumer already has inside the
unit (`user-owned`, `on_conflict: prompt`) is listed as "overwrites your file"
and settled by the same `[y]`, with no second per-file question. The one
exception is `on_conflict: skip`: the manifest declared that the consumer's own
file is kept, so an accepted unit keeps it. A local edit held in a unit keeps
its 3-way base while the pin moves on: the base is the version whose hash its
lock entry still carries, looked up in the cache history when the pinned blob
differs, so the upstream change merges once the unit is confirmed.

> `diff` and `--dry-run` STOP HERE. Everything above is read-only.

### 12 — Write the copy (atomic)

Write a **COPY** (never a symlink) atomically (temp + `os.replace`). Record
`materialized_sha256 = hash AS WRITTEN` (≠ `source_sha256` exactly when
prompt-fields were injected — that's the clean-copy vs prompt-injected
signal in the lock).

After a clean Step-7 merge of a local edit, `materialized_sha256` stays the
overlay's own version, not the merged bytes. The file therefore keeps reporting
as `locally-modified` on every later sync, and that is what sends the next
upstream change through the merge instead of overwriting the edit.

### 13 — Ecosystem fragment

If the manifest declares `ecosystem_fragment`, `ecosystem.<org>.yaml` is
planned like any other managed file (Steps 4 to 12): it has a lock entry, a
local edit goes through the Step-7 3-way merge, `diff` and `--dry-run` list it,
and `remove` deletes it only while it is clean. Two differences: the source
lives at the overlay **root** (not under `source_root`), and it is copied
**verbatim** (no scope tripwire, no prompt-fields) and never narrowed by
`select:`. Then **idempotently** ensure the `@ecosystem.<org>.yaml` `@import`
line exists in `CLAUDE.md`, also when the overlay ships the same file under
`source_root` as well. **Never block-merge** into `ecosystem.yaml`.

The engine marks every lock entry it writes with `fragment_managed: true`.
Under that marker a fragment with no `files[]` entry is the consumer's own
(`user-owned`, typically a registry that was there before the subscription) and
is never merged into or removed.

A lock from before the fragment was managed has neither the marker nor an entry.
That engine wrote the fragment verbatim at the pinned `resolved_sha`, so the
first sync compares the live file against that blob: equal is untouched (take
the upstream change), different is a local edit (3-way merge). If that blob is
gone (a force-pushed overlay, a re-cloned cache), a fragment equal to the new
source is adopted as is. Anything else is kept, reported as a conflict and
recorded with the overlay's current version as its base; an upstream change that
landed while the base was unknown is therefore not replayed into it, later ones
merge normally. If the overlay stops shipping its fragment, a clean copy is
pruned (Step 14) and its `@import` is dropped with it.

### 14 — Prune upstream-deleted

A file in the lock but **absent** from the new plan (the org removed it): delete
it **if clean**; **prompt** if it was locally modified.

### 15 — Write the lockfile

Rewrite `overlays.lock.yaml` for this overlay: `resolved_sha`,
`manifest_sha256`, `last_synced` (ISO-8601 UTC), and per-file
`src/dest/source_sha256/materialized_sha256` + `prompted_fields[]` (paths
only). Update `materialize.ref` in `bridge-config.yaml` if it changed.

### 16 — Fleet record

Update `infra/instances/<this-instance>.yaml` `subscribes_overlays` (add the
name + url + precedence on `add`; remove on `remove`). This is how the fleet
knows which Bridge consumes which overlay.

### 17 — Report counts

```
overlay sync — example-org (resolved 9f3a… ← ref main)
  clean (skipped)        12
  upstream-ahead          3   re-materialized
  local-edit (3-way)      1   merged clean
  conflict                0
  prompted (fields)       2   workflow/contexts/example-org-billing.yaml
  CORE-refused            1   tree/_template.yaml  (overlays never ship templates)
  leak-refused            0
  orphan (pruned)         1   workflow/projects/example-org-old.yaml
  →  lock updated · fleet record updated
```

`--dry-run` prints the same matrix with **"(plan — nothing written)"** and is
**idempotent**.

---

## Conflict / precedence model

**Two distinct axes — never conflate them:**

1. **Overlay vs user (layering).** The overlay is the lower layer; your edits
   are the upper layer. A file you changed since the last sync is detected in
   Step 6(d) and recovered via the Step-7 3-way merge — the overlay's update is
   *merged into* your edit, not dropped on top of it. Markers / GC'd base ⇒
   prompt. **last-writer is YOU**, mediated by the merge.

2. **Overlay vs overlay (precedence).** When two subscribed overlays target
   the **same dest**, the integer `precedence` decides: **higher wins**. Step 5
   refuses the lower-precedence overlay's claim on a dest already owned (in the
   lock) by a higher-precedence overlay. Equal precedence ⇒ a takeover with a
   note (last sync wins; surfaced so you can re-rank). This is the only place
   "last-writer by precedence int" applies — and only *between overlays*.

A user file always beats both: an unmanaged dest you own is Step 6(a)
(`on_conflict`, default `prompt`), never silently overwritten.

## 3-way base recovery (when the base is gone)

The Step-7 base is `git -C <cache> show <old_resolved_sha>:<src>`. The old SHA
can be unreachable if the cache was re-cloned shallow or the upstream
force-pushed/GC'd. Recovery ladder:

1. **Base present** → normal `git merge-file` 3-way. Best fidelity.
2. **Base GC'd, `source_sha256` in the lock matches a fetchable object** →
   fetch that blob, use it as base.
3. **Base unrecoverable** → drop to a **2-way diff** (live vs new) and
   **prompt** (`keep-local` / `take-upstream` / `manual`). Document in the
   report that the merge was 2-way (lower confidence).

Never silently take-upstream when the base is missing — that would erase a
local edit you can't see.

## Dry-run / diff semantics

- `diff [name]` and `--dry-run` run Steps 1–11 and **stop before Step 12**.
  Output: the plan, per-file before/after, the same count matrix tagged
  "(plan — nothing written)". No cache mutation beyond Step 2's fetch
  (`diff` may fetch to compare; pass nothing destructive).
- Idempotent by construction: a `diff` immediately after a `sync` on a clean
  tree shows **all clean**, zero writes pending.

## Status counts (`status [name]`)

Read-only health, no writes:

- `resolved_sha` (lock) vs `git -C <cache> rev-parse HEAD` → behind/ahead/at.
- `days-since(last_synced)` vs `pull_interval_days` → 🟢/🟡/🔴.
- `last unattended`: when the scheduled `sync --unattended` last ran and what it
  did (`applied`, `held` with the conflict or deletion that held it, `failed`),
  from `.bridge/overlay-unattended.yaml`. `never` until the job has run.
- Provenance per file: `git -C <cache> log -1 <src>` and
  `git -C <cache> blame <src>` for "who shipped this line".
- Bucketed counts: `{clean · locally-modified · upstream-ahead · conflict ·
  orphan · pending-confirm · CORE-refused}`. `orphan` = in lock, gone from the
  cache's plan (an upcoming prune); `locally-modified` = Step 6(d) candidates;
  `upstream-ahead` includes files the consumer does not have yet (`--json`
  used to report them under a separate `clean-new` key);
  `pending-confirm` = files the next sync holds at the Step 11 gate, listed
  under `withheld` by unit. A withheld file is never missing from the counts.

## `remove <name>` and `--keep-files`

```
remove example-org
  hash-verify each file in the lock entry:
    live == materialized_sha256  → CLEAN  → delete
    live != materialized_sha256  → DIRTY  → prompt [d]elete / [k]eep
  then:
    - drop .bridge/overlays/example-org/            (cache)
    - drop upstreams[] materialize: block (and the entry if pull-only otherwise)
    - drop the example-org entry from overlays.lock.yaml
    - remove the @ecosystem.example-org.yaml @import line from CLAUDE.md
      (ecosystem.example-org.yaml is a lock-recorded file: deleted if clean,
      kept if locally modified)
    - update infra/instances/<this>.yaml subscribes_overlays
```

`--keep-files` ends the subscription (drops cache + materialize block + lock
entry + `@import`) but **leaves every materialized file in place** — they
become plain USER files you now own outright. Use this to "fork off" an overlay
you no longer want to track but whose content you want to keep and edit freely.

Only **clean** managed files are deleted automatically; a locally-modified file
always prompts. `remove` never deletes a file the lock doesn't claim.

## Multi-overlay separation

- Each overlay is a **separate** `upstreams[]` entry, a **separate** cache dir
  (`.bridge/overlays/<name>/`), and a **separate** key in `overlays.lock.yaml`.
  No shared state between overlays except the precedence arbitration in Step 5.
- `sync` / `apply` / `status` / `diff` with **no name** iterate **all**
  subscribed overlays, lowest precedence first so higher-precedence overlays
  resolve dest collisions last (and win).
- Org-namespaced slugs (`<org>-*`) are what keep two overlays' flat-discovered
  instances from colliding — Step 3 warns when an overlay ships a bare slug.
- A dest claimed by overlay A cannot be silently re-claimed by overlay B; B is
  refused unless `precedence_B ≥ precedence_A` (Step 5). The lock's `files[]`
  per overlay is the ownership registry.

## Fleet-record update

On `add`/`remove`, the engine updates the active instance's record under
`infra/instances/<this-instance>.yaml`:

```yaml
subscribes_overlays:
  - name: example-org
    url: https://github.com/example-org/bridge-overlay.git
    precedence: 10
```

This makes overlay membership visible across the fleet (multi-instance
awareness) without any instance reaching into another — registration is
awareness only, per `infra/instances/_template.yaml`.

## Recovery notes

- **Partial-clone unsupported** (Step 2): the engine retries a full clone
  automatically; the sparse set still applies via `sparse-checkout`.
- **Manifest invalid** (Step 3): abort the overlay (no files touched); surface
  the `check-jsonschema` error verbatim so the org can fix their manifest.
- **A single file refused** (Steps 5 / 9): never aborts the run — it's dropped
  and reported; the rest of the plan proceeds.
- **Interrupted write**: atomic temp+replace (Step 12) means a crash leaves
  either the old file or the new one, never a half-written file; re-run `apply`
  to converge offline.
