---
scope: core
description: Meta-rule — where new knowledge belongs (CLAUDE.md vs rules/ vs docs/ vs standing-order vs memory) and the scope discipline every rule must carry
---

# Knowledge Growth — where does new content go

The Bridge's knowledge base grows by adding to the **right tier**, not by
piling everything into `CLAUDE.md`. This rule is the decision table for
that, plus the scope discipline that keeps generic CORE separate from
instance-specific content.

## The four tiers

| Tier | Loaded | Holds | Size discipline |
|---|---|---|---|
| `CLAUDE.md` | always (session start) | Operating manual: routing tables, gates, command index, section pointers. **Meta-content, not detail.** | Lean — link out, don't inline workflows or examples |
| `rules/*.md` | on demand (linked from CLAUDE.md or triggered) | Always-on gates + detailed workflows: session-start, operations, promote-safety, task-management. The *how*. | One concern per file |
| `docs/*.md` | human reference | Narrative, decision matrices, examples, onboarding. The *why* + the long form, for people. | Frontmatter (`summary`/`type`/`last_updated`) |
| memory | recall | Hard-won facts, gotchas, decisions-and-why. One fact = one file. | Index line short |

**Decision:**
- A *gate* or *workflow the agent must follow* → `rules/`.
- *Explanation a human reads to understand the system* → `docs/`.
- A *non-obvious fact / workaround / decision* → memory.
- A *pointer/routing rule the agent needs every session* → a short line in
  `CLAUDE.md` that links to the `rules/` or `docs/` detail.

> **Knowledge-routing reflex:** a "drift" / "audit" / "consistency" /
> "is X still accurate" request routes to the `bridge-audit` skill (it has the
> checks codified) — don't ad-hoc grep. When you rename a file/skill/command,
> add it to `skills/bridge-audit/data/renames.yaml` so the next audit keeps up.

If you're about to add more than ~10 lines to `CLAUDE.md`, it almost
certainly belongs in a `rules/` file with a one-line pointer from
`CLAUDE.md` instead.

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
5. **Cross-session insight → memory, WITH a session-link** — `reference` (gotcha) / `project` (ongoing) / `feedback` (rule), each carrying its `<session-id>.jsonl` path so future sessions can trace back; keep the `MEMORY.md` index line short.

## Live inventory

The current scoped inventory is whatever the validator reports — read it
live, don't maintain a table here (snapshots drift):

```
python3 scripts/validate-bridge.py --surface rules
```

Adding a new rule: pick the tier (is it really a gate/workflow, or a doc?),
set `scope:` explicitly (`core` unless it carries org/personal content),
and let the validator confirm it.
