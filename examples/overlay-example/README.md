---
summary: "Worked example org overlay (example-org) — manifest + ecosystem fragment + a tree/ that mirrors the Bridge layout, every file scope:org"
type: readme
last_updated: 2026-06-27
related:
  - overlay.manifest.yaml
  - ecosystem.example-org.yaml
  - ../../docs/schemas/overlay-manifest.schema.yaml
  - ../../docs/org-overlays.md
---
# Overlay Example — `example-org`

A complete, PII-free **org overlay**: the bundle an organisation ships so its
Bridge consumers can `add` org-internal boards, contexts, recipients, accounts,
rules, agents, and skills — without forking CORE.

Everything here is fictional and generic; the only org named is `example-org`.
This tree doubles as the schema-validation fixture for
[`docs/schemas/overlay-manifest.schema.yaml`](../../docs/schemas/overlay-manifest.schema.yaml).
Full mechanics: [`docs/org-overlays.md`](../../docs/org-overlays.md).

## What an overlay repo ships

```
overlay-example/
├── overlay.manifest.yaml          ← REQUIRED — root declaration (validated)
├── README.md                      ← REQUIRED — this file (outside tree/)
├── ecosystem.example-org.yaml     ← OPTIONAL fragment (@import-wired, never block-merged)
└── tree/                          ← mirrors the Bridge layout; every file = scope:org
    ├── .claude/agents/
    ├── identity/{accounts,mandants}/
    ├── rules/org/
    ├── skills/
    └── workflow/{contexts,projects}/
```

`.github/workflows/publish-guard.yml` (a leak gate that runs before publish) is
part of the contract too; it is omitted from this example fixture.

## How `tree/` materializes

A file at `tree/<path>` materializes to `<path>` in the consumer (strip the
`tree/` prefix). Each file below becomes the consumer file on the right:

| `tree/` file | Becomes on the consumer | Notes |
|---|---|---|
| [`tree/workflow/projects/example-board.yaml`](tree/workflow/projects/example-board.yaml) | `workflow/projects/example-board.yaml` | `scope:org` board; prompts for `$.project.org` + `$.project.number` |
| [`tree/workflow/contexts/example-docs.yaml`](tree/workflow/contexts/example-docs.yaml) | `workflow/contexts/example-docs.yaml` | **FLAT** so `discover()` sees it; covered by the flat mirror (no `files[]` entry) |
| [`tree/identity/mandants/example-team.yaml`](tree/identity/mandants/example-team.yaml) | `identity/mandants/example-team.yaml` | recipient group; prompts for `$.persons[*].channels.email` (**pii**) |
| [`tree/identity/accounts/example-cloud.yaml`](tree/identity/accounts/example-cloud.yaml) | `identity/accounts/example-cloud.yaml` | only `keychain://` / `azure-keyvault://` URIs; prompts for `$.cloud.tenant_id` |
| [`tree/rules/org/example-routing.md`](tree/rules/org/example-routing.md) | `rules/org/example-routing.md` | org-only rule; `rules/org/**` layers additively over CORE rules |
| [`tree/.claude/agents/example-org-coordinator.md`](tree/.claude/agents/example-org-coordinator.md) | `.claude/agents/example-org-coordinator.md` | **behavioural** — `kind: agent`, top-level `scope: org` |
| [`tree/skills/example-org-coordinator/SKILL.md`](tree/skills/example-org-coordinator/SKILL.md) | `skills/example-org-coordinator/SKILL.md` | **behavioural** — `kind: skill`, `metadata.scope: org` |

The [`ecosystem.example-org.yaml`](ecosystem.example-org.yaml) fragment is copied
to the consumer root and registered as an `@import` — it adds `example-org` repos
beside the consumer's own registry, never overwriting it.

## Hard rules the engine enforces

- **Never ship** `_template.yaml` / `_schema.yaml`, a wrapper `README.md`,
  `identity/personas/**`, or `work/**` — see `selection.exclude` in the manifest.
- **Discoverable instances** (contexts, projects, mandants) must be **flat**
  `<slug>.yaml`; a nested `<slug>/context.yaml` is invisible to `discover()`.
- **Slugs are org-namespaced** (`example-*` / `example-org-*`) so flat discovery
  never collides with a consumer's own files.
- **Accounts** carry only `azure-keyvault://` / `keychain://` / `1password://`
  URIs — the raw-secret scan refuses anything else.
- **Every `tree/` file** carries the right `scope: org` (or `metadata.scope: org`
  for skills) tripwire — org content never promotes to the public CORE upstream.
