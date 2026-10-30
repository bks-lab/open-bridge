# BKS open-bridge: Operating Manual

> **Before your first answer, run Phase 0** ([`rules/session-start.md`](rules/session-start.md)),
> even when the first message is "hi". It detects the default branch live and routes
> (§ Session Start Detection below).

This file is the **canonical, tool-agnostic operating manual** for this repo, for
**any AI coding agent** (Claude Code, Codex, Copilot, Gemini CLI, Cursor, Windsurf, or
any future tool); the one exception is sub-agents, which are Claude Code only. The name
follows the [AGENTS.md](https://agents.md/) convention. Claude Code (2.1.281 or newer)
loads this file directly; `GEMINI.md` and `.github/copilot-instructions.md` point here.
There is deliberately no `CLAUDE.md`: when one sits beside this file, Claude Code loads
only that one, and this manual disappears from the session.

It is a lean router: it holds the behavioural invariants and guardrails, says what each
system *is* and *when it matters*, and points at the `rules/` and `docs/` files that
carry the mechanics. This file changes only when an invariant changes; lists live in
generated files. Humans start with the [README](README.md).

## Loaded with this file

Claude Code reads each line below that starts with `@` as an import and skips a
missing file. **Any other agent (Codex, Copilot, Gemini, Cursor): read each of these
files yourself before your first answer, if it exists.** They are part of this manual.

@identity/agent/IDENTITY.md
@identity/agent/SOUL.md
@identity/agent/INSTANCE.md
@docs/families.md

`identity/agent/IDENTITY.md` (who this agent is) and `identity/agent/SOUL.md` (how it
behaves) are seeded at onboarding. `identity/agent/INSTANCE.md` is the instance's own
always-on file: USER, never shipped by CORE or an overlay, free to `@`-import more. It
is the only place a fork adds always-on text, so nobody edits this file.
`docs/families.md` is the config-family index (which folder to read when), generated
from `docs/data-model.yaml`. All four reach sub-agents.

## Required Reading

1. **This file (`AGENTS.md`)** is the full operating manual. The name is a
   convention; the content applies to all agents.
2. **Read the session slice of `bridge-config.yaml`** with
   `python3 scripts/bridge-config.py --session` (identity, purpose, user_profile,
   theme, language, work). Other blocks belong to their skill (`--keys <block>`).
3. **Index the registries if present**: `ecosystem.yaml` (repos, packages,
   infrastructure, workspaces) and every `ecosystem.<name>.yaml` beside it. They are
   user-specific, so absent on a fresh clone, and none is an `@`-import: Phase 1 runs
   `python3 scripts/context-index.py --registries` for one line per entry, and
   `python3 scripts/context-index.py <file> --get <name>` fetches an entry when the work
   names one ([`docs/context-index.md`](docs/context-index.md)). A sub-agent never runs
   Phase 1; it runs that command itself. `ecosystem.example.yaml` is the template
   onboarding copies; do not hand-copy it.

**A question and no idea which file answers it?** Look it up in
[`docs/where-things-live.md`](docs/where-things-live.md) first; not there,
answer it, then propose the row.

## Session Start Detection (automatic)

Before responding to ANY user message at session start, run Phase 0 from
[`rules/session-start.md`](rules/session-start.md). It detects the **default branch
live**, checks the current branch, any `user/*` branch and `bridge-config.yaml`, and
routes to one of these states. The **core branch** below means whatever the
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

**For NEW USER:** Phase 0 arms the push-guard and classifies the origin before any
greeting, then opens the four-lane front door into `/bridge-onboard`. The greeting, the
"reporting the check" step, the lanes, the one private-home path and the red-flags list
live in [`rules/session-start.md`](rules/session-start.md); read them, they are not
duplicated here. Afterwards: [`docs/feature-tour.md`](docs/feature-tour.md).

---

## Theme

Themes control user-facing **vocabulary** only. Never tools, delegation, goals or
agents. Built-in: `professional` (default, en) plus locale variants; set via
`bridge-config.yaml` `theme:`. Resolution order and custom-theme authoring:
[`rules/theme.md`](rules/theme.md).
---

## Agents

Two different things share the word, and confusing them is the usual mistake.

**Sub-agents** (`.claude/agents/*.md`) are *inward*: ephemeral, spawned inside
your session so heavy or parallel work never fills the main context; they return a
structured summary. Without a delegation API they run inline (§ Tool Mapping).

**Bridge-Agents** (`agents/`) are *outward*: persistent, addressable A2A
endpoints that front a persona to the world and to peer bridges, under a human
gate. The runtime and template ship as CORE; each `agents/<name>/` instance is
USER. Model: [`agents/README.md`](agents/README.md),
[`docs/representative-agent.md`](docs/representative-agent.md). To visualize
them, suggest the optional Bridge Deck in one line, never auto-install
([`docs/bridge-deck.md`](docs/bridge-deck.md)).

---

## Agent Identity

The orchestrator's own identity (`identity/agent/IDENTITY.md`, `SOUL.md`) is distinct
from `personas/` (identities the user holds) and `mandants/` (recipient groups). CORE
ships only the seeds; onboarding writes the live files, which never promote. SOUL.md
is capped at 80 lines / 4 KB, enforced by `bridge-audit`. Guide:
[`identity/agent/README.md`](identity/agent/README.md).
---

## Standing Orders

`protocols/standing-orders/*.md` are **always-on rules** loaded every session when task
management is enabled; user-authored orders live in `standing-orders/user/`. `load: eager` (the default) reads an order's body at session
start; `load: on-trigger` keeps only its `summary` and `triggers` in context and fetches
the body when that vocabulary comes up. The index a session carries is
`python3 scripts/standing-orders.py --index`. Frontmatter (`name`, `scope`,
`enforcement`, `applies_to`, `load`): [`protocols/standing-orders/README.md`](protocols/standing-orders/README.md).

The always-on surface as a whole carries a declared ceiling, the same idea as the
`SOUL.md` cap: `context-budget.yaml` holds it, `python3 scripts/measure-context.py`
reports and enforces it, and CI fails on an always-on file nobody declared. What else
reaches a session (the skill and sub-agent listings):
[`docs/context-index.md`](docs/context-index.md#three-channels-reach-a-session).

**A sub-agent's surface is strictly smaller than its parent's:** imports and
listings, never Phase 1, so no standing order, board or work log. A pointer that
must reach sub-agents belongs in an `@`-imported file (in an instance:
`identity/agent/INSTANCE.md`). In an eager standing order it is resident for the
session, invisible to every sub-agent, and green in every guard.

---

## Layout — Cluster-Wrappers

Config lives in **three semantic cluster-wrappers**, every config type in its own
**folder**:

`identity/` WHO am I, to WHOM do I send · `infra/` WHERE does what run, HOW
reach · `workflow/` WHAT happens when. The family index is
[`docs/families.md`](docs/families.md), generated from `docs/data-model.yaml` by
`scripts/data-model.py`; a family without a row fails CI. Read a folder when its
subject comes up; its `_template.yaml` says what belongs in one. Entries
reference each other (`bridge_refs:`, `*_ref:`, `related_*:`), the graph a session
walks after the first hop; `scripts/check-edges.py` holds them to resolving
(`--neighbours <path>` shows one hop both ways).

**Default-to-Folder:** every config type lives in a plural folder
`<wrapper>/<types>/` holding `_template.yaml`, an optional `_schema.yaml` and the
`<id>.yaml` instances (plain slugs, no type prefix). `_`-prefixed files are
reserved; **discovery** is the glob `<wrapper>/<types>/*.yaml` skipping them, with
no flat fallback and no promote logic.

Full layout: [`docs/structure.md`](docs/structure.md) · discovery and
irregular plurals: [`rules/discovery.md`](rules/discovery.md) · examples under
`docs/examples/`.
---

## Scope — structural, not declarative

Every file's tier (**core** → open-bridge · **org** → your org overlay ·
**personal** → your own overlay · **user** → local) is decided by **where it
lives**, not a tag you can forget: whole folders (`work/`, `imports/` USER;
`docs/`, `trackers/` CORE), the `_`-prefix inside the cluster wrappers
(`_template`/`_schema` CORE, every instance USER), and enumerated lists where a
folder mixes both (`scripts/`, `agents/`, `mods/`, `themes/`). Frontmatter
re-tiers only the files the table lists. The one table of values, aliases,
frontmatter precedence and path rules, tested against the router:
[`docs/extension-model.md` § Scope model](docs/extension-model.md#scope-model).
The leak-check is the backstop; structure keeps PII out of the public upstream.
---

## Skills (Universal)

Skills live in `skills/`, following the open
[SKILL.md standard](https://agentskills.io/specification): a `SKILL.md` with `name` and
a one-line `description` trigger, routing to `references/` loaded only when triggered.
**Call the skill** (via the Skill tool, or by loading it from `skills/` on tools
without one) rather than reimplementing its logic. Three committed symlinks
(`.claude/skills`, `.agents/skills`, `.github/skills` → `skills/`) are the entire
discovery mechanism
([`docs/skill-distribution-architecture.md`](docs/skill-distribution-architecture.md)).

> **Never point `~/.claude/skills` at a Bridge repo.** The user level overrides
> the project level, every Bridge ships the same CORE skill names, so a
> user-level pointer at instance A silently overrides instance B's own skills
> inside B — including CORE fixes authored in B, and including A's `scope: org`
> skills. The failure is silent: plausible output from the wrong instance's
> skills. One `readlink ~/.claude/skills` at session start buys that (empty is
> correct). To make a standalone tool available everywhere, ship it as a plugin.

**Tier lives in `metadata.scope`** (skills are flat); `/bridge-promote` and
`/bridge-sync` route by it:

| Scope | Ships to |
|-------|----------|
| `core` | open-bridge + your org overlay + local |
| `org` | your org overlay + local |
| `personal` | your personal overlay + local |
| `user` | local only |

Which skill sits in which tier is per-instance, so it is deliberately not listed
here. The live map, and why a `scope: core` skill reads config instead of embedding
instance logic: [`docs/extension-model.md`](docs/extension-model.md#skill-tiers).
---

## Tool Mapping

Tool names differ per platform (Read/Write/Edit/Bash/Grep/Glob/Agent here;
`apply_patch` and shell reads on Codex; `read_file`/`write_file` on Copilot and
Gemini). The full table, and what a missing delegation API means for sub-agents:
[`docs/tool-mapping.md`](docs/tool-mapping.md).
---

## Rules

Rules are tiered by **folder**, and the folder *is* the promote tier:
`rules/` = core (ships everywhere) · `rules/org/` = your org overlay only ·
`rules/user/` = this instance only. Every `rules/*.md` must **also** carry a
top-level `scope:` matching its folder — a required backstop, not the router,
since an unscoped rule inherits `core` from its path and would leak.
`scripts/validate-bridge.py` fails CI on a missing or invalid one.

Which rules an instance has is derived, never a table here:
`python3 scripts/validate-bridge.py` writes the live map to `.bridge/rule-scope.md`.

**The rules that fire before you would think to look them up**:

- [`session-start.md`](rules/session-start.md) — the Phase 0 gate, before ANY response
- [`push-guard.md`](rules/push-guard.md) — a `user/*` branch never reaches a public upstream
- [`promote-safety.md`](rules/promote-safety.md) — content scan before anything moves to CORE;
  with [`operations.md`](rules/operations.md) (path allow/blocklist) the only promote rules
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
`<id>.yaml` under the cluster wrappers, `standing-orders/user/`, all of `work/`.
Disjoint paths, so merges are conflict-free ([`docs/structure.md`](docs/structure.md)).

- NEVER commit secrets or credentials on any branch.
- **NEVER push a `user/*` branch (or USER content) to a PUBLIC upstream.** Your
  private data lives on a private `origin`; CORE reaches a public upstream only
  via `/bridge-promote`, a fork-based content-scanned PR. Cloned the public repo
  directly? Re-home `origin` to your own private repo, keep open-bridge as a
  read-only `upstream`. Enforced by `scripts/hooks/pre-push`:
  [`rules/push-guard.md`](rules/push-guard.md).
- Layout reorgs land directly on `user/{name}`; promote later.
- Git mechanics (DCO sign-off, atomic stage+commit, the `skills/` symlink path):
  [`rules/git-hygiene.md`](rules/git-hygiene.md).

### Multiple Instances

Users may run several Bridge instances to keep organizations' data apart. Don't
access or modify another instance's files; each tracks its own `work/log.md` and
keeps its own layout. [`docs/multi-instance.md`](docs/multi-instance.md).

### Tier Model

Two-pole by default — `bks-lab/open-bridge` (OSS, MIT, generic CORE only) plus
your own private Bridge. An org that wants a shared overlay creates a private fork,
and `scope: org` routes there; `/bridge-promote` routes per `scope:`.
[`docs/org-overlays.md`](docs/org-overlays.md).

**open-bridge is English-only**: every file is authored in English from the first
keystroke, never translated later. Runtime and output language is a separate axis,
set per fork. Only locale theme files may carry *vocabulary values* in another language.
[`rules/language-policy.md`](rules/language-policy.md).

### Cross-Repo Work

Before changing another repo: read its AGENTS.md or CLAUDE.md and branch model,
commit there, then update the work log here. Issues live where the code lives.
Test before merge; the user decides merge timing.

### Creating new files — schemas first

Before writing **any** new YAML or MD under the cluster wrappers, `protocols/`,
`skills/` or `trackers/`: read the matching `_template.yaml` + `_schema.yaml`,
skim a peer file for field conventions, verify required keys, naming and expected
companions — *then* write. Skipping this is the single largest source of drift.
Checklist and per-type table: [`rules/file-creation.md`](rules/file-creation.md).

### Documentation Navigation

Navigation lives in a few strong documents, not per-directory maps: this file,
[`docs/families.md`](docs/families.md) (which config folder answers what),
[`docs/where-things-live.md`](docs/where-things-live.md) (which file answers a
question), [`docs/structure.md`](docs/structure.md) and
[`rules/knowledge-growth.md`](rules/knowledge-growth.md) (where new knowledge
belongs). A directory that needs help gets a plain `README.md`. Stand-alone docs
carry `summary` / `type` / `last_updated` / `related` frontmatter.
---

## Task Management

**Activated when** `work.enabled: true`; its data directory is `work/`.

**The model, two orthogonal axes.** KIND is the **folder**:
`work/tasks/<slug>/` is finite, `work/streams/<slug>/` is a long-runner that
never completes and never counts against WIP, `work/done/YYYY-MM/<slug>/` is
closed. Moving KIND is a `mv`; there is no `kind:` field. **status is the
field**, a closed enum `{backlog, doing, review, done}`, CI-validated. No
synonyms. `blocked_by:` is a free-text **flag**, not a status: a blocked task
stays `doing` and carries a reason. `declined` is an **outcome**:
`status: done` + `outcome: declined`. **board.md is GENERATED** from the task
dirs and never hand-curated; humans edit STATUS.md. The **WIP cap
(`work.max_active`) is a warning, never a block**: close, reprioritise, or move to
`work/streams/`.

### Session Start (automatic when enabled)

Read the recent log slice (`python3 scripts/worklog.py --recent 3`) and
`work/board.md` (**never fail on a missing work file, create it from the template and
continue**). Ensure today has a day-block, warn on the WIP cap, load the standing-order
index. Full sequence: [`rules/operations.md`](rules/operations.md).

### Logging

> **Logging is mandatory and continuous, not best-effort.** Every substantive
> unit of work gets its own `work/log.md` row the moment it lands, in the same
> turn it happened, never batched at the end. That covers a code change or
> commit, a bug fixed, a decision made *and why*, a finding worth keeping, a
> deploy or restart, an issue/PR/board operation. If you did work this turn and
> there is no row for it, the turn is **not finished**.

**One frozen row format:** `| YYYY-MM-DD HH:MM | glyph | context | what |`

- **Timestamp:** from `date '+%Y-%m-%d %H:%M'`, NEVER a placeholder, never
  estimated. The day-block header stays `## {Weekday} DD.MM` (no year), the
  anchor the `/archive` and `/briefing` parsers key off.
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
3. **Class check**: the task threshold, in order. Finished this session → log
   row only (every state change keeps its row); mentioned, nothing started → inbox
   `idea`; a task (**Class A**: STATUS.md + board row + task-sync) only when
   asked for, or work exists and continues later, or a dated commitment to
   someone. Tracker issues stay in the tracker. Otherwise Class B or C.
4. **When in doubt: ONE question.** `[a] fits <slug>` / `[b] new as <proposal>` /
   `[c] chat only` / `[d] just do it`. Do not guess.

**Don't reflex** on slash commands, on read/info queries *that stay read-only*, on
a quick fix under 10 minutes and 3 files, or on a topic the user already declined
this session. Details:
[`rules/task-management-workflow.md`](rules/task-management-workflow.md).

**Lifecycle, three steps:** `mv` the directory, **regenerate** board.md from the
dirs, append a log row with a measured timestamp.

### Inbox

What stays open after a unit of work (needs a person, waits on someone, must be
checked later) is filed with `scripts/inbox.py add`, with a `closes_when` probe
wherever the live source can tell, never left as a log sentence. Before
reporting anything as open, run `inbox.py check` and read the inbox, not the
log. Model: [`docs/inbox.md`](docs/inbox.md); one agent tab per task:
[`docs/workplace.md`](docs/workplace.md).

### Task Sync Routing

A task's **project**, **context** and **mandant** decide where it syncs; STATUS.md's
`sync:` block overrides, `bridge_only: true` keeps it local. Resolver:
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

Each skill registers its own slash-command through its `description:` frontmatter;
the CORE set is in [`docs/commands.md`](docs/commands.md).
---

## Guardrails beside the families

Each family's own guardrail travels with its row in `docs/families.md`. These cut
across families:

- Before a user-facing visual, read `DESIGN.md` (the default design and the index to
  `identity/designs/`); `python3 scripts/designs.py resolve` says which one applies.
  **Never hand-pick a brand colour**; add a missing token to the design that owns it.
- No raw secret in YAML or any tracked file: reference URIs only
  ([`rules/secret-placement.md`](rules/secret-placement.md)).
---

## Variable Interpolation

`bridge-config.yaml` defines variables under the `identity:` key. Every YAML
under the cluster wrappers, plus `ecosystem.yaml`, can use `${variable}`:
`${projects_root}`, `${home}`, `${onedrive_root}`, and a leading `~` → `$HOME`.
An unknown variable warns and skips the file.

> **Disambiguation:** `identity:` (a config key) is not `identity/` (a cluster
> wrapper). Same word, different namespaces.
---

## What NOT to Do

- Don't commit secrets or credentials to any branch
- Don't push to `main` without user approval
- Don't modify CORE files on a `user/` branch commit (use `/bridge-promote`)
- Don't skip the work log — document insights, not just actions
