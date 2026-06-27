---
name: bridge-overlay
description: >-
  Subscribe a Bridge to an ORG OVERLAY — a git repo an organisation
  publishes that ships its shared config (contexts, projects, mandants,
  accounts, org skills/agents/standing-orders, an ecosystem fragment) as a
  flat mirror tree. /overlay add <git-url> sparse-clones the overlay,
  validates its manifest, previews a per-file plan with risk flags, and
  materializes COPIES into your repo under a lockfile — never block-merging
  your config, never clobbering your edits (3-way merge), never touching
  CORE. sync/apply/status/diff/remove/list manage the subscription over
  time. The overlay is the LOWER layer; your user files always win.
  Trigger: "/overlay", "org overlay", "subscribe to overlay",
  "materialize org config", "pull org overlay", "unsubscribe overlay",
  "add org config by git url", "list overlays", "overlay status",
  "overlay diff".
metadata:
  scope: core
---

# Bridge Overlay — subscribe to an org's config bundle

An **org overlay** is a git repo an organisation publishes so its members'
Bridges can share config without each person hand-copying files. It mirrors a
**flat tree** of files (`tree/<path>` → `<path>`), every file `scope: org`,
declared by a root `overlay.manifest.yaml`. `/overlay` is the consumer side:
it subscribes, materializes COPIES under a lockfile, and keeps them in sync.

It is the **mirror-image** of the push skills:

| Skill | Direction | Unit |
|---|---|---|
| `/promote` · `/bridge-sync` | **push** your `scope:org`/`core` commits **up** to an upstream | commits |
| `/overlay` | **pull** an org's published config **down** into your repo | manifest-declared files |

Read the referenced file ONLY when triggered.

## When to use

- An org gives you a git URL: "subscribe your Bridge to our overlay"
- You want the org's shared contexts / projects / mandants / accounts / org
  skills materialized locally and kept current
- You already subscribed and want to pull updates (`sync`), preview them
  (`diff`), re-materialize offline (`apply`), check freshness (`status`),
  or end the subscription (`remove`)

**NOT** for:
- Publishing an overlay (that's the org's job — see `references/authoring.md`)
- Pushing YOUR changes upstream (`/promote`, `/bridge-sync`)
- One-off file copies with no ongoing subscription (just copy the file)

## What an overlay carries

An overlay ships an org's `scope: org` building blocks as a flat `tree/` mirror —
**config AND tools**, so one git-URL is a *complete* org bridge, not just config:

| Group | Path | Kind | Gate |
|---|---|---|---|
| Contexts / projects / mandants / accounts | `workflow/` · `identity/` | config | batch-confirm |
| Remotes / shared infra | `infra/` | config | batch-confirm |
| Org rules | `rules/org/**` | rule | batch-confirm |
| **Org skills (complete)** | `skills/<name>/**` | skill | **per-file `[y]`** |
| **Org sub-agents** | `.claude/agents/<name>.md` | agent | **per-file `[y]`** |
| Ecosystem fragment | `ecosystem.<org>.yaml` | ecosystem-fragment | `@import` |

**Skills ship COMPLETE.** A skill is a directory: `SKILL.md` declares the tier in
its `metadata.scope`; the sibling `scripts/`, `references/`, `assets/` carry no
inline scope and **inherit the tier of their SKILL.md** (resolved from the overlay
SOURCE, so a fresh `add` ships the scripts too — they are NOT refused as CORE).
A markdown-only skill and a script-bearing skill both transfer whole.

**Don't ship framework as org.** A skill/agent that already exists in the
consumer's CORE (e.g. a generic `bridge-*` tool, or a `scope:core` sub-agent like
`archivist`) must NOT be in the overlay — it collides (`user-owned`) and would
clobber the canonical core copy. Carry only what is genuinely org-specific; leave
framework to the framework. The CORE-refusal gate stops anything that classifies
`core`, but a core tool mis-tagged `scope: org` in the source slips that gate — so
exclude it at authoring time (the publish guard + a `user-owned` count in
`status` are the backstops).

## The 7 commands (`/overlay <cmd>`)

| Command | What it does |
|---|---|
| `add <git-url> [--ref main] [--name N] [--select GLOB…] [--precedence N] [--dry-run]` | Subscribe: write a `role: org-overlay` `upstreams[]` entry + `materialize:` sub-block in `bridge-config.yaml`, sparse-clone into `.bridge/overlays/<name>/`, validate the manifest, **preview the plan** with per-kind risk flags + explicit per-file `[y]` for behavioural files, first materialize, write `overlays.lock.yaml`. |
| `sync [name] [--dry-run] [--yes]` | Pull the cache, recompute the sparse set + hashes, 3-way vs the lock, re-materialize clean / upstream-ahead files, **prompt** on conflict + on PII prompt-fields, prune upstream-deleted files, bump `resolved_sha`. No `name` ⇒ all overlays. |
| `apply [name]` | **OFFLINE** re-materialize from cache + lock (no network). Idempotent — a clean tree reports all-clean and writes nothing. |
| `status [name]` | `resolved_sha` vs cache HEAD; days-since-sync vs `pull_interval_days`; `git -C <cache>` log/blame provenance; counts `{clean·locally-modified·upstream-ahead·conflict·orphan·CORE-refused}`. |
| `diff [name]` | Preview the next `sync`/`apply` (plan + per-file before/after). **No writes.** |
| `remove <name> [--keep-files]` | Unsubscribe: hash-verify each lock-recorded file, delete **only clean** managed files (prompt on locally-modified), drop the cache + `materialize:` block + lock entry + the ecosystem `@import`. `--keep-files` ends the subscription but leaves the files in place. |
| `list` | Subscribed overlays from `upstreams[]` (`role: org-overlay`): name, url, ref, `resolved_sha`, precedence, file-count, `last_synced`. |

Engine: `scripts/overlay.py` (the deterministic implementation). The full
17-step sync algorithm, conflict/precedence model, and 3-way base recovery
live in `references/workflow.md`.

## HARD GATES (non-negotiable)

1. **Refuse off `user/*`.** CORE branches (`main` / `development`) **never**
   materialize. An overlay writes USER-tier files onto a user branch only.
2. **CORE-refusal (path-authoritative).** Never materialize a dest that
   classifies `core`, is `_`-prefixed, is a cluster-wrapper `README.md`, is a
   `_template`/`_schema`, or path-escapes the tree. **Path classification wins:**
   an inline `scope: org` line can only re-tier a dest on a frontmatter-bearing
   path (`skills/`, `.claude/agents/`, `identity/agent/{IDENTITY,SOUL}`) — it can
   never smuggle a CORE file (`rules/`, `docs/`, `scripts/`, `CLAUDE.md`, …) past
   the gate. An overlay ships `scope: org` content only — it can never overwrite CORE.
3. **Behavioural per-file `[y]`.** A `skill` / `agent` / `standing-order`
   requires an **explicit per-file `[y]`** at first materialize (shown in the
   preview). config / rule files batch-confirm. `--yes` is valid
   non-interactively for **non-behavioural** files only.
4. **Leak gate BEFORE write.** Every staged file passes a **raw-secret regex**
   (accounts = `azure-keyvault://` / `keychain://` / `1password://` URI refs
   only) on the staged temp file; the `no-scrub-leak.py` CORE-boundary scan runs
   only when the materialize target is itself `core` (never for an org overlay —
   its org names/emails are not a leak). A hit refuses
   **that file**, surfaces it, and continues the rest.
5. **Never clobber a user edit.** A locally-modified dest goes through 3-way
   merge (overlay = lower layer, user = upper). Markers / a GC'd base escalate
   to a prompt — the engine never silently overwrites your edit.
6. **Never push.** `/overlay` reads from the overlay and writes into your
   working tree. It never pushes your branch anywhere and never opens a PR.
7. **Never auto-merge config.** The ecosystem fragment is wired as an
   idempotent `@ecosystem.<org>.yaml` `@import` line — never block-merged into
   `ecosystem.yaml`. No config file is structurally merged.
8. **Exclude the managed dests from git.** At materialize, the engine writes a
   marked, idempotent `# >>> overlay:<name>` block into the **local, untracked**
   `.git/info/exclude` (never the tracked `.gitignore`) listing every managed
   dest — because skills/agents land in **tracked** paths (`skills/`,
   `.claude/agents/`) that config patterns don't cover, and a fork of a public
   repo is itself public: without this a `git add -A` would publish org-internal
   content. Using `.git/info/exclude` keeps the dests ignored **without** touching
   any tracked file, so neither the content nor the org filenames can be
   published. The block is dropped on `remove`. Org content is consumed, never
   re-committed.

## Authoring note — org facts mirror VERBATIM, not as prompt-fields

A `prompt_field` in the manifest marks a value a **consumer may override** (it is
prompted interactively; under `--yes` the source value is kept). Do **not** mark a
**shared org fact** — a GitHub board number, an org recipient email — as a
prompt-field: it is the same for every consumer, so it must mirror **verbatim**.
Mis-modelling an org fact as a prompt-field is a real footgun (an automated/`--yes`
run, or a fat-fingered `y` at the value prompt, silently overwrites the org fact —
and it is valid YAML, so parse checks sail past it). Reserve prompt-fields for
genuinely per-consumer values; ship org facts plain. A consumer that must diverge
edits the file locally — the 3-way merge protects that edit on re-sync.

## Testing (required) — the engine is test-locked

The engine `scripts/overlay.py` is covered by **`scripts/tests/test-overlay.sh`**
(deterministic, model-free — it drives the REAL engine against a throwaway copy of
the tree). **Any engine change MUST keep the suite green AND add a case for the new
behaviour.** Run before every commit:

```bash
bash scripts/tests/test-overlay.sh        # must end "N passed, 0 failed"
```

The suite's 21 sections assert, among others:

- subscribe + materialize (every dest exists · inline `scope: org` · lock hashes);
  idempotent re-apply; dry-run writes nothing; `remove` restores a clean tree
- 3-way merge (clean + conflict) · precedence · **CORE-refusal** · path-traversal
- **§16 prompt-field override survives a re-sync** — scalar restore, no silent
  clobber; **§18 a wildcard `[*]` override never cross-wires** to the wrong element
- **§17 leak gate** — real secrets (base32/hex, `AccountKey=`, `totp_secret`)
  refused; URI / `${}` / comment / prose pass; **code files** skip the assignment
  heuristic but still get the format scan (`api_key = get()` passes, an `AKIA…`
  literal in a `.py` is caught)
- **§19 a `scope:org` skill ships COMPLETE** — its scripts materialize (inherit the
  SKILL.md tier), never CORE-refused
- **§21 CORE-refusal is path-authoritative** — an inline `scope: org` on a core
  path (`rules/`, `CLAUDE.md`, `scripts/`) is still refused; a real org
  SKILL.md/agent still ships (the carve-out doesn't over-refuse)
- **§22 ecosystem_fragment name** is enforced in-engine (flat `ecosystem.<org>.yaml`)
  even on a consumer without check-jsonschema

**When carrying skills/agents in a real overlay**, also smoke-test a full
materialize before you publish — `add --dry-run` then `status` — and confirm
**zero `user-owned`** (no framework skill rode along), **zero `leak-refused`**, and
every skill's `scripts/` present on disk. A `user-owned` count > 0 means a CORE
tool is mis-tagged in the overlay; pull it out.

## Decision Tree

```
User wants to...
├── Subscribe to an org overlay (git URL)   → references/workflow.md § add (Steps 1–17)
├── Pull updates / re-sync                   → references/workflow.md § sync
├── Re-materialize offline                   → references/workflow.md § apply
├── See freshness / drift counts             → references/workflow.md § status
├── Preview the next sync/apply              → references/workflow.md § diff
├── Unsubscribe (keep or drop files)         → references/workflow.md § remove
├── List subscriptions                       → references/workflow.md § list
├── PACKAGE an overlay for an org to ship    → references/authoring.md
└── Schemas (manifest / lock)                → docs/schemas/overlay-manifest.schema.yaml
                                                docs/schemas/overlays-lock.schema.yaml
```

## Reference Files

| File | Purpose |
|---|---|
| `references/workflow.md` | Operator runbook — the full 17-step sync algorithm, conflict/precedence model, 3-way base recovery, dry-run semantics, status counts, `remove`/`--keep-files`, multi-overlay separation, fleet-record update |
| `references/authoring.md` | For an ORG packaging its overlay — the repo contract, manifest authoring with examples, the publish-guard CI gate, build-artifact discipline |

## Related Files

- `docs/org-overlays.md` — narrative + architecture for org overlays
- `docs/schemas/overlay-manifest.schema.yaml` — `overlay.manifest.yaml` schema
- `docs/schemas/overlays-lock.schema.yaml` — generated `overlays.lock.yaml` schema
- `scripts/overlay.py` — the engine `/overlay` drives
- `infra/instances/_template.yaml` — fleet record; the engine updates
  `subscribes_overlays` on the active instance
