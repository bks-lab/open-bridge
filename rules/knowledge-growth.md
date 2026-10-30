---
scope: core
description: Meta-rule — where new knowledge belongs (AGENTS.md vs rules/ vs docs/ vs standing-order vs memory) and the scope discipline every rule must carry
---

# Knowledge Growth — where does new content go

The Bridge's knowledge base grows by adding to the **right tier**, not
piling into `AGENTS.md`. This table decides where, plus the scope
discipline that keeps generic CORE separate from instance-specific content.

## The tiers

| Tier | Loaded | Holds | Size discipline |
|---|---|---|---|
| `AGENTS.md` | always (session start) | The kernel: invariants, gates and section pointers. **Meta-content, not detail, and no lists.** CORE only: an instance never edits it. | Sections and byte ceiling declared in the `kernel:` block of `docs/data-model.yaml`; link out |
| `docs/families.md` | always (imported by `AGENTS.md`) | The config-family index: which folder to read when. Generated from `docs/data-model.yaml`, never edited by hand. | One `route:` per family in the model |
| `identity/agent/INSTANCE.md` | always (imported by `AGENTS.md`, so sub-agents see it too) | An instance's own always-on text: its families, registries, routes and vocabulary. USER, never shipped by CORE or an overlay. | Capped in `context-budget.yaml`; link out like `AGENTS.md` |
| `rules/*.md` | on demand (linked from AGENTS.md or triggered) | Always-on gates + detailed workflows: session-start, operations, promote-safety, task-management. The *how*. | One concern per file |
| `docs/*.md` | human reference | Narrative, decision matrices, examples, onboarding. The *why* + the long form, for people. | Frontmatter (`summary`/`type`/`last_updated`) |
| memory | recall | Hard-won facts, gotchas, decisions-and-why. One fact = one file. | Index line short |

**Decision:**
- Gate or workflow the agent must follow → `rules/`.
- Explanation a human reads to understand the system → `docs/`.
- A lesson about **one skill** (a trap, convention or example of using it),
  needed by that skill's next run → its `LEARNINGS.md` (§ A lesson about one
  skill). Checked first: it is the narrower case of the next line.
- Non-obvious fact / workaround / decision → memory.
- Routing for a config family → a `route:` in `docs/data-model.yaml`
  (rendered to `docs/families.md`). Any other pointer needed every session → in
  CORE, one `AGENTS.md` sentence only if it is a new invariant, linking to the
  `rules/` or `docs/` detail; in an instance, a line in
  `identity/agent/INSTANCE.md`, never `AGENTS.md`, because a downstream edit to
  `AGENTS.md` conflicts on every upstream merge.

> **Knowledge-routing reflex:** a "drift" / "audit" / "consistency" /
> "is X still accurate" request routes to the `bridge-audit` skill (it has the
> checks codified) — don't ad-hoc grep. When you rename a file/skill/command,
> add it to `skills/bridge-audit/data/renames.yaml` so the next audit keeps up.

**The kernel rule.** `AGENTS.md` gets no new section and no list. A new config
family is a row with a `route:` in `docs/data-model.yaml` (it then appears in
`docs/families.md`); feature mechanics go to `docs/<feature>.md`; only a new
invariant earns an `AGENTS.md` sentence. `scripts/data-model.py` fails CI on an
undeclared section, a family table row or a file past the byte ceiling.

If you're about to add more than ~10 lines to `AGENTS.md` (or to `INSTANCE.md`
in an instance), it almost certainly belongs in a `rules/` file with a one-line
pointer from that file instead.

## Write-time gate test (before saving a memory)

Run this checkpoint **before writing any memory file** — it is what keeps
`rules/` fed instead of letting behavioral gates accrete in the private,
never-promoted memory store.

**Memory is good — and fully usable while it is part of this instance.** It is
the personal, non-shipped layer: a fresh clone, the OSS upstream, your org
overlay, and a memory-less run do **not** carry it. So a recurring **process or
rule** must be reachable from the *shipped repo alone* — its home is the Bridge
structure (a `rules/` gate, a `skill`, a `protocols/standing-orders/` surface,
or a config field), not memory. Reaching for memory to hold something recurring
is the signal to place it in the structure instead.

Ask: **is this a behavioral GATE — an "always / never" instruction, or a
Trigger → Action routing rule the agent must follow?**

- **YES → it belongs in `rules/<tier>/`** (core / org / user per § Rules are
  tiered by folder), *not* in memory. Write the rule. The originating memory
  may stay only as **dated provenance** once the rule exists (it documents the
  incident behind the rule — see § End-of-work and the consolidation banner in
  `MEMORY.md`).
- **NO — it's a non-obvious FACT, a workaround, a decision-and-why, or
  project state → memory is correct.**
- **It's recurring but no tier fits cleanly → flag it, don't bury it.** If a
  repeating process/rule has no obvious structural home (a missing rule file,
  skill, standing-order, or config field), **say so** — name the gap. Memory may
  hold it only as a temporary `TODO: needs structural home` note, never as the
  silent final resting place. Surfacing the misfit is the action.

Examples that are **gates → `rules/`** (a fresh clone needs to obey them):
- "Always run `bridge-audit` on a drift/consistency request, never ad-hoc grep."
- "Never push directly to `main`/`development` without explicit approval."
- "On any GitHub op, read `workflow/projects/<slug>.yaml` first — never hardcode field values."

Examples that are **facts → memory** (instance-specific or hard-won detail):
- "macOS NFD ↔ Synology NFC: normalize to NFC before file-tree diffs, else false misses."
- "AKV auth fails with AKV10032 → it's a tenant mismatch; `az account set --subscription` fixes it."
- "The DS718+ Foto-Master sync finished and is byte-verified (project state)."

Litmus test: if a teammate cloning the Bridge would have to **behave**
differently, it's a gate → `rules/`. If they'd only need to **know**
something to avoid a trap, it's a fact → memory.

## A lesson about one skill

Route a lesson by **who needs it next**, to exactly one place:

| Who needs it next | Destination |
|---|---|
| The next run of one specific skill (a trap, a convention, a worked example of that skill) | `skills/<name>/LEARNINGS.md`, dated; appended in-session when the user names the lesson, no proposal |
| Every session, whatever it runs; or a fact about the world, not a skill | memory (write-time gate above) |
| A change to how a skill, rule or standing order behaves, or a lesson spanning skills | a `/bridge-learn` proposal |

Writing the same lesson to two of these is a failure, not thoroughness. The
journal is opt-in: the first entry creates `LEARNINGS.md` and the routing block
in `SKILL.md` together, from the templates in
[`docs/skill-learnings.md`](../docs/skill-learnings.md); a skill with neither is
fine. Matured entries move into `references/` through
`/bridge-curator --pass learnings <skill>`.

## Rules are tiered by folder

Rules live in three folders — **the folder *is* the promote tier**, no
per-file guessing:

- **`rules/*.md`** (top level) — **CORE**: generic, makes sense in any Bridge.
  Promotes to the public OSS upstream (English-only there).
- **`rules/org/**`** — **org-tier**: hardcodes customer/org content
  (stakeholder names, customer systems, org-specific defaults). Routes to
  the org-internal upstream only, **never** the public OSS one.
- **`rules/user/**`** — **USER**: a personal operating rule for this instance
  only. Never promoted. This is the home for **user-added rules**: drop a
  `*.md` in `rules/user/` and it stays local.

Each Bridge **layers its own** rules under `rules/org/` (org) and `rules/user/`
(personal) — additive, like nested AGENTS.md. The frontmatter still carries
`scope:` (core/org/user) and it **must match the folder** — that match is the
redundant backstop, not the router:

```yaml
---
scope: core        # must match the folder this file sits in
description: <one line>
---
```

**Org aliases.** A concrete org tag (your organisation's short name) is
*not* hardcoded in any CORE file — it is declared once in `bridge-config.yaml`
under `promote.scopes.org_aliases` and routes identically to `org`. On
promote to the OSS upstream it is scrubbed back to `org`.

**Why this matters:** `/promote` and `/bridge-sync` route by **folder**
(`rules/operations.md` § Scope-Routing). A personal rule in `rules/user/`
**cannot** leak to the OSS upstream — it's structurally outside the core tier,
not relying on a frontmatter tag being set right. Enforced two ways:
- **Hard gate** — `scripts/validate-bridge.py --surface rules` (pre-commit
  + CI) **fails** on a top-level `rules/*.md` with a missing or invalid scope.
- **Folder↔scope consistency** — `bridge-audit` Check 6 flags a rule whose
  frontmatter scope contradicts its folder (e.g. a `scope: core` rule in
  `rules/org/`).

> User-added rules vs. standing orders: a `rules/*.md` with `scope: user`
> is a **persistent operating rule**. A `protocols/standing-orders/*.md`
> is a **session-surfaced behaviour** whose `scope:` means *when it fires*
> (`always` / `per-repo` / `per-context`), not *whether it promotes*. Use a
> `scope: user` rule for "always behave this way"; use a standing order for
> "surface this at session start / on this repo".

## End-of-work documentation discipline

At the close of a **substantive** work unit (not trivial / conversational
turns), document across the five layers — fill the ones that apply:

1. **Deliverables → PARA, PII local.** Customer/finance/tax artifacts go to `~/PARA-Documents/…`, never the Git repo; figures carry a source.
2. **Task → `work/tasks/<slug>/STATUS.md`** — plan, phases, data state, limits — for cross-session or multi-step work.
3. **Cleanup / audit trail → the matching log** (e.g. `work/doc-system/log.md` for file ops); record reorg mappings so "where did X move" stays traceable.
4. **Code / config → commit** (atomic, scope-split CORE → BKS → USER); push when the tree is clean.
5. **Cross-session insight → memory, with a session-link** — `reference` (gotcha) / `project` (ongoing) / `feedback` (rule), each carrying its `<session-id>.jsonl` path for traceability; keep the `MEMORY.md` index line short. The link resolves only while the harness keeps that transcript (30 days by default), so write the fact to stand on its own text: [`docs/memory.md`](../docs/memory.md) § Retention.

A question whose answer took a search to find is a sixth thing to keep: propose it
as a row of [`docs/where-things-live.md`](../docs/where-things-live.md), phrased the
way you asked it, so the next person finds the file without the search. An answer
that lives only in this instance goes into `work/where-things-live.md` (§ Adding rows).

## Live inventory

The current scoped inventory is whatever the validator reports — read it
live, don't maintain a table here (snapshots drift):

```
python3 scripts/validate-bridge.py --surface rules
```

Adding a new rule: pick the tier (is it really a gate/workflow, or a doc?),
set `scope:` explicitly (`core` unless it carries org/personal content),
and let the validator confirm it.
