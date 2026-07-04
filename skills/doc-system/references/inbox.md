# Doc-Inbox — Document intake

Shows all waiting documents with details. Bridge between monitoring and processing.
Categorizes files by type and routes to the matching workflow.

## Arguments

| Argument | Meaning | Default |
|----------|-----------|---------|
| `--scan` | Count only, no details | false |
| `--source X` | Only one source (ScanSnap, Downloads, Import) | all |
| `--postausgang` | Show open outbox items | false |

## Path resolution

Like `/doc-status`: Read `bridge-config.yaml → doc_sensor.onedrive_root`, expand `~`.

## Workflow (standard)

### 1. Scan sources

Scan all import sources (from `doc_sensor.scan_paths`).

### 2. Categorize files

Each file is assigned to a category by extension:

| Category | Extensions | Routing |
|-----------|----------|---------|
| Documents | `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx` | → `/doc-process` |
| Recordings | `.mp4`, `.m4a`, `.wav`, `.webm` | → `/debrief` |
| Folders | (directories) | → `/doc-process` (as a whole) |
| Screenshots | `.png`, `.jpg`, `.jpeg`, `.heic` | → check manually |
| HTML reports | `.html` | → read content, assign project, rename (do NOT delete!) |
| Other | `.txt` (without matching .mp4), other | → check manually |

**Special rule for folders:** Folders are handled as a whole — not individual files inside.
Analyze content (file types, names), rename folder per schema, tag, and move.
Example: `scan folder xyz/` → `2026-02-05_<Area>_<Context>_<Description>/` → `<area-path>/`

**Special rule for transcripts:** A `.txt` file with the same base name as an `.mp4`
(e.g. `Meeting-Recording.mp4` + `Meeting-Recording.txt`) belongs in the **Recordings** category
and is forwarded together with the video to `/debrief`.

### 3. Analyze all items + preview table

Right after scanning: analyze ALL items and show a **preview table**.
No intermediate step — the user does not need to first choose what to analyze.

**For documents + folders:** read/analyze content, generate proposal.
**For screenshots:** show image (Read), describe content, generate proposal.
**For recordings:** mark as `/debrief`.
**For other:** read content, generate proposal.

```
── Preview ({N} items) ──────────────────────────────────────────

| #  | Cat | Original                        | New name                                            | Target                            | Action          |
|----|-----|---------------------------------|-----------------------------------------------------|-----------------------------------|-----------------|
|  1 | DOC | 359377_..._2026_01.pdf          | 2026-01-10_<Area>_<Vendor>_<Type>_<Description>.pdf | <area-path>/                      | move            |
|  2 | DOC | Insurance 2026 <Name>.pdf       | 2026-02-04_<Area>_<Insurer>_Policy_2026.pdf         | <area-path>/                      | move            |
|  3 | DOC | <Donation>-Receipt-2025.pdf     | 2025-12-01_<Area>_<Charity>_DonationReceipt         | <persona-dest>/                   | move ⚠          |
|  4 | REC | Call with <Person>...mp4 (+.txt)| —                                                   | —                                 | debrief         |
|  5 | IMG | 401CAEA1-D551-...png            | (empty background, illegible)                       | —                                 | trash           |
|  6 | IMG | Screenshot 2026-02-17...        | (chat screenshot, project topic)                    | —                                 | keep            |
|  7 | DIR | scan-folder-xyz/                | 2026-02-05_<Area>_<Context>_<Description>/          | <area-path>/<sub>/                | move            |
|  8 | ??? | report.html                     | (HTML report, analyze content)                      | —                                 | keep / route    |

⚠ = persona routing (e.g. tax-advisor filing) — please check
Cat: DOC=document, REC=recording, IMG=screenshot, DIR=folder, ???=other
```

### 4. User correction

In the preview, the user can:
- **Enter** = execute everything as proposed
- **Name numbers** to change action/target (e.g. "3 to Taxes/Declarations/", "5 keep", "6 trash")
- **`x` + numbers** to skip items (e.g. "x4,8" = do not process, stays in import)

### 5. Execution + log

After confirmation:
1. Run all actions (move, trash, keep, debrief)
2. Set tags (for move actions)
3. **Write log** → `PROCESSING-LOG.md` (see below)
4. Show summary:

```
Done: 5 moved, 2 deleted, 1 kept, 1 → /debrief
Log: → PROCESSING-LOG.md
```

## --postausgang mode

Shows all open persona-outbox receipts (e.g. tax-advisor bundle),
grouped by persona. Paths come from
`identity/personas/<persona>.yaml.destinations.<dest>`, which are
symbolically aliased in `context.yaml.personas`.

Example groups (user-specific — whatever is in context.yaml applies):

| Group | Resolved from | Persona alias |
|---|---|---|
| Persona A | `personas/<persona-a>.yaml.destinations.<dest-key>` | see `context.personas` |
| Persona B | `personas/<persona-b>.yaml.destinations.<dest-key>` | see `context.personas` |

```
── Outbox open ──────────────────────────────────────────────

  <Persona-A> ({N}):
    1. <Prefix>_2026-01-22_<Area>_<Vendor>_<Type>.pdf  9 days
    2. <Prefix>_2026-01-31_<Area>_<Vendor>_<Type>.pdf  1 day
    ...

  <Persona-B> ({N}):
    1. <Prefix>_2026-01-08_<Area>_<Vendor>_<Type>.pdf  23 days
    2. 2021-12-31_<Area>_<Vendor>_<Type>.pdf  4+ years!
    ...

⚠ {N} documents open for more than 30 days!
Action? [s=reminder mail to recipient, e=mark as submitted, Enter=nothing]
```

**Anti-patterns are not skill knowledge.** They live declaratively in
`context.yaml.anti_patterns` so different setups can express different
edge cases (e.g. separate insurance vs.
tax workflow, distinguish "advisor info letter" vs. "real
submission"). The skill reads them at runtime and
shows a warning in the preview table.

## Routing sources

Concrete routing rules live in `workflow/contexts/doc-system.yaml`:
- `routing[*]` — prioritized match rules
- `anti_patterns` — edge cases (e.g. "advisor info" vs. "real
  submission", insurance-before-tax order, vehicle-plate mapping)
- `special` — HTML / recording / screenshot / folder handling

Concrete target paths live in the persona files (aliases resolved via
`context.personas`):
- `identity/personas/<persona>.yaml.destinations` — per persona
  the filing locations (e.g. tax-advisor outbox, health records,
  personal documents)

NEVER apply routing rules from memory — always from context.yaml.

## Screenshots & logos

Screenshot and branding routing comes from `context.special.screenshots`
and `context.special.branding_assets`:

```yaml
# in workflow/contexts/doc-system.yaml
special:
  screenshots:
    default_target: "1_PROJECT/Screenshots"       # or your own convention
    by_topic:
      <topic-key>: "1_PROJECT/Screenshots/<Folder>"
  branding_assets:
    target: "3_RESOURCES/Branding"
```

Naming convention (from `context.naming.pattern`):
`YYYY-MM-DD_{Cat}_Screenshot_{Description}.png`

## Processing HTML files

HTMLs are NOT throwaway files! They often contain valuable reports,
dashboards, or generated content.

**Workflow for HTMLs:**
1. Read content (Read tool) — understand title, description, content
2. Determine category (report, dashboard export, presentation, tool output)
3. Rename per schema: `YYYY-MM-DD_{Cat}_Report_{Description}.html`
4. Move into matching folder — routing like PDFs via
   `context.routing[*]`, or for generic reports to
   `context.special.html_default_target` (if defined)

## Rules for trash/delete

- **NEVER** delete files without explicit OK from the user
- **HTMLs** always read and categorize first — do NOT dismiss as "other"
- All trash proposals must be confirmed individually

## Processing log (CRITICAL)

**File:** `work/doc-system/log.md` (versioned in git)

The log is the audit trail — without it you cannot trace
what went where. It is written immediately on EVERY move, not
only at the end. Lives in the git repo instead of the documents tree, so it
survives FileProvider / cloud-sync / migration incidents.

### Iron rules

1. **FULL filenames** — NEVER shorten, NO `...`, NO summaries
   - WRONG: `20260210_<Vendor>...pdf`
   - RIGHT: `20260210_<Vendor>_<full-original-name>.pdf`

2. **FULL paths** — always relative to the documents root with areas prefix
   - WRONG: `<Area>/`, `<Subfolder>/`
   - RIGHT: `2_AREAS/<Area>/`, `2_AREAS/<Area>/<Sub>/<File>/` (pattern from `context.areas[*].path`)

3. **EVERY file individually** — no batch entries like "21 files from X to Y"
   - WRONG: `| move | 21 | <source>/ | <target>/ |`
   - RIGHT: One line per file with full name

4. **Document intermediate steps** — when a file is moved multiple times, log each step
   - Example: first to _open, then correction to _submitted → both steps in the log

5. **Log immediately** — do not wait until everything is done. Write the log after each batch right away.

### Format

One header per run, with one line per file beneath it. Format documented
in the header of `work/doc-system/log.md`. Columns:

```markdown
## YYYY-MM-DD HH:MM — /doc-inbox ({N} items)

| # | Action | Original | New name | Source | Target | Persona | Rule |
|---|--------|----------|------------|--------|------|---------|------|
| 1 | move | <original>.pdf | 2026-01-31_<Area>_<Vendor>_<Type>.pdf | 0_Import/ | 2_AREAS/<Area>/<Sub>/ | — | <rule-id> |
| 2 | move | <original>.pdf | <Prefix>_2026-04-28_<Area>_<Vendor>_<Type>.pdf | 0_Import/ | <persona-dest-path>/ | <persona> | <rule-id> |
| 3 | move | <folder>/ (DIR) | 2026-02-03_<Area>_<Person>_<Sub>_<Description>/ | 0_Import/ | 2_AREAS/<Area>/<Sub>/ | <persona> | <rule-id> |
```

### Column rules

| Column | Rule |
|--------|-------|
| **#** | Running number |
| **Action** | `move`, `skip`, `debrief`. NO `trash` without user OK! |
| **Original** | FULL filename as it was in the source folder |
| **New name** | FULL new filename (on skip/keep: `—`) |
| **Source** | FULL path with trailing slash: `0_Import/`, `2_AREAS/Import/` |
| **Target** | FULL path: `2_AREAS/Family/School/`, `2_AREAS/Taxes/_TaxAdvisor/_open/Private/` |
| **Persona** | If routed via persona destination: `freelancer` / `private` / `assets`; otherwise `—` |
| **Rule** | ID of the matching routing rule from context.yaml (e.g. `bewirtung`, `nebenkosten-hausgeld`); `manual-override` when the user overrides the rule |

## Before acting: analyze existing structure

**REQUIRED before any move:**
1. Look at the existing folder structure — which subfolders, which naming conventions?
2. Recognize and respect `_open/` and `_submitted/` patterns (or the
   equivalent convention declared in `context.areas[*].subfolders`)
3. Files that were in `_open` = NOT submitted. Files that were in `_submitted` = submitted.
4. NO unilateral assumptions about submission status — when in doubt, ask the user
5. Respect persona separation — see `identity/personas/<persona>.yaml.notes`
   (which persona, which tax IDs, which vehicles belong to it)
6. ALWAYS observe anti-patterns from `context.yaml.anti_patterns` — the skill
   reads the list declaratively. Typical examples a setup may define:
   - Separate "advisor info" vs. "real submission"
   - Insurance workflow before tax workflow (doctor's invoices)
   - Vehicle plate ↔ persona mapping (business vs. private vehicle)
   - Do not mix persona-specific tax IDs

## Work log

On processing → entry in `work/log.md`:
```
| {YYYY-MM-DD HH:MM} | 📁 | docs | /doc-inbox: {N} files processed |
```
