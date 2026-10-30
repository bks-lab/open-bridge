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
carry the mechanics. Humans start with the [README](README.md).

## Loaded with this file

Claude Code reads each line below that starts with `@` as an import and skips a
missing file. **Any other agent (Codex, Copilot, Gemini, Cursor): read each of these
files yourself before your first answer, if it exists.** They are part of this manual.

@identity/agent/IDENTITY.md
@identity/agent/SOUL.md
@identity/agent/INSTANCE.md

`identity/agent/IDENTITY.md` (who this agent is) and `identity/agent/SOUL.md` (how it
behaves) are seeded at onboarding. `identity/agent/INSTANCE.md` is the instance's own
always-on file: USER, never shipped by CORE or an overlay, free to `@`-import more. It
is the only place a fork adds always-on text, so nobody edits this file. All three
reach sub-agents.

## Required Reading

1. **This file (`AGENTS.md`)** is the full operating manual. The name is a
   convention; the content applies to all agents.
2. **Read the session slice of `bridge-config.yaml`** with
   `python3 scripts/bridge-config.py --session` (identity, purpose, user_profile,
   theme, language, work). The other fifteen blocks belong to the skill that owns
   them; read a block with `--keys <block>` when that skill runs.
3. **Index the registries if present**: `ecosystem.yaml` (repos, packages,
   infrastructure, workspaces) and every `ecosystem.<name>.yaml` beside it (an org
   overlay's fragment, a personal one). User-specific (ignored unless the origin is
   private, docs/structure.md), so absent on a fresh clone. None is an `@`-import:
   Phase 1 runs `python3 scripts/context-index.py --registries` for the settings plus
   one line per entry, and `python3 scripts/context-index.py <file> --get <name>`
   fetches an entry when the work names one
   ([`docs/context-index.md`](docs/context-index.md)). A sub-agent never runs Phase 1;
   it runs that command itself when it needs a registry. `ecosystem.example.yaml` **is**
   present on a fresh clone as the registry template — onboarding uses it as the starting
   point (copy + auto-populate → `ecosystem.yaml`); do not hand-copy it.

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
your session so heavy or parallel work (log dumps, file trees, API results)
never fills the main context; they return a structured summary. Add one by
dropping in a `{name}.md`; no registration. Without a delegation API they run
inline (§ Tool Mapping).

**Bridge-Agents** (`agents/`) are *outward*: persistent, addressable A2A
endpoints that front a persona to the world and to peer bridges, under a human
gate. The runtime and template ship as CORE; each `agents/<name>/` instance is
USER. Model: [`agents/README.md`](agents/README.md),
[`docs/representative-agent.md`](docs/representative-agent.md). To visualize
them, suggest the optional Bridge Deck in one line, never auto-install
([`docs/bridge-deck.md`](docs/bridge-deck.md)).

---

## Agent Identity

The orchestrator carries its own identity, distinct from `personas/` (identities
the user holds) and `mandants/` (recipient groups): `identity/agent/IDENTITY.md`
(who am I) and `SOUL.md` (how I behave). CORE ships only the seeds; onboarding
writes the live files, which stay on the `user/*` branch and never promote. They
load through § Loaded with this file. SOUL.md is capped at 80 lines / 4 KB, enforced
by `bridge-audit`. Guide: [`identity/agent/README.md`](identity/agent/README.md).
---

## Standing Orders

`protocols/standing-orders/*.md` are **always-on rules** loaded every session when task
management is enabled (task-sync, board-task-criteria, drift-advisory, …). Each carries
`name`, `scope`, `enforcement` and `applies_to` frontmatter; `scope: always` orders are
matched against every sub-agent dispatch, then filtered by `applies_to` (sub-agent names,
empty = all). `protocols/` stays **top-level**: `standing-orders/` ships CORE defaults,
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
`name` + `description` of every skill and sub-agent into every session and
dispatch, one line each. Measured as `listing:skills` and `listing:agents`, capped
on the sum, heaviest entries named. It is load-bearing, so `check-reachability.py`
reads it too: a description naming a config path is a route.

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
reach · `workflow/` WHAT happens when. Every family below is a route: read the
folder when its subject comes up, and its `_template.yaml` says what belongs in
one. `scripts/check-reachability.py` fails CI when a family in the tree is named
in nothing a session loads, so this list cannot quietly fall behind the tree.
Entries also reference each other (`bridge_refs:`, `*_ref:`, `related_*:`);
those references are the graph a session walks after the first hop, and
`scripts/check-edges.py` holds them to resolving (`--neighbours <path>` shows
one hop both ways, `--fix` rewrites a reference whose task merely moved KIND).

| Family | Read it when |
|---|---|
| `identity/personas/` | an identity the user HOLDS: signature, tax data, filing paths |
| `identity/mandants/` | who RECEIVES an outgoing message |
| `identity/accounts/` | a cloud tenant, subscription or vault reference |
| `identity/contracts/` | a recurring obligation: utility, telco, insurance, SaaS |
| `identity/vehicles/` | a vehicle the user owns or leases: plate, VIN, the persona that bears it |
| `identity/agent/` | this orchestrator's own name, role and voice |
| `identity/designs/` | a brand: colours, type and shapes a generated visual uses |
| `infra/remotes/` | a machine: ssh, wake, services, "which PC" |
| `infra/channels/` | an outbound transport: mail, chat, bot, digest |
| `infra/backups/` | what is backed up where, and whether it is fresh |
| `infra/instances/` | another Bridge this one should know about |
| `infra/transcriptions/` | recording → transcript topology |
| `infra/secret-stores/` | where a secret lives, who reaches it, and which kind belongs in it |
| `infra/object-stores/` | where content that is not configuration lives: recordings, documents, exports |
| `infra/a2a-peers/` | an A2A agent this Bridge may ask: card, auth, token reference |
| `infra/utilities/` | a supply contract at a location: power, gas, water, heat |
| `workflow/briefings/` | what a briefing shows, from which trackers |
| `workflow/mail-profiles/`, `identity/mail-footers/` | drafting a mail: the occasion, and how it is signed |
| `workflow/calendars/` | a scheduled outbound action |
| `workflow/meetings/` | a recurring meeting series |
| `workflow/contexts/` | where a piece of work gets documented |
| `workflow/projects/` | a board's field values and state map, before ANY tracker call |
| `workflow/workloads/` | one declared run on one machine |
| `workflow/ai-services/` | which AI model a service or worker uses (default Claude) |
| `workflow/cost-centers/` | a project's costs across accounts: the cost card's Project filter |
| `workflow/workspaces/` | a named binding of repos + config overlays |

Top-level, own lifecycle: `rules/` `protocols/standing-orders/` `skills/`
`trackers/` `themes/` `.claude/agents/` `mods/` `work/` `docs/`.

**Default-to-Folder:** every config type lives in a plural folder
`<wrapper>/<types>/` holding `_template.yaml`, an optional `_schema.yaml` and the
`<id>.yaml` instances (plain slugs, no type prefix). `_`-prefixed files are
reserved; **discovery** is the glob `<wrapper>/<types>/*.yaml` skipping them, with
no flat fallback and no promote logic.

Full layout and routing map: [`docs/structure.md`](docs/structure.md) ·
reference implementation and irregular-plural caveats:
[`rules/discovery.md`](rules/discovery.md) · examples per type under
`docs/examples/`.
---

## Personas

A persona is an identity THE USER HOLDS (`identity/personas/<id>.yaml`), carrying
tax data, signature blocks, filing destinations (a mandant is a recipient group).
Load one when a skill or routing order references it via
`persona_ref`. Guide: [`docs/personas.md`](docs/personas.md).
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
foldered. It is what `/bridge-promote` and `/bridge-sync` route by, kept honest by
`scripts/validate-skill-scope.py` (CI + pre-commit).

| Scope | Ships to |
|-------|----------|
| `core` | open-bridge + your org overlay + local |
| `org` | your org overlay + local |
| `personal` | your personal overlay + local |
| `user` | local only |

**Which skill sits in which tier is per-instance, so it is deliberately not
listed here**: an enumeration in a CORE file diverges on the day it is written and
carries local skill names upward on promote. `python3 scripts/validate-skill-scope.py`
writes the live map to `.bridge/skill-scope.md` (derived, gitignored); the
frontmatter is authoritative.

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

**Which rules an instance has is derived, never a table here**: a local table
cannot converge across instances. `python3 scripts/validate-bridge.py` writes the
live map to `.bridge/rule-scope.md`, including whether git will track a **new**
rule at that path (in an overlay-subscribed instance, the difference between
authoring a rule and losing it silently).

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
`<id>.yaml` under the cluster wrappers, `standing-orders/user/`, and all of
`work/`. The two touch disjoint paths, so merges are conflict-free by
construction. Per-path table: [`docs/structure.md`](docs/structure.md).

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
your own private Bridge. The middle tier is an optional convention: an org that
wants a shared overlay creates a private fork it names itself, and `scope: org`
routes there. `bridge-config.yaml.upstreams` is a list; `/bridge-promote` routes per
`scope:`. Full model, including the subscribe direction:
[`docs/org-overlays.md`](docs/org-overlays.md).

**open-bridge is English-only**: every file is authored in English from the first
keystroke, never translated later. Runtime and output language is a separate axis,
set per fork. Only locale theme files may carry *vocabulary values* in another language.
[`rules/language-policy.md`](rules/language-policy.md).

### Cross-Repo Work

Before changing code in another repo: read that repo's AGENTS.md or CLAUDE.md, check its
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

**Activated when** `work.enabled: true`; its data directory is `work/`.

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

Read the recent log slice (`python3 scripts/worklog.py --recent 3`) and
`work/board.md`, creating either from templates if missing (**never fail on a
missing work file, create and continue**). Ensure today has a day-block. Warn, do
not block, on the WIP cap. Load the standing-order index (§ Standing Orders). Full
sequence: [`rules/operations.md`](rules/operations.md).

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
3. **Class check**: the task threshold, in order. Finished this session → log
   row only (every state change keeps its row); mentioned, nothing started → inbox
   `idea`; a task (**Class A**: STATUS.md + board row + task-sync) only when
   asked for, or work exists and continues later, or a dated commitment to
   someone. Tracker issues stay in the tracker. Otherwise Class B or C.
4. **When in doubt: ONE question.** `[a] fits <slug>` / `[b] new as <proposal>` /
   `[c] chat only` / `[d] just do it`. Do not guess.

**Don't reflex** on slash commands, on read/info queries *that stay read-only*, on
a quick fix under 10 minutes and 3 files, or on a topic the user already declined
this session. Intent lists, similarity algorithm, cluster detection, class
examples and repair recipes:
[`rules/task-management-workflow.md`](rules/task-management-workflow.md).

**Lifecycle, three steps:** `mv` the directory, **regenerate** board.md from the
dirs, append a log row with a measured timestamp.

### Inbox

What stays open after a unit of work (needs a person, waits on someone, must be
checked later) is filed with `scripts/inbox.py add`, with a `closes_when` probe
wherever the live source can tell, never left as a log sentence. Before
reporting anything as open, run `inbox.py check` and read the inbox, not the
log. Model: [`docs/inbox.md`](docs/inbox.md). The workplace
(`scripts/workplace.py`, driver-based) opens one agent tab per task:
[`docs/workplace.md`](docs/workplace.md).

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
frontmatter (no files in `.claude/commands/`); invoking it via the Skill tool is
the same as typing the command. The CORE set: [`docs/commands.md`](docs/commands.md);
an instance's live list is the skill listing itself.
---

## Remotes — Remote Machines

Your physical and virtual machines live in `infra/remotes/*.yaml`. In Bridge
context **"remote" means remote MACHINE, never `git remote`** — check
`infra/remotes/` before asking "which PC?". The **`remote`** skill owns the
directory and auto-loads on a machine name, "my PC / fleet status", "wake / WoL",
"ssh to / RDP to". Schema: `infra/remotes/_template.yaml`. Capability `arm`
marks the always-on machine ([`docs/always-on-machine.md`](docs/always-on-machine.md)).
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

`DESIGN.md` is the default design and the index to every other one; each further
brand is `identity/designs/<id>.md`, same format, own `scope:`, so it travels with its
overlay. Generators ask `python3 scripts/designs.py resolve` which one applies.
**Never hand-pick a brand colour**; add a missing token to the design that owns it.
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
