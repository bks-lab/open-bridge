# Debrief — Full 7-phase workflow

The complete checkpoint-based processing pipeline for a meeting transcript.
Each phase completes before the next starts, with user confirmation at the
critical gates.

## Phase 1: Find Transcripts

**Phase 0 — Transcription pickup (config-gated, runs first):** if
`bridge-config.yaml` → `integrations.transcription.enabled: true`, fetch
finished transcripts from the pipeline worker **before** scanning, so they're
present for the Find below.

**The destination is declared in the yaml, not guessed.**
`integrations.transcription.contexts` is a map of `<context> → { imports: <dir> }`
that says **where each context's transcripts must go**: a consumer instance
routes a customer context (e.g. `customer-x`) into its own imports; an operator
instance can route a context into another instance's imports. For **each**
context, resolve its
destination (`imports`, default `work.imports_dir`), expand `~` to an absolute
path, and pull just that one context into it:
```bash
# for each <ctx>: <dest> = integrations.transcription.contexts.<ctx>.imports
#                          (fallback: work.imports_dir)
BRIDGE_IMPORTS="<abs <dest>>" TRANSCRIBE_CONTEXTS="<ctx>" \
  "<integrations.transcription.sync_script>" pull
```
(Legacy list form `contexts: [a, b]` → all route into `work.imports_dir`.)

It lands transcripts as `<context>-<name>.md` (idempotent — the worker moves
each to `_debriefed/` so it's pulled once). The context prefix also drives
downstream routing (`<customer>-*` → customer repo per your rules; `<org>-*` → internal).
Skip silently if the integration is disabled, and continue gracefully if the
worker is unreachable (the script exits non-zero — just proceed with whatever is
already in imports). The reverse `push` direction (handing un-transcribed audio
found in the scan to the pipeline) is described in SKILL.md § Transcription
pipeline.

If no path argument, scan **all** of these sources (deduplicate by filename):

1. **Legacy imports dir** — `bridge-config.yaml` → `work.imports_dir`
   (path relative to repo root). If key missing, fall back to `work/imports/`.
2. **PARA recordings sources** — read `bridge-config.yaml` → `doc_sensor.scan_paths[*]`
   and include every entry where `kind: recordings` (or label contains "Audio").
   Resolve paths relative to `doc_sensor.onedrive_root` (the PARA tree root).
   This catches `2_AREAS/Import_Audio/` after the PARA migration.
3. **Optional fallback search** (only if above two yield nothing):
   `~/Desktop/`, `~/Downloads/`, `~/Library/Application Support/com.apple.voicememos/`,
   sibling Bridge instances' `work/tasks/*/transcripts/`, `work/streams/*/transcripts/`.

Match patterns: `*.mp3`, `*.m4a`, `*.wav`, `*.webm`, `*.txt`, `*.md`, `*.vtt`, `*.srt`.

For audio/text **pairs** (same basename, different extension): treat as one item
(e.g. `Voice Chat 20260331 1020.mp3` + `20260331 1020 Transcription.txt`).

**Skip already-processed files**: ignore anything in a `processed/` subfolder
of any source. Cross-check filenames against `work/archive/days/{YYYY-MM}/` —
if `{DD}_{HHMM}_*.txt` already exists with matching basename, mark as
"already archived, original redundant" and offer cleanup instead of re-processing.

**Orphan-audio dedup is by CONTENT, not basename.** An audio found in imports
(or pushed back from the worker) is frequently a re-push of a recording that was
already debriefed — and the basename will NOT reveal it: bundle/transcript names
carry the **push date**, not the record date (and Audio Hijack stamps the
recording *start*, not the meeting time), so the same bytes show up under a
different name and slip past every name-based check above. Before re-transcribing
or re-debriefing **any** orphan audio, dedup by **md5 + byte-size** against the
PARA processed/ archive (`work.audio_archive_dir` under `doc_sensor.onedrive_root`
→ the `processed/` audio store):

1. For each orphan `.mp3`/`.m4a`, compute `md5` + `stat -f %z` and compare against
   the archived audios in `processed/`. **Never** trust the bundle/file date or
   the worker manifest `recorded_at` (both are push-time) — the audio's mtime + md5
   are the only truth.
2. **Match** (byte-identical) → already processed: trash the dupe, do **not** send
   it through the pipeline. Move the redundant worker bundle to `_debriefed/` and
   drop the redundant inbox bundle.
3. Also treat any transcript already under `~/Transcripts/<ctx>/_debriefed/` as
   done — never re-pull it. Only a true orphan (no md5 match **and** no
   `_debriefed/` entry) goes to the `meeting-transcription` worker.

This prevents a redundant re-transcript of a meeting that was already archived.

4. If import-rules enabled (`work.import_rules: true`):
   read `work/import-rules.yaml` for custom patterns
5. List found files in a preview table, confirm which to process

If path provided: use that file directly.

## Phase 1.5: Context Lookup (optional, capability-based)

`/debrief` declares the capabilities it needs:

| Phase 1.5 needs | Why |
|---|---|
| `calendar` | Authoritative attendees + event subject for Phase 2 / Phase 7 |
| `chat` | Action-item-flagged messages around meeting time for Phase 4 |
| `calls` | Optional — call participants when calendar event missing |

Discover providers in `bridge-config.yaml` →
`integrations.context_sources.*` where `enabled: true` AND `provides`
intersects the needed capability set. The provider's `skill:` field
names the installed skill that performs the pull. **No provider name
is hardcoded here** — same provider-fan-out pattern as Stream B
(trackers): a new provider is just a new config block, no workflow
code change.

**Window**: ±`debrief.context_window_min` minutes around the transcript
timestamp. Default: 30. Override per instance via top-level
`debrief.context_window_min:` in `bridge-config.yaml`.

**Window detection** (in priority order):

1. Filename timestamp pattern: `YYYYMMDD HHMM`, `YYYY-MM-DD HHMM`,
   `YYYY-MM-DD HH-MM-SS`, `{DD}_{HHMM}_*`
2. Audio/text file mtime (last-modified) when no pattern matches
3. Skip Phase 1.5 if neither resolves to a usable timestamp

**Per-capability fan-out** (in parallel, 10s timeout per provider):

| Capability | Pull behaviour | Extract |
|---|---|---|
| `calendar` | events overlapping the window via configured skill | event subject, organizer, required + optional attendees |
| `chat` | messages in `[t − window, t + window]` | participants, action-item-flagged messages, links |
| `calls` | call records in the same window | call participants, duration |

If multiple providers expose the same capability (e.g. both `outlook`
and `google` provide `calendar`), merge their results and deduplicate
by event id / message hash. If a provider's CLI/skill is missing or
unauthenticated → warning, skip that provider, continue. **Never abort
`/debrief` for a context-lookup failure.**

**Surface a compact preview before Checkpoint 1:**

```
Phase 1.5 context for {transcript-filename} @ {timestamp}:
  calendar: "{event subject}" — organizer: {name}, {N} attendees ({absent} absent)
  chat:     {N} call(s), {M} flagged messages in {window_min}min window
  [y] use as ground-truth  [s] skip context  [e] edit
```

**Phase 2 consumes this** as ground-truth anchors:
- Real attendees override Whisper-detected names → less reliance on
  `name-corrections.yaml` heuristics
- Calendar event subject seeds the slug + target-repo routing decision
- Calendar organizer becomes default `distribution_mandant` candidate
  for Phase 7

**Phase 4 consumes this** for the Context category (#6) — chat snippets
and call participant context that don't appear in the transcript itself.

**No matching providers** → skip Phase 1.5 silently and proceed to
Phase 2 with transcript-only inputs (legacy behaviour).

### Flags (batch modes)

| Flag | Behavior |
|------|----------|
| `--all` | Process **every** unprocessed transcript in imports/ in one run. After Phase 2 classification, present a single confirmation table for all files; user can deselect individuals before continuing. Useful for catching up after a few days/weeks. |
| `--date YYYY-MM-DD` | Process only transcripts whose filename starts with that date (matches `YYYYMMDD` or `YYYY-MM-DD` prefix patterns). |
| `--quick` | Switch to 5-phase quick-workflow (no task-reconciliation, no email, no formal protocol). |

`--all` and `--date` can combine with `--quick` for fast batch processing
of personal voice memos. They don't combine with `{path}` — when a path
is given, only that file is processed.

## Phase 2: Classify Meeting Type

Read `classification.md` for the full classification rules, workshop signals
regex, and participant detection logic.

Present **Checkpoint 1** (classification review) before proceeding.

## Phase 3: Apply Name Corrections

Read `classification.md` § Name Corrections for the correction categories and
`work/name-corrections.yaml` format. If `work/name-corrections.yaml` does not
exist, skip the file-based step (do not invent corrections).

**Resolve the context first.** Take the transcript's `<prefix>-` (`acme-2026-…`
→ `acme`) and map it to a workflow context: use
`integrations.transcription.contexts.<prefix>.context` if set, otherwise the
prefix itself (so `acme` → `workflow/contexts/acme.yaml`; a transcription context
named differently from its workflow context — e.g. `customer-x` → `customer-x-project` —
declares the link via that `context:` field, not by assuming equal names). Load
`workflow/contexts/<resolved>.yaml` if it exists and apply its `roster[].aliases`
+ `entities[].aliases` as corrections (e.g. a misheard surname mapped to its
canonical spelling, or a first-name variant normalised). These are the
per-context source of truth, kept in sync with the
transcriber's voice library, and take precedence over the cross-context
canonical list in `classification.md`. The resolved context's `entities[].task`
/ `.project` are carried into Phase 5 as reconciliation hints. If the context
defines no `meeting_protocol_routing` (e.g. an ADO-tracked client whose protocols
live in a work archive, not a wiki tree), Phase 6 falls back to generic
behaviour — do not force a wiki path.

## Phase 4: 7-Category Insight Extraction

Analyze the transcript and extract:

| Category | What to Extract |
|----------|----------------|
| **Facts** | Stated facts, numbers, dates, names |
| **Decisions** | What was decided, by whom, with what rationale |
| **Problems** | Issues raised, blockers, complaints |
| **Contradictions** | Conflicting statements or requirements |
| **Action Items** | Who does what by when (explicit commitments) |
| **Context** | Background information that explains decisions |
| **Open Questions** | Unresolved questions that need follow-up |

### Daily Insights Aggregation (NEW)

Extracted insights are also **appended** to the day-aggregate file
`work/archive/days/{YYYY-MM}/{DD}_insights.md` (target-repo-aware — see
Phase 8). This file collects every meeting's insights for one day so
`/briefing` and `/archive` can show what happened that day at a glance.

Format (create if missing, append if exists):

```markdown
# Insights {Weekday} {DD.MM.YYYY}

**Transcriptions:**
- {HH:MM} — {meeting-type}: {slug-topic}

---

## {HH:MM} — {meeting-type-label}

### 1. FACTS
- ...
### 2. DECISIONS
- ...
### 3. PROBLEMS
- ...
### 4. CONTRADICTIONS
- ...
### 5. ACTION ITEMS
| Who | What | Deadline | Source |
|---|---|---|---|
| ... | ... | ... | this transcript |
### 6. CONTEXT
- ...
### 7. OPEN QUESTIONS
- ...

---
```

When multiple meetings on same day → append a new `## {HH:MM} — …` block;
do not rewrite existing blocks. The header `Transcriptions:` list grows too.

This is in addition to (not replacement of) Phase 6 protocol generation —
the protocol is the formal artifact for the wiki, the insights file is the
working log for the day.

## Phase 5: Task Reconciliation + Execute (Checkpoint 2)

Read `references/task-reconciliation.md` for the full flow. Summary:

1. Pre-load open issues from `reconcile_projects` (from classification config
   **and** the resolved context's `reconcile_projects`).
2. Score matches between action items and existing issues.
3. Build decision matrix (UPDATE/CREATE/REASSIGN/SKIP) with **minimum principle**:
   aim for 1–5 operations per meeting, group related micro-tasks into one
   comment on the parent issue rather than splitting.
4. Present **Checkpoint 2** — the matrix with WAS / WARUM / ASSIGNEE columns.
5. On `[y]`: execute approved operations (gh api + issue comments + assignees).
6. Return `updated_issues[]` and `new_issues[]` with URLs for later phases.

### 5a. Reconcile against EXISTING local tasks (not just GitHub issues)

GitHub-issue reconciliation alone misses local `work/tasks/*` tasks —
especially `bridge_only` ones (e.g. `example-project`) and any topic the
meeting only *mentions*. Do this in addition to the issue matrix:

1. **Entity hits (config):** for each `entities[]` from the resolved context
   whose name (or alias) appears in the transcript, the entity's `task:` names
   the existing local task it maps to.
2. **Discovery (no config):** scan `work/tasks/*/STATUS.md` + `work/streams/*/STATUS.md` + `work/board.md`
   for slug / stakeholder / keyword matches against the meeting's topics and
   action items — same matching as `rules/task-management-workflow.md`
   Active-task-check.
3. For each hit, add a matrix row whose op is **UPDATE-LOCAL** (append a dated
   note / cross-link to that task's STATUS.md) or **WIKI-XREF** (cross-reference
   in the related wiki area) — distinct from CREATE. A bare mention that is a
   *different* engagement than the task's focus → propose a clearly-labelled
   side-note, not a merge (let the user decide; never auto-merge unrelated work).
4. Surface these rows in the **same Checkpoint 2** matrix, so creating a new
   task, updating GitHub issues, and cross-linking existing local tasks are all
   one approval. **Do not** finish a debrief having created only a new task
   while silently ignoring the existing tasks the meeting touched.

Hard rule: this phase runs **before** Phase 6 protocol generation, so the
protocol can reference the real issue URLs.

## Phase 6: Generate Protocol

Read `protocol-templates.md` for the 4 depth-based templates (Full, Workshop,
Standard, Minimal) and their structure.

**Resolve the wiki path from the context, do not guess.** If the resolved
context (Phase 3) defines `meeting_protocol_routing`, the protocol path is
`<sync.defaults.wiki.root>/<meeting_protocol_routing[<classification>]>/<slug>.md`
— e.g. an internal strategy session → `<wiki>/protocols/strategy-meetings/`,
a team-weekly → `…/weekly-meetings/`, an ad-hoc one-on-one sync (`internal-sync`)
→ `…/protocols/` (top-level). Touch the routing map's `_index` MOC. Match the
frontmatter + section shape of the **existing neighbour protocols** in that
folder. Only fall back to the generic `wiki_path` from `classification.md`
when the context defines no routing map. The wiki target repo for an internal
context is the one declared in the context's `sync.defaults.wiki.repo`
(org-internal data → org wiki) — never hardcoded here.

Embed the **real URLs** from Phase 5 in the protocol (related_issues
frontmatter + inline references in Action Items table). If protocol is
written before Phase 5 updates land, links will be broken.

**Org topics are wiki-obligated (`work.meetings.tracked_obligations.wiki_protocol`).**
When the resolved context's `scope == org` (per `required_for_scopes`), this meeting
**owes a wiki protocol** — the *relevant parts* (decisions, action items, the key
discussion topics — NOT the full transcript), written to the context's wiki
(`sync.defaults.wiki.repo` + `meeting_protocol_routing`). Two hard rules:

- **Source-pointer:** every org protocol carries a `source:`
  line pointing back to the **archived original** (audio + naked transcript paths from
  `work.meetings.raw_record_dir`) **and** the `summary.md` — so a reader can trace
  any claim to the recording. Never embed the full transcript in the wiki.
- **Track + don't force:** writing to the shared wiki is **gated** (`write_is_gated`)
  — a deliberate push, never an auto-flood. If you write it now, set the summary.md
  frontmatter `wiki: { status: done, repo: …, path: … }`. If there's **no time**
  (capture-only debrief), set `wiki: { status: pending }` — the **/briefing** then
  surfaces it as a missing org protocol (workflow Stream A 5b) so it is never lost.
  Same model for tasks: extracted now (Phase 5) → `tasks: { status: done }`, deferred
  → `tasks: { status: pending }` + a `triage.md`, which /briefing also surfaces.

This is the answer to "debrief = capture, briefing = remind": a debrief MAY go deep
(Phase 5 tasks + Phase 6 protocol) or stay shallow (capture + set both statuses
`pending`); either way the obligations are tracked in the summary frontmatter and
the briefing is the safety-net.

### Gold-Standard Meeting Protocol Output

For customer calls (and internal follow-ups), build a per-meeting home with
transcripts co-located, run the anchoring tool, then write `summary.md` from
the template — every claim carries a one-click evidence link.

**1. Build the meeting home and co-locate transcripts.**

```
work/tasks/_meetings/<YYYY-MM-DD>-<slug>/
  transcript-call.md        ← customer call (copied here, not just an archive pointer)
  transcript-internal.md    ← internal follow-up, if one exists (optional)
  summary.md                ← produced in steps below
```

`work.meetings.home_dir` in `bridge-config.yaml` may override the `work/tasks/_meetings/`
prefix. The originals (audio + naked transcript) stay in the external archive (`record:`
frontmatter points there); the co-located copies here are what the summary links into —
a deliberate exception to the Phase 8 pointer-only rule, scoped to gold-protocol meetings.

**2. Anchor the transcripts.**

```bash
python skills/debrief/scripts/anchor_transcript.py \
  <home>/transcript-call.md <home>/transcript-internal.md --prefix c i
```

This is a **mechanical bridge-side transform** — it rewrites each utterance in-place
with a stable anchor `<a name="c-NNN"></a>` and a relative timestamp `[+MM:SS]`,
and writes `transcript-call.index.tsv` / `transcript-internal.index.tsv`
(columns: `anchor ⇥ rel ⇥ speaker ⇥ text`). Idempotent. The worker merge stays
untouched. Interpretation always happens in-session (hard rule).

**3. Write `summary.md` from `work/templates/meeting-gold-summary.md`.**

Fixed section order — never reorder:

```
## Contents           (TOC → anchor links to the five sections below)
## Short Summary      (3–5 sentences; load-bearing statements already linked)
## Detailed Summary   (prose, every claim linked)
## Facts              (table: # | Fact/Decision | Evidence)
## Recommended Tasks  (table: # | Task | Owner | Evidence | Issue/Task)
## Sources
```

**Evidence-link convention — every claim, no exceptions:**

```markdown
[↪ Speaker +mm:ss](transcript-call.md#c-NNN)
```

Resolve `c-NNN` from the `.index.tsv` sidecar: grep the statement keyword →
read the `anchor` column of the matching row. Use `i-NNN` for claims from
`transcript-internal.md`. Never leave a claim unlinked.

**Issue/Task column:** leave `—` when the row is first written; fill with the
GitHub issue URL once the task is created via `github-projects-manager` (Phase 5
runs before this step for exactly that reason — real URLs are available here).

**Worked example shape:** a meeting home like
`work/tasks/_meetings/<date>-<slug>/` containing `summary.md` plus the
co-located anchored transcripts.

Optionally mirror the gold summary into your knowledge repo if your context
defines one (then set the summary's `wiki:` frontmatter to `done` + url).

## Phase 7: Distribution Email (optional)

Read `references/distribution-email.md` for the full flow. Triggered when:
- `meeting_types.{type}.distribution.email: true` in classification config, OR
- user flag `--email`

Summary:
1. Resolve recipients from `identity/mandants/{distribution_mandant}.yaml` — only
   **participants**, never absent team members.
2. Build compact body (< 60 lines) with live issue URLs from Phase 5.
3. Write drafts at `work/drafts/emails/{date}-{slug}.{md,txt}`.
4. **Checkpoint 3:** `[s]` send via your mail skill (org overlay, optional) · `[o]` open Apple Mail draft
   · `[k]` keep as draft · `[e]` edit first. Default recommendation: `[o]`
   (human-in-the-loop for visible-to-others actions).

## Phase 8: Update Task Management + Archive

> **Layout-SoT:** every path in this phase comes from `work.meetings.*` in
> `bridge-config.yaml` (the central meeting-layout prescription). Do not hardcode —
> read `raw_record_dir`, `home_dir`, `summary_file`, `triage_file`, `insights_dir`,
> `summary_format`. This keeps the worker, /debrief and /briefing on one structure.

1. Add log entry to `work/log.md`. Pick the type emoji from
   `bridge-config.yaml → activity_types` (fallback `📝` if not configured):
   ```
   | {time} | {emoji} | {context} | /debrief: {filename} — {n} updates, {n} creates, email {s|o|k} |
   ```
2. For any action item that became neither an issue nor a calendar entry,
   add a TODO line to log.md under the current day-block.
2b. **PROCESSING-LOG.md (OneDrive)** — if `${onedrive_root}/PROCESSING-LOG.md`
   exists, append an audit-trail line with full source filename, full target path,
   and a one-line summary. Cross-system trail for documents that originated from
   the OneDrive doc-system pipeline.
3. Determine **target repo** from the routing decision in Phase 2 (see
   `classification.md` § Target-Repo Routing). Default = current repo's
   `work/archive/days/{YYYY-MM}/`. Customer-specific transcripts route to the
   resolved context's `target_instance` (e.g. a customer-x-context meeting → that
   instance) and lead interviews (`wiki/leads/{slug}/meetings/`) override the
   default.
4. Propose archiving. **The worker delivers a NAKED transcript
   (no `claude -p` summary) and the summary is produced HERE in-session,
   context-aware** (name-conventions, ecosystem, board, open issues, contexts,
   prior meetings). The three artifacts go to three homes:
   - **Naked transcript + audio → PARA, PAIRED, OUTSIDE the repo** (the immutable,
     reusable meeting record = the recoverable "original"; in the backup, repo
     stays lean). Path = `work.meetings.raw_record_dir` (relative to
     `doc_sensor.onedrive_root` = PARA root; expand it). **Same stem for both**
     (`work.meetings.transcript_pairing: paired`): `{YYYY-MM-DD}_{HHMM}_{slug}.mp3`
     (audio) + `…{slug}.md` (naked transcript, frontmatter `type:
     work.meetings.transcript_type`). **Always RENAME descriptively** — never the
     raw source name (`Voice Chat 20260603 1506.mp3`). `processed/` is scanner-skipped.
   - **Context-aware summary → `{home_dir}/{YYYY-MM-DD}-{slug}/{summary_file}`**
     (`work.meetings.home_dir` + `summary_file`, i.e. `…/summary.md`), in the
     **`themen-toc` format** (`work.meetings.summary_format`): a topic
     table-of-contents (topics + time ranges) at the very top, then TL;DR ·
     decisions · action items · topics in detail · open questions. Frontmatter
     `record:` points to the PARA audio + transcript (pointer-only — the transcript
     is NOT copied into the repo). Mark it *"do not share 1:1 — regenerable"*;
     sharing is a deliberate, audience-filtered step. **Never fuse
     summary+transcript into one repo file** (old behaviour).
   - **Tasks → triage**: `{home_dir}/{YYYY-MM-DD}-{slug}/{triage_file}`
     (`work.meetings.triage_file`, i.e. `…/triage.md`, `status: pending-triage`).
     A debrief CAPTURES; the **/briefing** surfaces the open points and is where
     you DECIDE them — do not force task decisions here.
   **Never trash the source audio**: always MOVE the mp3/m4a
   into the PARA archive, even when the worker holds a copy. The naked transcript
   often survives only on the worker bundle (`transcript-raw.md`) — `scp` it into
   PARA alongside the audio. The `~/.Trash/` route is for worthless voice memos
   only (<60s, no speaker change), never for meetings. Use Python + collision-check
   for bulk moves (zsh-regex trap), never overwrite an existing target.
5. Update the **daily insights file** at `{target_repo}/{work.meetings.insights_dir}/{YYYY-MM}/{DD}_insights.md`
   (append the per-meeting insights block from Phase 4) — small, in-repo, what
   `/briefing` + `/archive` parse. Its `source:` line points at the archived naked
   transcript + the `summary.md` (NOT a repo-local transcript copy). (The bulky
   naked transcript itself lives in PARA, not here.)
6. Never move without `[a]` confirmation — user may want to re-run the flow.

### Bulk-Move Safety Rules

When moving multiple files in this phase:
- **Use Python**, not zsh-Regex. The Bash tool runs zsh; `BASH_REMATCH` is
  always empty there → captures collapse, all targets become `_.txt` →
  silent overwrite chain → data loss.
- **Dry-run with collision detector first**: build the full target list,
  check `target.exists()` for each, show user a confirmation table, only
  then execute.
- **`mv -n` (no-clobber)** for shell calls; `pathlib.rename` raises on
  existing target by default — both safer than plain `mv`.
- **OneDrive-synced source folders**: `mv` out of OneDrive does NOT
  reliably create a recycle-bin entry on macOS Tahoe + FileProvider.
  Before bulk-moving from OneDrive, copy locally first or accept that
  recovery requires the SharePoint Stage-2 admin recycle bin.

## Example output sketch (team-weekly, 8 phases with checkpoints)

```
→ transcript: {imports_dir}/20260101 0900 Transcription.txt
✓ Phase 2 classification: team-weekly, 4 participants (charlie absent)
  [y] continue  [e] edit  [c] cancel  > y
✓ Phase 3 name-corrections applied: Sammy→Sam, Rob→Robin
✓ Phase 4 extraction: 12 facts · 4 decisions · 8 actions · 2 open questions
  Phase 5 reconciliation (Project #7):
    # | Op     | Target | Action item                | Ass.     | Reason
    1 | UPDATE | #42    | Example issue A            | alice    | HI match, status change
    2 | UPDATE | #41    | Example issue B            | alice    | HI match, dep on #42
    3 | UPDATE | #38    | Example issue C (3 combined)| bob     | MED match, via comment
  [y] alle / [e N] edit / [s N] skip  > y
✓ Phase 5 executed: 3 updates applied (2 field changes, 3 comments)
✓ Phase 6 protocol written: wiki/{org}/protocols/weekly-meetings/{YYYY-MM-DD}-weekly.md
✓ Phase 7 email draft: work/drafts/emails/{YYYY-MM-DD}-weekly-summary.md
  [s] send / [o] Apple Mail draft / [k] keep / [e] edit  > o
✓ Phase 7 Apple Mail draft opened (4 recipients, charlie excluded)
✓ Phase 8 log.md updated · audio+naked transcript → PARA (paired) · summary.md (themen-toc) + triage.md → _meetings/{YYYY-MM-DD}-weekly/ · insights → days/{YYYY-MM}/{DD}_insights.md
```

## Import Rules (optional)

If `work.import_rules: true` in bridge-config.yaml, read `work/import-rules.yaml`:

```yaml
rules:
  - pattern: "weekly-*.m4a"
    action: debrief
    context: internal
    auto_tasks: true

  - pattern: "client-*.txt"
    action: debrief
    context: customer
    auto_tasks: true

  - pattern: "*.pdf"
    action: file
    destination: docs/
```

## Integration

- **process-transcription** (global skill, if installed): Handles org-specific
  participant lists, wiki directory routing, and customer-specific templates.
  When present, debrief defers meeting classification and protocol routing to it.
- **project-advisor**: Provides governance rules and execution patterns for
  GitHub issue creation from extracted tasks.
- **Project Registry** (`workflow/projects/*.yaml`): Source of truth for field values
  when creating GitHub issues from meeting action items.
