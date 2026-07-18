---
summary: "Directory structure: where everything lives, what format, what it does — the cluster-wrapper layout in prose (mirrors AGENTS.md)."
type: reference
last_updated: 2026-07-18
related:
  - AGENTS.md
  - docs/extension-model.md
---

# Bridge Directory Structure

Where everything lives, what format, what it does.

> **Operating truth:** [`AGENTS.md`](../AGENTS.md) section "Layout — Cluster-Wrappers" is the canonical source. This file mirrors that for human reading. Visualisation: [`docs/repo-layout/regions.yaml`](repo-layout/regions.yaml).

## Reading map — what to look at first

The top-level entry count looks heavy but collapses into a few groups, and a fresh
clone only needs the first one. (Three entries — `.agents/` `.claude/` `.github/` — are
standard tooling you ignore on sight; the three cluster-wrappers absorb ~13 config types
that would otherwise be flat top-level folders, so dissolving them would make the tree
*larger*, not smaller.)

1. **Start here** — `README.md` + `AGENTS.md`, the two onboarding seeds
   (`bridge-config.yaml.template`, `ecosystem.example.yaml`), and the full sample
   instance `examples/agency/`.
2. **Configuration — the 3 cluster-wrappers** (the anti-sprawl move): `identity/`
   (WHO am I, to WHOM), `infra/` (WHERE runs what), `workflow/` (WHAT happens when).
3. **Behaviour** — `skills/`, `rules/`, `protocols/`, `themes/`, `trackers/`.
4. **Documentation** — `docs/` (+ per-type config snippets in `docs/examples/`).
5. **Your workspace (USER)** — `work/`, `imports/` (ship empty, seed your own).
6. **Tooling & meta** (skip on first read) — `scripts/`, `bin/`, `.github/`,
   `.claude/`, `.agents/`.

The detailed per-path tables below are the reference; this map is the orientation.

## Top-level

```
bridge-config.yaml      USER     Main config (identity, theme, integrations)
ecosystem.yaml          USER     Repo registry (created at onboarding, gitignored)
bridge-deck.config.yaml USER     Daemon collectors for the pixel dashboard
AGENTS.md               CORE     Canonical operating manual (all agents)
CLAUDE.md               CORE     Thin Claude-Code wrapper — imports AGENTS.md
README.md               CORE     Pitch + architecture (for humans)
DESIGN.md               CORE     Design system manifest

identity/   infra/   workflow/   ← Cluster wrappers (see below)
.claude/    skills/    rules/    themes/    trackers/    docs/    scripts/    bin/
protocols/   work/    imports/    examples/   agents/
```

## Cluster wrappers — Default-to-folder

Every config type lives in **`<wrapper>/<types>/`** — a plural folder with templates, schemas and instances side by side. No flat configs, no promote mechanic, no thresholds.

### `identity/` — Who am I, to whom do I send

| Path | Layer | Purpose |
|------|-------|---------|
| `identity/personas/_template.yaml` | CORE | Persona template |
| `identity/personas/_schema.yaml` | CORE | Persona schema |
| `identity/personas/<id>.yaml` | USER | One self-identity (tax data, signatures) |
| `identity/accounts/_template.yaml` | CORE | Account template |
| `identity/accounts/<id>.yaml` | USER | One mail/calendar account |
| `identity/mandants/_template.yaml` | CORE | Mandant template |
| `identity/mandants/_schema.yaml` | CORE | Mandant schema |
| `identity/mandants/<id>.yaml` | USER | One recipient group |
| `identity/contracts/_template.yaml` | CORE | Contract template |
| `identity/contracts/_schema.yaml` | CORE | Contract schema |
| `identity/contracts/<id>.yaml` | USER | One recurring financial obligation (utility, telco, insurance, SaaS) |
| `identity/agent/_template.SOUL.md` | CORE | Orchestrator voice template |
| `identity/agent/_template.IDENTITY.md` | CORE | Orchestrator identity template |
| `identity/agent/_soul-deck.yaml` | CORE | Pickable principle library (onboarding) |
| `identity/agent/SOUL.md` | USER | Orchestrator voice (seeded at onboarding) |
| `identity/agent/IDENTITY.md` | USER | Orchestrator name/role/backstory (seeded) |

### `infra/` — Where does what run, how to reach it

| Path | Layer | Purpose |
|------|-------|---------|
| `infra/remotes/_template.yaml` | CORE | Remote template |
| `infra/remotes/<name>.yaml` | USER | One machine (SSH, network, WoL, capabilities) |
| `infra/remotes/<name>-setup.md` | USER | Setup notes (BIOS, provisioning) — companion |
| `infra/remotes/<name>/` | USER | Optional machine-specific sub-configs (scripts, launchd, …) |
| `infra/channels/_template.yaml` | CORE | Channel template |
| `infra/channels/<name>.yaml` | USER | One transport (iMessage, email, Telegram, …) |
| `infra/channels/bots/` | USER | Bot instances (sub-folder for complex bots) |
| `infra/instances/_template.yaml` | CORE | Instance template |
| `infra/instances/_schema.yaml` | CORE | Instance schema |
| `infra/instances/<slug>.yaml` | USER | One known Bridge instance (location, purpose, data/push policy) |
| `infra/backups/_template.yaml` | CORE | Backup template |
| `infra/backups/topology.yaml` | USER | Sources × targets × pipelines |
| `infra/backups/_state.yaml` | USER (written by skill) | Last-run state |
| `infra/backups/volumes/` | USER | Volume inventory |
| `infra/backups/launchd/` | USER | Scheduled-backup launchd plists |
| `infra/transcriptions/_template.yaml` | CORE | Transcription topology template |
| `infra/transcriptions/_schema.yaml` | CORE | Transcription topology schema |
| `infra/transcriptions/topology.yaml` | USER | Pipeline placement (mode local/remote, worker host) |

### `workflow/` — What happens when

| Path | Layer | Purpose |
|------|-------|---------|
| `workflow/calendars/_template.yaml` | CORE | Calendar template |
| `workflow/calendars/_schema.yaml` | CORE | Calendar schema |
| `workflow/calendars/entries.yaml` | USER | Master calendar (all scheduled outbound) |
| `workflow/contexts/_template.yaml` | CORE | Context template |
| `workflow/contexts/<id>.yaml` | USER | Context bundle (routing rules, persona refs) |
| `workflow/contexts/<id>.README.md` | USER | Optional: context maintenance doc (companion) |
| `workflow/projects/_template.yaml` | CORE | Project template |
| `workflow/projects/<slug>.yaml` | USER | GitHub/ADO project config (fields, governance, state mappings) |

## Top-level (own lifecycle, no cluster wrapper)

| Path | Layer | Purpose |
|------|-------|---------|
| `protocols/` | CORE | `standing-orders/` always-on rules (CORE defaults; user orders in `standing-orders/user/`) |
| `work/` | USER | Tasks + logs: `tasks/` (finite) · `streams/` (long-running) · `done/YYYY-MM/` · `templates/` (CORE seeds) · `_learning/` · `archive/` · `imports/` |
| `docs/` | CORE | Human-readable documentation, onboarding guides |
| `rules/` | **Tiered by folder** | Always-on rules. `rules/*.md` = core (ship to all) · `rules/org/**` = org (ship to org overlay) · `rules/user/**` = user (local only). The folder *is* the promote tier. `validate-bridge.py` checks each rule declares a valid `scope:` (presence + allowed value); folder↔scope consistency itself is an advisory `bridge-audit` check, not a hard gate. Each bridge layers its own under `rules/org/`+`rules/user/`. See [`rules/knowledge-growth.md`](../rules/knowledge-growth.md). |
| `themes/` | CORE | Vocabulary themes (`professional`, `professional-de`) |
| `trackers/` | CORE | Tracker-provider playbooks (`github.md`, `ado.md`) |
| `skills/` | CORE · `metadata.scope: core` (USER skills: `scope: user`; ORG: `scope: org`) | Skills with SKILL.md + references/. **Scope lives under `metadata:` (`metadata.scope`)** — skill-creator's validator only allows standard top-level keys; sub-agents keep top-level `scope:`. Hard-gated by `scripts/validate-skill-scope.py` (CI + pre-commit; regenerates the SKILL-SCOPE table in `AGENTS.md`). |
| `scripts/` | CORE (`scope: user/private` for USER tools) | Validators + build/state tools (`validate-bridge.py`, `validate-skill-scope.py`, `scaffold-user.sh`, …). |
| `bin/` | CORE | Post-clone bootstrap: `setup` (bash · macOS/Linux/WSL) + `setup.ps1` (Windows) — repair the skills discovery symlinks. |
| `imports/` | USER (scratch) | Generic drop-zone for external files (ephemeral, `/imports/*` gitignored except `.gitkeep`). The work-system-specific inbox is `work/imports/`. |
| `examples/` | CORE | Complete reference instance `agency/` (full clone-and-read sample) + `bridge-deck.config.yaml.template`. |
| `docs/examples/` | CORE | Per-type example snippets (`personas/`, `projects/`, `knowledge-repo/`) — distinct from the full instance under top-level `examples/`. |
| `agents/` | **Tiered by path** | Bridge-Agents — persistent, addressable A2A endpoints that front a persona to the outside world (the *outward* counterpart to the *inward* sub-agents below). `_runtime/` (engine), `_template/` (instance scaffold), `_gateway/` (MCP→A2A gateway), `tests/` = CORE; `agents/<name>/` (one instance per persona) = USER. Full guide: [`agents/README.md`](../agents/README.md), [`docs/representative-agent.md`](representative-agent.md). |
| `.claude/agents/` | CORE (with scope) | Native sub-agents |
| `.claude/skills/` | CORE (symlink → `../skills/`) | Discovery symlink so Claude Code finds skills (slash-command triggers live in each skill's `description`; there is no separate commands directory) |
| `.claude/hooks/` | CORE | Optional hook scripts |

## Discovery — how skills find all of this

Skills read `<wrapper>/<types>/*.yaml` directly. Reference implementation:

```python
def discover(type_singular: str, repo_root: Path | None = None) -> list[Path]:
    root = Path(repo_root or os.environ.get("BRIDGE_ROOT") or Path.cwd())
    for wrapper in ["identity", "infra", "workflow"]:
        folder = root / wrapper / f"{type_singular}s"
        if folder.is_dir():
            return sorted(f for f in folder.glob("*.yaml") if not f.name.startswith("_"))
    return []
```

`discover('mandant')` → `identity/mandants/*.yaml` (excluding `_`-prefixed). The folder always exists, even when empty. Full doc in [`rules/discovery.md`](../rules/discovery.md).

## Scope is structural

A file's tier is decided by **where it lives**, not by a tag you can forget. Three mechanisms:

1. **Whole folder** — the path *is* the tier. `work/`, `imports/` = USER; `docs/`, `themes/`, `trackers/`, `scripts/`, `bin/`, `examples/`, `protocols/standing-orders/*.md` = CORE.
2. **`_`-prefix** (cluster wrappers `identity/ infra/ workflow/`) — `_template.yaml`/`_schema.yaml` = CORE, every other instance `*.yaml` = USER.
3. **Frontmatter — skills only.** Skills are flat under `skills/`, so tier lives in `metadata.scope`, hard-gated by `scripts/validate-skill-scope.py`.

**Rules are tiered by folder:** `rules/*.md` = core · `rules/org/**` = org · `rules/user/**` = user. Each bridge layers its own under `rules/org/` + `rules/user/` — additive, like nested AGENTS.md.

**Onboarding** lays down the (empty) USER structure idempotently via `scripts/scaffold-user.sh`, so a fresh clone gets `work/`, `rules/user/`, the cluster-wrapper instance dirs etc. even when it shipped only CORE templates.

Protection (scrub, leak-check) is the **backstop**, not the primary guard — structure is what keeps PII/customer content out of the public OSS upstream.

## bridge-deck collectors

The daemon config (`bridge-deck.config.yaml`) references the layout directly:

```yaml
collectors:
  - package: "@bridge-deck/collector-channels"
    options:
      channelsPath: "~/Developer/<org>/<your-bridge>/infra/channels"

  - package: "@bridge-deck/collector-calendar"
    options:
      calendarPath: "~/Developer/<org>/<your-bridge>/workflow/calendars/entries.yaml"

  - package: "@bridge-deck/collector-mandants"
    options:
      mandantsPath: "~/Developer/<org>/<your-bridge>/identity/mandants"
```

Mandant files are PII — they are not pushed to the OSS upstream (blocked by the promote allow-list); the visualisation host receives them out-of-band via rsync.

## CORE / USER split

CORE paths (developed on `main`):
- `CLAUDE.md`, `README.md`, `AGENTS.md`, `DESIGN.md`
- `docs/`, `rules/*.md` (core), `themes/`, `trackers/`, `skills/` (scope: core), `scripts/` (tooling), `bin/` (bootstrap), `examples/` (reference instance)
- `.claude/agents/` (scope: core)
- Templates and schemas in every wrapper folder:
  - `identity/{personas,accounts,mandants}/{_template.yaml,_schema.yaml}`
  - `infra/{remotes,channels,backups,transcriptions}/{_template.yaml,_schema.yaml}`
  - `workflow/{calendars,contexts,projects}/{_template.yaml,_schema.yaml}`
- `protocols/standing-orders/*.md` (shipped always-on rules)
- `docs/examples/` (example configs for personas, projects)

USER paths (`user/{name}` branch):
- `bridge-config.yaml`, `bridge-deck.config.yaml`
- `identity/{personas,accounts,mandants}/<id>.yaml` (excluding templates/schemas)
- `infra/remotes/<name>.yaml + setup.md`, `infra/channels/<name>.yaml`,
  `infra/backups/topology.yaml + _state.yaml`, `infra/transcriptions/topology.yaml`
- `workflow/calendars/entries.yaml`, `workflow/contexts/<id>.yaml`,
  `workflow/projects/<slug>.yaml`
- `protocols/standing-orders/*.md` (own always-on rules)
- `work/`
- personal user-scope features (`scope: user`, never upstream) live in `rules/user/` + `work/streams/<stream>/` — such as a job-application pipeline
- `.claude/agents/<name>.md` (scope: org/user)

## gitignore policy

Personas, mandants, contexts and workflow data are USER-layer files. In OSS-public forks they are gitignored; in private downstream instances they may be tracked as offsite backup:

```
identity/personas/*.yaml             # USER PII
!identity/personas/_template.yaml    # CORE
!identity/personas/_schema.yaml      # CORE
!identity/personas/examples/*.yaml   # CORE examples (anonymised)

identity/mandants/*.yaml             # USER PII (recipient contacts)
!identity/mandants/_template.yaml    # CORE
!identity/mandants/_schema.yaml      # CORE

workflow/contexts/*.yaml             # USER PII (routing + persona refs)
workflow/contexts/*.md               # ditto
!workflow/contexts/_template.yaml    # CORE

infra/remotes/lab-device/{firmware,captures}/   # too large / sensitive
```

## Routing map (short)

Routing decisions ("input → destination") live per domain in exactly one path. **Standing orders are not routing sources.**

| Domain | Source of truth | Resolved by |
|---|---|---|
| Documents (PDFs, scans) | `workflow/contexts/doc-system.yaml` | `doc-system` skill |
| Mail attachments | same — `intake_sources.mail[]` inside | `doc-system` skill (mail-source pickers); dedicated `mail-attachment-processor` / `outlook-attachment-processor` skills are an org overlay (`scope: org`) |
| Outbound (calendar-driven) | `workflow/calendars/entries.yaml.recipients[]` | `calendar` skill |
| Recipients | `identity/mandants/<id>.yaml` | `/mandants`, calendar |
| Channels | `infra/channels/<name>.yaml` | `channel` (an `email-manager` is an org overlay, `scope: org`) |
| Persona destinations | `identity/personas/<id>.yaml.destinations` | referenced from context routing rules |
| Tracker / issues | `workflow/projects/<slug>.yaml` | `github-projects-manager` |

Full description with schema and examples: [`docs/extension-model.md` § Routing Map](extension-model.md#routing-map).
