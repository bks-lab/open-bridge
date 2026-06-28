---
summary: "Architecture Decision Record for skill distribution across the Bridge tier model — why open-bridge stays a framework repo and why an organization's overlay may add a plugin marketplace"
type: reference
last_updated: 2026-05-14
related:
  - extension-model.md
  - structure.md
---

# Skill Distribution Architecture

> ADR for the question: **where do skills physically live, how do they
> reach each developer's machine, how do we avoid duplicate maintenance?**

This document is a design pattern, not a prescription. It's written
because anyone forking open-bridge into an organizational overlay
(`<your-org>/<your-org>-bridge`) will hit the same question we did,
and the trade-off space is non-obvious.

## Context

The Bridge tier model (see `extension-model.md`)
separates concerns across three repositories:

| Repo | Role | Skills content |
|---|---|---|
| `open-bridge` | OSS framework | CORE skills (briefing, archive, bridge-*, …) |
| `<your-org>/<your-org>-bridge` | Org overlay | Org-specific skills + tools |
| `<your-username>/your-bridge` (or your personal seed) | Seed / single-edit-point | Everything (core + org + user) |

The question **where skills physically live** can't be answered from
the repo split alone — it depends on **how the skills are used**.

## Problem

Skills come in two semantic flavors with very different distribution
needs:

### Bridge-context-bound skills

`briefing`, `archive`, `bridge-status`, `calendar`, `channel`, `dashboard`,
`mandants`, `remote`, `schedule`, `debrief`, `doc-system`, and similar:

- Read Bridge state: `work/log.md`, `work/board.md`, `infra/*.yaml`,
  `workflow/*.yaml`, `identity/*.yaml`
- Write Bridge state: `work/log.md` entries,
  `work/_learning/proposals/`, audit logs
- Only meaningful to trigger when CWD = a Bridge instance

→ These skills **don't need** to be globally discoverable. A
clone-as-framework pattern (clone the repo, skills work inside the
repo's CWD) is sufficient.

### Standalone tool skills

Examples (illustrative, not exhaustive): a PDF generator with your
org's branding, a customer-specific log analyst, a Kibana dashboard
helper, an Outlook attachment processor, an Azure function provisioner,
a TTS-voice-clone delivery skill, an email composer with your house
style:

- Take input, produce output — no Bridge state dependency
- Don't need a Bridge to function
- Valuable in **any** context — especially in unrelated repos you happen
  to be working in (customer code, sister projects, scratch directories)

→ These skills **must** be globally discoverable. Repo-CWD-only
discovery is a limitation, not a feature.

## Options evaluated

### Option A — Symlink farm (rejected)

Migrate skills to `your-bridge/skills/`, create symlinks back to
`~/.claude/skills/`.

**Rejected because:**

- GitHub Issue #25367 (anthropics/claude-code): symlinked skill
  directories fail at init with `Error: Unknown skill` — validation
  doesn't resolve symlinks
- Duplicated in issues #14836 and #764
- Per-skill symlink workarounds fix it only partially
- Brittle: skills break if the repo is moved

### Option B — Frontmatter-only classification (interim default)

Skills stay physically where they are, get a `scope:` frontmatter tag
for classification. Physical migration deferred until a marketplace
backend is in place.

**Status:** workable interim. The promote/sync router (`/bridge-sync`,
`/bridge-promote`) already reads frontmatter `scope:` to decide
which upstream a skill belongs to.

### Option C — Pure plugin distribution (technically infeasible)

Distribute the entire Bridge as a Claude Code plugin — no
clone-as-framework anymore.

**Rejected because:**

- `CLAUDE.md` is framework-bound (declares the project to Claude), not
  packageable inside a plugin
- `work/log.md`, `work/board.md` are per-user runtime state, not plugin content
- Claude Code's plugin model doesn't support this

### Option D — Composition pattern (deferred)

Org overlay consumes `open-bridge` as a dependency rather than forking
it. Symmetric pattern, no drift, but two repos to clone per developer.

**Deferred:** attractive once open-bridge is public and OSS-community
PRs are flowing — composition reduces merge friction. At early-stage
overlay-team scale (few contributors, frequent edits), fork-plus-sync
is operationally simpler.

### Option E — Hybrid (Framework + Plugin) — **selected for the target architecture**

`open-bridge` stays a pure framework repo. The org overlay (`<your-org>-bridge`)
becomes **both**: a framework overlay (clone-as-instance) AND a Claude Code
Plugin Marketplace (distributes the standalone tool-skills).

## Decision

**Target architecture:**

```
open-bridge                         [framework only, no marketplace]
├── skills/                         ← CORE skills (Bridge-context-bound)
├── rules/, protocols/, docs/, CLAUDE.md
└── bin/setup                       ← symlinks .claude/skills/ → ../skills/

<your-org>/<your-org>-bridge        [framework + marketplace]
├── skills/                         ← org overlay skills (scope: org, tier: framework)
│   ├── bridge-dashboard/
│   ├── doc-system/
│   └── customer-a-coordinator/
├── plugins/
│   └── org-tools/                  ← plugin (scope: org, tier: plugin)
│       ├── .claude-plugin/plugin.json
│       └── skills/
│           ├── org-pdf-generator/
│           ├── org-news-generator/
│           └── ... (standalone tool skills)
├── .claude-plugin/
│   └── marketplace.json            ← registers org-tools as a plugin
└── bin/setup                       ← does both: symlink + plugin install

<your-username>/your-bridge          [seed, single-edit-point]
├── skills/                         ← all skills editable here
└── (everything else)
```

## Routing rules

`/bridge-sync` and `/bridge-promote` read frontmatter and route:

| Seed frontmatter | Routing destination |
|---|---|
| `scope: core` | `open-bridge/skills/<name>/` |
| `scope: org` + `tier: framework` | `<your-org>-bridge/skills/<name>/` |
| `scope: org` + `tier: plugin` | `<your-org>-bridge/plugins/org-tools/skills/<name>/` |
| `scope: user` | stays local in the seed |

## Consumption patterns on developer machines

### Org employee (default setup)

```bash
# One-time setup per machine
git clone <your-org>/<your-org>-bridge ~/Developer/<your-org>-bridge
cd ~/Developer/<your-org>-bridge && ./bin/setup
```

`bin/setup` does:

1. `.claude/skills → ../skills` symlink (Bridge overlay)
2. `~/.claude/plugins/known_marketplaces.json` entry for `<your-org>-bridge`
3. `claude /plugin install org-tools@<your-org>/<your-org>-bridge` (tool skills globally)

Result: all org skills available everywhere, plus the Bridge instance
when CWD is inside the `<your-org>-bridge` repo.

### OSS user (open-bridge only)

```bash
git clone https://github.com/bks-lab/open-bridge.git ~/Developer/open-bridge
cd ~/Developer/open-bridge && ./bin/setup
```

Result: CORE skills available inside the Bridge CWD. No plugin layer
needed because CORE skills have no standalone value (they read Bridge
state).

> This is read-only skills consumption — `origin` stays public open-bridge,
> and `bin/setup` arms the pre-push guard. To run your *own* instance with
> private data (personas, `work/` logs), follow the private-origin setup in
> the [README](../README.md#get-started), not a bare clone of this repo.

### Seed user (the contributor who edits skills)

```bash
# Seed is the edit point, not a consumption pattern.
# But: you can additionally install the org-tools plugin for global access.
/plugin marketplace add <your-org>/<your-org>-bridge
/plugin install org-tools@<your-org>/<your-org>-bridge
```

## Anti-patterns (do NOT do)

- ❌ Manually edit skills in the org overlay — always in the seed
- ❌ Maintain skills in two repos in parallel
- ❌ `~/.claude/skills/` as a hand-curated copy collection
- ❌ Symlink `~/.claude/skills/` onto skill directories (bug #25367)
- ❌ Distribute CORE skills as a plugin — no value, they're Bridge-bound

> Edit-the-seed and stay-generic are two faces of the same discipline: a CORE
> skill is config-driven and edited in one place. See [`extension-model.md` §
> Generic CORE Skills](extension-model.md).

## Migration phases

| Phase | What | Trigger |
|---|---|---|
| **Phase 1**: Frontmatter classification | Add `scope:` + `tier:` to every skill | Pre-overlay setup |
| **Phase 2**: Marketplace scaffold | Set up `<your-org>-bridge/plugins/<org-tools>/.claude-plugin/marketplace.json` | When you have ≥3 standalone tool-skills |
| **Phase 3**: Router extension | Teach `/bridge-sync` + `/bridge-promote` to route `tier: plugin` correctly | After Phase 2 |
| **Phase 4**: Composition evaluation | Consider switching org overlay from fork to dependency-consume of open-bridge | When OSS-community PRs flow on open-bridge |

Phase 1 alone gets you the routing semantics without the plugin
infrastructure. Phase 2+ are about making the standalone tool-skills
globally discoverable on every machine, not just inside a Bridge CWD.

## When you don't need this

If your overlay has **only** Bridge-context-bound skills (no standalone
tool skills), skip the plugin marketplace entirely. Option B
(frontmatter-only) + clone-as-framework gives you everything. The
marketplace step is purely about distributing standalone tool-skills
to non-Bridge CWDs.

## References

- [Claude Code Plugin Marketplaces documentation](https://code.claude.com/docs/en/plugin-marketplaces)
- Scott Spence — *Organising Claude Code Skills Into Plugin Marketplaces*
- Will Jackson — *Distributing Claude Code skills across a team*
- *How to Share Claude Code Skills With Your Team* (Agensi guide)
- GitHub Issue #25367 — Symlinked skills fail validation (anthropics/claude-code)
- GitHub Issue #14836 — `/skills` doesn't find symlinked directories
- GitHub Issue #764 — Symlink resolution bug
- Aayush Ostwal — *Scaling Claude Code across 100+ Repos*
- Karun Ramakrishna — *Multi-Repo Workspaces*
- `runkids/skillshare` CLI — Cross-tool skill distribution
