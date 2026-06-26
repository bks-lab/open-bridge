---
summary: "Extension model: how CORE platform and USER extensions relate, plus the canonical Routing Map (where each routing domain lives in C-prime)"
type: guide
last_updated: 2026-05-02
related:
  - CLAUDE.md
  - docs/structure.md
  - docs/repo-layout.md
---

# Bridge Extension Model

The Bridge has two layers: a **CORE platform** (generic, on `main`)
and **USER extensions** (org-specific, on `user/*` branches). This document
formalizes that split, names where each routing domain lives, and prepares
for future Plugin extraction.

## Option C — Current Model (USER Branch = Extension)

Everything on your `user/{name}` branch that is NOT on `main` IS
your extension. This is the working model.

### What lives where

| Layer | Branch | Purpose | Example |
|-------|--------|---------|---------|
| **CORE** | `main` | Generic platform, shareable | Skills, templates, schemas, examples, docs |
| **Extension** | `user/{name}` | Org-specific configs, agents, data | Project configs, contexts, personas, coordinator |

### Extension inventory (Org, post-C-prime)

| Category | Path | Scope | What it contains |
|----------|------|-------|------------------|
| **Project Configs** | `workflow/projects/<slug>.yaml` | USER · promote-on-demand | Tracker project configs (GitHub Projects V2 / ADO Boards) — field values, governance, health checks |
| **Sub-Agents** | `.claude/agents/customer-a-*.md`, `network-reconcile.md` | `scope: org` | CustomerA engagement specialists |
| **Coordinator Skill** | `skills/customer-a-coordinator/` | `scope: org` | End-to-end orchestrator with references + playbooks + domain knowledge |
| **Doc System** | `skills/doc-system/` | `scope: core` | Generic document-intake skill — reads `workflow/contexts/doc-system.yaml` (the context file stays `scope: org`) and runs the document-intake flow |
| **Routing Contexts** | `workflow/contexts/<id>.yaml` | USER (gitignored — PII) | Per-domain routing rules (see [Routing Map](#routing-map) below) |
| **Personas** | `identity/personas/<id>.yaml` | USER (gitignored — PII) | Self-identities (tax data, signatures, destination paths) |
| **Mandants** | `identity/mandants/<id>.yaml` | USER (gitignored — PII) | Recipient groups for outbound messages |
| **Calendar** | `workflow/calendars/entries.yaml` | USER | Scheduled outbound actions with recipient refs |
| **Rules** | `rules/*.md` (core), `rules/org/**` (org), `rules/user/**` (user) | tiered by FOLDER | Operating rules tiered by folder — top-level `rules/*.md` is `scope: core`, `rules/org/**` is `scope: org`, `rules/user/**` is `scope: user` (personal rules, e.g. for a private pipeline) |
| **Standing Orders** | `protocols/standing-orders/<name>.md` (CORE defaults), `standing-orders/user/<name>.md` (USER) | CORE / USER · cross-cutting | Always-on advisory/blocking rules (NOT routing — see [Routing Map](#routing-map)) |
| **Remotes** | `infra/remotes/<name>.yaml` (+`-setup.md`) | USER (PII clean) | Machine inventory + Wake-on-LAN + SSH config |
| **Channels** | `infra/channels/<name>.yaml` | USER | Outbound transport definitions |
| **Backups** | `infra/backups/topology.yaml` + `_state.yaml` | USER | Source × Target × Pipeline topology |
| **Work** | `work/` | USER | Logs, board, active/ongoing/done tasks |
| **Config** | `bridge-config.yaml` | USER · gitignored | Theme, language, features, identity-block, integrations |
| **Bridge-Deck Config** | `bridge-deck.config.yaml` | USER | Daemon collector paths for the Pixel-Art Visualizer |
| **Ecosystem** | `ecosystem.yaml` | **USER** | Repo registry — created at onboarding, gitignored (absent on a fresh clone) |

### How it works today

1. Clone open-bridge → get CORE platform on `main` (templates, schemas, skills — you create `ecosystem.yaml` at onboarding)
2. Create `user/{name}` branch → start your extension
3. Run `/bridge-onboard` → creates `bridge-config.yaml`, work system, optionally first persona/mandant/context from templates
4. Add project configs, sub-agents, contexts as needed
5. `git merge main` → pull CORE updates without conflicts (paths don't overlap by design — see CLAUDE.md "Git & Branches")

### Sharing within a team

For a colleague to pick up Org extension content:

1. Clone open-bridge
2. `git checkout -b user/their-name` from `main`
3. Cherry-pick or copy specific files from `user/user`:
   - `workflow/projects/<slug>.yaml` (Org project configs)
   - `.claude/agents/customer-a-*.md`, `.claude/agents/network-reconcile.md` (CustomerA sub-agents, `scope: org`)
   - `skills/customer-a-coordinator/` (Org-scoped skill)
   - Cross-cutting standing orders that apply (e.g. `code-standards.md`, `security-baseline.md`, `document-work.md`)
4. Create their own `bridge-config.yaml` (gitignored) and persona/mandant/context files

Personas, mandants, contexts, calendar entries are **NEVER** shared cross-user (PII-by-construction).

---

## Routing Map

The Bridge has multiple **routing domains** — distinct kinds of "input → destination" decisions.
Each lives in exactly one place. **No routing belongs in `protocols/standing-orders/`** —
those are cross-cutting always-on rules, not routing.

### Per-domain routing table

| Routing domain | Source of truth | Schema / pattern | Resolved by |
|---|---|---|---|
| **Documents** (PDFs, scans, downloads) | `workflow/contexts/doc-system.yaml` | `sources[]`, `areas{}`, `rules[]` with `when:` predicates and `route:` targets | `doc-system` skill at `/doc-inbox` |
| **Mail attachments** | same — `workflow/contexts/doc-system.yaml`, `intake_sources.mail[]` | account-references plus the same routing rules | `doc-system` skill (mail-source pickers); an org overlay can add dedicated `mail-attachment-processor` / `outlook-attachment-processor` skills (`scope: org`) |
| **Outbound messages** (calendar-driven) | `workflow/calendars/entries.yaml` `recipients[]` | each entry references `mandant/person` pairs | `calendar` skill, `bridge-deck` Calendar tab |
| **Recipient groups** (who to address) | `identity/mandants/<id>.yaml` | `persons[]` with channels per person | `/mandants`, calendar entries, message composers |
| **Channel selection** (which transport) | `infra/channels/<name>.yaml` | `type`, `runtime.host`, credentials-ref | `channel` skill (an org overlay can add transport-specific skills such as an `email-manager`, `scope: org`) |
| **Persona destinations** (filing paths per identity) | `identity/personas/<id>.yaml.destinations` | key→path map, variable-interpolated | referenced by name from context routing rules |
| **Tracker / Issue dispatch** | `workflow/projects/<slug>.yaml` | field values, governance rules, state mappings | `github-projects-manager`, `project-advisor` |
| **Sub-repo / context tagging** | `skills/org-context/SKILL.md` (org overlay) | tag-table | `org-context` skill — an org-overlay addition (`scope: org`), always-active when present, not shipped in open-bridge |
| **Cross-cutting always-on rules** *(not routing — listed here for contrast)* | `protocols/standing-orders/<name>.md` | scope: always, enforcement: advisory/blocking | session-start of every Bridge session |

### Routing-context naming convention

`workflow/contexts/<domain>.yaml` — one file per routing domain.

Examples (existing or plausible):
- `context.doc-system.yaml` — document filing (active)
- `context.invoices.yaml` — invoice generation/filing (future)
- `context.contracts.yaml` — contract handling (future)
- `context.mail-triage.yaml` — incoming-mail classification (future)

The contract:
- `persona_ref: <id>` — which identity this routing operates under
- `sources[]` — where input arrives (filesystem paths, mail accounts, ...)
- `rules[]` — `when: { ... }` predicates → `route: { target: <destination-key> }`
- `areas{}` — destination tree structure (path + per-area metadata)
- destination-key resolution: first the context's own `destinations:` block, then fallback to `personas/<persona_ref>.yaml.destinations`

### Sub-routing companion files

Inside the destination tree, an `_INFO.md` per area can carry human-friendly notes
(history, edge cases, area conventions). The hard rule:

> Conflict between `workflow/contexts/<id>.yaml` and a destination-tree `_INFO.md` —
> **the YAML wins.** `_INFO.md` is supplementary doc, not routing source.

This is the same "machine-readable wins, human notes annotate" principle as
`infra/remotes/<name>.yaml` vs `infra/remotes/<name>-setup.md`.

### Why standing-orders are NOT routing

Standing orders solve a different problem: **always-on rules that govern Claude's
behavior across all sessions.** They have no `route:` field. Examples:

- `code-standards.md` — code quality guidelines (advisory)
- `document-work.md` — log all significant actions to work log (blocking)
- `work-board-reconciliation.md` — folder ↔ board coherence check (advisory)
- `security-baseline.md` — security practices (advisory)

If you find yourself wanting to put `route: <X>` into a standing order, you want
a routing context, not a standing order. Create `workflow/contexts/<your-domain>.yaml`.

---

## Downstream materialization (org overlays)

The extension inventory above is the **publish** side: `/promote` reads each
file's tier from where it lives ([`scripts/categorize-commits.py`](../scripts/categorize-commits.py))
and routes `scope:org` content up to your org overlay, `scope:core` to
open-bridge, `scope:user` nowhere. **Org overlays are the downstream inverse**:
they answer how a teammate's *fresh* clone gets that `scope:org` content back —
without cloning the whole seed and without the org content ever leaking into the
OSS CORE.

The `/overlay` skill (`bridge-overlay`, engine [`scripts/overlay.py`](../scripts/overlay.py))
subscribes a consumer Bridge to one or more overlay repos and **materializes**
their files into the live tree as tracked copies, each pinned to an immutable
git SHA. Subscription state lives in two USER-tier root files — a generated
`overlays.lock.yaml` (per-file source/materialized hashes, the drift detector)
and a sparse `.bridge/` cache — both gitignored in a public fork. Each
subscription is a `role: org-overlay` entry in `bridge-config.yaml.upstreams[]`
carrying its own `materialize:` block; an instance opts in via
`infra/instances/<slug>.yaml` `subscribes_overlays:`. The same classifier and
scope tripwire run in both directions, so a file `/promote` routes to the org
overlay is exactly the file `/overlay` pulls back — and exactly the file both
refuse to let reach open-bridge. Full guide:
[`docs/org-overlays.md`](org-overlays.md).

---

## Option B — Future Plugin Extraction

When the Org extension needs to be shared as a proper package, extract it
into a **Claude Code Plugin** at `<your-org>/bridge-org-extension`.

### Plugin structure (C-prime aligned)

```
bridge-org-extension/
├── plugin.json                          # Claude Code plugin manifest
├── README.md                            # What this extension adds
│
├── .claude/
│   └── agents/                          # Sub-agents (scope: org)
│       ├── customer-a-log-analyst.md
│       ├── customer-a-incident-handler.md
│       ├── customer-a-deployment-verifier.md
│       └── network-reconcile.md
│
├── skills/                              # Org-specific skills (scope: org)
│   └── customer-a-coordinator/           # SKILL.md + references/ + playbooks/
│   # (doc-system/ is scope: core — ships in the base bridge, not this extension)
│
├── workflow/                            # Routing + project configs (templates)
│   ├── project.customer-a.yaml.template
│   ├── project.org-ops.yaml.template
│   ├── context.doc-system.yaml.template
│   └── ...
│
└── protocols/
    └── standing-orders/                 # ONLY cross-cutting always-on rules
        ├── code-standards.md
        └── security-baseline.md
        # (No routing-*.md — routing lives in workflow/contexts/<id>.yaml)
```

### plugin.json

```json
{
  "name": "bridge-org-extension",
  "version": "1.0.0",
  "description": "Org overlay for open-bridge — a customer coordinator, project configs, doc-system",
  "author": "<your-org>",
  "requires": {
    "open-bridge": ">=1.0.0"
  },
  "install": {
    "copy": [
      { "from": ".claude/agents/", "to": ".claude/agents/", "merge": true },
      { "from": "skills/", "to": "skills/", "merge": true },
      { "from": "workflow/", "to": "workflow/", "merge": true, "rename": { ".template": "" } },
      { "from": "protocols/standing-orders/", "to": "protocols/standing-orders/", "merge": true }
    ]
  }
}
```

### Extraction checklist

When ready to extract from USER branch to Plugin:

- [ ] Copy `.claude/agents/customer-a-*.md` + `network-reconcile.md` (all `scope: org`)
- [ ] Copy `skills/` entries with `scope: org` (customer-a-coordinator)
- [ ] Copy `workflow/projects/<slug>.yaml` (the Org project configs)
- [ ] Sanitize `workflow/contexts/doc-system.yaml` → `.template` (strip personal paths, keep schema)
- [ ] Copy cross-cutting standing orders (`code-standards`, `security-baseline`, `document-work`, etc.) — NOT routing
- [ ] Create `plugin.json` manifest
- [ ] Neutralize absolute paths (use `${CLAUDE_PLUGIN_ROOT}` + `${onedrive_root}` for script refs)
- [ ] Run `rules/promote-safety.md` scan on all files (no secrets, no PII)
- [ ] Test: fresh bridge clone + plugin install + `/bridge-onboard` → working system

### What stays on USER branch (never in plugin)

- `bridge-config.yaml` — personal identity, theme, language (gitignored anyway)
- `identity/personas/<id>.yaml` — tax data, signatures (gitignored)
- `identity/mandants/<id>.yaml` — recipient PII (gitignored)
- `workflow/contexts/<id>.yaml` — concrete routing instances (gitignored — uses real paths)
- `workflow/calendars/entries.yaml` — concrete schedule
- `infra/remotes/<name>.yaml` — personal machine inventory
- `infra/channels/<name>.yaml` — personal messaging configs
- `infra/backups/topology.yaml` — personal backup pipelines
- `work/` — personal work log and tasks

### Installation flow (future)

```bash
# From a fresh bridge clone:
cd open-bridge
git checkout -b user/alice

# Install Org extension:
claude plugins add <your-org>/bridge-org-extension

# Run onboard:
# /bridge-onboard detects context.doc-system.yaml.template, offers to instantiate
# /bridge-onboard detects customer-a-coordinator skill, registers it
```

---

## Extension Design Principles

1. **CORE is self-sufficient** — the bridge works without any extension
2. **Extensions are additive** — they add templates, configs, scripts but never modify CORE files
3. **No secrets in extensions** — credentials stay in KeyVault/1Password, extensions reference them by name
4. **Routing lives in `workflow/contexts/<id>.yaml`** — never in standing-orders, never hardcoded in skills (one instance of principle 8 / § Generic CORE Skills)
5. **Persona destinations are key→path maps** — referenced by name from routing rules, swappable per persona
6. **Project configs are the contract** — `workflow/projects/<slug>.yaml` defines tracker field values and governance
7. **Standing orders are always-on rules** — they govern Claude's behavior, not where things go
8. **CORE skills are config-driven** — a `scope: core` skill stays generic; instance-specific configuration *and* workflow live in USER/config files (`bridge-config.yaml`, `workflow/`, `infra/`, `identity/`, state/snapshots). Skills read config; they never embed instance logic, hardcoded queries, org/project IDs, personas, or thresholds. See § Generic CORE Skills below.

---

## Generic CORE Skills — the one "never hardcode" principle

Principles 4, 6, and 8 are the same rule from three angles: **a CORE file or
skill carries the generic mechanism; the instance carries the data.** The repo
states this per domain in several places — these are all instances of this
single principle, not separate rules:

| Domain | Per-domain statement | Stated in |
|---|---|---|
| Tracker fields | `workflow/projects/<slug>.yaml` is the contract — never hardcode field values | `AGENTS.md` § Project Registry, `rules/knowledge-growth.md` |
| Routing | routing lives in `workflow/contexts/<id>.yaml` — never hardcoded in skills | principle 4 above |
| Backups | `topology.yaml` is the truth — never hardcode paths | `CLAUDE.md` § Backups, `infra/backups/README.md` |
| Tracker queries | briefing reads `integrations.{name}.*` from `bridge-config.yaml` — not hardcoded | `skills/briefing/` |
| Skill edits | edit the seed skill, never a downstream overlay copy | `docs/skill-distribution-architecture.md` |

**Why it's load-bearing:** a `scope: core` skill is shipped and merged
upstream. The moment instance logic — an ADO pipeline ID, a customer query, a
persona, a render block — lands inside `SKILL.md` or `references/`, the skill
stops being generic: it breaks upstream-mergeability and leaks instance shape
into OSS CORE. The fix is always the same — move the data to
`bridge-config.yaml` (or the matching `workflow/` / `infra/` / `identity/`
file) and have the skill read it. If no config key exists yet, add the key plus
a template default first, then read it.

**The test before adding anything to a CORE skill:** *would this line be wrong
in someone else's Bridge?* If yes, it is instance config, not skill content —
it belongs in `bridge-config.yaml` / a USER file, and the skill reads it.

Operating-manual summary (auto-loaded at session start): [`CLAUDE.md` §
Generic CORE Skills](../CLAUDE.md).

---

## Related

- [`docs/structure.md`](structure.md) — full C-prime layout (cluster-wrappers + Default-to-Folder)
- [`docs/personas.md`](personas.md) — persona schema + multi-persona patterns
- [`docs/mandants.md`](mandants.md) — mandant schema + recipient groups
- [`docs/calendar.md`](calendar.md) — calendar entries + scheduling
- [`CLAUDE.md` → Layout](../CLAUDE.md) — canonical CORE/USER table
