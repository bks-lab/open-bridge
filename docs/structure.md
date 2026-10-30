---
summary: "Directory structure: where everything lives, what format, what it does — the cluster-wrapper layout in prose (mirrors AGENTS.md)."
type: reference
last_updated: 2026-10-24
related:
  - AGENTS.md
  - docs/extension-model.md
---

# Bridge Directory Structure

Where everything lives, what format, what it does.

> **Operating truth:** [`AGENTS.md`](../AGENTS.md) section "Layout — Cluster-Wrappers" is the canonical source. This file mirrors that for human reading. Visualisation: [`docs/repo-layout/regions.yaml`](repo-layout/regions.yaml).

## Reading map — what to look at first

The top-level entry count looks heavy but collapses into a few groups, and a fresh
clone only needs the first one. (Five entries, `.agents/` `.claude/` `.codex/` `.github/` `.vibe/`, are
standard tooling you ignore on sight; the three cluster-wrappers absorb ~13 config types
that would otherwise be flat top-level folders, so dissolving them would make the tree
*larger*, not smaller.)

1. **Start here** — `README.md` + `AGENTS.md`, the two onboarding seeds
   (`bridge-config.yaml.template`, `ecosystem.example.yaml`), and the two full
   sample instances `examples/agency/` (a two-client agency) and
   `examples/portfolio/` (one person with several hats).
2. **Configuration — the 3 cluster-wrappers** (the anti-sprawl move): `identity/`
   (WHO am I, to WHOM), `infra/` (WHERE runs what), `workflow/` (WHAT happens when).
3. **Behaviour** — `skills/`, `rules/`, `protocols/`, `themes/`, `trackers/`.
4. **Documentation** — `docs/` (+ per-type config snippets in `docs/examples/`).
5. **Your workspace (USER)** — `work/`, `imports/` (ship empty, seed your own).
6. **Tooling & meta** (skip on first read): `scripts/`, `bin/`, `.github/`,
   `.claude/`, `.agents/`, `.codex/`, `.vibe/`.

The detailed per-path tables below are the reference; this map is the orientation.

## Top-level

```
bridge-config.yaml      USER     Main config (identity, theme, integrations)
ecosystem.yaml          USER     Repo registry, instance base (created at onboarding; tracked on a private origin, kept out of git otherwise, see § gitignore policy). Never promoted: an org overlay shares its own ecosystem.<org>.yaml
bridge-deck.config.yaml USER     Daemon collectors for the pixel dashboard
AGENTS.md               CORE     Canonical operating manual (all agents)
GEMINI.md               CORE     Thin pointer to AGENTS.md
CLAUDE.md               USER     Legacy entry, never shipped: when present Claude Code loads only it (scripts/migrate-entry-file.py)
README.md               CORE     Pitch + architecture (for humans)
DESIGN.md               CORE     Default design, and the index to identity/designs/

identity/   infra/   workflow/   ← Cluster wrappers (see below)
.claude/    skills/    rules/    themes/    trackers/    docs/    scripts/    bin/
protocols/   work/    imports/    examples/   agents/   mods/
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
| `identity/mail-footers/_template.yaml` | CORE | Mail footer template |
| `identity/mail-footers/_schema.yaml` | CORE | Mail footer schema |
| `identity/mail-footers/<id>.yaml` | USER | One way of signing a mail (org when an overlay ships a team footer) |
| `identity/contracts/_template.yaml` | CORE | Contract template |
| `identity/contracts/_schema.yaml` | CORE | Contract schema |
| `identity/contracts/<id>.yaml` | USER | One recurring financial obligation (utility, telco, insurance, SaaS) |
| `identity/vehicles/_template.yaml` | CORE | Vehicle template |
| `identity/vehicles/_schema.yaml` | CORE | Vehicle schema |
| `identity/vehicles/<id>.yaml` | USER | One owned/leased vehicle — tax classification plus pointers to its telemetry, receipts, logbook and contracts |
| `identity/designs/_template.md` | CORE | Design template (DESIGN.md format plus `scope`, `use_for`, `source`) |
| `identity/designs/_schema.yaml` | CORE | Design front-matter schema |
| `identity/designs/<id>.md` | USER | One brand a generated visual can wear, routed by its own `scope:` (org when an overlay ships the organisation's brand); `scripts/designs.py` resolves which one applies |
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
| `infra/secret-stores/_template.yaml` | CORE | Secret-store template |
| `infra/secret-stores/_schema.yaml` | CORE | Secret-store schema |
| `infra/secret-stores/<slug>.yaml` | USER | One store: where it is, who reaches it, which kind of secret belongs in it |
| `infra/object-stores/_template.yaml` | CORE | Object-store template |
| `infra/object-stores/_schema.yaml` | CORE | Object-store schema, and the source of the object reference grammar |
| `infra/object-stores/_tests/**` | CORE | The schema's controls and their mutation battery |
| `infra/object-stores/<slug>.yaml` | USER | One store: where it is, who reaches it, which class of content belongs in it |
| `infra/a2a-peers/_template.yaml` | CORE | A2A peer template |
| `infra/a2a-peers/_schema.yaml` | CORE | A2A peer schema |
| `infra/a2a-peers/<name>.yaml` | USER | One peer: card URL, auth, token reference (org when an overlay ships it) |
| `infra/transcriptions/_template.yaml` | CORE | Transcription topology template |
| `infra/transcriptions/_schema.yaml` | CORE | Transcription topology schema |
| `infra/transcriptions/topology.yaml` | USER | Pipeline placement (mode local/remote, worker host) |
| `infra/utilities/_template.yaml` | CORE | Utility template |
| `infra/utilities/<id>.yaml` | USER | One supply contract at a location (power, gas, water, heat): meter, readings, instalment |

### `workflow/` — What happens when

| Path | Layer | Purpose |
|------|-------|---------|
| `workflow/briefings/_schema.yaml` | CORE | Briefing profile schema |
| `workflow/briefings/_template.yaml` | CORE | Briefing profile template |
| `workflow/briefings/<id>.yaml` | USER | One briefing: ordered sections, tracker queries, inbox rules (org when an overlay ships it) |
| `workflow/mail-profiles/_schema.yaml` | CORE | Mail profile schema |
| `workflow/mail-profiles/_template.yaml` | CORE | Mail profile template |
| `workflow/mail-profiles/<id>.yaml` | USER | One occasion for mail: footer, theme, greeting, attachments, who it applies to (org when an overlay ships it) |
| `workflow/calendars/_template.yaml` | CORE | Calendar template |
| `workflow/calendars/_schema.yaml` | CORE | Calendar schema |
| `workflow/calendars/entries.yaml` | USER | Master calendar (all scheduled outbound) |
| `workflow/meetings/_schema.yaml` | CORE | Meeting series schema |
| `workflow/meetings/_template.yaml` | CORE | Meeting series template |
| `workflow/meetings/<id>.yaml` | USER | One recurring series: folder match, follow-up skill, wiki protocol target |
| `workflow/contexts/_template.yaml` | CORE | Context template |
| `workflow/contexts/<id>.yaml` | USER | Context bundle (routing rules, persona refs) |
| `workflow/contexts/<id>.README.md` | USER | Optional: context maintenance doc (companion) |
| `workflow/projects/_template.yaml` | CORE | Project template |
| `workflow/workloads/_schema.yaml` | CORE | Workload contract (one declared run on one machine) |
| `workflow/workloads/_template.yaml` | CORE | Workload template |
| `workflow/workloads/_tests/**` | CORE | The contract's own regression suite (see docs/workloads.md) |
| `workflow/workloads/<id>.yaml` | USER | One declared run: host, kind, runtime, owner, schedule, command |
| `workflow/projects/<slug>.yaml` | USER | GitHub/ADO project config (fields, governance, state mappings) |
| `workflow/ai-services/_schema.yaml` | CORE | AI service schema |
| `workflow/ai-services/_template.yaml` | CORE | AI service template |
| `workflow/ai-services/<id>.yaml` | USER | Which AI model one service or worker uses (default Claude) |
| `workflow/cost-centers/_schema.yaml` | CORE | Cost center schema |
| `workflow/cost-centers/_template.yaml` | CORE | Cost center template |
| `workflow/cost-centers/<id>.yaml` | USER | One project's costs across accounts (`docs/cloud-costs.md`) |
| `workflow/workspaces/_schema.yaml` | CORE | Workspace schema |
| `workflow/workspaces/_template.yaml` | CORE | Workspace template |
| `workflow/workspaces/<name>.yaml` | USER | A named binding of repos and config overlays (`scripts/workspace.py`) |

## Top-level (own lifecycle, no cluster wrapper)

| Path | Layer | Purpose |
|------|-------|---------|
| `protocols/` | CORE · `standing-orders/user/` USER | `standing-orders/*.md` = shipped always-on rules (CORE) · `standing-orders/user/*.md` = an instance's own orders (USER, never promoted) |
| `work/` | USER | Tasks + logs: `tasks/` (finite) · `streams/` (long-running) · `done/YYYY-MM/` · `inbox/` (items that need a person, [`docs/inbox.md`](inbox.md)) · `cockpit/settled/` (rows settled in the cockpit, shared through git, [`docs/bridge-cockpit.md`](bridge-cockpit.md)) · `templates/` (CORE seeds) · `_learning/` · `archive/` · `imports/` |
| `docs/` | CORE | Human-readable documentation, onboarding guides |
| `rules/` | **Tiered by folder** | Always-on rules. `rules/*.md` = core (ship to all) · `rules/org/**` = org (ship to org overlay) · `rules/user/**` = user (local only). The folder *is* the promote tier. `validate-bridge.py` checks each rule declares a valid `scope:` (presence + allowed value) and fails a rule whose `scope:` disagrees with its folder (a hard gate in CI). Each bridge layers its own under `rules/org/`+`rules/user/`. See [`rules/knowledge-growth.md`](../rules/knowledge-growth.md). |
| `themes/` | CORE (shipped) · any other theme USER unless it declares `meta.scope` | Vocabulary themes (`professional`, `professional-de`, `professional-fr`, `professional-zh-cn`) |
| `trackers/` | CORE | Tracker-provider playbooks (`github.md`, `ado.md`, `gitlab.md`) |
| `skills/` | CORE · `metadata.scope: core` (USER skills: `scope: user`; ORG: `scope: org`) | Skills with SKILL.md + references/. **Scope lives under `metadata:` (`metadata.scope`)** — skill-creator's validator only allows standard top-level keys; sub-agents keep top-level `scope:`. Hard-gated by `scripts/validate-skill-scope.py` (CI + pre-commit). It writes the per-instance tier map to `.bridge/skill-scope.md`, never into `AGENTS.md`: a table generated from the local skill tree cannot converge across instances. |
| `scripts/` | CORE, **allowlisted** · any unlisted script USER | Validators + build/state tools (`validate-bridge.py`, `validate-skill-scope.py`, `scaffold-user.sh`, …). A new core script is registered in `SCRIPTS_CORE_ALLOWLIST` (`scripts/categorize-commits.py`); there is no per-script tag. |
| `bin/` | CORE | Post-clone bootstrap: `setup` (bash · macOS/Linux/WSL) + `setup.ps1` (Windows) — repair the skills discovery symlinks. |
| `imports/` | USER (scratch) | Generic drop-zone for external files (ephemeral, `/imports/*` gitignored except `.gitkeep`). The work-system-specific inbox is `work/imports/`. |
| `examples/` | CORE | Complete reference instance `agency/` (full clone-and-read sample) + `bridge-deck.config.yaml.template`. |
| `docs/examples/` | CORE | Per-type example snippets (`personas/`, `projects/`, `knowledge-repo/`) — distinct from the full instance under top-level `examples/`. |
| `agents/` | **Tiered by path** | Bridge-Agents — persistent, addressable A2A endpoints that front a persona to the outside world (the *outward* counterpart to the *inward* sub-agents below). `_runtime/` (engine), `_template/` (instance scaffold), `_gateway/` (MCP→A2A gateway), `tests/` = CORE; `agents/<name>/` (one instance per persona) = USER. Full guide: [`agents/README.md`](../agents/README.md), [`docs/representative-agent.md`](representative-agent.md). |
| `.claude/agents/` | CORE (with scope) | Native sub-agents |
| `.claude/skills/` | CORE (symlink → `../skills/`) | Discovery symlink so Claude Code finds skills (slash-command triggers live in each skill's `description`; there is no separate commands directory) |
| `.claude/hooks/` | CORE | Optional hook scripts |
| `mods/` | **Enumerated** | Claude Code mods that ship with open-bridge (function hooks, Claude Code only), published through the folder marketplace `mods/.claude-plugin/marketplace.json` (`open-bridge-mods`). `README.md`, the marketplace file and each shipped mod folder (today `cockpit-relay/`) = CORE, listed in the `mods/` lookahead of `USER_PATTERNS` in `scripts/categorize-commits.py`; any other folder here routes USER until it is registered. Guide: [`mods/README.md`](../mods/README.md). |
| `.claude/mods/` | USER | An instance's own mods and their folder marketplace; never promoted. |
| `.codex/hooks.json` | CORE | Codex CLI `Stop` hook: runs `scripts/worklog-drift-check.sh --client codex` ([`tool-mapping.md`](tool-mapping.md)) |
| `.vibe/hooks.toml` | CORE | Mistral Vibe `post_agent` hook: runs `scripts/worklog-drift-check.sh --client vibe` ([`tool-mapping.md`](tool-mapping.md)) |

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

A file's tier is decided by **where it lives**, not by a tag you can forget: whole
folders (`work/` is USER, `trackers/` is CORE), the `_`-prefix inside the cluster
wrappers (`_template.yaml`/`_schema.yaml` CORE, every other instance USER), and
enumerated lists where a folder mixes both (`scripts/`, `agents/`, `mods/`,
`themes/`). Frontmatter decides only for what cannot be foldered (skills, sub-agents,
docs, themes) and for the cluster-wrapper families whose instances an overlay may
share. The single table of scope values, which families a tag can re-tier,
and every path rule in router order is [`extension-model.md` § Scope
model](extension-model.md#scope-model); `scripts/tests/test_scope_docs.py` holds it and
the Layer columns above to the router.

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
- `README.md`, `AGENTS.md`, `DESIGN.md`
- A root `CLAUDE.md` is not part of the layout; when present, Claude Code loads only it and AGENTS.md disappears (scripts/migrate-entry-file.py moves its lines).
- `docs/`, `rules/*.md` (core), `themes/` (shipped), `trackers/`, `skills/` (scope: core), `scripts/` (allowlisted tooling), `bin/` (bootstrap), `examples/` (reference instance)
- `.claude/agents/` (scope: core)
- `mods/README.md`, `mods/.claude-plugin/marketplace.json` and the shipped mod folders (`mods/cockpit-relay/`)
- Templates and schemas in every wrapper folder:
  - every `_template.yaml` / `_schema.yaml` (and `_tests/`) under `identity/<family>/`, `infra/<family>/` and `workflow/<family>/`, see the per-family tables above
- `protocols/standing-orders/*.md` (shipped always-on rules)
- `docs/examples/` (example configs for personas, projects)

USER paths (`user/{name}` branch):
- `bridge-config.yaml`, `bridge-deck.config.yaml`
- every instance file under `identity/<family>/`, `infra/<family>/` and `workflow/<family>/` (every non-`_` file, e.g. `identity/mandants/<id>.yaml`, `infra/remotes/<name>.yaml`, `workflow/projects/<slug>.yaml`, plus the skill-written `infra/backups/_state.yaml`)
- `protocols/standing-orders/user/*.md` (own always-on rules)
- `work/`
- personal user-scope features (`scope: user`, never upstream) live in `rules/user/` + `work/streams/<stream>/` — such as a job-application pipeline
- `.claude/agents/<name>.md` (scope: org/user)
- `.claude/mods/` (an instance's own mods)

## gitignore policy

Every instance file under the cluster wrappers is a USER-layer file: `bridge-config.yaml`,
`bridge-deck.config.yaml`, `ecosystem*.yaml` (not the tracked `ecosystem.example.yaml`),
`overlays.lock.yaml`, `workspaces.lock.yaml`, `context-budget.user.yaml`, `edges.yaml`,
`reachability-scenarios.yaml`, every non-`_` `*.yaml` directly under an `identity/<family>/`,
`infra/<family>/` or `workflow/<family>/` folder, `identity/agent/*.md` (except `README.md`
and the `_template.*.md` seeds), `identity/designs/*.md` (except `_template.md`), and
`work/memory/`. The shipped root `.gitignore` ignores all
of it, in a block generated by `python3 scripts/user-data.py patterns` and held to the tree
by `scripts/tests/test_user_data.py`. The block is **generic** (`/identity/*/*.yaml`, not a
named family), so a fresh clone of a public repo is protected before anything at all has run
in it, and a family added tomorrow is covered without editing this file.

A **private** origin re-allows its own data, per clone, via
[`scripts/user-data.py`](../scripts/user-data.py) `arm` (run by `bin/setup`, i.e. at every
session start, and by Phase 0, see [`rules/session-start.md`](../rules/session-start.md)).
Origin classification is [`scripts/lib/remote-class.sh`](../scripts/lib/remote-class.sh), the
same one `scripts/hooks/pre-push` uses:

- **origin private** → `arm` writes `identity/.gitignore`, `infra/.gitignore`,
  `workflow/.gitignore` and `work/.gitignore`, each carrying a negation
  (`!/*/*.yaml`, `!/agent/*.md`, `!/memory/`); a deeper `.gitignore` wins over the root one, so
  the instance data underneath becomes trackable again. Those four files are USER tier
  themselves, committed with the instance, so a fresh clone of your own private repo is
  correct before `bin/setup` has even run there. The root-level files (`bridge-config.yaml` and
  the rest) cannot be re-allowed below the root, so `arm` stages them once with `git add -f`
  on a `user/*` branch; once tracked, being listed in the root `.gitignore` no longer matters.
  `arm` never deletes a negation file on its own: `gh` being offline can make a private origin
  read as unknown, and deleting the file then would silently drop the backup.
- **origin public or unknown** → `arm` writes nothing, and the shipped root `.gitignore`
  keeps every family out, same as a fresh clone.

`python3 scripts/user-data.py check` warns when a private instance still has untracked
instance files ignored by some rule (the silent-backup-gap case). Two guards stand behind the
decision on every clone regardless of origin: `scripts/hooks/pre-commit` refuses a credential
in a staged instance file (`scripts/user-data.py scan-staged`, reading the INDEX, not the
working tree), and `scripts/hooks/pre-push` refuses USER content, including the four negation
files themselves, to any remote that is not confirmed private
([`rules/push-guard.md`](../rules/push-guard.md); promoting a negation file would re-allow
instance data in every public clone that later merges it).

Making a private origin public on its git host publishes the whole instance history at once:
no local hook runs on that action, so nothing here can prevent or catch it.

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
