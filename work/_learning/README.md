---
summary: "Aggregation layer of the Bridge Learning-Loop — where postmortems, proposals, audit-history, trigger-corrections live before /bridge-learn surfaces them for review."
type: readme
last_updated: 2026-05-13
related:
  - ../../skills/task-close-postmortem/SKILL.md
  - ../../protocols/standing-orders/task-sync.md
---

# work/_learning/ — Aggregation Layer

This folder is the **middle layer** of the Bridge Learning-Loop architecture.

```
Layer 1 — CAPTURE (existing)
  log.md, /bridge-audit, MEMORY.md, /debrief, STATUS.md
                          │
                          ▼
Layer 2 — AGGREGATION (you are here)
  work/_learning/
                          │
                          ▼
Layer 3 — PROPOSAL EDGE
  /bridge-learn (Phase 2 of rollout)
```

Nothing here is mutated by a human directly except in two cases:
- `audit-trail.md` — when `/bridge-learn` records accept/reject (it writes,
  not the user)
- Initial folder bootstrapping (you reading this, after Phase 1 setup)

Everything else is written by automation:
- `postmortems/<slug>.md` ← copied here when task closes (from work/done/)
- `proposals/*.md` ← written by `task-close-postmortem` skill
- `audit-history/*.json` ← written by `/bridge-audit` (Phase 3)
- `trigger-corrections.md` ← appended by Claude when user corrects (Phase 4)
- `skill-usage.jsonl` ← appended by PostToolUse hook (Phase 4, opt-in)

## Layout

```
work/_learning/
├── README.md                           ← this file
├── postmortems/                        ← one MD per closed task (auto-copied)
│   └── <task-slug>.md
├── proposals/                          ← one MD per improvement candidate
│   ├── <YYYY-MM-DD>-<task-slug>-<topic>.md     ← status: pending
│   ├── accepted/                                ← /bridge-learn moves here
│   └── rejected/                                ← /bridge-learn moves here
├── audit-history/                      ← Phase 3, one JSON per /bridge-audit run
│   └── <YYYY-MM-DD-HHMM>.json
├── trigger-corrections.md              ← Phase 4, append-only
├── skill-usage.jsonl                   ← Phase 4 opt-in, append-only
└── audit-trail.md                      ← /bridge-learn writes accept/reject log
```

## Scope (USER, not CORE)

Everything in `work/_learning/` is **USER scope**:
- contains task-specific reflections (often with customer references)
- contains user-language trigger-corrections (private speech patterns)
- contains usage telemetry (privacy)

**Promote rules:**
- `.gitignore` for shared Bridge variants (open-bridge, your org overlay): exclude
  `work/_learning/postmortems/`, `audit-history/`, `trigger-corrections.md`,
  `skill-usage.jsonl`, `audit-trail.md`.
- `proposals/*.md` with `scope: core` get cherry-picked by `/bridge-sync`
  separately — but the proposal file ITSELF stays in USER scope; only the
  diff it describes lands in CORE.
- The personal/seed Bridge instance keeps everything for full trend analysis.

## Proposal lifecycle

```
pending → accepted   → implemented    (commit lands on user/<name>)
pending → rejected                    (moved to proposals/rejected/ with reason)
pending → deferred                    (re-surfaced by /bridge-learn later)
pending → superseded                  (newer proposal covers same target)
```

Status transitions are recorded in `audit-trail.md` with:
- timestamp
- proposal id
- old → new status
- user-supplied reason (if any)
- linked commit hash (for `implemented`)

## How a proposal gets here

**Source 1 — Task close (Phase 1, live):**

User says "task fertig" → `task-sync.md` Phase 3b → `task-close-postmortem`
skill runs 6-question script → maps `bridge_gaps[]` answers + free-text Q6
to proposal files in `proposals/`.

**Source 2 — Recurring audit findings (Phase 3, planned):**

`/bridge-audit` writes JSON to `audit-history/`. Trend-detection script
compares last N runs; same fingerprint in ≥3 consecutive runs auto-generates
a proposal with `source.type: audit-recurring`.

**Source 3 — Trigger corrections (Phase 4, planned):**

User says "ich wollte Skill X, du hast Y geladen". Claude appends to
`trigger-corrections.md`. After 2+ corrections for the same skill, a
proposal lands with `source.type: trigger-correction`.

**Source 4 — Manual (always):**

User runs `/bridge-learn create` (or writes a proposal file directly with
correct schema). `source.type: manual`. Useful for "I noticed this in a
conversation, capture it for review later".

## How a proposal gets out

`/bridge-learn` (Phase 2) is the review skill. It:
- lists all `proposals/*.md` with `status: pending`
- groups by severity (P0/P1 surface first)
- offers per-proposal accept / reject / edit / defer
- on accept: applies the diff_preview (or asks user to write the diff),
  moves the proposal file to `proposals/accepted/`, logs to `audit-trail.md`,
  suggests a commit message
- on reject: prompts for 1-line reason, moves to `proposals/rejected/`, logs

## What is NOT here

- ❌ MEMORY.md — that's a separate system, see CLAUDE.md § Auto Memory.
  Proposals MAY suggest a memory entry via `target.type: memory`, but the
  actual write to MEMORY.md happens human-approved later.
- ❌ Per-skill telemetry beyond invocation count — privacy + signal-to-noise.
- ❌ Cross-instance learning — only this Bridge instance learns over itself.
- ❌ Auto-applied changes — every Bridge edit requires user approval through
  `/bridge-learn`.

## Bootstrap state (2026-05-13)

Folders are present but empty. First proposals appear after first task close
with the postmortem skill active. `audit-history/` populates only after
`/bridge-audit` learns to write its findings here (Phase 3).
