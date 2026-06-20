---
summary: "Per-board project configs consumed by project-advisor and github-projects-manager. One file per external board (GitHub, ADO, Linear, ...)."
type: readme
last_updated: 2026-05-11
related:
  - _template.yaml
  - _schema.yaml
  - ../../skills/project-advisor/SKILL.md
  - ../../skills/github-projects-manager/SKILL.md
  - ../../trackers/README.md
---

# Project Registry — `workflow/projects/`

Per-board configuration. Each `<slug>.yaml` describes one external
project board (GitHub Projects V2, Azure DevOps Boards, Linear, Jira,
GitLab). Skills read these files as the source of truth for valid
field values, governance rules, and state mappings.

## Who reads it

| Skill | What it reads |
|---|---|
| `skills/project-advisor/` | `fields`, `governance`, `state_map` — for issue-creation decisions and board-health checks |
| `skills/github-projects-manager/` | `fields`, `conventions` — for `gh project item-edit` commands |
| `skills/briefing/` (Stream B) | `state_map` — to normalize raw status labels into the unified view |
| `protocols/standing-orders/task-sync.md` *(Phase 3)* | `context_ref`, `mandant_ref` — for per-task sync resolution |

## File layout

```
workflow/projects/
├── README.md             ← you are here
├── _template.yaml        ← CORE — copy when adding a new board
├── _schema.yaml          ← CORE — JSON Schema validating each <slug>.yaml
└── <slug>.yaml           ← USER — one per board (e.g. <your-project>.yaml)
```

`_template.yaml` + `_schema.yaml` ship with the framework (CORE). The
actual board configs (`<slug>.yaml`) live on the user branch — they
contain organization-specific field values and governance.

## Naming convention

| File | Slug pattern |
|---|---|
| Per-board config | `<short-name>.yaml` — lowercase, dash-separated, no `project.` prefix |
| Matches `identity.slug` | yes — slug inside the file must equal the filename without `.yaml` |
| Stable | never rename in place; `git mv` to preserve history |

Examples: `<customer-a>.yaml` (Project #N), `<area>-operations.yaml`
(Project #M), `<personal-project>.yaml` (Project #P).

## Adding a new board

1. Copy `_template.yaml` to `<slug>.yaml`
2. Fill in `identity`, `project`, `fields`, `state_map`, `governance`
3. (Optional) Set `context_ref` and `mandant_ref` to link to
   `workflow/contexts/<slug>.yaml` and `identity/mandants/<slug>.yaml`
4. Add the `# yaml-language-server: $schema=./_schema.yaml` hint at the top
5. Validate: `check-jsonschema --schemafile workflow/projects/_schema.yaml workflow/projects/<slug>.yaml`
6. Add to `bridge-config.yaml` `integrations.<tracker>.projects` (or set `projects: ecosystem` to inherit from `ecosystem.yaml.github_projects`)

## Three-axis routing — projects × contexts × mandants

A task in `work/tasks/<slug>/STATUS.md` can reference three
orthogonal axes that resolve to defaults across the system:

| Axis | Where it lives | What it answers |
|---|---|---|
| **Project** | `workflow/projects/<slug>.yaml` | "What fields/values are on the board?" |
| **Context** | `workflow/contexts/<slug>.yaml` | "Where do we document this work?" |
| **Mandant** | `identity/mandants/<slug>.yaml` | "Who are the relevant recipients?" |

A STATUS.md sets `context:` and (optionally) `mandant:`; the Phase 3
`task-sync` standing-order resolves defaults from the chain. The
project is reached indirectly via `context.sync.defaults.github.project`.

## Scope layering

- `_template.yaml`, `_schema.yaml`, `README.md` → **CORE** (ships with open-bridge)
- `<slug>.yaml` with org-shared field values → **org-shared** (downstream fork) or **USER** (personal)
- Customer-specific governance rules → typically live in a downstream fork

See `rules/operations.md` for the full path table.

## Related

- `trackers/README.md` — provider playbooks for `/briefing` Stream B (read-only)
- `skills/project-advisor/SKILL.md` — governance enforcement
- `skills/github-projects-manager/SKILL.md` — write operations
- `protocols/standing-orders/task-sync.md` *(Phase 3)* — per-task sync routing
