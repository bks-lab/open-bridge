# The Bridge — Agent Instructions

This file is the **canonical, tool-agnostic operating manual** for this repo —
session start flow, rules, task management, agents, standing orders, commands. It is
for **any AI coding agent** (Claude Code, GitHub Copilot, Gemini CLI, Codex, Cursor,
Windsurf, or any future tool). It is tool-agnostic with ONE exception — sub-agents are
Claude Code only; every other feature works identically across tools. The filename follows
the [AGENTS.md](https://agents.md/) convention (Linux Foundation); the content applies
to all agents regardless of which name your tool looks for. `CLAUDE.md` and
`GEMINI.md` are thin wrappers that point here.

This repo is your **central command hub**. From here you navigate to every repo,
project, and tool in your ecosystem. Your agents handle analysis, deployment,
security, communication, and monitoring — in parallel.

**For humans:** the [README](README.md) is the narrative + architecture overview with
mermaid diagrams. Read it first if you're new to the project.

**For you (the agent):** this file is a lean router. It holds the behavioural
invariants and guardrails, says what each system *is* and *when it matters*, and
points at the `rules/` and `docs/` files that carry the mechanics.

> **Strategic status:** `bks-lab/open-bridge` (OSS, MIT) is the public CORE layer.
> Downstream forks (org overlays, personal instances) add overlays via the `/promote`
> flow with `scope:` routing.

## Required Reading

1. **This file (`AGENTS.md`)** is the full operating manual. The name is a
   convention; the content applies to all agents.
2. **Read the session slice of `bridge-config.yaml`** with
   `python3 scripts/bridge-config.py --session` (identity, purpose, user_profile,
   theme, language, work). The other fifteen blocks belong to the skill that owns
   them; read a block with `--keys <block>` when that skill runs.
3. **Index `ecosystem.yaml` if present** — the project registry (repos, packages,
   infrastructure, workspaces). Created during onboarding, user-specific and gitignored
   (like `bridge-config.yaml`), so absent on a fresh clone. It is **not** an `@`-import:
   Phase 1 runs `python3 scripts/context-index.py ecosystem.yaml` for the settings plus
   one line per entry, and `--get <name>` fetches an entry when the work names one — the
   split skills have always had, applied to a declared map
   ([`docs/context-index.md`](docs/context-index.md)). `ecosystem.example.yaml` **is**
   present on a fresh clone as the registry template — onboarding uses it as the starting
   point (copy + auto-populate → the gitignored `ecosystem.yaml`); do not hand-copy it.

## Session Start Detection (automatic)

Before responding to ANY user message at session start, run Phase 0 from
[`rules/session-start.md`](rules/session-start.md). It detects the repo's **default branch
live**, then checks current branch, `user/*` branch existence, and `bridge-config.yaml`
presence, and routes to one of these states. The **core branch** below means whatever the
live default resolves to (`main` on `bks-lab/open-bridge`; `development` on most
org-internal overlays; whatever fork-default elsewhere).

| State | Trigger | Action |
|---|---|---|
| **NEW USER** | **core** + no `user/*` + no `bridge-config.yaml` | Open the four-lane front door (§ NEW USER front door in `rules/session-start.md`), then route the chosen lane into `/bridge-onboard` (or, no Skill tool, read `skills/bridge-onboard/SKILL.md` → `references/workflow.md` inline) |
| **WRONG BRANCH** | **core** + `user/{name}` exists + `bridge-config.yaml` present | Suggest `git checkout user/{name}` |
| **ORPHAN STATE** | **core** + no `user/*` + `bridge-config.yaml` present | Offer: recreate user branch / reset config + onboard / CORE-only |
| **BROKEN CONFIG** | **core** + `user/{name}` exists + no `bridge-config.yaml` | Suggest `git checkout user/{name}` — config likely lives there |
| **NORMAL** | on `user/*` branch with config | Proceed to Phase 1 work-system load |
| **CORE DEV MODE** | on any non-core branch | Skip work-system load, answer normally |

**Critical:** Do not answer the first user message (even "hi", "status",
"what can you do") before running Phase 0. Generic questions are the exact
case this gate exists for — they don't bypass it.

**Critical:** The core/default branch is detected **LIVE** (per
[`rules/session-start.md`](rules/session-start.md)), never hardcoded to `main` — a
hardcoded branch name has caused a real misfire before. Resolve the default at session
start; do not assume it.

**For NEW USER:** Phase 0 first **arms the push-guard** (`git config core.hooksPath
scripts/hooks`, via `bin/setup`) and classifies the origin — unconditionally, before any
greeting. Then open the **four-lane front door** (`[1]` see it run · `[2]` describe your
goal → tailored setup · `[3]` make it private first · `[4]` bind a workspace), which routes
into the `bridge-onboard` wizard (Quick Identity + Purpose → Discovery Scan (broader only —
confined default skips it) → Smart Suggestions → Quick-Wins → Feature Catalog → Validate,
ending on a live first briefing). Explain CORE/USER split, ecosystem vs cluster wrappers,
and sub-agents as you go. Goal: running in 5 minutes. Then point at
[`docs/feature-tour.md`](docs/feature-tour.md).

The load-bearing detail for the NEW-USER turn lives in
[`rules/session-start.md`](rules/session-start.md): the exact **NEW-USER greeting**, the
**"reporting the check"** step (how to surface what Phase 0 detected before acting), and the
**red-flags list** (what aborts onboarding). Read those sections — they are not duplicated here.

---

## Theme

Themes control user-facing **vocabulary** only. Never tools, delegation, goals or
agents. Built-in: `professional` (default, en) and `professional-de`; set via
`bridge-config.yaml` `theme:`. Resolution order and custom-theme authoring:
[`rules/theme.md`](rules/theme.md).
---

## Agents

Two different things share the word, and confusing them is the usual mistake.

**Sub-agents** (`.claude/agents/*.md`) are *inward*: ephemeral, spawned inside
your session, they exist so heavy or parallel work (log dumps, file trees, API
results) never fills the main context, and they return a structured summary. Add
one by dropping in another `{name}.md`; no registration. On platforms without a
delegation API the same logic runs inline
([`docs/tool-mapping.md`](docs/tool-mapping.md)).

**Bridge-Agents** (`agents/`) are *outward*: persistent, addressable A2A
endpoints that front a persona to the world and to peer bridges, under a human
gate. The runtime and template ship as CORE; each `agents/<name>/` instance is
USER. Model: [`agents/README.md`](agents/README.md),
[`docs/representative-agent.md`](docs/representative-agent.md).

The older `/crew` command is retired — edit `.claude/agents/*.md` directly.
---

## Agent Identity

The orchestrator carries its own identity, distinct from `personas/` (identities
the user holds) and `mandants/` (recipient groups): `identity/agent/IDENTITY.md`
(who am I) and `SOUL.md` (how I behave, loaded every session). CORE ships only
the seeds; onboarding writes the live files, which stay on the `user/*` branch
and never promote. SOUL.md is capped at 80 lines / 4 KB, enforced by
`bridge-audit`. Guide: [`identity/agent/README.md`](identity/agent/README.md).
---

## Standing Orders

`protocols/standing-orders/*.md` are **always-on rules** loaded every session when task
management is enabled (task-sync, board-task-criteria, drift-advisory, document-work, …). Each
carries `name`, `scope`, `enforcement`, and `applies_to` frontmatter; orders with
`scope: always` are matched against every sub-agent dispatch, then filtered by `applies_to`
(sub-agent names, empty = all — so an order can target only specific sub-agents rather than
every dispatch). `protocols/` stays **top-level**
(CORE content with its own lifecycle) — `standing-orders/` ships CORE defaults;
user-authored orders live in `standing-orders/user/`.

`scope: always` says an order **applies** always; `load:` says when its **body**
is read. `load: eager` (the default) reads it at session start; `load: on-trigger`
keeps only a `summary` and a `triggers` vocabulary in context and fetches the body
when that vocabulary comes up — the disclosure model skills already use. Stay
eager only when the order bites while nobody says its own vocabulary. The index a
session carries is `python3 scripts/standing-orders.py --index`; `--check` refuses
an order that defers without a trigger, since it would read as enforced and load
never.

The always-on surface as a whole carries a declared ceiling, the same idea as the
`SOUL.md` cap: `context-budget.yaml` holds it, `python3 scripts/measure-context.py`
reports and enforces it (bytes gate, token counts inform), and CI fails on an
always-on file nobody declared.

**Three channels reach a session, and only two are files.** The `@`-imports and
the Phase 1 reads come off disk. The third is DERIVED: the harness injects
`name` + `description` of every skill and sub-agent into every session and every
dispatch, one line each, with no file to point at. Measured as `listing:skills`
and `listing:agents`, capped on the sum, heaviest entries named in the report
because a listing grows one description at a time. It is load-bearing, not
overhead, so `check-reachability.py` reads it too: a description naming a config
path is a route, and on one instance it was a family's only one.

**A sub-agent's surface is strictly smaller than its parent's:** imports and
listings, never Phase 1, so no standing order, board or work log. A pointer that
must reach sub-agents belongs in an `@`-imported file. In an eager standing
order it is resident for the session, invisible to every sub-agent, and green in
every guard.

---

## Layout — Cluster-Wrappers

Config lives in **three semantic cluster-wrappers**, and every config type gets
its own **folder** — no exceptions, no thresholds:

`identity/` WHO am I, to WHOM do I send · `infra/` WHERE does what run, HOW
reach · `workflow/` WHAT happens when. Every family below is a route: read the
folder when its subject comes up, and its `_template.yaml` says what belongs in
one. `scripts/check-reachability.py` fails CI when a family in the tree is named
in nothing a session loads, so this list cannot quietly fall behind the tree —
five families were missing from it when that check was first run. Entries also
reference each other (`bridge_refs:`, `*_ref:`, `related_*:`); those references
are the graph a session walks after the first hop, and
`scripts/check-edges.py` holds them to resolving (`--neighbours <path>` shows
one hop both ways, `--fix` rewrites a reference whose task merely moved KIND).

| Family | Read it when |
|---|---|
| `identity/personas/` | an identity the user HOLDS: signature, tax data, filing paths |
| `identity/mandants/` | who RECEIVES an outgoing message |
| `identity/accounts/` | a cloud tenant, subscription or vault reference |
| `identity/contracts/` | a customer contract: term, rate, notice |
| `identity/vehicles/` | a vehicle the user owns or leases: plate, VIN, the persona that bears it |
| `identity/agent/` | this orchestrator's own name, role and voice |
| `infra/remotes/` | a machine: ssh, wake, services, "which PC" |
| `infra/channels/` | an outbound transport: mail, chat, bot, digest |
| `infra/backups/` | what is backed up where, and whether it is fresh |
| `infra/instances/` | another Bridge this one should know about |
| `infra/transcriptions/` | recording → transcript topology |
| `infra/utilities/` | a supply contract at a location: power, gas, water, heat |
| `workflow/calendars/` | a scheduled outbound action |
| `workflow/contexts/` | where a piece of work gets documented |
| `workflow/projects/` | a board's field values and state map, before ANY tracker call |
| `workflow/workloads/` | one declared run on one machine |
| `workflow/workspaces/` | a named binding of repos + config overlays |

Top-level, own lifecycle: `rules/` `protocols/standing-orders/` `skills/`
`trackers/` `themes/` `.claude/agents/` `work/` `docs/`.

**Default-to-Folder:** every config type lives in `<wrapper>/<types>/` — a plural
folder holding `_template.yaml`, an optional `_schema.yaml`, and all `<id>.yaml`
instances together. `_`-prefixed files are reserved and excluded from discovery;
filenames are plain slugs without a type prefix. Going from 1 instance to 5 is
zero work. **Discovery** is the glob `<wrapper>/<types>/*.yaml` skipping `_`
files: no flat fallback, no promote logic.

Full layout and routing map: [`docs/structure.md`](docs/structure.md) ·
reference implementation and irregular-plural caveats:
[`rules/discovery.md`](rules/discovery.md) · examples per type under
`docs/examples/`.
---

## Personas

A persona is an identity THE USER HOLDS (`identity/personas/<id>.yaml`), carrying
tax data, signature blocks, filing destinations. Unlike a mandant, which is a
recipient group. Load one when a skill or routing order references it via
`persona_ref`. Guide: [`docs/personas.md`](docs/personas.md).
---

## Scope — structural, not declarative

Every file's tier (**core** → open-bridge · **org** → your org overlay · **user**
→ local) is decided by **where it lives**, not a tag you can forget:

1. **Whole folder** — the path *is* the tier. `work/`, `imports/` = USER;
   `docs/`, `themes/`, `trackers/`, `scripts/`, `protocols/standing-orders/*.md`
   = CORE.
2. **`_`-prefix** inside the cluster wrappers — `_template.yaml` / `_schema.yaml`
   = CORE, every other `*.yaml` instance = USER.
3. **Frontmatter**, for the two things that cannot be foldered: skills carry
   `metadata.scope`, and every `rules/*.md` carries a top-level `scope:` matching
   its folder. Both are hard-gated in CI. An unscoped rule silently inherits
   `core` from its path and would leak, so the field is a required backstop, not
   an option.

**Promote routes mechanically on these inputs.** The content leak-check is the
backstop, not the primary guard: structure is what keeps PII out of the public
upstream. Full model with schemas:
[`docs/extension-model.md`](docs/extension-model.md).
---

## Skills (Universal)

Skills live in `skills/` at the project root, following the open
[SKILL.md standard](https://agentskills.io/specification). Each has a `SKILL.md`
with `name` + a single-line `description` trigger, and a decision tree routing to
`references/` files loaded only when triggered. **Call the skill** (via the Skill
tool, or by loading it from `skills/` on tools without one) rather than
reimplementing its logic.

Three committed symlinks (`.claude/skills`, `.agents/skills`, `.github/skills` →
`skills/`) are the entire discovery mechanism, so every clone gets it.
Distribution, Windows setup and the plugin path:
[`docs/skill-distribution-architecture.md`](docs/skill-distribution-architecture.md).

> **Never point `~/.claude/skills` at a Bridge repo.** The user level overrides
> the project level, every Bridge ships the same CORE skill names, so a
> user-level pointer at instance A silently overrides instance B's own skills
> inside B — including CORE fixes authored in B, and including A's `scope: org`
> skills. The failure is silent: plausible output from the wrong instance's
> skills. One `readlink ~/.claude/skills` at session start buys that (empty is
> correct). To make a standalone tool available everywhere, ship it as a plugin.

**Tier lives in `metadata.scope`**, because skills are flat and cannot be
foldered. It is what `/promote` and `/bridge-sync` route by, kept honest by
`scripts/validate-skill-scope.py` (CI + pre-commit).

| Scope | Ships to |
|-------|----------|
| `core` | open-bridge + your org overlay + local |
| `org` | your org overlay + local |
| `personal` | your personal overlay + local |
| `user` | local only |

**Which skill sits in which tier is per-instance, so it is deliberately not
listed here** — any enumeration baked into a CORE file diverges from every other
instance on the day it is written and carries local skill names upward on
promote. Run the validator for the live map:

```bash
python3 scripts/validate-skill-scope.py     # validates, then writes .bridge/skill-scope.md
```

That map is derived and gitignored; the authoritative tier is the frontmatter,
which is what the routing actually reads.

**Generic CORE skills:** a `scope: core` skill earns its tier by staying generic
*inside* — it **reads** config and never embeds instance logic, hardcoded
queries, org IDs, personas or thresholds. If it needs a new knob, add the config
key and read it.
[`docs/extension-model.md`](docs/extension-model.md).
---

## Tool Mapping

Tool names differ per platform (Read/Write/Edit/Bash/Grep/Glob/Agent here;
`apply_patch` and shell reads on Codex; `read_file`/`write_file` on Copilot and
Gemini). The full table, and what a missing delegation API means for skills that
would dispatch a sub-agent, is in
[`docs/tool-mapping.md`](docs/tool-mapping.md).
---

## Rules

Rules are tiered by **folder**, and the folder *is* the promote tier:
`rules/` = core (ships everywhere) · `rules/org/` = your org overlay only ·
`rules/user/` = this instance only. Every `rules/*.md` must **also** carry a
top-level `scope:` matching its folder — a required backstop, not the router,
since an unscoped rule inherits `core` from its path and would leak.
`scripts/validate-bridge.py` fails CI on a missing or invalid one.

**Which rules an instance has is derived, never a table here** — a table
generated from a local tree cannot converge across instances. Run the validator
for the live map, including the column frontmatter cannot express (whether git
will track a **new** rule at that path, which in an overlay-subscribed instance
is the difference between authoring a rule and losing it silently):

```bash
python3 scripts/validate-bridge.py     # validates, then writes .bridge/rule-scope.md
```

**The rules that fire before you would think to look them up**, since knowing
they exist is the whole point of naming any of them here:

- [`session-start.md`](rules/session-start.md) — the Phase 0 gate, before ANY response
- [`push-guard.md`](rules/push-guard.md) — a `user/*` branch never reaches a public upstream
- [`promote-safety.md`](rules/promote-safety.md) — content scan before anything moves to CORE
- [`deploy-reconciliation.md`](rules/deploy-reconciliation.md) — a declared `status:` is never truth
- [`file-creation.md`](rules/file-creation.md) — template + schema + peer example before any new file
- [`multi-instance-isolation.md`](rules/multi-instance-isolation.md) — never pull another instance's content in
- [`ci-discipline.md`](rules/ci-discipline.md) — verify CI green after every push, unprompted
- [`knowledge-growth.md`](rules/knowledge-growth.md) — where a new piece of knowledge belongs
- [`secret-placement.md`](rules/secret-placement.md) — no raw secret in a tracked
  file: reference URIs only (`azure-keyvault://`, `keychain://`, `1password://`),
  and an `env` block carries the locator, never the value

### Git & Branches

CORE files (the default branch) are generic and ship with the repo. USER files
(`user/{name}`) are your instances: `bridge-config.yaml`, `ecosystem.yaml`, every
`<id>.yaml` under the cluster wrappers, `standing-orders/user/`, and all of
`work/`. The two touch disjoint paths, so merges are conflict-free by
construction. Per-path table: [`docs/structure.md`](docs/structure.md).

- NEVER commit secrets or credentials on any branch.
- **NEVER push a `user/*` branch (or USER content) to a PUBLIC upstream.** Your
  private data lives on a private `origin`; CORE reaches a public upstream only
  via `/promote`, a fork-based content-scanned PR. Cloned the public repo
  directly? Re-home `origin` to your own private repo and keep open-bridge as a
  read-only `upstream`. Enforced behaviourally and deterministically by
  `scripts/hooks/pre-push`: [`rules/push-guard.md`](rules/push-guard.md).
- Layout reorgs land directly on `user/{name}`; promote later.
- Git mechanics (DCO sign-off, atomic stage+commit, the `skills/` symlink path):
  [`rules/git-hygiene.md`](rules/git-hygiene.md).

### Multiple Instances

Users may run several Bridge instances to keep organizations' data apart. Don't
access or modify another instance's files; each tracks its own `work/log.md` and
keeps its own layout. [`docs/multi-instance.md`](docs/multi-instance.md).

### Tier Model

Two-pole by default — `bks-lab/open-bridge` (OSS, MIT, generic CORE only) plus
your own private Bridge. The middle tier is an optional convention: an org that
wants a shared overlay creates a private fork it names itself, and `scope: org`
routes there. `bridge-config.yaml.upstreams` is a list; `/promote` routes per
`scope:`. Full model, including the subscribe direction:
[`docs/org-overlays.md`](docs/org-overlays.md).

**open-bridge is English-only** — every file here is authored in English from the
first keystroke, never written in another language and translated later. Runtime
and output language is a separate axis, set per fork. The one exception is locale
theme files, whose *vocabulary values* may be in the target language.
[`rules/language-policy.md`](rules/language-policy.md).

### Cross-Repo Work

Before changing code in another repo: read that repo's CLAUDE.md, check its
branch model, commit the change there rather than here, then return and update
the work log. Issues belong in the repo where the code lives. Test before merge;
the user decides merge timing.

### Creating new files — schemas first

Before writing **any** new YAML or MD under the cluster wrappers, `protocols/`,
`skills/` or `trackers/`: read the matching `_template.yaml` + `_schema.yaml`,
skim a peer file for field conventions, verify required keys, naming and expected
companions — *then* write. Skipping this is the single largest source of drift.
Checklist and per-type table: [`rules/file-creation.md`](rules/file-creation.md).

### Documentation Navigation

Navigation lives in a few strong documents, not per-directory maps: this file,
[`README.md`](README.md), [`docs/structure.md`](docs/structure.md) (layout +
routing), [`docs/extension-model.md`](docs/extension-model.md) (CORE/USER +
schemas), [`rules/knowledge-growth.md`](rules/knowledge-growth.md) (where new
knowledge belongs) and [`docs/memory.md`](docs/memory.md). Where a directory
needs help, use a plain `README.md`. Stand-alone docs carry `summary` / `type` /
`last_updated` / `related` frontmatter.
---

## Task Management

**Activated when** `work.enabled: true`. The system is **Task Management**; its
data directory stays named `work/`.

**The model, two orthogonal axes.** KIND is the **folder**:
`work/tasks/<slug>/` is finite, `work/streams/<slug>/` is a long-runner that
never completes and never counts against WIP, `work/done/YYYY-MM/<slug>/` is
closed. Moving KIND is a `mv`; there is no `kind:` field. **status is the
field**, a closed enum `{backlog, doing, review, done}`, CI-validated. No
synonyms. `blocked_by:` is a free-text **flag**, not a status: a blocked task
stays `doing` and carries a reason. `declined` is an **outcome**:
`status: done` + `outcome: declined`. **board.md is GENERATED** from the task
dirs and never hand-curated; humans edit STATUS.md. The **WIP cap is a warning,
never a block** — session start warns when `doing + review` exceeds
`work.max_active`, and the remedy is to close, reprioritise, or reclassify to
`work/streams/`.

### Session Start (automatic when enabled)

Read the recent slice of the log
(`python3 scripts/worklog.py --recent 3`) and `work/board.md`, creating either
from templates if missing — **never fail on a missing work file, create and
continue**. Ensure
today has a day-block. Warn, do not block, on the WIP cap. Load the standing-order
index (§ Standing Orders). Full sequence:
[`rules/operations.md`](rules/operations.md).

### Logging

> **Logging is mandatory and continuous, not best-effort.** Every substantive
> unit of work gets its own `work/log.md` row the moment it lands, in the same
> turn it happened, never batched at the end. That covers a code change or
> commit, a bug fixed, a decision made *and why*, a finding worth keeping, a
> deploy or restart, an issue/PR/board operation. If you did work this turn and
> there is no row for it, the turn is **not finished**.

**One frozen row format:** `| YYYY-MM-DD HH:MM | glyph | context | what |`

- **Timestamp:** full ISO date+time from `date '+%Y-%m-%d %H:%M'`, so every row
  self-dates and a stale log is never ambiguous. NEVER a placeholder, never
  estimated. The day-block header stays `## {Weekday} DD.MM` — a display anchor
  the `/archive` and `/briefing` parsers key off, so no year there.
- **glyph** from `activity_types` in config; **context** is the repo tag;
  appended chronologically inside the current day-block.

Document **insights, not just actions**: log.md is the working memory `/briefing`
reads. Level semantics: [`docs/work-system.md`](docs/work-system.md).

### Consult before write

The Bridge advises; it does not act autonomously. **Reflex-pause before the first
*write* of any unit of work** — and a write is not only a productive-folder
change but **any state change anywhere**: a commit or push on *any* repo, a
GitHub/ADO issue-or-PR-or-board operation, an outbound message. Reading is always
free; the pause fires the instant you are about to change state.

**Escalation cancels the read-only exemption.** A turn that began as research is
exempt only while it stays read-only. The instant it grows a write, re-enter this
gate. Never ride an opening "just have a look" into real changes.

1. **Active-task check** — `ls work/tasks/` + `ls work/streams/` + the board's
   Doing. A slug, context or stakeholder match → propose *"Fits `<slug>`?"*
   before creating anything new; three siblings sharing a prefix → cluster
   warning. Skipping this is how duplicate tasks get born.
2. **Mode check** — PLAN (research, sketch, draft, explore, evaluate) → answer in
   chat. BUILD (implement, create, deploy, merge, commit, fix, close, open a PR)
   → allowed after steps 1 and 3. Ambivalent → ask.
3. **Class check** — cross-session pickup OR an external recipient → **Class A**
   (STATUS.md + board row + task-sync). Otherwise Class B (log only) or C.
4. **When in doubt: ONE question.** `[a] fits <slug>` / `[b] new as <proposal>` /
   `[c] chat only` / `[d] just do it`. Do not guess.

**Don't reflex** on slash commands, on read/info queries *that stay read-only*, on
a quick fix under 10 minutes and 3 files, or on a topic the user already declined
this session. Intent lists, similarity algorithm, cluster detection, class
examples and repair recipes:
[`rules/task-management-workflow.md`](rules/task-management-workflow.md).

**Lifecycle, three steps:** `mv` the directory, **regenerate** board.md from the
dirs, append a log row with a measured timestamp.

### Task Sync Routing

Every task sits at the intersection of three orthogonal axes: **project**
(`workflow/projects/<slug>.yaml`, board fields), **context**
(`workflow/contexts/<slug>.yaml`, where we document) and **mandant**
(`identity/mandants/<slug>.yaml`, who gets notified). STATUS.md's `sync:` block
declares per-task overrides, the resolver merges with context defaults, and
`bridge_only: true` is the explicit local-only fallback. Canonical resolver:
[`protocols/standing-orders/task-sync.md`](protocols/standing-orders/task-sync.md).

### Trackers and the Project Registry

Work items come from external trackers via pluggable provider playbooks in
`trackers/*.md`, each normalizing its CLI output into a shared schema
([`trackers/README.md`](trackers/README.md)). Enable per provider under
`integrations.<name>.enabled`. Writes go through the
**`github-projects-manager`** skill, never raw `gh issue create`.

> **Before ANY GitHub/ADO operation, read the matching
> `workflow/projects/<slug>.yaml`** for valid field values and state mappings.
> **Never hardcode a field value, never guess an emoji prefix** — the config is
> the source of truth. After adding an item to a project, verify it is actually
> on the board. Never set an issue straight to "Done": use "In Review" and let
> the user confirm.

### Commands

Each skill registers its own slash-command through its `description:`
frontmatter; there are no files in `.claude/commands/`, and invoking a skill via
the Skill tool is equivalent to typing its command. The CORE set:
[`docs/commands.md`](docs/commands.md). An instance carries more, and which ones
is per-instance, so the live list is the skill listing itself.
---

## Remotes — Remote Machines

Your physical and virtual machines live in `infra/remotes/*.yaml`. In Bridge
context **"remote" means remote MACHINE, never `git remote`** — check
`infra/remotes/` before asking "which PC?". The **`remote`** skill owns the
directory and auto-loads on a machine name, "my PC / fleet status", "wake / WoL",
"ssh to / RDP to". Schema: `infra/remotes/_template.yaml`.
---

## Workloads — Declared Runs

A **workload** is one thing that runs on one machine: a scheduled report, a
poller, a daemon, a watcher, a one-shot. One declaration per run in
`workflow/workloads/<id>.yaml`; the `workload` skill renders, provisions and
reconciles from it. There is deliberately no `status:` field. Data model,
contract rules and the case behind each: [`docs/workloads.md`](docs/workloads.md).
## Channels — Messaging & Outbound Transports

Transport declarations live in `infra/channels/*.yaml` (iMessage, email,
Telegram, digests, bots). The `/channel` skill triggers on "channel status /
health / deploy", "new channel for X", or a known channel name; scheduled sends
go to `/schedule`. Detail: [`docs/channels.md`](docs/channels.md).
---

## Visualization — Bridge Deck (optional)

Optional read-only pixel-art renderer of your Bridge. Suggest it as a one-liner
when the user asks to visualize their agents; never auto-install.
[`docs/bridge-deck.md`](docs/bridge-deck.md).
---

## Calendar + Mandants

Optional system for scheduled outbound with recipient attribution: **mandants**
(`identity/mandants/<id>.yaml`) are recipient groups, **calendar entries**
(`workflow/calendars/entries.yaml`) are what/whom/when. Enable via
`calendar.enabled` + `mandants.enabled`. Commands `/calendar` and `/mandants`.
Full model: [`docs/calendar.md`](docs/calendar.md),
[`docs/mandants.md`](docs/mandants.md).
---

## Backups

Data model in `infra/backups/topology.yaml` (`sources` × `targets` ×
`pipelines`), state in `_state.yaml`, written only by the skill. Activated by the
file existing. CORE ships the data model, not an executor. Validation rules and
target-versus-actual comparison:
[`infra/backups/README.md`](infra/backups/README.md).
---

## Cloud Accounts & Secrets

Cloud accounts and their secret stores live as inventory in
`identity/accounts/<provider>-<scope>.yaml`. **Before any cloud operation**
(`az`, `wrangler`, `gcloud`, `gh api`, provider REST) read the matching file for
tenant, subscription, vault and bootstrap snippet rather than reconstructing it
from memory. **No raw secret in YAML** — reference URIs only
([`rules/secret-placement.md`](rules/secret-placement.md)). Per-provider recipes,
tenant switching, rotation:
[`docs/cloud-accounts.md`](docs/cloud-accounts.md).
---

## Design System

`DESIGN.md` is the design-system manifest (palette, typography, spacing,
component anatomy). **Read it before generating user-facing visuals** — any skill
emitting HTML, PDF, slides, certificates or styled email pulls its tokens from
there. **Never hand-pick a brand colour**; if a token is missing, add it to
[`DESIGN.md`](DESIGN.md) first, then reference it.
---

## Variable Interpolation

`bridge-config.yaml` defines variables under the `identity:` key. Every YAML
under the cluster wrappers, plus `ecosystem.yaml`, can use `${variable}`:
`${projects_root}`, `${home}`, `${onedrive_root}`, and a leading `~` → `$HOME`.
An unknown variable warns and skips the file.

> **Disambiguation:** `identity:` (a config key) is not `identity/` (a cluster
> wrapper). Same word, different namespaces.
---

## Promote

Two canonical rules govern cherry-picks onto `main`:

- `rules/operations.md` — path allowlist / blocklist, scope-gated paths.
- `rules/promote-safety.md` — pre-commit + pre-promote content scan, scope-check for
  `skills/` and `.claude/agents/` (anything with `scope: org` or `scope: private` stays on
  the user branch).

These two files are the single source of truth — there is no supplementary promote
documentation under `docs/`.

---

## What NOT to Do

- Don't commit secrets or credentials to any branch
- Don't push to `main` without user approval
- Don't modify CORE files on a `user/` branch commit (use `/promote`)
- Don't skip the work log — document insights, not just actions
