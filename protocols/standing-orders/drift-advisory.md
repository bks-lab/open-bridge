---
name: drift-advisory
scope: always
applies_to: []
enforcement: advisory
---

# Drift Advisory

Surface a one-line reminder when a change touches files that have
cross-document or cross-repo coupling, where forgetting to update one
location creates silent drift.

## When to surface

When the user makes a change that touches one of these high-coupling files:

| File class | Why coupled | What to remind |
|---|---|---|
| `LICENSE` | Mirrored in README badge + footer + CLAUDE.md license claim + memory | "License-file changed — also update README badge, footer, CLAUDE.md, and memory entries (`bridge-audit --check license` will list them)." |
| `README.md` skill tree / `AGENTS.md` skill table | Must match `skills/` directory | "Touched skill list — run `bridge-audit --check skill-tree` to verify it still matches `skills/`." |
| `protocols/*.md` (add or remove a protocol) | Numeric "N protocols" mentions in README/CLAUDE | "Protocol added/removed — search for any `\d+ protocols` claims and update or remove the count." |
| Renamed: any file mentioned in `skills/bridge-audit/data/renames.yaml` `old:` | The whole repo grepped against the registry | "Renames registry catches stale references — run `bridge-audit --check renames` after rename." |
| `CLAUDE.md`, `README.md`, `AGENTS.md` | Each lives in the upstream `open-bridge` repo + downstream forks | "Touched a tri-repo doc — at the next sprint sync, run `/bridge-sync` to propagate." |
| `rules/operations.md`, `rules/promote-safety.md` | Cross-referenced from many places (`docs/extension-model.md`, `docs/structure.md`, etc.) | "Touched a routing rule — `bridge-audit --check routing-sot` checks for SoT-conflicts." |
| `workflow/projects/<slug>.yaml` | Read by `project-advisor` + `github-projects-manager` + `briefing` Stream B (state_map). Field-value changes affect every `gh project item-edit` from now on. | "Touched a project-registry entry — verify with `check-jsonschema --schemafile workflow/projects/_schema.yaml`, then cross-check against the live board: `gh project field-list <N> --owner <org>`." |
| `workflow/contexts/<slug>.yaml` `sync.defaults` block | Defines doc-routing defaults for every task with `context: <slug>`. Changes cascade into the Phase 3 `task-sync` standing-order. | "Touched a context's sync defaults — review `work/tasks/*/STATUS.md` + `work/streams/*/STATUS.md` files referencing this context for explicit `sync:` overrides that may now be redundant." |
| `work/templates/_schema.status.yaml` | Validates every STATUS.md frontmatter. Schema changes affect all `work/tasks/*/STATUS.md` + `work/streams/*/STATUS.md` + `work/done/**/STATUS.md`. | "Touched the STATUS schema — run the batch-validation snippet from `work/templates/STATUS.md` against `work/tasks/*/STATUS.md` before commit." |
| `work/tasks/*/STATUS.md` `sync` block | Machine-readable external bindings. Edit-time errors break the Phase 3 `task-sync` resolver. | "Touched a task's sync block — verify with `check-jsonschema --schemafile work/templates/_schema.status.yaml <(yaml-frontmatter status.md)`." |

## When NOT to surface

Skip the advisory for changes under:

- `work/` — personal work logs and tasks
- `identity/personas/<id>.yaml`, `identity/mandants/<id>.yaml` — user PII data
- `infra/remotes/<name>.yaml`, `infra/channels/<name>.yaml` — user infrastructure
- `workflow/calendars/entries.yaml`, `workflow/projects/<slug>.yaml` — user workflow data
- Any `_template.yaml`, `_schema.yaml` (those are reference, not consumed cross-doc)

## Surface format

A single line, after the user's change is applied, before the natural
end-of-turn summary:

```
ⓘ Drift advisory: <change-class> touched. Suggest: `/bridge-audit --check <name>` before next commit.
```

Do not pause for confirmation. Do not run the audit automatically — that's
the user's choice.

## Cooldown

Do not surface the same advisory twice in 10 minutes for the same
file class. The reminder is to nudge, not to pester.

## Origin

This standing order was extracted from a session where multiple
files needed manual cross-doc updates after a single rename, and the
audit-equivalent was performed by hand. The advisory shortens the gap
between "you changed X" and "X needs Y also updated".
