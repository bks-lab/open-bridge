---
summary: "Template skeletons for the Knowledge Repo Pattern — project metadata, MOC, index, context sync stub"
type: index
scope: core
last_updated: 2026-05-13
related:
  - ../../knowledge-repo-pattern.md
---

# Knowledge Repo Examples

Copy-paste templates for setting up an optional knowledge/documentation
repo paired with your Bridge instance. The conceptual overview lives in
[`docs/knowledge-repo-pattern.md`](../../knowledge-repo-pattern.md).

## What's here

| Path | Purpose | Drop into |
|---|---|---|
| `project-template/project.yaml` | Project metadata schema | `<knowledge-repo>/<area>/<slug>/projects/<project>/project.yaml` |
| `project-template/_MOC.md` | Curated entry-point skeleton | Same folder as `project.yaml` |
| `project-template/index.md` | File inventory skeleton | Same folder |
| `context-sync-stub.yaml` | Bridge context routing block | Paste into `workflow/contexts/<slug>.yaml` `sync:` block |

## How to use these templates

1. **Read [`docs/knowledge-repo-pattern.md`](../../knowledge-repo-pattern.md) first** — it explains the layout, principles, and Bridge integration points.
2. **Scaffold a project folder** in your knowledge repo by copying `project-template/` into `<area>/<slug>/projects/<project>/` and filling in the fields.
3. **Wire up Bridge routing** by pasting `context-sync-stub.yaml` into your `workflow/contexts/<slug>.yaml` (rename `wiki` → whatever you call your repo, or leave it).
4. **Optional but recommended:** run the [`knowledge-repo-init`](../../../skills/knowledge-repo-init/SKILL.md) skill — it walks you through the same setup interactively.

## Naming conventions baked into the templates

| Type | Format | Example |
|---|---|---|
| Meetings / dated protocols | `YYYY-MM-DD-{slug}.md` | `2026-05-13-status-call.md` |
| Milestones | `YYYY-QX-{name}.md` | `2026-q2-launch.md` |
| Directories | `kebab-case` | `e-invoice-inbound/` |

Tooling-agnostic — works whether your knowledge repo is on GitHub, GitLab,
self-hosted Gitea, or a local-only clone. The pattern depends on Git +
markdown + YAML frontmatter only.
