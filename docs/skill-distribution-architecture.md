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

- **It shadows every other instance** — the user level overrides the
  project level, so pointing `~/.claude/skills` at one Bridge's `skills/`
  silently overrides every *other* instance's own copies of the same
  names. This is the load-bearing reason and it does not expire; see
  [§ Why the user level is not a distribution channel](#why-the-user-level-is-not-a-distribution-channel).
- GitHub Issue #25367 (anthropics/claude-code): symlinked skill
  directories fail at init with `Error: Unknown skill` — validation
  doesn't resolve symlinks
- Duplicated in issues #14836 and #764
- Per-skill symlink workarounds fix it only partially
- Brittle: skills break if the repo is moved

> The symlink bugs are the *weaker* argument: they are upstream defects that
> may be fixed, and in practice the link often works. The shadowing is
> architectural — it follows from documented precedence and would survive
> every one of those bugs being closed. Reject Option A on the shadowing,
> not on the bug number.

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
- ❌ **Point `~/.claude/skills/` at a Bridge repo's `skills/`** (whole-directory
  symlink) — it silently overrides every other instance's own skills; see below
- ❌ Hardcode `~/.claude/skills/<name>/…` as a *filesystem path* in a script or
  launchd/systemd unit — resolve the instance's `skills/` directly instead
- ❌ Distribute CORE skills as a plugin — no value, they're Bridge-bound

> Edit-the-seed and stay-generic are two faces of the same discipline: a CORE
> skill is config-driven and edited in one place. See [`extension-model.md` §
> Generic CORE Skills](extension-model.md).

## Why the user level is not a distribution channel

The tempting shortcut, when the first Bridge is the only Bridge, is to point
the user level at it so its skills work in any directory:

```bash
ln -s ~/Developer/my-bridge/skills ~/.claude/skills   # do NOT do this
```

With one instance this is harmless and it appears to work. It becomes a trap
the moment a **second** instance exists — which `docs/multi-instance.md`
actively encourages for isolation between organizations.

**Precedence is documented and unconditional:**

> "When skills share the same name across levels, enterprise overrides personal,
> and personal overrides project."
> — [Claude Code skills documentation](https://code.claude.com/docs/en/skills.md)

Every Bridge ships the same CORE skill *names*. So instance A's copies win
inside instance B's sessions, and there is no lever to invert it — no
precedence switch, no custom skills path, no env var. `skillOverrides` keys on
the skill **name**, not a path: it can hide a name, not redirect it to a
location. A Bridge cannot defend its own skills; the only fix is to keep
colliding names out of the user level.

The failure is **silent by construction**: the shadowed instance produces
plausible output from the wrong instance's skills. There is no error to search
for. Observed consequences on a real two-instance setup:

- CORE fixes authored *in* the shadowed instance had no effect there.
- Its onboarding ran the *other* instance's wizard.
- `scope: org` skills — carrying one organization's customer names in their
  `description:` triggers — loaded into every session of an unrelated
  organization's instance.

That last point is the sharp one. `multi-instance.md` promises isolation
between organizations, and the **data** isolation holds perfectly throughout.
The **capability** isolation never existed. They are two different guarantees
and only one of them is implemented by the repo split.

### The rule

> `~/.claude/skills` must not point at a Bridge repo. Skills in a Bridge
> instance belong to **that instance**; the user level is for skills that
> belong to the **machine**.

A Bridge instance needs no user-level pointer at all: the committed
`.claude/skills → ../skills` symlink already makes its skills load whenever
the CWD is inside it. That is the entire supported mechanism.

### What to do instead

| You want | Do this |
|---|---|
| An instance's skills, inside that instance | Nothing — `.claude/skills → ../skills` already ships |
| A standalone tool skill in *any* directory | Distribute it as a **plugin** (Option E), not a symlink |
| A skill that belongs to the machine, not to any instance | Keep it as a real directory under `~/.claude/skills/`, owned by no repo |

The `scope:` frontmatter already tells you which is which: anything an instance
*ships* (`core`, `org`) belongs to that instance and must not reach the user
level. A skill no instance ships has no name to collide with.

### The second job of that path

Before removing an existing pointer, check what **resolves** it. The user-level
path frequently acquires a second, undocumented role: a stable filesystem path
that scripts hardcode.

```bash
find -L ~/bin ~/Library/LaunchAgents "$HOME/Library/Application Support" \
        /Library/LaunchAgents /etc/systemd -type f 2>/dev/null \
  | xargs grep -l '\.claude/skills/' 2>/dev/null
```

**Use `find -L`, not `grep -r`.** `grep -r` does not follow symlinks during its
descent (and `grep -R` did not either, where this was measured), while scheduler
units are routinely symlinks into a state dir. Measured on a real host: `grep -r`
reported **4** consumers where **13** existed — an inventory that says "safe to
remove" while nine live units hang off the pointer. Search the state dir too, not
just the symlink farm.

Discovery and path-resolution are two different consumers of one symlink.
Removing it fixes the first and silently breaks the second — a scheduled job
that can no longer resolve its helper fails with an exit code, not a symptom
anyone reads. Repoint the **live** consumers at the instance's `skills/`
directory first, then remove the link.

Check each reference actually resolves before treating it as a blocker: one that
points at a renamed or deleted skill is already broken and stays broken either
way. Counting those as consumers turns the safety step into a deterrent against
the fix — the user goes hunting for a repoint target that does not exist, or
keeps the pointer. `/bridge-audit --check skill-shadowing` reports live and dead
separately for this reason.

Remove the link itself with `mv` (or `rm`), never with a trash utility that
dereferences symlinks — following the link would move the instance's entire
tracked `skills/` tree, not the pointer.

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
