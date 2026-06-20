---
name: doc-system
description: >-
  Document management — inbox scan, processing, and status monitoring.
  Scans configured import sources (e.g. PARA, Johnny Decimal, custom),
  categorizes documents, applies routing rules from
  workflow/contexts/doc-system.yaml plus persona destinations from
  identity/personas/{id}.yaml. Renames, tags, files, and audits in
  work/doc-system/log.md.
  Trigger: "/doc-system", "doc inbox", "doc process", "doc status",
  "process documents", "scan documents", "document queue".
metadata:
  scope: core
---

# Doc-System

Document intake, processing, and monitoring.
Read the referenced file ONLY when triggered.

## Guard — run BEFORE anything else

1. Read `bridge-config.yaml`. If `doc_sensor.enabled` is not `true` or the
   block is missing → inform user "doc-system is not enabled in
   bridge-config.yaml. Set `doc_sensor.enabled: true` and
   `doc_sensor.onedrive_root` (the documents root — name is historical,
   any local folder works)" and stop.
2. Resolve `${onedrive_root}` from `doc_sensor.onedrive_root` (expand `~` and
   `$HOME`). If the path is empty or the directory does not exist → inform
   "documents root `{value}` not reachable" and stop. **Do not proceed with
   a blank interpolation.**

## REQUIRED: Load routing sources

Before EVERY processing run (after the guard above):
```
Read("workflow/contexts/doc-system.yaml")
# Personas referenced in context.personas → load automatically.
# Example: if context.personas contains
#   freelancer: my-freelancer
#   private:    my-private
# then:
Read("identity/personas/my-freelancer.yaml")
Read("identity/personas/my-private.yaml")
```

`workflow/contexts/doc-system.yaml` is the single source of truth for
areas, naming, tags, routing rules, and anti-patterns. Personas supply
concrete target paths via `destinations:`.

NEVER routing rules from memory — ALWAYS from context.yaml!

For edge cases, additionally read the local `_INFO.md` of the affected area
(`${onedrive_root}/<areas-root>/<area>/_INFO.md` — path convention
from `context.areas[*].path`) — as a detail hint for human maintenance, not
as an override for context.yaml.

## Decision Tree

```
User wants to...
├── Scan inbox / show what's new       → Read references/inbox.md
├── Process documents                  → Read references/process.md
├── Check document queue status        → Read references/status.md
└── Questions about doc system         → Answer from this file
```

## Path resolution

1. Read `bridge-config.yaml` → `doc_sensor.onedrive_root`
2. Expand `~` to `$HOME`
3. Areas root comes from `context.areas[*].path` (e.g. `2_AREAS/` for PARA,
   `20_<area>/` for Johnny Decimal, or anything for custom setup)
