# Process Meeting

Processes meeting recordings and transcripts into structured outputs.
Interactive workflow — analyzes first, proposes routing, user decides.

**Trigger:** `/debrief --quick`, `/debrief --quick {path}`, `/debrief --all`, `/debrief --date YYYY-MM-DD`

## Arguments

| Argument | Meaning | Default |
|----------|-----------|---------|
| `{path}` | Process a file directly (mp4, txt, or folder) | — |
| `--all` | All unprocessed transcripts from all sources | false |
| `--date YYYY-MM-DD` | Specific date | today |

## Sources

Scan in this order (dedupe by base name):

1. **Legacy imports dir** — `bridge-config.yaml` → `work.imports_dir`
   (default if unset: `work/imports/`).
2. **PARA recordings sources** — `bridge-config.yaml` → `doc_sensor.scan_paths[*]`
   where `kind: recordings` (or label contains "Audio"). Paths relative to
   `doc_sensor.onedrive_root`. Catches `2_AREAS/Import_Audio/`.
3. **Direct path as argument** — takes precedence.

Supported formats:
- `.txt` — transcript (with or without timestamps)
- `.mp3` / `.m4a` + `.txt` pair — recording + transcript (same base name)
- `.mp4`, `.wav`, `.webm` — audio (requires Whisper transcription)

**Skip rule:** Files in `processed/` subfolders are ignored. Files with
base-name match in `work/archive/days/{YYYY-MM}/` (`{DD}_{HHMM}_*.txt`)
count as already archived — do not re-process, instead mark as
"redundant, can be cleaned up".

**Orphan-audio dedup goes by CONTENT, not basename.** An orphan audio file in
imports (or re-pushed by the worker) is often **not a new meeting** but a
re-push of an already-debriefed recording — and the basename will NOT reveal
that: bundle/transcript names carry the **push date**, not the recording date
(recorders may also stamp the recording *start* time, not the meeting time),
so the same bytes reappear under a different name and slip past every
name-based check. Before any re-transcription or re-debrief, check orphan
audio against the archive via **md5 + byte size**
(`work.audio_archive_dir` under your archive root → `processed/`):

1. For each orphan `.mp3`/`.m4a`, compute `md5` + file size and compare
   against the `processed/` audios. **Never** go by bundle/file date or the
   worker's `recorded_at` (both are push time) — only audio mtime + md5 are
   truth.
2. **Match** (byte-identical) → already processed: trash the dupe, do **not**
   run it through the pipeline; move the redundant worker bundle to
   `_debriefed/`, remove the redundant inbox bundle.
3. Transcripts under the worker's `_debriefed/` folder count as done — never
   re-pull them. Only a true orphan (no md5 match AND no `_debriefed/` entry)
   goes to the transcription worker.

Prevents a redundant overnight re-transcript of an already-archived
recording.

## Reference

For the 7-category insights template and import-rules engine: see this skill's own `references/` (the 7-category structure is defined alongside this workflow). A `work-system` skill, if present as an org overlay, can supply an extended import-rules engine.
Imports folder: configurable via `bridge-config.yaml` → `work.imports_dir` (legacy default: `work/imports/`)

## Workflow

### Phase 1 — Find + read transcripts

Scan both sources (see above):
1. `work.imports_dir` (legacy)
2. `doc_sensor.scan_paths` with `kind: recordings` (PARA tree)

OR use the given path.
Skip `processed/` subfolders and already archived files (base name in
`work/archive/days/{YYYY-MM}/`). Read the transcript in full and analyze.

### Phase 1.5 — Context lookup (optional)

Identical to the full version: capability-based discovery in
`bridge-config.yaml` → `integrations.context_sources.*`. Phase 1.5
needs `calendar` + `chat` (+ optional `calls`); every provider with
`enabled: true` AND a matching `provides:` is queried in parallel.
Window: ±`debrief.context_window_min` (default 30) around the transcript
timestamp (filename or mtime). Provider skill is swappable via the `skill:` field
— no vendor name in the workflow. Details:
`references/full-workflow.md` § Phase 1.5. No matching providers:
skip, continue to Phase 2.

### Phase 2 — Show analysis preview

Right after reading, show a preview:

```
── Meeting analysis ────────────────────────────────────────────────

Date:         29.12.2025, 10:41
Duration:     ~41 minutes
Participants: Alice, Bob
Type:         Internal conversation (example project)
Topics:       File organization with AI, project progress,
              AI-automated development, product vision

── Detected outputs ───────────────────────────────────────────────

| # | Output | Target proposal | Details |
|---|--------|---------------|---------|
| 1 | Insights (7-cat) | work/archive/days/2025-12/29_insights.md | Standard, always |
| 2 | Wiki protocol | wiki/my-org/protocols/2025-12-29-alice-meeting.md | Internal meeting |
| 3 | Issue: document learnings | my-org/wiki #25 | Action Item |
| 4 | Issue: review CLAUDE.md | my-org/codex #20 | Action Item |
| 5 | Archive | work/archive/days/2025-12/ | mp4 + txt |

Action? [Enter=all, numbers=selection, x+numbers=skip]
```

### Phase 3 — User decision

The user can:
- **Enter** = create all proposed outputs
- **Numbers** = only certain ones (e.g. "1,3,5" = Insights + 1 issue + archive)
- **Numbers + correction** = change target (e.g. "2 to wiki/customers/{name}/")
- **x + numbers** = skip

### Phase 4 — Execution

For every confirmed output:

#### Insights (7 categories) — ALWAYS create

Path: `work/archive/days/{YYYY-MM}/{DD}_insights.md`
If file exists: append, do not overwrite.

Format:
```markdown
# Insights {Weekday} {DD.MM.YYYY}

**Transcriptions:**
- HH:MM - [meeting name or topic]

---

## 1. FACTS
## 2. DECISIONS
## 3. PROBLEMS
## 4. CONTRADICTIONS
## 5. ACTION ITEMS
| Who | What | Deadline | Source |
## 6. CONTEXT
## 7. OPEN QUESTIONS

---

## Summary
[1-2 sentences]
```

#### Wiki protocol — when meeting type matches

Create the protocol per the P1-P5 wiki principles.
Path depends on meeting type:
- Customer meeting → `wiki/customers/{customer}/protocols/meetings/YYYY-MM-DD-{title}.md`
- Internal meeting → `wiki/<your-org>/protocols/weekly-meetings/YYYY-MM-DD-{title}.md`
- Workshop → deep processing with goals/tasks document

**IMPORTANT:** Read the wiki CLAUDE.md before writing a protocol (`~/Developer/org/wiki/CLAUDE.md`).

#### GitHub issues — when action items detected

Create issues via `/github-projects-manager` (knows required fields, projects, governance).
Do not use `gh issue create` manually!

Clarify with the user beforehand:
- Which repo? (code bug → operator repo, docs → wiki, cross-cutting → wiki)
- Which project? (#18 CustomerA, #25 Org Operations, #20 Agents & MCPs, etc.)
- Who is the assignee?

#### Archive

**Repo routing first!** Default is `<your-bridge>/work/archive/days/{YYYY-MM}/`,
but switch on customer or lead markers (see `classification.md` §
Target-Repo Routing):

| Marker | Target instead of default |
|---|---|
| CustomerC / their product / their team | `~/Developer/<other-instance>/work/archive/days/{YYYY-MM}/` |
| Application / hourly rate / recruiter / probability | `wiki/leads/{slug}/meetings/{YYYY-MM-DD}_{HHMM}_{topic}.{ext}` |
| Voice memo without value (<60s, no speaker change) | `~/.Trash/` |
| Mixed meeting | Split and route both parts separately |

Move recording + transcript:
- From source → `{target-repo}/work/archive/days/{YYYY-MM}/`
- Rename to: `{DD}_{HHMM}_{short-name}.{ext}`
- Example: `29_1041_call-Bob.mp4`

**Important safety rules** (learned 2026-04-25):
- Always do bulk file renames with **Python**, not zsh regex (`BASH_REMATCH`
  is empty under the zsh tool → captures collapse → data loss).
- Show a dry run with collision detector beforehand.
- `mv -n` (no-clobber) or `pathlib.rename` instead of bare `mv`.
- OneDrive-synced sources: no reliable recycle-bin entry on
  `mv` out → copy locally first or accept Stage-2 recovery.

### Phase 5 — Protocol + work log

1. **PROCESSING-LOG.md** (OneDrive) — entry with full filename, source, target
2. **work/log.md** — work-log entry:
   ```
   | {HH:MM} | Meeting | {context} | {meeting name} → {outputs} |
   ```

## Meeting-type detection

| Type | Detection markers | Standard outputs |
|-----|-------------------|-----------------|
| Customer meeting | Customer name (CustomerA, CustomerB, etc.), external participants | Insights + wiki protocol + issues |
| Internal meeting | Org team only, planning, strategy | Insights + wiki protocol |
| Workshop | Longer than 60min, multiple topics, goals | Insights + wiki + issues + goals document |
| Short call | <15min, 1 topic | Insights only |
| Voice memo | 1 person, thoughts/notes | Insights (compact) |
| Brainstorming | Ideas, concepts, no firm decisions | Insights + optionally wiki |

## Rules

- **HTMLs, PDFs mentioned in the transcript:** Do not auto-process, only reference
- **Full filenames in the log:** No abbreviations, no `...`
- **Always get OK before deleting:** Do not delete original files after archiving without confirmation
- **Wiki protocols:** ALWAYS read `wiki/CLAUDE.md` first for P1-P5 principles and naming
- **Issues:** ALWAYS via the `/github-projects-manager` skill, not manually
