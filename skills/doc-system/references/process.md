# Doc-Process — Document processing

Processes documents from the import sources: analyzes content, renames, tags, and moves.

## Arguments

| Argument | Meaning | Default |
|----------|-----------|---------|
| `[file]` | Process a specific file | — |
| `--preview N` | Analyze N documents, show table | — |
| `--batch N` | Process N documents automatically | — |
| `--dry-run` | Preview only, do not change | false |
| `--source X` | Only from source X (ScanSnap, Downloads, Import) | all |

## Path resolution

1. Read `bridge-config.yaml` in this Bridge repo
2. Find `doc_sensor.onedrive_root` (name is historical — it means
   the local documents root; OneDrive is not required)
3. Expand `~` to `$HOME`
4. Areas root comes from `context.areas[*].path` (e.g. `2_AREAS/` with PARA)

## REQUIRED: Load routing sources (before EVERY processing run!)

```
Read("workflow/contexts/doc-system.yaml")
# Plus dynamically load every file referenced in context.personas.
# Example: if context.personas contains
#   freelancer: my-freelancer
#   private:    my-private
#   business:   my-llc
# then:
Read("identity/personas/my-freelancer.yaml")
Read("identity/personas/my-private.yaml")
Read("identity/personas/my-llc.yaml")
```

`workflow/contexts/doc-system.yaml` is the **single source of truth** for:
- `areas[*]` — folder structure, sub-areas, persona bindings
- `naming` — filename schema (`{YYYY-MM-DD}_{Area}_{Context}_{Type}_{Description}.{ext}`)
- `tags` — tag schema (e.g. `Person:Name`, `Year:YYYY`, `Cat:Area`)
- `routing[*]` — prioritized match rules (first match wins)
- `anti_patterns` — edge cases and warnings (declared per user)
- `special` — HTML / recording / screenshot / folder handling

`identity/personas/<id>.yaml` provides concrete paths via `destinations:`.
Which destination keys exist is declared by each persona itself (e.g.
`<persona>_open`, `<persona>_submitted`, `bank`, `health`,
`<area>_tax_advisor_open` — depending on setup). Routing rules reference
these keys via `target: { persona: <alias>, dest: <dest-key> }`.

**NEVER** apply routing rules from memory — ALWAYS from context.yaml!

For edge cases additionally read `${onedrive_root}/<areas-root>/<area>/_INFO.md`
(local maintenance doc per area). On conflict, context.yaml wins.

## Workflow

### 1. Scan sources

Import sources from `bridge-config.yaml → doc_sensor.scan_paths`:
```bash
/usr/bin/find "${ONEDRIVE_ROOT}/${scan_path}" -type f \
  -not -name '.DS_Store' -not -name '_INFO.md' -not -name '.gitkeep' \
  2>/dev/null
```

### 2. For every document

1. **Analyze source-folder context** — the folder path is a valuable hint
2. **Read content** — `Read()` for PDFs (Claude Vision for scans)
3. **Extract metadata** — date, person, area, type, description, vendor
4. **Match routing rule** — walk `context.routing[*]` by priority,
   pick the first matching rule. Anti-patterns are at the start of the
   routing list (they fire before generic rules step in).
5. **Resolve persona path** — when `target.persona` is set:
   resolve `context.personas[<alias>]` → yields persona file ID;
   then read `identity/personas/<id>.yaml.destinations.<dest>`.
   When `target.area` is set: `areas[<area>].path + subpath`.
6. **Generate filename** — per `context.naming.pattern`,
   optionally with persona prefix from `context.naming.prefixes.<alias>` (e.g.
   `Freelancer_`, `Private_`) when the rule hits a persona filing
   and bundle sorting is desired.
7. **Set tags** — `tag --set "Person:X,Year:Y,Cat:Z" "file"`
8. **Move** — `mv` to target folder
9. **Anti-pattern check** — if rule has a `note` (warning), mark in
   the preview table as ⚠, have the user confirm
10. **Audit** — entry in `work/doc-system/log.md` with persona + rule ID

### 3. Work log (two places)

**Audit trail** in `work/doc-system/log.md` (one line per file,
versioned in git — see the header of the file for format).

**Bridge log** in `work/log.md` (once per run, compact):
```
| {YYYY-MM-DD HH:MM} | 📁 | docs | {N} documents processed |
```

## Modes

### Single document (default)

Show proposal, user confirms:
```
Original:  scan_20240115.pdf
New name:  2024-01-15_<Area>_<Person/Context>_<Type>_<Description>.pdf
Folder:    <area-path>/<sub>/
Tags:      Person:<Name>, Year:2024, Cat:<Area>

[Enter = OK] [e = edit] [s = skip]
```

### Preview (--preview N)

Table with all proposals, user picks which to skip:
```
| #  | Source    | Original     | New name                            | Folder        | Warning |
|----|-----------|--------------|-------------------------------------|---------------|---------|
| 1  | ScanSnap  | scan_001.pdf | 2024-01-15_<Area>_<Context>_<Type>..| <area-path>/  | ✓       |
| 2  | ScanSnap  | scan_002.pdf | 2024-03-10_<Area>_<Context>_<Type>..| <area-path>/  | ⚠ check |

Which numbers to skip? (comma-separated, Enter = all OK)
```

### Batch (--batch N)

Process automatically, stops at:
- Uncertainty about target folder (no rule matched)
- Persona filing (e.g. tax-advisor bundle — user confirms each entry)
- Anti-pattern triggered (see `context.anti_patterns`)
- Files from OLD folders with "not_yet", "submit", etc.

### Dry-run (--dry-run)

Preview only, no changes.

## Batch parallelization

For more than 5 documents: use sub-agents (max 5 in parallel).
Each agent reads `workflow/contexts/doc-system.yaml` + the referenced
personas itself and processes one document end-to-end.
