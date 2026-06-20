---
scope: core
description: Pre-write checklist — schemas, templates, conventions to verify before creating any new YAML/MD in the Bridge
---
# File Creation — Schemas First

> **Rule of thumb:** never write a new config or doc file from memory.
> Always anchor on the matching template + schema + a peer example first.
> 30 seconds reading saves a future audit fix.

## Why

The Bridge has a strict layout (Default-to-Folder, cluster wrappers, frontmatter
conventions). Skills, sub-agents, and `/bridge-sync` all rely on those conventions
to function. A file with the wrong frontmatter, wrong filename pattern, or missing
companion doc looks fine in isolation but breaks routing, discovery, or validation
downstream. The fix is always more expensive than the prevention.

## Pre-write checklist

Run this every time, in order:

1. **Locate the destination folder.** Use the cluster-wrapper map (CLAUDE.md
   § Layout — Cluster-Wrappers). Personas/Mandants/Accounts → `identity/`;
   Remotes/Channels/Backups → `infra/`; Calendars/Contexts/Projects → `workflow/`;
   Protocols, Skills, Trackers, Themes → top-level.
2. **Read the `_template.yaml`** in the destination folder. This is the field
   shape that the schema validates against and that peer skills expect.
3. **Read the `_schema.yaml`** if present. Pay attention to `required:`,
   `additionalProperties:` (strict vs permissive), and enum constraints.
4. **Skim one existing peer file** to see real-world usage — what comments
   look like, what optional fields people actually fill in, what conventions
   exist that aren't captured in the schema (e.g. UTF-8 umlauts, mixed
   DE/EN comments in `org` scope, English-only in `core` scope).
5. **Decide on companion docs:**
   - Provisioning notes (BIOS, tokens, setup that must happen **before** the
     YAML is active) → `<slug>-setup.md`
   - Overview / pattern guide (explains what the YAML means, when to use which
     pattern, decision matrices) → `<slug>.README.md`
   - Both possible — use both with the dash/dot trenner to keep the purpose
     visible in the filename.
6. **Verify the filename:** simple slug, no type-prefix.
   ✅ `identity/mandants/team.yaml` ❌ `identity/mandants/mandant.team.yaml`
7. **Determine scope** for `/bridge-sync` routing:
   - Generic templates, schemas, docs, skills → `core` → open-bridge (+ your org overlay)
     - A `scope: core` skill must stay **config-driven**: configure via
       `bridge-config.yaml` / USER files, never hardcode instance specifics
       (queries, org/project IDs, personas, thresholds). See
       [`docs/extension-model.md` § Generic CORE Skills](../docs/extension-model.md).
   - Org-internal data (org personas, mandants, tenants, contexts) →
     `org` → your org overlay only
   - User-personal data (personas, accounts, work logs) → `user` →
     stays local
   - **Scope by who pays/owns, not by which login path you used.** For an asset
     file (most often a cloud-account YAML under `identity/accounts/`), ask *who
     owns or is billed for this*, never *whose login opens it*. An org-billed or
     org-owned account is `org` scope — so the team sees, via the
     org-internal upstream, that the account exists and the org carries the cost —
     **even when it is reached through a personal login** (root via a personal
     email, a personal daily-driver account on an org tenant). A purely private
     account (own billing, own tool) is `user`. The login path is mechanism, not
     ownership. (Cloud accounts live in `identity/accounts/`, not
     `infra/remotes/` — that folder is machines only.)
   Path-based routing is in [`rules/operations.md` § Scope-Routing](operations.md).
8. **Then** write the file.

## Where templates live (lookup table)

| File pattern you're creating | Template path | Schema path | Peer example |
|---|---|---|---|
| `identity/personas/<id>.yaml` | `identity/personas/_template.yaml` | `identity/personas/_schema.yaml` | `docs/examples/personas/` |
| `identity/accounts/<id>.yaml` | `identity/accounts/_template.yaml` | `identity/accounts/_schema.yaml` (permissive) | `examples/agency/identity/accounts/cloud-provider.yaml` |
| `identity/mandants/<id>.yaml` | `identity/mandants/_template.yaml` | `identity/mandants/_schema.yaml` | `examples/agency/identity/mandants/team.yaml` |
| `infra/remotes/<name>.yaml` | `infra/remotes/_template.yaml` | `infra/remotes/_schema.yaml` | `examples/agency/infra/remotes/prod-server.yaml` |
| `infra/channels/<name>.yaml` | `infra/channels/_template.yaml` | `infra/channels/_schema.yaml` | `examples/agency/infra/channels/email.yaml` |
| `infra/backups/*.yaml` | `infra/backups/_template.yaml` | — | `examples/agency/infra/backups/topology.yaml` |
| `workflow/contexts/<id>.yaml` | `workflow/contexts/_template.yaml` | `workflow/contexts/_schema.yaml` | `examples/agency/workflow/contexts/webapp/context.yaml` |
| `workflow/projects/<id>.yaml` | `workflow/projects/_template.yaml` | `workflow/projects/_schema.yaml` | `docs/examples/projects/` |
| `workflow/calendars/*.yaml` | `workflow/calendars/_template.yaml` | `workflow/calendars/_schema.yaml` | `examples/agency/workflow/calendars/entries.yaml` |
| `work/tasks/<slug>/STATUS.md` | `work/templates/STATUS.md` | `work/templates/_schema.status.yaml` | any current finite task |
| `protocols/standing-orders/<name>.md` | `protocols/standing-orders/_template.md` | — | `protocols/standing-orders/task-sync.md` |
| `skills/<name>/SKILL.md` | — | — | any existing skill, e.g. `skills/mandants/SKILL.md` |
| Doc with frontmatter (`docs/*.md`, `<folder>/README.md`) | — | — | shape in CLAUDE.md § Documentation Navigation |

## Common gotchas (real history)

- **Filename type-prefix.** Old layout had `mandants/mandant.team.yaml`. Current
  rule: simple slug, type from the folder. `mandants/team.yaml`.
- **`_`-prefix is reserved.** Templates, schemas, state files start with `_`
  and are excluded by discovery. Never name a real instance with leading `_`.
- **Companion doc trennzeichen is intentional.** Dash for `-setup.md` (pre-activation),
  dot for `.README.md` (overview). The inconsistency makes the purpose visible
  at-a-glance.
- **Frontmatter for standalone docs:** `summary`, `type`, `last_updated`,
  `related:` — shape in CLAUDE.md § Documentation Navigation. Skipping this
  means the doc won't be triaged correctly by AI-first reading.
- **UTF-8 native, not entities.** Umlauts as `ä`/`ö`/`ü`/`ß`, em-dash as `—`,
  Euro as `€`. Never `&auml;`, never `ä`, never `ae`. Applies to
  comments and content equally.
- **Scope-routing is path-based, not always inline.** `identity/` files don't
  typically carry `scope:` frontmatter — routing is inferred from the path
  (per [`rules/operations.md`](operations.md)). Protocols carry inline
  top-level `scope:`. **Skills** carry `scope:` under `metadata:`
  (`metadata.scope`) — skill-creator's validator only permits the standard
  top-level keys (`name`/`description`/`license`/`allowed-tools`/`metadata`/
  `compatibility`), so non-standard keys nest under `metadata:`. Sub-agents
  (`.claude/agents/*.md`) keep `scope:` top-level.
- **Cross-references over duplication.** If two files would carry the same
  data (e.g. service-account mapping), pick ONE canonical home and reference
  it from the other. Duplication = drift risk.
- **English-only in `open-bridge` scope.** Templates, schemas, and `core`-scope
  docs/skills must be English. Mixed DE/EN is OK in `org`/`user` scope only.
  When in doubt: write English in the template, German in the user-instance.

## When you legitimately don't have a template

A handful of file types don't have explicit `_template.yaml` files
(ad-hoc docs in `docs/`, skill `SKILL.md` files). In those cases:

1. Find the 2–3 most similar existing files
2. Skim them for the implicit structure
3. Document the new pattern explicitly in your file's top comment if you're
   establishing a new convention — so the next author has something to follow

When you find yourself wanting a template that doesn't exist yet **and**
you'll be creating multiple instances of this type, create the `_template.yaml`
first, **then** the instance. That's the path that scales.
