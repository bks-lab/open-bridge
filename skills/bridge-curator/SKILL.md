---
name: bridge-curator
description: >-
  Periodic background consolidation pass over the Bridge itself. Three phases:
  (1) Library pass — scans skills/, protocols/, rules/, docs/ for drift
  (sleeping skills 30d+, overlapping triggers, description-budget busters,
  duplicates, umbrella candidates); (2) Queue pass — scans work/_learning/proposals/
  for stale pending (30d+), conflict clusters (same target), supersedes
  relations; (3) User-pattern pass — synthesizes 3-8 bullet observations
  about user preferences from postmortems + audit-trail + trigger-corrections
  of the last 30 days, writes append-only to
  work/_learning/user-patterns.md. All findings land as proposals
  (source.type=curator-suggestion) in work/_learning/proposals/ — **never
  direct edits to Bridge files**. Trigger: "/bridge-curator", "bridge curator",
  "curator", "curation", "weekly review", "library consolidation",
  "consolidate skills", "what patterns do I have", "user pattern synthesis",
  "consolidate", "skill consolidation", "umbrella skill".
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
metadata:
  scope: core
---

# Bridge Curator

`bridge-curator` is the periodic background-reflection skill. Once a week
(configurable), it walks the Bridge's own state and asks three orthogonal
questions:

1. **Is the skill library still coherent?** (Library pass)
2. **Is the proposal queue still actionable?** (Queue pass)
3. **What has the system observed about how this user works lately?** (User-pattern pass)

The output of all three phases is **always proposals** — markdown files
under `work/_learning/proposals/` with `source.type: curator-suggestion`.
The curator never edits Bridge files directly. All accepts happen via
`/bridge-learn`.

This is the deliberate inversion of the autonomy-maximalist curator
pattern observed in some agentic frameworks (e.g. Hermes Agent's
background-curator-fork). See `rules/learning-autonomy.md` § Layer B for
the full design rationale.

## When to run

- **Manual:** user says `/bridge-curator`, "bridge curator", "curator", etc.
- **Scheduled:** weekly via cron or `/schedule`, if configured in
  `bridge-config.yaml.learning.curator.schedule`.
- **Surface in `/briefing`:** on the configured `auto_surface_in_briefing`
  day (default Sunday), `/briefing` Stream D adds a "curator due / overdue"
  one-liner. Running the curator itself stays manual unless user opts into
  auto-run.

## Arguments

| Argument | Effect | Default |
|---|---|---|
| `(none)` | Run all three passes sequentially | — |
| `--pass library` | Only library consolidation | all |
| `--pass queue` | Only proposal-queue consolidation | all |
| `--pass user-patterns` | Only user-pattern synthesis | all |
| `--dry-run` | Surface findings, do NOT write proposals or user-patterns | false |
| `--since <date>` | Scan window starts at this date (default: last curator run) | last run |

## Three passes

### Pass 1 — Library

Full procedure in [`references/library-pass.md`](references/library-pass.md).

Scans `skills/`, `protocols/`, `rules/`, `docs/`. Detects:

- **Sleeping skill** — no invocation in `skill-usage.jsonl` for ≥30 days
  (if Phase-4 telemetry on); else heuristic via skill-name in `work/log.md`
- **Trigger overlap** — two or more skills with significantly overlapping
  trigger phrases in their description fields
- **Description-budget buster** — a SKILL.md description field that alone
  exceeds 1536 chars (Skills 2.0 discovery budget)
- **Umbrella candidate** — three or more skills that share a clear parent
  workflow and could be one skill with internal modes
- **Stale doc** — a doc whose `last_updated:` is older than the last edit
  to anything it references
- **Missing scope frontmatter** — a skill or agent file without explicit
  `scope:` (already caught by `/bridge-audit` Check 6, but the curator
  cross-references the audit-history JSON to escalate if recurring)

Each finding becomes a proposal in `work/_learning/proposals/`.

### Pass 2 — Queue

Full procedure in [`references/queue-pass.md`](references/queue-pass.md).

Scans `work/_learning/proposals/`. Detects:

- **Stale pending** — `status: pending` and `created` >30 days ago
- **Same-target conflict** — two pending proposals with the same
  `target.path` and incompatible `target.action`
- **Likely supersede** — a newer proposal that is a strict superset of
  an older one (covers same finding plus additional context)
- **Drift in source** — a proposal whose `target.path` has been edited in
  git since the proposal was written (the diff_preview may be stale)
- **Reject-pile accumulation** — `proposals/rejected/` has accumulated
  >10 entries with the same `target.type` pattern, suggesting the
  underlying generator (postmortem questions, audit checks) is producing
  low-signal proposals that should be filtered upstream

Output: each cluster becomes a meta-proposal — a curator-suggestion that
asks `/bridge-learn` to perform a specific consolidation action (accept-A-reject-B,
defer-both, merge into combined).

### Pass 3 — User patterns

Full procedure in [`references/user-pattern-pass.md`](references/user-pattern-pass.md).

Reads, in this order:
- `work/log.md` last 30 days
- `work/done/YYYY-MM/<slug>/STATUS.md` postmortems closed in window
- `work/_learning/audit-trail.md` accept/reject decisions in window
- `work/_learning/proposals/rejected/*.md` reasons in window
- `work/_learning/trigger-corrections.md` (if Phase-4 active)

Synthesizes 3-8 observations about how the user works. Format:

```markdown
- <Observation in 1-2 sentences>.
  Evidence: <pointers — N postmortems, M rejections, K log entries>
  Strength: weak | medium | strong
```

Writes append-only to `work/_learning/user-patterns.md` under a new
section `## YYYY-MM-DD — Weekly synthesis (n=<sessions>, n=<postmortems>)`.

**Does NOT write to MEMORY.md.** A strong-pattern observation may
produce an additional proposal with `target.type: memory` that
`/bridge-learn` can accept into the user's MEMORY.md via the normal
proposal flow.

**Minimum-signal threshold:** if window contains fewer than 5 postmortems
and 5 accept/reject events combined, the user-pattern pass produces an
"insufficient signal" note instead of forced observations.

## Output: Curator Report

After running, emit a single block:

```
═══ Bridge Curator — <YYYY-MM-DD> ═══

Library pass:   <N> findings → <K> proposals written
  • <severity> <topic-slug>  — <one-line>
  ...

Queue pass:    <N> findings → <K> meta-proposals written
  • <topic-slug> — <conflict-or-stale-or-supersede>
  ...

User-patterns: <N> observations appended to work/_learning/user-patterns.md
                <K> strong-pattern proposals (target.type: memory)
  • <observation excerpt>
  ...

→ Review via /bridge-learn  (current pending: <total>)
```

If `--dry-run`: same output, but report uses "would write" instead of
"wrote", no files touched.

## Proposal-file shape for curator-suggestions

Standard `_schema.proposal.yaml` with these field defaults:

```yaml
source:
  type: curator-suggestion           # NEW source.type enum value
  evidence:
    - "work/_learning/audit-history/<ts>.json"     # if Phase 3 data drove it
    - "work/done/<month>/<slug>/STATUS.md#postmortem"  # if postmortem drove it
    - "skills/<name>/SKILL.md"                    # the affected file

severity: P2                         # default, P1 if recurring or strong
status: pending
scope: core | user (depends on target)

target:
  type: skill | standing_order | rule | doc | memory
  path: ...
  action: edit | delete | rename | create

proposal_type: structured | needs-triage
```

The `source.evidence` chain is always concrete — the curator must cite
which files / scans led to the finding. No invented proposals.

## Edge cases

- **Empty Bridge** (new install, no postmortems, no audit-history yet) →
  all three passes return "insufficient signal — run more sessions then
  re-curate". Friendly message, no error.
- **Conflicting consolidation suggestions** (library pass says merge A+B
  into C, queue pass says A is stale) → emit both as separate proposals
  and let `/bridge-learn` resolve.
- **Privacy mode in user-pattern pass** — if `bridge-config.yaml.learning.curator.user_patterns.privacy: strict`,
  observations are written with redacted task slugs and customer names
  (replaced by `<task>` / `<customer>` placeholders) so the file is safe
  to share. Strict mode is opt-in, not default.
- **Pass-failure isolation** — if user-pattern pass crashes (e.g.
  malformed log entry), library + queue still complete. Failures are
  reported in the curator report, not bubbled as fatal.

## What this skill deliberately does NOT do

- ❌ Edit any Bridge file directly. All changes route via proposals.
- ❌ Write to MEMORY.md. User-patterns is a separate, lower-trust file.
- ❌ Auto-accept its own proposals. Even if a finding has 5-of-5 evidence
  pointers, `/bridge-learn` still gates the apply.
- ❌ Send any data off-machine. No cloud user-model service. No
  telemetry export.
- ❌ Run in a separate subprocess / agent fork without user awareness.
  The curator is a foreground skill invocation; the user sees the report.
- ❌ Promote findings to your org overlay or open-bridge automatically.
  Promotion is `/bridge-sync` territory after `/bridge-learn` accept
  flowed it through the normal commit pipeline.

## Related

- `rules/learning-autonomy.md` — the design rule this skill embodies
- `skills/task-close-postmortem/` — Layer 1 proposal generator (postmortem)
- `skills/bridge-audit/` — Layer 1 proposal generator (recurring findings)
- `skills/bridge-learn/` — the review surface that closes the loop
- `work/_learning/README.md` — aggregation layer layout
- `work/_learning/user-patterns.md` — output target for Pass 3
- `bridge-config.yaml.learning.curator` — config block (schedule + pass toggles)
