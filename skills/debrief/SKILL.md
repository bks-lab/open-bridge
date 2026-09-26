---
name: debrief
description: >-
  Meeting and transcript processing: classifies meeting type, name
  corrections, extracts insights, generates protocols, proposes tasks.
  Full 8-phase flow (GitHub reconciliation, distribution email) or quick
  5-phase.
  Trigger: "/debrief", "/debrief {path}", "/debrief --quick",
  "/debrief --all", "/debrief --date YYYY-MM-DD", "meeting minutes".
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
- **Fail-soft (hard rule):** worker unreachable (sync script exits non-zero) →
  proceed with whatever is already in imports. A missing or broken worker must
  never block a debrief run.
- **Silent vs. surfaced — these are not the same absence, do not conflate them:**
  - `integrations.transcription.enabled: false` → skip **silently**. A
    deliberate no stays a no; re-asking is nagging.
  - The `integrations.transcription` block **absent entirely** → not a no,
    just no answer yet. Run TWO cheap, read-only checks before choosing
    silence (neither is a scan — both read something already on disk for
    exactly this purpose):
    1. **local** — does [`infra/transcriptions/topology.yaml`](../../infra/transcriptions/README.md)
       resolve a worker (`mode: remote` + `worker.host`, or `mode: local`),
       or does a `sync_script` exist at the conventional path
       (`skills/meeting-transcription/scripts/debrief_sync.sh`)?
    2. **cross-instance** — does `~/.bridge-capabilities/transcription.yaml`
       carry an entry (see [`docs/capability-registry.md`](../../docs/capability-registry.md))?
       This is a **sibling Bridge instance's** opted-in worker on the same
       machine — the case that motivated this split (see issue #105/#107):
       a fully working worker, invisible because it was never registered
       *here*.
    If EITHER check finds something, say **one line** and continue — never
    block, never prompt:
    > Note: a transcription pipeline appears to exist on this machine but
    > isn't registered for this bridge (`integrations.transcription` missing
    > from `bridge-config.yaml`). `/debrief` continues without it —
    > `/bridge-onboard --add transcription` to wire it up.

    When the evidence is a registry entry, name the sibling and be honest
    about its age — no active liveness probe is run (probing would turn a
    read into a scan, which the registry is explicitly designed to avoid):
    an entry with `registered_at` older than ~90 days gets *"last confirmed
    {date} by {registered_by} — verify it's still running"* rather than
    being asserted as current fact.
    If NEITHER check finds anything → stay silent, exactly as today. Most
    users have no worker; noise is worse than silence.

The full worker contract (config block, sync-script verbs, failure semantics,
output format) lives in
[`docs/transcription-worker.md`](../../docs/transcription-worker.md).

## Integration points

- **Transcription worker** (optional, bring-your-own): see § Transcription
  pipeline above + [`docs/transcription-worker.md`](../../docs/transcription-worker.md).
  A full reference implementation ships as `skills/meeting-transcription/`.
- **process-transcription** (global, if installed): owns Org-specific
  participant lists and wiki routing — debrief defers to it.
- **github-projects-manager**: governance + execution for GitHub issues
  created from extracted action items.
- **workflow/projects/{slug}.yaml**: source of truth for issue field values.
