---
summary: "Inventory of files in this project folder — no judgment, just what exists"
type: index
last_updated: 2026-05-13
related:
  - _MOC.md
  - project.yaml
---

# {{Project Name}} — File Inventory

> No judgment, no prose, no duplication of content. Just **what exists**
> here. Update this row-by-row when files are added or removed.

## Files at this level

| File | Type | Purpose |
|---|---|---|
| [`project.yaml`](project.yaml) | metadata | Project identity, status, ownership |
| [`_MOC.md`](_MOC.md) | moc | Curated "what matters now" entry-point |
| [`index.md`](index.md) | index | This file |

## Subdirectories

| Path | What's in it |
|---|---|
| [`documentation/`](documentation/) | Technical docs, architecture, API specs |
| [`requirements/`](requirements/) | Stakeholder requirements and acceptance criteria |
| [`milestones/`](milestones/) | Timeline, phase gates, release plan |
| [`attachments/`](attachments/) | Binaries, PDFs, screenshots, exported diagrams |
| [`protocols/`](protocols/) | Meeting notes, decision records (`YYYY-MM-DD-*.md`) |

## How to add a new file

1. Drop the file into the right subdirectory (or here, if it's project-level).
2. Add a row to the matching section above with the file name and a
   one-line purpose.
3. If the file represents a decision, incident, or status change,
   **also** update [`_MOC.md`](_MOC.md).
