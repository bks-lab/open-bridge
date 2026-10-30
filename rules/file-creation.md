---
scope: core
description: Pre-write checklist — schemas, templates, conventions to verify before creating any new YAML/MD in the Bridge
---
# File Creation — Schemas First

> **Rule of thumb:** never write a new config or doc file from memory.
> Always anchor on the matching template + schema + a peer example first.
> 30 seconds reading saves a future audit fix.

## Why

Strict layout conventions (Default-to-Folder, cluster wrappers, frontmatter)
are what let skills, sub-agents, and `/bridge-sync` function. A file with
the wrong frontmatter, filename pattern, or missing companion doc looks
fine in isolation but breaks routing, discovery, or validation downstream.
The fix is always more expensive than the prevention.

## Pre-write checklist

Run this every time, in order:

1. **Locate the destination folder.** Use the cluster-wrapper map (AGENTS.md
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
| `identity/designs/<id>.md` | `identity/designs/_template.md` (or copy the root `DESIGN.md`) | `identity/designs/_schema.yaml` (front matter) | the root `DESIGN.md` |
| `identity/accounts/<id>.yaml` | `identity/accounts/_template.yaml` | `identity/accounts/_schema.yaml` (permissive) | `examples/agency/identity/accounts/cloud-provider.yaml` |
| `identity/mandants/<id>.yaml` | `identity/mandants/_template.yaml` | `identity/mandants/_schema.yaml` | `examples/agency/identity/mandants/team.yaml` |
| `infra/remotes/<name>.yaml` | `infra/remotes/_template.yaml` | `infra/remotes/_schema.yaml` | `examples/agency/infra/remotes/prod-server.yaml` |
| `infra/channels/<name>.yaml` | `infra/channels/_template.yaml` | `infra/channels/_schema.yaml` | `examples/agency/infra/channels/email.yaml` |
| `infra/backups/*.yaml` | `infra/backups/_template.yaml` | — | `examples/agency/infra/backups/topology.yaml` |
| `infra/secret-stores/<slug>.yaml` | `infra/secret-stores/_template.yaml` | `infra/secret-stores/_schema.yaml` | the template itself, which is written as one |
| `infra/object-stores/<slug>.yaml` | `infra/object-stores/_template.yaml` | `infra/object-stores/_schema.yaml` | `infra/object-stores/_tests/valid/` |
| `workflow/contexts/<id>.yaml` | `workflow/contexts/_template.yaml` | `workflow/contexts/_schema.yaml` | `examples/agency/workflow/contexts/webapp/context.yaml` |
| `workflow/projects/<id>.yaml` | `workflow/projects/_template.yaml` | `workflow/projects/_schema.yaml` | `docs/examples/projects/` |
| `workflow/calendars/*.yaml` | `workflow/calendars/_template.yaml` | `workflow/calendars/_schema.yaml` | `examples/agency/workflow/calendars/entries.yaml` |
| `work/tasks/<slug>/STATUS.md` | `work/templates/STATUS.md` | `work/templates/_schema.status.yaml` | any current finite task |
| `protocols/standing-orders/<name>.md` | `protocols/standing-orders/_template.md` | — | `protocols/standing-orders/task-sync.md` |
| `skills/<name>/SKILL.md` | — | — | any existing skill, e.g. `skills/mandants/SKILL.md`; then § Writing skill steps below |
| `skills/<name>/LEARNINGS.md` + its routing block | `docs/skill-learnings.md` § Templates | `scripts/check-skill-learnings.py` | the template itself |
| Doc with frontmatter (`docs/*.md`, `<folder>/README.md`) | — | — | shape in AGENTS.md § Documentation Navigation |

## Common gotchas (real history)

- **`_`-prefix is reserved.** Templates, schemas, state files start with `_`
  and are excluded by discovery. Never name a real instance with leading `_`.
- **Companion doc trennzeichen is intentional.** Dash for `-setup.md` (pre-activation),
  dot for `.README.md` (overview). The inconsistency makes the purpose visible
  at-a-glance.
- **Frontmatter for standalone docs:** `summary`, `type`, `last_updated`,
  `related:` — shape in AGENTS.md § Documentation Navigation. Skipping this
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

## Writing skill steps: procedure or workaround

A skill is usually written in one session by whatever model runs it, then
executed by others: a sub-agent on a smaller tier, or another harness entirely.
Two kinds of step read alike and age differently:

- **Procedure:** what to do and why. "Read the project config, then check the
  field the step names." Any capable model can follow it and can improve on it.
- **Workaround:** a step that exists only to keep one model from failing: a bare
  literal command in place of a described intent, a string-conversion rule, a
  fallback for one model's parsing quirk. It helps the model it was written for
  and can hold a stronger one back from doing the step properly.

**Mark every workaround** directly above the line it guards, naming who it is
for (a model tier such as `small models`, or a harness name) and the failure it
prevents:

```markdown
<!-- workaround(small models): they split this pipeline across calls and lose
     the intermediate file; a larger model can write one script instead -->
Run exactly: `jq -r '.items[].id' out.json > ids.txt && wc -l ids.txt`
```

A procedure gets no marker. Keep a workaround when it is the only reliable path
for a step every model trips on; the marker is what lets a later author, or a
stronger executor, tell it apart from the intent and replace it when the reason
is gone.

**Worked example.** A first draft of a report step read:

```markdown
3. Run `python3 -c "import json;print(len(json.load(open('r.json'))['rows']))"`
   and paste the number. Never compute it in your head.
```

Rewritten, the intent leads and the workaround is labelled:

```markdown
3. Count the rows in `r.json` and state the number with its source.
   <!-- workaround(small models): they estimate counts from a truncated read;
        the one-liner forces a real count -->
   On a small-tier executor, run `python3 -c "import json;print(len(json.load(open('r.json'))['rows']))"`.
```

This is a **hypothesis carried over from benchmark runs, not a measured
open-bridge result.** WikiSkill (Tang et al., arXiv:2608.27454v1, section 4.2.2,
page 9, Table 2 on page 10) reports a skill written by a small model dropping a
stronger model's score from 50.5% to 18.1% on one benchmark, traced to such
low-level workarounds. Nothing in this repo has measured the effect yet.

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
