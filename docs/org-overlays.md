---
summary: "Org overlays — the downstream inverse of /promote: how a consumer Bridge subscribes to an org's scope:org content and materializes it as git-excluded copies (opt-in tracked), with a manifest, a lockfile, and per-file conflict + leak gates."
type: guide
last_updated: 2026-10-24
related:
  - rules/org-overlays.md
  - docs/extension-model.md
  - docs/multi-instance.md
  - docs/schemas/overlay-manifest.schema.yaml
  - docs/schemas/overlays-lock.schema.yaml
---

# Org Overlays

An **org overlay** is a repository an organization publishes so that a fresh
Bridge clone can pull in the org's shared `scope:org` content — coordinator
skills, sub-agents, routing contexts, project configs, an ecosystem fragment —
without that content ever touching the public OSS upstream. The `/overlay`
skill (engine: [`scripts/overlay.py`](../scripts/overlay.py)) subscribes a
consumer Bridge to one or more overlay repos and **materializes** their files
into the live tree as copies, pinned to immutable hashes. By default those
copies are kept **out of git** — see § Git tracking of managed dests below for
what that means for backup, and the opt-in switch that changes it.

## The downstream inverse of `/promote`

`/promote` moves content **up and out**: it reads each commit's tier from
where the file lives (`scripts/categorize-commits.py`) and routes `scope:core`
to open-bridge, `scope:org` to your org overlay, `scope:user` nowhere. It is
the *publish* direction. Into an overlay in the flat-mirror layout below, the
publish step is an **export**, not a cherry-pick: see § Authoring an overlay.

Overlays are the missing *subscribe* direction. `/promote` answers "how does my
org's shared content leave my seed Bridge"; overlays answer the inverse: **"how
does a teammate's fresh clone get that org content back, without anyone
cloning the whole seed and without the org content leaking into OSS CORE?"**

```
        seed Bridge (user/*)                       org overlay repo
        ───────────────────                        ────────────────
        scope:core ──/promote───────▶ open-bridge  overlay.manifest.yaml
        scope:org  ──overlay-export─▶ org overlay ◀┐ tree/  (every file scope:org)
        scope:user   (stays local)               │ ecosystem.<org>.yaml
                                                  │
        consumer Bridge (user/*)                  │
        ────────────────────────                  │
        scope:org content  ◀──/overlay sync───────┘   (materialize as copies)
```

The two directions share the same classifier and the same scope tripwire, so a
file that `overlay-export.py` puts into the org overlay is exactly the file `/overlay`
will pull back down — and exactly the file both refuse to let reach
open-bridge.

## Why copy + manifest + lock — and not the obvious git mechanisms

The naive answer is "make the overlay a git submodule / subtree / symlink
farm." All three fail for the same structural reason: an overlay's files are
**scattered and interleaved** through the consumer tree — a skill under
`skills/`, a context under `workflow/contexts/`, an agent under
`.claude/agents/`, an account stub under `identity/accounts/`, an ecosystem
fragment at the repo root — sitting *next to* the consumer's own files at the
same paths. None of the three git mechanisms can express that.

### Not a git submodule

A submodule is a **single mount point**: one directory in the consumer maps to
one external repo at a pinned SHA. It cannot say "these twelve files at twelve
different paths all come from one upstream and interleave with my own files at
those paths." Forcing it would mean the org ships a parallel mounted tree that
never sits beside the consumer's own content. And a submodule working tree is
read-through to the remote — you cannot inject a prompt field or a `scope:org`
tripwire locally without dirtying the submodule.

### Not git subtree

`git subtree` grafts the overlay's **history** into the consumer's history. It
is a merge, not a copy — **irreversible** without history surgery. Removing an
overlay later means rewriting history or carrying dead commits forever, and
every pull re-merges, re-introducing path-collision and CORE-refusal problems
with none of the per-file gates. Subtree optimizes for "vendor a dependency and
forget it"; overlays need the opposite — visible, per-file, reversible,
re-syncable.

### Not a symlink farm

Symlinking consumer paths onto the overlay cache
(`skills/example-org-foo → .bridge/overlays/example-org/tree/skills/example-org-foo`)
has two fatal failure modes:

1. **Dangling.** The instant the cache is pruned, moved, or the overlay
   removed, every link dangles and the skill or agent silently disappears.
   Claude Code's skill loader already **fails** on symlinked skill directories
   (see [`docs/skill-distribution-architecture.md`](skill-distribution-architecture.md)
   § Option A — symlink farm, rejected).
2. **Edit-through data loss.** A prompt-field injection or a local tweak writes
   *through* the link into the cache. The next `git pull` of the cache clobbers
   the user's edit — or the user's edit pollutes the shared cache other
   materializations read. A symlink cannot hold "a copy that started from
   upstream but now carries local prompt values."

### What the engine does instead

It writes **real copies** into the consumer tree (git-tracked only if you
opt in — see § Git tracking of managed dests below; excluded from git by
default), records each in a lockfile keyed to the upstream's resolved SHA
plus per-file source and materialized hashes, and re-derives them on demand
from a sparse cache under `.bridge/overlays/<name>/`:

| Piece | Buys you |
|---|---|
| **Copy** (never symlink) | the file is real — survives cache loss, edits don't write through, the skill loader sees a normal directory |
| **Manifest** (`overlay.manifest.yaml`) | the org declares *exactly* which files mirror, how conflicts resolve, which fields to prompt before a behavioural file is live |
| **Lock** (`overlays.lock.yaml`) | the consumer can tell, per file, whether it is a clean upstream copy, a prompt-injected copy, or a local edit — so a re-sync 3-way-merges instead of clobbering |

This is the only model that supports scattered interleaved files, local prompt
injection, reversible removal, and conflict-aware re-sync **at the same time**.

## The overlay-repo source contract

What an org ships in its overlay repo (full authoring guide:
`skills/bridge-overlay/references/authoring.md`):

```
example-org-bridge/
├── overlay.manifest.yaml          # REQUIRED — the single declaration (root)
├── README.md                      # REQUIRED — what this overlay adds
├── ecosystem.example-org.yaml     # OPTIONAL — ecosystem fragment (@import-wired)
├── .github/workflows/publish-guard.yml   # leak gate BEFORE publish
└── tree/                          # mirrors the Bridge layout; every file scope:org
    ├── skills/example-org-coordinator/SKILL.md
    ├── .claude/agents/example-org-incident-handler.md
    ├── workflow/contexts/example-org-ops.yaml
    ├── workflow/projects/example-org-board.yaml
    └── identity/accounts/example-org-cloud.yaml
```

`tree/<path>` materializes to `<path>` (the `source_root` prefix is stripped).
The manifest's `defaults`, `selection`, and `files[]` blocks decide what mirrors
and how — schema + field-by-field comments live in
[`docs/schemas/overlay-manifest.schema.yaml`](schemas/overlay-manifest.schema.yaml).

**Hard rules the engine refuses or warns on** (the org honours them at authoring
time; the consumer engine enforces them again at materialize time):

- **Never ship** `_template.yaml` / `_schema.yaml`, a cluster-wrapper
  `README.md`, `identity/personas/**`, or `work/**`. Those are CORE or
  per-user — not overlay content. (`selection.exclude` should list them; the
  engine CORE-refuses them anyway.)
- **Discoverable instances** (contexts, projects, mandants, …) **must be FLAT**
  `<slug>.yaml`. The Bridge's `discover()` globs `<wrapper>/<types>/*.yaml` and
  cannot see a nested folder — the engine *warns* on nested-context discovery.
- **Slugs must be org-namespaced** (`example-org-*`) so a materialized file
  cannot collide with a user's own flat-discovered file of the same name.
- **Accounts carry only** `azure-keyvault://` / `keychain://` / `1password://`
  URI references. A raw-secret scan **refuses** the file otherwise.

## Authoring an overlay

The source contract above is a **flat mirror**: `tree/` plus a manifest, read by
[`scripts/overlay.py`](../scripts/overlay.py) only below `defaults.source_root`
(`tree/` when the manifest is silent). That layout decides how content gets in.

- **Export, never cherry-pick.** `/bridge-promote` and `/bridge-sync` write each
  file at the path it has in your Bridge. In a flat mirror that is the repo
  root, which no consumer reads: the PR merges green and the file is invisible
  everywhere, without an error. Both skills therefore fetch every overlay
  destination and check it with `python3 scripts/overlay-export.py --check-ref
  <name>/<branch>` (or `--target <checkout or manifest> --check-target` for a
  local checkout), and **refuse** it on any non-zero exit: 3 for a flat mirror,
  2 when the ref or path cannot be verified. No flag overrides the refusal.
  Only an overlay without a manifest, or one whose `source_root` is the repo
  root (`.`), passes.
- **Build the mirror with [`scripts/overlay-export.py`](../scripts/overlay-export.py).**
  It copies every file the router classifies into one tier to `tree/<path>`,
  prunes mirror files that left the tier, and regenerates the manifest's
  `files[]`. It never writes into your Bridge.

The authoring loop, run from the Bridge that owns the content:

1. **Pull colleagues' work back first.** A teammate's PR against `tree/` lands
   only in the overlay. The next export rewrites `tree/` from your live files,
   so a change that is not in your Bridge by then is overwritten, and a file
   that is not in your tier is pruned. Read the overlay's own history, which
   works whether or not this Bridge subscribes to the overlay: with `<last>`
   the overlay commit your previous export landed as,
   `git -C <overlay checkout> log --oneline <last>..HEAD -- tree/` lists what
   others changed and `git -C <overlay checkout> diff <last>..HEAD -- tree/`
   shows it. Carry every change into the live file in your Bridge. If this
   Bridge also subscribes to the overlay, `python3 scripts/overlay.py sync
   <name> --dry-run` followed by `python3 scripts/overlay.py diff <name>` is a
   second view of the same drift; a source Bridge that does not subscribe gets
   nothing from it, which is not the same as nothing to pull back.
2. **Preview:** `python3 scripts/overlay-export.py --target <overlay checkout>
   --scope org --dry-run` lists every `+ tree/...` copy and `- tree/...` prune.
   An unexpected prune is usually step 1 not done.
3. **Export** with the same command minus `--dry-run`, review
   `git -C <overlay checkout> diff`, run the leak gate, and open the PR in the
   overlay repo.

Hand edits to `tree/` from your Bridge and files at the overlay root other than
the manifest, its README and the ecosystem fragment are the two other ways a
mirror drifts from its source. The checklist in
`skills/bridge-overlay/references/authoring.md` covers them.

## The lock model

`overlays.lock.yaml` is a **generated** root file (`scope: user`) — the audit
trail and drift detector. Never hand-edited; the engine rewrites it on every
`add` / `sync`. Per overlay it pins `url`, `ref`, `resolved_sha`,
`manifest_sha256`, `precedence`, `last_synced`, and a `files[]` array. Per file
it records `src`, `dest`, `source_sha256`, and `materialized_sha256`. Schema:
[`docs/schemas/overlays-lock.schema.yaml`](schemas/overlays-lock.schema.yaml).

The integrity rule is the hash pair:

```
materialized_sha256 == source_sha256   ⇒  clean copy (no prompts injected)
materialized_sha256 != source_sha256   ⇒  prompt-fields were injected
```

That single comparison lets a re-sync distinguish "upstream changed" from "the
user edited locally" from "we injected a prompt value here" — without ever
storing the value. `prompted_fields` holds the JSONPath **paths** that were
prompted, **never** the supplied values (a value may be PII). The lock is
`scope: user`: the shipped root `.gitignore` ignores it for every clone, and a private origin
re-allows it (`scripts/user-data.py arm`, same policy as `ecosystem.<name>.yaml`), staging it
once with `git add -f` since a root file cannot be re-allowed by a deeper `.gitignore`.
The sparse cache under `.bridge/` is always gitignored, regardless of origin.

## Git tracking of managed dests

Materialized dests can land in **tracked** paths (`skills/`, `.claude/agents/`)
that no `.gitignore` pattern covers. By **default**, the engine keeps every
managed dest **out of git**: at materialize it writes a marked, idempotent
block into the consumer's LOCAL, untracked `.git/info/exclude` (never the
tracked `.gitignore`) listing every dest the overlay owns. That guard exists
because a fork of a public repo is itself public — without it, a plain
`git add -A` in the consumer could publish org-internal content (and even the
managed filenames) to a public upstream. Org content is consumed, not
re-committed, unless you opt in (below).

**Consequence: with the default off, the consumer's copy is not backed up
anywhere.** It never enters the consumer's git history, so a fresh clone of
the consumer doesn't get it, and losing the one working copy that carries a
local prompt-field override or a manual edit loses it for good. The
**authoritative backup of consumed org content is the overlay's own source
repo** — nowhere else, unless this switch is on.

For a consumer where that's the wrong tradeoff (typically a **private**
instance, where a public leak isn't a concern and the user wants consumed org
content backed up in their own git history), set the overlay's own
`materialize.track_managed_dests: true` in `bridge-config.yaml` — an explicit,
per-overlay, off-by-default switch (`/overlay add --track-managed-dests`, or
hand-edit the config and re-run `/overlay sync` / `/overlay apply`). The
engine never derives this from the consumer repo's visibility automatically —
it is always a deliberate, user-set choice. When set, the next materialize
drops any exclude block it had previously written for that overlay (so
flipping the switch takes effect without a manual edit to
`.git/info/exclude`) and the dests become normal, `git add`-able tracked
files like any other USER content. Flipping it back off re-excludes them on
the next sync/apply — it does not retroactively un-stage or un-commit files
you already added while it was on.

## The conflict + precedence model

The default is **merge, never clobber**. A materialize compares three things —
the live file on disk, the value recorded in the lock, and the new source — and
classifies each destination:

| Case | Condition | Action |
|---|---|---|
| **a. USER-owned** | absent from lock, but a file exists on disk | `on_conflict` (default: prompt) — never silently overwrite a user's file |
| **b. idempotent** | in lock, live == materialized, source unchanged | **skip** |
| **c. upstream-ahead** | in lock, live == materialized, source changed | re-materialize cleanly |
| **d. local edit** | in lock, live != materialized | **3-way merge** (see below) |

For case **d**, the engine reconstructs the merge base
(`git -C <cache> show <old_resolved_sha>:<src>`) and runs `git merge-file
<live> <base> <new>`: a clean merge is written; conflict markers or a
garbage-collected base fall back to a 2-way diff and a prompt
(keep-local / take-upstream / manual). **A local edit is never clobbered.**

`on_conflict` is an enum the manifest sets per overlay or per file —
`prompt` (default) · `skip` (keep the consumer's file) · `overlay-wins`
(overlay replaces it). Behavioural kinds (skill / agent / standing-order)
**ignore** `overlay-wins` for first materialize and force a per-file `[y]`
regardless.

**Precedence** resolves collisions *across* overlays. Each overlay carries an
integer `precedence`; **higher wins** a destination collision. The engine
refuses to let one overlay write a path already owned by another overlay
**unless** it has equal-or-higher precedence — a single owner per path,
deterministically.

**CORE-refusal** sits above all of this and is non-overridable — see
[`rules/org-overlays.md`](../rules/org-overlays.md) Gate 1.

## Multiple bridges side by side — per-URL structural separation

Subscribing to several orgs is just several entries. Each `role: org-overlay`
entry in `bridge-config.yaml.upstreams[]` carries its **own** `materialize`
sub-block — its own `cache`, `precedence`, and `select` glob — and its own
lockfile entry keyed by overlay name:

```yaml
# bridge-config.yaml  (USER layer)
upstreams:
  - name: open-bridge
    repo: bks-lab/open-bridge
    branch: main
    role: oss-core
    primary: true
  - name: example-org                       # ← added by /overlay add
    repo: example-org/example-org-bridge
    branch: main
    role: org-overlay
    contribute: true
    pull_interval_days: 7
    materialize:
      url: https://github.com/example-org/example-org-bridge.git
      ref: main
      cache: .bridge/overlays/example-org/   # own sparse cache
      precedence: 10                         # higher wins a path collision
      select: ["**"]
```

The separation is **structural, not declarative**: a `role: org-overlay` entry
**without** a `materialize` block — or an instance whose
`infra/instances/<slug>.yaml` has `subscribes_overlays: []` or omits it — is
**overlay-incapable**. There is nothing to disable: the engine simply has no
work to do and reports CORE-only. You opt *in* by adding a materialize block via
`/overlay add`, never out.

## The scope-leak model

The whole design exists to keep org content out of the public OSS upstream
**by structure**, not by remembering to scrub:

- **Org files are `scope:org` by path *and* inline tripwire.** Every
  materialized instance file carries `scope: org` (`metadata.scope` for skills;
  top-level for agents, project configs, and cluster-wrapper YAML), and the
  engine verifies or injects it (Gate 4). `classify_file` therefore routes them
  **org-overlay-only** — never to open-bridge.
- **Only the generic engine ships to open-bridge.** `scripts/overlay.py`, the
  `bridge-overlay` skill, the two schemas, and a single PII-free `example-org`
  fixture — zero org data, all English — are the CORE half. The org's *content*
  rides in the org's overlay repo, never here.
- **CORE-refusal keeps the weekly merge conflict-free.** Because no overlay file
  ever lands on a CORE branch, `git merge main` from a consumer's `user/*`
  branch never collides with materialized content.
- **PII values are never persisted** — the lock stores prompted **paths** only.
  Accounts are URI references only; raw secrets are refused at the file
  boundary (Gate 5/6).
- **The lock and cache stay out of public git** — lock is `scope: user`,
  `.bridge/` is gitignored.

> **Open question — `standing-order` tiering.** A standing order's `scope:`
> frontmatter is its *dispatch mode* (`always | per-repo | per-context`), not a
> tier — so a flat org standing order has no clean tier signal, and a bare
> `/promote` would misclassify it CORE. The engine recognizes
> `kind: standing-order` (forcing a behavioural `[y]`), but the `example-org`
> fixture deliberately ships none until the framework settles how a flat org
> standing order is tiered (a `protocols/standing-orders/org/` folder like
> `rules/org/`, or a dedicated tier field). Express org-wide behaviour via a
> `skill`, `agent`, or a `rules/org/` rule for now.

Full normative statement of each gate:
[`rules/org-overlays.md`](../rules/org-overlays.md).

## The `/overlay` CLI

The `/overlay` skill (`skills/bridge-overlay/`, `metadata.scope: core`) wraps
the engine. All seven verbs operate on the consumer's `user/*` branch; off a
user branch every verb is a CORE-only no-op (Gate 0).

### `add <git-url> [--ref main] [--name N] [--select GLOB...] [--precedence N] [--track-managed-dests] [--dry-run]`

Subscribe to an overlay. Writes the `role: org-overlay` `upstreams[]` entry and
its `materialize` sub-block, sparse-clones the repo into
`.bridge/overlays/<name>/`, validates the manifest against the schema, previews
the materialize plan with per-kind risk flags and an explicit per-file `[y]` for
every behavioural file, does the first materialize, and writes
`overlays.lock.yaml`. `--dry-run` stops after the plan. `--track-managed-dests`
opts this overlay's dests into normal git tracking instead of the default
`.git/info/exclude` guard (see § Git tracking of managed dests) — off by
default; can also be set later by hand-editing `materialize.track_managed_dests`
in `bridge-config.yaml` and re-running `sync`/`apply`.

### `sync [name] [--dry-run] [--yes] [--unattended]`

Pull the cache up to date and re-materialize. Fetches the ref, recomputes the
sparse selection and hashes, runs the 3-way comparison against the lock,
re-materializes clean and upstream-ahead files, prompts on conflict and on PII,
prunes files the upstream deleted, and bumps `resolved_sha`. No `name` syncs all
subscribed overlays. `--yes` is valid **only** for non-behavioural batches;
behavioural files always prompt.

`--unattended` is the scheduled run, and what `scripts/overlay-autosync.sh`
calls. It applies an overlay only when its whole plan needs nobody:

| The plan contains | Unattended run |
|---|---|
| updates, new config files, clean 3-way merges | applied |
| a behavioural file arriving for the first time | applied without it; listed as pending until a `[y]` in `/overlay sync` |
| a conflict with a local edit | the overlay is **held**: nothing written, the lock pin stays |
| a file it would delete | **held** |
| nothing new, inside `pull_interval_days` | `not-due`, nothing fetched |

A conflict holds the whole overlay because `sync --yes` keeps the local side
**and** advances the pin. From the next run on the 3-way base is the new
upstream, the file reads as an ordinary local edit, and the upstream change is
lost with nothing left that says so. The lock has one pin per overlay, so the
overlay waits as a whole until somebody resolves the conflict interactively. A
held or failed overlay is looked at again on every run; an applied one waits
out its `pull_interval_days` (top level of the `upstreams[]` entry, default 7).

Schedule it with one step: `scripts/install-upstream-autoupdate.sh --overlays`
installs a daily LaunchAgent at 07:15, after the CORE auto-update at 07:00, with
the same Signal notification. It notifies when the outcome changes, not every
morning. `--print` renders the job without installing it.

### `apply [name]`

**Offline** re-materialize from cache + lock only — no network. Idempotent: on a
clean tree it reports all-clean and writes nothing. Use it to rebuild the live
files after a fresh checkout without re-fetching.

### `status [name]`

Reports `resolved_sha` vs cache `HEAD`, days-since-sync vs `pull_interval_days`,
the last unattended run and its outcome (`applied`, `held` with the reason, or
`failed`), git provenance (`git -C <cache> log` / `blame`), and per-file counts:
`clean | locally-modified | upstream-ahead | conflict | orphan | CORE-refused`.

### `diff [name]`

Preview what the next `sync` / `apply` would change — the plan plus per-file
before/after — **without writing anything**.

### `remove <name> [--keep-files]`

End a subscription. Hash-verifies each lock-recorded file and deletes **only**
the clean managed ones (prompts on any locally-modified file), then drops the
cache, the `materialize` block, the lock entry, and the ecosystem `@import`.
`--keep-files` ends the subscription but leaves the materialized files in place.

### `list`

List subscribed overlays from the `role: org-overlay` `upstreams[]` entries:
`name`, `url`, `ref`, `resolved_sha`, `precedence`, file-count, `last_synced`.

## How a sync resolves (engine walkthrough)

The full algorithm lives in [`scripts/overlay.py`](../scripts/overlay.py); the
load-bearing order, condensed:

1. **Branch gate** — refuse off `user/*`; no `materialize` block ⇒ CORE-only
   no-op.
2. **Cache** — clone `--filter=blob:none --sparse` (cone-set to `source_root`)
   if absent, else `fetch && checkout <ref> && pull`; `resolved_sha = rev-parse
   HEAD`. Fall back to a full clone if partial-clone is unsupported.
3. **Validate** the manifest against the schema; record `manifest_sha256`; lint
   for org-namespaced FLAT slugs (warn on nested contexts).
4. **Plan** — expand `selection.include` minus `exclude` over the cache,
   intersect `materialize.select`, union the `files[]` exceptions; map `src →
   dest` by stripping `source_root`.
5. **CORE-refuse** any `dest` that is core / `_`-prefixed / a wrapper README /
   `_template|_schema` / path-escapes the tree; refuse a `dest` owned by another
   overlay of higher precedence.
6. **Merge-not-clobber** — the four-case classification above (a–d).
7. **3-way merge** for local edits — never clobber.
8. **Prompt fields** — JSONPath-lite into the staged YAML; prompt where the
   value still equals the shipped placeholder (`pii: true` masks it); record
   **paths** only.
9. **Leak gate BEFORE write** — a raw-secret regex on the staged temp file (the
   `scripts/no-scrub-leak.py` CORE-boundary scan runs only when the target is
   itself `core`, never for an org overlay); a hit refuses **that** file and
   continues the rest.
10. **Scope tripwire** — verify or inject inline `scope: org`.
11. **Behavioural gate** — skill / agent / standing-order require an explicit
    per-file `[y]` at first materialize; config and rule files batch-confirm.
12. **Write a COPY atomically** (never a symlink); `materialized_sha256 = hash
    as written`.
13. **Ecosystem fragment**: `ecosystem.<org>.yaml` goes through Steps 4 to 12
    like any managed file (lock entry, 3-way merge on a local edit, listed by
    `diff`), copied verbatim from the overlay root; then idempotently ensure its
    `@import` line in `CLAUDE.md`. Never block-merge.
14. **Prune** files in the lock but absent from the new plan (delete if clean,
    prompt if modified).
15. **Write the lockfile** (resolved SHA, manifest digest, timestamp, per-file
    hashes + prompted paths).
16. **Fleet record** — update this instance's `infra/instances/<slug>.yaml`
    `subscribes_overlays`.
17. **Report counts**; `--dry-run` stops before step 12 (plan only).

## Related

- [`rules/org-overlays.md`](../rules/org-overlays.md) — the normative contract
  (every gate the engine enforces, fail-closed).
- [`docs/extension-model.md`](extension-model.md) — CORE vs USER vs org tiers,
  the Routing Map, and the Plugin-extraction alternative.
- [`docs/multi-instance.md`](multi-instance.md) — several Bridges side by side;
  overlays are orthogonal (each instance subscribes independently).
- [`docs/skill-distribution-architecture.md`](skill-distribution-architecture.md)
  — why symlink farms were rejected for skills, the same reason overlays copy.
- [`docs/schemas/overlay-manifest.schema.yaml`](schemas/overlay-manifest.schema.yaml)
  · [`docs/schemas/overlays-lock.schema.yaml`](schemas/overlays-lock.schema.yaml)
  — the two schemas.
