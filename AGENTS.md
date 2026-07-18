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
2. **Read `bridge-config.yaml`** for user preferences (theme, language, features).
3. **Read `ecosystem.yaml` if present** — the project registry (repos, packages,
   infrastructure, workspaces). It is created during onboarding and is user-specific
   and gitignored (like `bridge-config.yaml`), so it is absent on a fresh clone. When
   present, `CLAUDE.md` imports it via `@ecosystem.yaml`. `ecosystem.example.yaml` **is**
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

Themes control all user-facing vocabulary — terms and phrases. They NEVER control tools,
delegation, or goals, and never define agents. Built-in: `professional` (default, en) and
`professional-de` (de); set via `bridge-config.yaml` field `theme:`. Resolution: read
`theme:` → load `themes/{theme}.yaml` (fall back to `professional`) → deep-merge
`meta.extends` parent → fill defaults from `_schema.yaml`.

**Full details** (resolution steps, custom-theme authoring, vocabulary table):
[`rules/theme.md`](rules/theme.md).

---

## Agents

The Bridge uses **native Claude Code sub-agents** under `.claude/agents/*.md` — markdown
definitions with YAML frontmatter (`name`, `description`, `tools`, `model`, optional
`scope`), auto-discovered at session start, spawned via the `Task` tool with
`subagent_type: {name}` (other tools: see the Tool Mapping table below). Their purpose:
offload heavy/parallel/isolated work so raw output (log dumps, file trees, API results)
never fills the main context — they return structured summaries. Coordinator skills
dispatch them by workflow stage. Add one by dropping another `{name}.md` into the folder —
no registration needed.

**On non-Claude tools** (Copilot CLI, Gemini CLI, Cursor, Codex): sub-agents aren't
available in their native API. Skills that would dispatch a sub-agent run that logic
**inline** instead — the capability is preserved; only the delegation/isolation
architecture differs (work happens in the main context rather than an isolated one).

The older `/crew` command is retired — create sub-agents by editing `.claude/agents/*.md`
directly.

**Bridge-Agents** (`agents/`) are the *outward* counterpart to the *inward* sub-agents
above — don't confuse them. A sub-agent is ephemeral, works for you inside your session, and
returns a summary; a **Bridge-Agent** is a persistent, addressable A2A endpoint that fronts a
persona to the world (and to peer bridges) under a human gate. The generic runtime + template
ship as CORE under `agents/`; each `agents/<name>/` instance is USER. A thin, stateless
MCP→A2A gateway (`list_bridges`, `get_bridge_card`, `ask_bridge`) ships as CORE under
`agents/_gateway/`. Full model: [`agents/README.md`](agents/README.md),
[`agents/_gateway/README.md`](agents/_gateway/README.md),
[`docs/representative-agent.md`](docs/representative-agent.md).

---

## Agent Identity

The orchestrator carries its own identity — distinct from `personas/` (identities the user
holds) and `mandants/` (recipient groups). Two files in `identity/agent/`: `IDENTITY.md`
(name, role, backstory — *who am I*) and `SOUL.md` (voice, posture, defaults applied to
every skill and conversation — *how I behave*).

**CORE ships only the seeds, not a finished voice.** A fresh clone has no live
`SOUL.md`/`IDENTITY.md` — only CORE companions (`_template.*`, `_soul-deck.yaml`,
`_schema.yaml`). Onboarding seeds the live files (which carry `scope: user`, stay on the
`user/*` branch, never promote) and adds the `@`-imports to `CLAUDE.md`. Size cap for
SOUL.md is 80 lines / 4 KB, enforced by `bridge-audit`. Full guide:
[`identity/agent/README.md`](identity/agent/README.md). The `SOUL.md` convention was
pioneered by Peter Steinberger (OpenClaw), standardized by [SoulSpec](https://soulspec.org/),
and adopted by agents like Nous Research's Hermes (see [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md)).

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

---

## Layout — Cluster-Wrappers

Config files live in **three semantic cluster-wrappers**. Every config type gets its own
**folder** — no exceptions, no thresholds. Templates and schemas live inside the folder.

```
identity/    WHO am I, to WHOM do I send    (personas, accounts, mandants, contracts, agent)
infra/       WHERE does what run, HOW reach (remotes, channels, backups, instances)
workflow/    WHAT happens when              (calendars, contexts, projects)
```

Top-level (own lifecycle): `protocols/` `work/` `docs/` `rules/` `trackers/` `themes/`
`skills/` `.claude/`. Root configs: `bridge-config.yaml` `ecosystem.yaml` (both user-created
at onboarding, gitignored) `bridge-deck.config.yaml`.

**Default-to-Folder rule:** every config type lives in **`<wrapper>/<types>/`** — a plural
folder with `_template.yaml`, optional `_schema.yaml`, and all `<id>.yaml` instances
together. Companions: `<id>-setup.md` (provisioning notes you need *before* the YAML runs)
vs `<id>.README.md` (overview of what the YAML *means*). `_`-prefixed files are reserved and
excluded from discovery; filenames are simple slugs without type-prefix
(`mandants/team.yaml`). Going from 1 instance to 5 is zero work — the folder already exists.

**Discovery** is a simple glob `<wrapper>/<types>/*.yaml` (skip `_`-prefixed) — no flat
fallback, no promote logic. Onboarding lays down the empty USER structure idempotently, so a
fresh clone has the instance dirs even when it shipped only CORE templates.

**Full maps:** [`rules/discovery.md`](rules/discovery.md) (reference impl + irregular-plural
caveats), [`docs/structure.md`](docs/structure.md) (full layout + routing map, current
allocation, template/schema locations), [`docs/extension-model.md`](docs/extension-model.md)
(CORE/USER split with schemas). Examples per type: `docs/examples/<type>/`.

---

## Personas

A persona represents an identity THE USER HOLDS, stored in `identity/personas/<id>.yaml`.
Unlike mandants (recipient groups for outgoing messages), a persona carries tax data,
signature blocks, document-filing destination paths, and vehicle classification. Load a
persona when a skill, sub-agent, or routing standing-order references one via `persona_ref`.
Schema + guide: `identity/personas/_template.yaml`, `_schema.yaml`,
[`docs/personas.md`](docs/personas.md).

---

## Scope — structural, not declarative

Every file's tier (**core** → open-bridge · **org** → your org overlay · **user**
→ local) is decided by **where it lives**, not a tag you can forget. Three mechanisms:

1. **Whole folder** — the path *is* the tier. `work/`, `imports/` = USER;
   `docs/`, `themes/`, `trackers/`, `scripts/`, `protocols/standing-orders/*.md` = CORE.
2. **`_`-prefix** (cluster-wrappers `identity/ infra/ workflow/`) —
   `_template.yaml`/`_schema.yaml` = CORE, every other instance `*.yaml` = USER.
3. **Frontmatter — skills and rules.** Skills are flat under `skills/` (open Agent-Skills
   standard — discovered by Claude Code, Copilot CLI, Codex, Gemini, Cursor via the
   `.claude/skills` / `.agents/skills` / `.github/skills` symlinks → `skills/`). They can't
   be foldered, so tier lives in `metadata.scope`, hard-gated by
   `scripts/validate-skill-scope.py` (CI + pre-commit; regenerates the SKILL-SCOPE table in
   this file). Rules *are* foldered (§ Rules) and still route by path, but every `rules/*.md`
   must **also** carry a top-level `scope:` matching its folder — hard-gated by
   `scripts/validate-bridge.py` (CI). Without it an unscoped rule silently inherits `core`
   from its path and would leak, so the field is a required backstop, not an option.

**Rules are tiered by folder:** `rules/*.md` = core · `rules/org/**` = org · `rules/user/**`
= user. Only core `rules/*.md` ship in open-bridge; `rules/org/` + `rules/user/` are added
by a downstream overlay — additive, like nested AGENTS.md.

**Promote routes mechanically** on these inputs (`rules/operations.md` is the
SoT; `scripts/categorize-commits.py` classifies by them); the content
leak-check is the **backstop**, not the primary guard — structure is what keeps
PII/customer content out of the public OSS upstream.

**Generic CORE skills:** a `scope: core` skill earns its tier by staying generic *inside* —
it **reads** config (`bridge-config.yaml`, `workflow/`, `infra/`, `identity/`) and never
embeds instance logic, hardcoded queries, org/project IDs, personas, or thresholds. If it
needs a new instance knob, add the config key and read it. Detail + anti-pattern:
[`docs/extension-model.md` § Generic CORE Skills](docs/extension-model.md).

---

## Skills (Universal)

Skills live in `skills/` at the project root, following the open
[SKILL.md standard](https://agentskills.io/specification) (AAIF / Linux Foundation).
Each skill has a `SKILL.md` with YAML frontmatter (`name`, `description`) and a
decision tree routing to `references/` files. Only load a reference when triggered.
Every skill declares a single-line `description:` trigger. Always call the skill via the
Skill tool (or load it from `skills/` directly on tools without one) rather than
reimplementing the logic.

**Discovery symlinks** (committed, so every clone gets them):

| Symlink | Target | Discovered by |
|---------|--------|---------------|
| `.claude/skills` | `→ skills/` | Claude Code |
| `.agents/skills` | `→ skills/` | Copilot CLI, Gemini CLI, Codex, Cursor |
| `.github/skills` | `→ skills/` | GitHub Copilot (project skills) |

The canonical location remains `skills/` — edit there, the symlinks follow.

> **Never point `~/.claude/skills` at a Bridge repo.** These three committed
> symlinks are the *entire* discovery mechanism — an instance's skills load
> whenever the CWD is inside it, and no user-level pointer is needed. The user
> level overrides the project level on a name collision, and every Bridge ships
> the same CORE skill names, so a user-level pointer at instance A silently
> overrides instance B's own skills inside B — including CORE fixes authored in
> B, and including A's `scope: org` skills. The failure is silent (plausible
> output from the wrong instance's skills). Skills in an instance belong to that
> instance; the user level is for skills that belong to the machine. To make a
> standalone tool skill available in any directory, ship it as a **plugin**.
> Detail: [`docs/skill-distribution-architecture.md` § Why the user level is not
> a distribution channel](docs/skill-distribution-architecture.md#why-the-user-level-is-not-a-distribution-channel)
> · [`docs/multi-instance.md` § Capability Isolation](docs/multi-instance.md#capability-isolation).

> **Windows:** Symlinks require Developer Mode + `git config core.symlinks true`.
> Easiest: run `bin\setup.ps1` — it re-links **all three** targets (`.claude`,
> `.agents`, `.github` skills) with a junction fallback (no Developer Mode needed) **and**
> arms the pre-push guard. If linking by hand, recreate all three as links/junctions
> (`.claude/skills`, `.agents/skills`, `.github/skills` → `skills/`) — prefer a link over
> a copy so edits stay in sync.
> On a default Windows git checkout the committed `.agents/skills` + `.github/skills`
> symlinks degrade to plain-text files, so non-Claude tools find no skills — see the
> README (Windows section) for the fix.

| Group | Skills |
|-------|--------|
| **Bridge ops** (session lifecycle) | `briefing`, `archive`, `bridge-status`, `bridge-explorer`, `bridge-greeting` |
| **Bridge maintenance** | `bridge-audit` (drift detection), `bridge-leak-check` (categorized content scan), `bridge-curator` (consolidation pass), `bridge-learn` (learning-loop proposals), `onboard-sim` (adversarial push-guard leak simulation) |
| **Bridge setup + sync** | `bridge-onboard`, `bridge-promote`, `bridge-sync` (sprint-level batch sync to upstreams), `bridge-contribute` (fork-based upstream PRs), `bridge-overlay` (subscribe to org overlays), `knowledge-repo-init` (pair a knowledge repo), `workspace` (bind repos + config overlays into a project container) |
| **Communication / meetings** | `debrief` (full / `--quick` / `--all` / `--date`), `meeting-transcription` (recording → transcript pipeline feeding `/debrief`) |
| **Messaging + scheduling** | `channel`, `schedule`, `calendar`, `mandants` |
| **Infrastructure** | `remote` |
| **Projects** | `dashboard`, `project-advisor`, `github-projects-manager`, `tracker-sync`, `task-close-postmortem` |
| **Documents** | `doc-system` |
| **Authoring / visuals** | `html-canvas` (single-file HTML deliverables), `bridge-dashboard` (Bridge Control Center) |
| **USER-scoped (`scope: org`)** | downstream `*-bridge` overlays add their own (e.g. customer coordinators, document routers, dashboards) |

The groups above are a human-readable index. The **authoritative tier** (what `/promote` and
`/bridge-sync` route by) is the per-skill `metadata.scope`. Skills are flat under `skills/`
and can't be foldered, so scope lives in frontmatter, kept honest by
`scripts/validate-skill-scope.py` (CI + pre-commit) — the validator is what makes it
load-bearing instead of drift-prone. USER-scoped skills never land on `main` — see § Promote.

<!-- SKILL-SCOPE:START (auto-generated by scripts/validate-skill-scope.py — do not edit by hand) -->

| Scope | Ships to | Skills |
|-------|----------|--------|
| `core` | open-bridge + your org overlay + local | `archive`, `bridge-audit`, `bridge-contribute`, `bridge-curator`, `bridge-dashboard`, `bridge-explorer`, `bridge-greeting`, `bridge-leak-check`, `bridge-learn`, `bridge-onboard`, `bridge-overlay`, `bridge-promote`, `bridge-status`, `bridge-sync`, `briefing`, `calendar`, `channel`, `dashboard`, `debrief`, `doc-system`, `github-projects-manager`, `html-canvas`, `knowledge-repo-init`, `mandants`, `meeting-transcription`, `onboard-sim`, `project-advisor`, `remote`, `schedule`, `task-close-postmortem`, `tracker-sync`, `workspace` |
| `org` | your org overlay + local | — |
| `user` | local only | — |

<!-- SKILL-SCOPE:END -->

> **Historical note:** `bridge-core`, `bridge-ops` (as a skill), `bridge-setup` and
> `bridge-fleet` are obsolete names from an earlier monolithic shape. The current split is
> listed above. Ignore stale references in older docs.

---

## Tool Mapping

If your platform uses different tool names, map them:

| Claude Code | Codex | Copilot CLI | Gemini CLI | Cursor/Windsurf | Purpose |
|-------------|-------|-------------|------------|----------------|---------|
| Read | shell read (`sed`, `cat`) | read_file | read_file | open/read file | Read file contents |
| Write | `apply_patch` | write_file | write_file | create file | Create/overwrite file |
| Edit | `apply_patch` | edit_file | edit_file | patch file | Patch existing file |
| Bash | shell command | run_command | run_command | terminal | Execute shell command |
| Grep | `rg` | search | search | search | Search file contents |
| Glob | `rg --files` / `find` | find_files | find_files | file search | Find files by pattern |
| Agent | sub-agent tool if available | — | — | background agent if available | Spawn/delegate work |

> **`—` in the Agent row** means the tool has no delegation API; skills run inline with
> identical logic (capability preserved — only the isolation architecture differs).

**Codex notes:** Prefer `rg`/`rg --files` for search, `apply_patch` for manual edits, and
`AGENTS.md` (this file) as the repo-level instruction file. Codex can use the same universal
skills via `.agents/skills/*/SKILL.md`.

---

## Rules

Rules are tiered by **folder** — the folder *is* the promote tier, and every `rules/*.md`
must **also** carry a top-level `scope:` in frontmatter matching that folder. The field is a
required backstop rather than the router: an unscoped rule inherits `core` from its path and
would leak, so `scripts/validate-bridge.py` fails CI on a missing or invalid one.

- **`rules/`** — CORE framework rules, always-on, ship to every downstream.
- **`rules/org/`** — org-tier rules (ship to a downstream `*-bridge` overlay only, never open-bridge).
- **`rules/user/`** — this instance's own rules (never ship anywhere).

Each bridge layers its own rules under `rules/org/` (org) or `rules/user/` (personal) —
additive, like nested AGENTS.md. Other tools: read `rules/*.md` plus whichever tier folders
apply to your instance at session start.

| Rule | Tier | Purpose |
|------|------|---------|
| `session-start.md` | core | **Phase 0 gate** — branch/config detection before ANY response at session start |
| `operations.md` | core | Session management (Phase 1), commit hygiene, CORE/USER promote routing, work logging |
| `ci-discipline.md` | core | Verify CI green after every push unprompted; diagnose a red run from its log, not the workflow YAML |
| `contribute-advisor.md` | core | Suggest upstream contributions when CORE-eligible files are created |
| `deploy-reconciliation.md` | core | Declared `status:` fields are never trusted — probe the actual remote before any "running/deployed" claim |
| `discovery.md` | core | Config-type resolution helper — the Default-to-Folder discovery glob over the cluster wrappers |
| `file-creation.md` | core | Pre-write checklist — anchor on the matching template + schema + a peer example before creating any new YAML/MD |
| `git-hygiene.md` | core | Git mechanics gates — DCO sign-off, atomic stage+commit, the `skills/` symlink path |
| `knowledge-growth.md` | core | Meta-rule — where new knowledge belongs (CLAUDE.md vs `rules/` vs `docs/` vs standing-order vs memory) |
| `language-policy.md` | core | CORE content is authored in English; runtime/output language is a separate per-fork axis |
| `learning-autonomy.md` | core | The four layers the Bridge can change about itself, and the human gate at each one |
| `multi-agent-review.md` | core | Three-phase parallel-agent review engine for strategic/high-stakes written communication |
| `multi-instance-isolation.md` | core | Inbound isolation between Bridge instances — never pull another instance's content in |
| `org-overlays.md` | core | Fail-closed contract for materializing an org overlay's `scope:org` content into a consumer Bridge |
| `promote-safety.md` | core | Content-leak prevention before cherry-pick/merge to CORE branches — scope-check for `skills/` and `.claude/agents/` |
| `push-guard.md` | core | Push-boundary gate blocking `user/*` branches and USER content from reaching a public upstream |
| `skill-routing.md` | core | Discipline for picking skills over ad-hoc prompts |
| `task-management-workflow.md` | core | Detailed workflow for task management — reflex pause, plan/build classification, similarity, cluster detection |
| `theme.md` | core | Theme system — resolution order, built-in themes, custom theme authoring |
| `visual-output.md` | core | Cross-skill gates for generated visual deliverables — light/dark toggle, source attribution on every figure |

Only the `core` rules above ship in open-bridge. The `rules/org/` and `rules/user/` folders
do **not** ship in CORE OSS — a downstream `*-bridge` overlay adds its own org-tier rules
under `rules/org/` (e.g. wiki conventions when a `wiki/` sibling exists) and personal rules
under `rules/user/`. They are added by overlays, never present in a fresh open-bridge clone.

### Git & Branches

CORE files (the default branch — `main` here) are generic and ship with the repo: skills,
templates, schemas, docs, examples, CORE sub-agents, CORE standing-orders, `CLAUDE.md` /
`README.md` / `AGENTS.md` / `GEMINI.md`. USER files (`user/{name}`) are your concrete
instances: `bridge-config.yaml`, `ecosystem.yaml`, every `<id>.yaml` under the cluster
wrappers, `workflow/projects/<slug>.yaml`, `standing-orders/user/`, and all of `work/`. CORE
and USER touch disjoint paths, so merges are conflict-free by construction. Full per-path
table: [`docs/structure.md`](docs/structure.md).

- NEVER commit secrets or credentials on any branch
- **NEVER push a `user/*` branch (or USER content) to a PUBLIC upstream** (e.g.
  `bks-lab/open-bridge`). Your private data lives on a **private `origin`**; CORE
  reaches a public upstream only via `/promote` (a fork-based, content-scanned PR).
  Cloned the public repo directly? Re-home `origin` to your own private repo (or
  GitHub *Use this template → Private*) and keep open-bridge as a read-only
  `upstream`. Enforced behaviourally (onboarding + auto-end-of-work) and
  deterministically by `scripts/hooks/pre-push`. Full rule:
  [`rules/push-guard.md`](rules/push-guard.md)
- Layout reorgs land directly on `user/{name}` — promote later

### Multiple Instances

Users may run multiple Bridge instances for data isolation between organizations — each a
separate clone with its own `user/` branch, some pushed to a remote, some local-only to keep
client data off shared remotes. Don't access or modify another instance's files;
cross-instance work logging is not supported (each tracks its own `work/log.md`); other
instances keep their own layout. **Full guide:** [`docs/multi-instance.md`](docs/multi-instance.md).

### Tier Model (two-pole + optional org overlay)

The base model is **two-pole** — open-bridge plus your own freely named private Bridge(s).
The middle tier is an **optional convention**: an org that wants a shared overlay creates a
private fork it names itself (`<your-org>/<your-bridge>`), and `scope: org` routes to it.

| Tier | Role |
|---|---|
| `bks-lab/open-bridge` | OSS project — generic CORE only (this repo) |
| `<your-org>/<your-bridge>` (optional private fork) | open-bridge + org overlay |
| `<your-username>/your-bridge` (private fork) | upstream overlay(s) + personal PII |

- **Multi-upstream:** `bridge-config.yaml.upstreams` as a list. `/promote` routes per `scope:` (core → open-bridge, org → your org overlay, user → local).
- **Promote-safety is repo-specific:** open-bridge has a strict block-list; your org overlay is relaxed.
- **Licence: MIT.**
- **open-bridge is English-only.** Every file in this repo (CLAUDE.md, README.md, AGENTS.md, GEMINI.md, docs/, rules/, skills/, themes/, trackers/, examples/) must be entirely in English — no German sentences, headings, or comments in templates/schemas. CORE here is authored in English from the first keystroke — never written in another language and translated later. A downstream fork that contributes CORE upward must translate it to English before it lands; open-bridge itself never translates at promote. Runtime/output language is a separate axis (set per fork via `bridge-config.yaml` `language.conversation` / `language.artifacts`) — a German-speaking user still gets German conversation while these CORE files stay English. **Exception:** locale theme files under `themes/` (e.g. `professional-de.yaml`) legitimately carry non-English *vocabulary translations* — the theme's structural comments/keys stay English, but the user-facing vocabulary values may be in the target language. Full policy: [`rules/language-policy.md`](rules/language-policy.md).

**Org Overlays — the subscribe direction.** `/promote` publishes `scope:org` content *up* to your org overlay; **org overlays** pull it back *down* into a teammate's fresh clone. The `/overlay` skill (`bridge-overlay`) sparse-clones an overlay repo named in a `role: org-overlay` upstream's `materialize:` block and materializes its files as tracked copies pinned to immutable hashes — never touching the public OSS upstream, conflict-free against `git merge main`. Full guide: [`docs/org-overlays.md`](docs/org-overlays.md).

### Commits & PRs

- Test before merge, user decides merge timing
- Issues belong in the repo where the code lives

### Cross-Repo Work

Before changing code in another repo: (1) read that repo's CLAUDE.md, (2) check its branch
model, (3) commit changes there not here, (4) return and update the work log.

### Creating new files — schemas first

Before writing **any** new YAML or MD under cluster wrappers, `protocols/`, `skills/`, or
`trackers/`: read the matching `_template.yaml` + `_schema.yaml`, skim an existing peer file
for field conventions, verify required keys / naming / expected companions — *then* write.
Skipping this is the #1 source of drift. Full checklist + per-type table:
[`rules/file-creation.md`](rules/file-creation.md).

### Documentation Navigation

Central navigation lives in **a few strong documents**, not per-directory MOCs: `AGENTS.md`
(this file — the canonical manual), `README.md`, [`docs/structure.md`](docs/structure.md)
(layout + routing), [`docs/extension-model.md`](docs/extension-model.md) (CORE/USER +
schemas), [`rules/knowledge-growth.md`](rules/knowledge-growth.md) (where new knowledge
belongs), and [`docs/memory.md`](docs/memory.md) (the file-based memory model + lean-index
discipline). When a directory genuinely needs navigation help, use a single industry-standard
`README.md` (GitHub/IDEs render it automatically) — no custom `_MOC.md` / `index.md`
conventions. Stand-alone doc files carry `summary` / `type` / `last_updated` / `related`
frontmatter.

### Key Conventions (quick reference)

- **CORE/USER branch split:** `main` = shared templates, `user/{name}` = personal data. Different paths, conflict-free merges.
- **Task Management:** `work/log.md` (daily log), `work/board.md` (generated task board), `work/tasks/` (finite tasks) + `work/streams/` (long-runners). Enabled via `work.enabled: true` in bridge-config.yaml.
- **Sub-agents:** Native Claude Code sub-agents in `.claude/agents/*.md` (frontmatter: `name`, `description`, `tools`, `model`, optional `scope`). Spawned via `Task(subagent_type: …)`.
- **Standing orders:** `protocols/standing-orders/` — always-on rules injected into every dispatch.
- **Channels:** Messaging integrations in `infra/channels/*.yaml` (email, Signal, Telegram, iMessage, etc.).
- **Calendar + Mandants:** Scheduled outbound actions in `workflow/calendars/entries.yaml`, recipient groups in `identity/mandants/*.yaml`.
- **Project Registry:** Per-project configs in `workflow/projects/*.yaml` — field values, governance rules, state mappings. Read the matching config BEFORE any GitHub/ADO operation.

---

## Task Management

**Activated when** `work.enabled: true` in bridge-config.yaml (set `false` to deactivate;
data under `work/` is preserved). The system is called **Task Management**; the directory
that holds its data stays named `work/`.

**The model (two orthogonal axes — KIND is the folder, status is the field):**

- **KIND = the folder.** `work/tasks/<slug>/` = a **finite** task (reaches `done`).
  `work/streams/<slug>/` = a **long-runner** (never `done`, excluded from WIP).
  `work/done/YYYY-MM/<slug>/` = closed. Moving KIND = `mv` the directory; there is no
  `kind:` field.
- **status = the field**, a closed enum: `status ∈ {backlog, doing, review, done}` —
  CI-validated against `work/templates/_schema.status.yaml`. No synonyms; the enum never
  grows informally.
- **`blocked_by:` is a free-text FLAG, not a status.** A blocked task stays `doing` (or
  `review`) and carries `blocked_by: "<reason>"`. **`declined` is an outcome:** a declined
  task is `status: done` + `outcome: declined`.
- **board.md is GENERATED** from the task dirs (sections == the enum + Streams + Done,
  counts == `ls`) — never hand-curated. Humans edit STATUS.md; the board is regenerated.
- **WIP cap is a WARNING, never a block.** Session-start warns when `doing + review` in
  `work/tasks/` exceeds `work.max_active`; new work is never refused. The remedy is to
  close, reprioritise, or reclassify a task to `work/streams/` (streams never count
  against WIP).

### Session Start (automatic when enabled)

Read `work/log.md` (last activity, current week) + `work/board.md` (active tasks); create
either from templates if missing — **never fail on missing work files, create and continue**.
Ensure today has a day-block. Warn (do not block) if `doing + review` in `work/tasks/`
exceeds `work.max_active`. Load standing orders with `scope: always`.

### Logging

> **Logging is mandatory and continuous — not best-effort.** Every substantive unit of work
> gets its own `work/log.md` row the moment it lands, in the same turn it happened — not
> batched at the end. That covers a code change or commit, a bug fixed, a decision made
> (+ the *why*), a finding worth keeping, a deploy/restart, an issue/PR/board operation. If
> you did work this turn and there is no row for it, the turn is **not finished** — append
> the row before you hand back.

Default level `hybrid`: auto-log on triggers (commits, command/skill invocations, repo
switches, significant results, end of a work block) and remind if >30 min silent. Levels
`auto` (triggers only) and `manual` (on request) are selectable in bridge-config.yaml.
Document **insights, not just actions** — log.md is the working memory `/briefing` reads.

**Format (one frozen row format):** `| YYYY-MM-DD HH:MM | glyph | context | what |`
- **Timestamp:** full-ISO date+time via `date '+%Y-%m-%d %H:%M'` — every row **self-dates**, so a
  stale or unarchived log is never ambiguous; NEVER xx:xx or placeholders. The day-block header
  stays `## {Weekday} DD.MM` (a display anchor the `/archive` + `/briefing` parsers key off — do
  NOT add a year there). The old time-only `| HH:MM | … |` row is retired.
- **glyph:** emoji from `activity_types` in bridge-config.yaml; **context:** repo tag from
  ecosystem.yaml; chronological append at the end of the current day-block.

Full level semantics: [`docs/work-system.md`](docs/work-system.md) (if present) /
`bridge-config.yaml` `work:`.

### Consult before write

The Bridge advises; it does not act autonomously. **Reflex-pause before the first
*write* of any unit of work** — and a write is not just a productive-folder change
(`skills/`, `protocols/`, `identity/`, `workflow/`, `infra/`, `work/tasks/<slug>/`,
`work/streams/<slug>/`, `work/board.md`, `work/log.md`) but **any state change
anywhere**: a commit or push on *any* repo, a GitHub/ADO issue-or-PR-or-board operation
(create · close · comment · merge), an outbound message. Reading is always free; the
pause fires the instant you are about to change state.

**Escalation cancels the read-only exemption.** A turn that began as read / info /
analysis is exempt only while it stays read-only. The instant it grows a write — an
issue you're about to close, a PR you're about to open, a task you're about to
create — re-enter this gate. Never ride the opening "just have a look" framing into
real changes.

Four steps; **step 1 is mandatory before the first write, whatever the mode:**

1. **Active-task check** — `ls work/tasks/` + `ls work/streams/` + board.md Doing.
   Slug / context / stakeholder match → propose *"Fits `<slug>`?"* before creating
   anything new; ≥3 siblings share a prefix → cluster warning. Skipping this is how
   duplicate tasks and orphaned streams get born.
2. **Mode check — plan or build?** PLAN (research / sketch / draft / explore / analyze /
   evaluate) → answer in chat. BUILD (implement / create-file / deploy / merge / verify /
   commit / fix / close-issue / open-PR) → allowed after steps 1 + 3. Ambivalent (create /
   review / audit / consolidate) → ask.
3. **Class check** ([`board-task-criteria.md`](protocols/standing-orders/board-task-criteria.md)):
   cross-session pickup OR external recipient → **Class A** (STATUS.md + board row,
   task-sync runs). Otherwise Class B (log only) or Class C (silent for routine commands).
4. **When in doubt: ONE question.** `[a] fits <slug>` / `[b] new as <proposal>` /
   `[c] chat only` / `[d] just do it`. Do not guess.

**Don't reflex** on: slash commands (`/briefing`, `/archive`, `/bridge-*`); read/info
queries **that stay read-only** (once one produces a write, the escalation clause fires);
quick fix <10 min and <3 files; a topic the user already declined this session.

Full intent lists, similarity algorithm, cluster detection, class A/B/C examples, repair
recipes: [`rules/task-management-workflow.md`](rules/task-management-workflow.md).

**Task buckets:** `work/tasks/<slug>/` = finite tasks in flight · `work/streams/<slug>/` =
long-running streams that never complete (do **not** count against `max_active`) ·
`work/done/$(date +%Y-%m)/<slug>/` = closed.

**Task lifecycle (3 steps):** (1) `mv work/{from}/{slug} work/{to}/{slug}` (done →
`work/done/$(date +%Y-%m)/`), (2) **regenerate** board.md from the dirs (never hand-edit it),
(3) log entry with timestamp. If `doing + review` in `work/tasks/` >= max_active → **WARN
only** (never blocks) and suggest closing, reprioritising, or moving a long-runner to
`work/streams/`.

### Task Sync Routing (three-axis model)

Every task lives at the intersection of three orthogonal axes — **project**
(`workflow/projects/<slug>.yaml`, board fields), **context**
(`workflow/contexts/<slug>.yaml`, where we document), **mandant**
(`identity/mandants/<slug>.yaml`, who gets notified). STATUS.md's `sync:` block declares
per-task overrides; the resolver merges with context defaults (most specific wins);
`bridge_only: true` is the explicit local-only fallback. Contexts can opt into stricter
rules (e.g. `dual_doku: required`). Canonical resolver + schemas:
[`protocols/standing-orders/task-sync.md`](protocols/standing-orders/task-sync.md),
`work/templates/STATUS.md`, `workflow/contexts/_schema.yaml`.

### Trackers (issue / work-item integration)

The Bridge reads work items from external trackers via **pluggable provider playbooks** in
`trackers/*.md` — each a markdown file telling the agent which CLI to run and how to normalize
output into a shared schema (contract: [`trackers/README.md`](trackers/README.md)). Shipped:
`github.md` (working, `gh` CLI), `ado.md` (reference, `az` CLI). A new tracker = a new
`trackers/{name}.md` matching the contract. Enable per provider in `bridge-config.yaml` under
`integrations.<name>.enabled`; `/briefing` Stream B fans out over enabled providers in
parallel.

**Write operations** (issues, board moves, governance) go through the
**`github-projects-manager`** skill, driven by the Project Registry
(`workflow/projects/<slug>.yaml`); `project-advisor` provides K/W/B governance and
board-health checks.

- **Before ANY GitHub/ADO operation:** read the matching `workflow/projects/<slug>.yaml` for valid field values + state mappings — **never hardcode field values**.
- Create issues through `github-projects-manager`, never raw `gh issue create`.
- After adding to a project: verify the item is actually on the board.
- Never set issues to "Done" directly — use "In Review" first, user confirms.

### Project Registry (CRITICAL)

Before creating issues, updating fields, or querying boards, **always** read the matching
project config from `workflow/projects/{slug}.yaml`. It defines:
- Valid field values (status, priority, type, size — with exact emoji prefixes)
- Governance level (`strict`/`standard`/`relaxed`) and per-rule overrides
- State mappings for tracker normalization
- Review comment templates

**Never hardcode field values.** Never guess emoji prefixes. The config is the source of
truth. (One instance of the general principle that CORE skills are config-driven — see
[`docs/extension-model.md` § Generic CORE Skills](docs/extension-model.md).) Template +
examples in `workflow/projects/_template.yaml` and `docs/examples/projects/` (operational,
technical, minimal, ADO).

### Commands

In Claude Code, each skill registers its own slash-command trigger via its `description:`
frontmatter — there are no separate files in `.claude/commands/`. Invoking the skill via the
`Skill` tool is equivalent to typing the slash-command. Other tools (Codex, Copilot, Gemini,
Cursor) load the skill from `skills/` directly.

| Command | Backing skill | Action |
|---------|---------------|--------|
| `/bridge-status` | `bridge-status` | Status dashboard: ecosystem, agents, work, remotes |
| `/bridge-explorer` | `bridge-explorer` | Ecosystem + repo-layout + constellation visualizations |
| `/briefing` | `briefing` | Daily briefing: board, git activity, goals, alerts |
| `/archive` | `archive` | Archive week + create summary |
| `/debrief` | `debrief` | Process transcripts: 7-category insights, tasks, protocols (full / `--quick` / `--all` / `--date`) |
| `/bridge-onboard` | `bridge-onboard` | New user setup or reconfiguration |
| `/channel` | `channel` | Channel management: list, health, deploy, start/stop |
| `/remote` | `remote` | Remote management: status, health, logs, restart, sync |
| `/schedule` | `schedule` | Scheduled tasks: list, create, deploy, disable |
| `/promote` | `bridge-promote` | Promote CORE changes upstream (scope:core → `bks-lab/open-bridge`, scope:org → your optional org overlay) |
| `/overlay` | `bridge-overlay` | Subscribe to org overlays + materialize scope:org content into the live tree (downstream inverse of `/promote`) |
| `/contribute` | `bridge-contribute` | Scan user branch for upstream-worthy contributions |
| `/calendar` | `calendar` | Calendar entries: list, add, cancel, confirm, show, status |
| `/mandants` | `mandants` | Mandant management: list, add, show, add-person |

---

## Remotes — Remote Machines

The user's physical and virtual machines live in **`infra/remotes/*.yaml`** — the single
source of truth for hardware inventory, network topology (Tailscale + LAN), SSH configs,
Wake-on-LAN, and per-box services. In Bridge context "remote" means **remote machine**, NOT
`git remote` — always check `infra/remotes/` first before asking "which PC?". Triggers: a
machine name, "my PC / my machines / fleet status", "wake / WoL", "ssh to / RDP to", "is
{name} online". The **`remote`** skill owns this directory and auto-loads on that vocabulary.
Schema in `infra/remotes/_template.yaml`; per-box setup notes in `<name>-setup.md`.

### Hard rules

- **Tailscale first**, LAN as fallback — LAN fails on VPN or foreign networks
- **No destructive operation** (shutdown, reboot, format) without per-action `[y]`
- **Never store credentials** in `infra/remotes/*.yaml` — KeyVault / 1Password URIs only
- **Honor `wake_on_lan.enabled: false`** — never force wake a machine that opted out
- **Deploy/bootstrap:** declared `status:` is never trusted, the remote's service manager is — [`rules/deploy-reconciliation.md`](rules/deploy-reconciliation.md) (launchd, systemd, watch-path)

---

## Channels — Messaging & Outbound Transports

Transport declarations live in **`infra/channels/*.yaml`** (iMessage, email, Telegram, news
digests, WhatsApp bots, …). Each channel's runtime usually sits on a remote as a
launchd/systemd unit or on-demand script. Trigger the `/channel` skill on "channel status /
health / deploy", "new channel for X", "set up bot", or any known channel name; delegate
scheduled messages to `/schedule`. **Deploy/status semantics:** declared `status:` is never
truth, the service manager is — [`rules/deploy-reconciliation.md`](rules/deploy-reconciliation.md).
Schema: `infra/channels/_template.yaml`; detail: [`docs/channels.md`](docs/channels.md).

---

## Visualization — Bridge Deck (optional)

Optional read-only pixel-art renderer of your Bridge (agents as walking sprites, calendar +
mandants tabs). Suggest it as a one-liner when the user asks to visualize their agents — do
NOT auto-install. Details: [`docs/bridge-deck.md`](docs/bridge-deck.md).

---

## Calendar + Mandants

Optional system for scheduled outbound (emails, iMessages, reports, digests) with recipient
attribution. Three layers: **Mandants** (`identity/mandants/<id>.yaml`) = recipient groups
(company / household / family / friends / colleagues / individual); **Calendar entries**
(`workflow/calendars/entries.yaml`) = what/whom/when with `delivery_at`,
`duration_estimate_min`, and an `origin` block; **Visualization** = bridge-deck Timeline
(read-only). Enable via `calendar.enabled: true` + `mandants.enabled: true`, then derive
files from the templates. Commands: `/calendar list|add|show|cancel|confirm|status`,
`/mandants list|add|show|add-person`.

**Key rules:** calendar/mandants files are read-only from bridge-deck. Calendar job IDs are
stable as `scheduled:calendar:${id}:slot-${N}`, never absolute timestamps.
`effective_at = delivery_at − duration_estimate_min`. Full docs:
[`docs/calendar.md`](docs/calendar.md), [`docs/mandants.md`](docs/mandants.md).

---

## Backups

Data model in **`infra/backups/topology.yaml`** (`sources` × `targets` × `pipelines`); state
(last_run, restic snapshot IDs) in `infra/backups/_state.yaml`, written only by the skill.
Topology is USER data. **Activated** simply by the file existing — no separate switch. CORE
ships the data model, not an executor: a topology-reader-plus-tool-dispatcher skill (your own
`backup` skill, or one distributed as a plugin) reads the topology and dispatches
`rclone-sync` / `rclone-copy` / `restic-backup` / `rsync-via-ssh`.

**Key rules:** `topology.yaml` is the truth — never hardcode paths (one instance of generic
CORE skills). `_state.yaml` is written only by the skill. Time-Machine pipelines
(`tool: time-machine`) are passive on macOS — the skill only documents intended state. Drift
surfaces as a briefing block, never a crash. Validation rules + target/actual comparison:
[`infra/backups/README.md`](infra/backups/README.md).

---

## Cloud Accounts & Secrets

Cloud-provider accounts and their secret stores live as inventory files in
**`identity/accounts/<provider>-<scope>.yaml`** — the single source of truth for tenant IDs,
subscriptions, vault names, resource-group maps, and bootstrap CLI sequences. Complex files
carry a `<id>.README.md` companion (decision matrix / setup recipes / rotation howto).

### Hard rules

- **Before any cloud op** (`az …`, `wrangler …`, `gcloud …`, `gh api …`, provider REST):
  read the matching `identity/accounts/<provider>-<tenant>.yaml` for tenant ID, subscription,
  vault names, and bootstrap snippet — never guess or reconstruct from memory.
- **No raw secret in YAML.** Only reference URIs (`azure-keyvault://…`, `keychain://…`,
  `1password://…`); real values live in the vault / keychain.

Full patterns (vocabulary triggers, per-provider recipes, tenant-switch and rotation
guidance): [`docs/cloud-accounts.md`](docs/cloud-accounts.md).

---

## Design System

`DESIGN.md` (repo root) is the open-bridge design-system manifest in
[Google Labs DESIGN.md alpha](https://github.com/google-labs-code/design.md) format —
token-level palette, typography, spacing, and component anatomy. **Read before generating
user-facing visuals:** skills that emit HTML, PDF, slides, certificates, dashboards, or
styled emails MUST pull colors/typography/spacing tokens from `DESIGN.md` instead of
inventing palettes (shipped consumers: `html-canvas`, `bridge-dashboard`). **Never
hand-pick brand colors** — if a token is missing, add it to `DESIGN.md` first (see § "Maintaining
this file"), then reference it.

---

## Variable Interpolation

`bridge-config.yaml` defines variables under the `identity:` config key. All YAML files under
the cluster wrappers (`identity/`, `infra/`, `workflow/`), plus `ecosystem.yaml`, can use
`${variable}`: `${projects_root}`, `${home}` (or `$HOME`), `${onedrive_root}`, and a leading
`~` → `$HOME`. Unknown variables → warning, file skipped.

> **Disambiguation:** `identity:` (config key in `bridge-config.yaml`) ≠ `identity/`
> (cluster-wrapper folder). Same word, different namespaces. Follow-up cleanup: rename the
> config key to `profile:` (see [Tier Model](#tier-model-two-pole--optional-org-overlay)).

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
