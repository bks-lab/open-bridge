---
name: debrief
description: 'Meeting and transcript processing — classifies meeting type, applies name corrections, extracts insights across 7 categories, generates protocols, proposes tasks with project field mapping. Checkpoint-based workflow. Supports full 8-phase flow (with GitHub reconciliation + distribution email) and quick 5-phase flow; `--all` and `--date YYYY-MM-DD` batch flags absorb the former /process-meeting. Trigger: "/debrief", "/debrief {path}", "/debrief --quick", "/debrief --all", "/debrief --date YYYY-MM-DD", "process meeting", "transcript processing", "create minutes", "process-meeting", "meeting minutes", "process transcript".'
metadata:
  scope: core
---

# Debrief

Process a meeting transcript. Read the referenced file ONLY when triggered.

## Sources and flow variants

Sources scanned: legacy `work.imports_dir` plus `doc_sensor.scan_paths` entries with
`kind: recordings` (catches PARA tree `2_AREAS/Import_Audio/` after the PARA migration).
Already-archived basenames in `work/archive/days/` are skipped as redundant.

Flow variants:

- **Full 8-phase flow** (`references/full-workflow.md`) with GitHub task-reconciliation
  (`references/task-reconciliation.md`) and optional distribution email
  (`references/distribution-email.md`) to meeting participants.
- **Quick 5-phase flow** (`references/quick-workflow.md`).
- **Batch flags:** `--all` processes every unprocessed transcript in `imports/`; `--date YYYY-MM-DD`
  processes only that day. (Both formerly lived in `/process-meeting`, now merged here.)

## Decision Tree

```
User wants to...
├── Full processing (8 phases)              → Read references/full-workflow.md
├── Quick processing (5 phases)             → Read references/quick-workflow.md
├── Classify a transcript only              → Read references/classification.md
├── Apply name corrections                  → Read references/classification.md (§ Name Corrections)
├── Generate a protocol from notes          → Read references/protocol-templates.md
├── Match actions to existing issues        → Read references/task-reconciliation.md
│                                             (called from Phase 5)
├── Pull calendar/chat context for transcript → Read references/full-workflow.md § Phase 1.5
│                                             (driven by integrations.meeting_context.*)
├── Send meeting summary email              → Read references/distribution-email.md
│                                             (called from Phase 7, after updates + protocol)
└── Questions about debrief                 → Answer from this file
```

## Phase order (hard rule)

1. Find → **1.5. Context Lookup** (only if any
`integrations.meeting_context.*` block in `bridge-config.yaml` is enabled
with `consumers: [debrief]`) → 2. Classify + corrections → 3. Extract →
4. (n/a — merged into 3) → **5. Task Reconciliation + Execute** →
**6. Protocol** → **7. Distribution Email** → **8. Work-log + Archive**

Updates **before** protocol (so wiki has real URLs). Protocol **before** email
(so email links to real issue updates AND the written wiki page). Email
**before** archive (so transcript is still next to the workflow).

## Flow selector

| Flag | Flow | When to use |
|------|------|-------------|
| `(none)` | Full 7-phase | Meetings with stakeholders, decisions, action items. Protocol required. |
| `--quick` | Quick 5-phase | Loose notes, personal debriefs, no formal protocol needed. |
| `{path}` | Full or quick | Path to transcript file. Flow selection via other flags. |

Both flows are checkpoint-gated — user confirms at classification and task
creation. Neither flow writes to GitHub, wiki, or archive without explicit `[y]`.

## Transcription pipeline (optional)

Debrief consumes transcripts; it does **not** transcribe. A transcription
worker is an optional integration — never a dependency:

- **No worker configured** (the default): transcribe with any tool and drop
  the transcript (or the audio + transcript pair, same basename) into imports —
  the Find phase picks it up. Nothing else is required.
- **Worker configured** (`integrations.transcription.enabled: true` in
  `bridge-config.yaml`): Phase 0 pulls finished transcripts via the
  `sync_script` before scanning (`pull`), and the Find phase may hand
  un-transcribed audio back to the worker (`push`).
- **Fail-soft (hard rule):** integration disabled → skip silently; worker
  unreachable (sync script exits non-zero) → proceed with whatever is already
  in imports. A missing or broken worker must never block a debrief run.

The full worker contract (config block, sync-script verbs, failure semantics,
output format) lives in
[`docs/transcription-worker.md`](../../docs/transcription-worker.md).

## Integration points

- **Transcription worker** (optional, bring-your-own): see § Transcription
  pipeline above + [`docs/transcription-worker.md`](../../docs/transcription-worker.md).
- **process-transcription** (global, if installed): owns Org-specific
  participant lists and wiki routing — debrief defers to it.
- **project-advisor**: governance + execution for GitHub issues created from
  extracted action items.
- **workflow/projects/{slug}.yaml**: source of truth for issue field values.
