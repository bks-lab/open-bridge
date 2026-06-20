---
name: task-close-postmortem
description: 'Postmortem capture + bridge-improvement scan at task close. Surfaces six optional questions (time invested, estimate vs actual, what went well, what burned time, where the bridge fell short, concrete improvement proposal), writes structured frontmatter back to STATUS.md, and generates proposal files under work/_learning/proposals/ for later review via /bridge-learn. Invoked automatically by protocols/standing-orders/task-sync.md Phase 3b at task close, and directly user-invokable for ad-hoc reflection. Trigger: "task done", "document everything", "wrap up", "wrap-up", "task complete", "post-mortem", "/postmortem the last hour", "reflect on the piece just finished", "review the last block", "what did we learn from X".'
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

# Task-Close Postmortem

Captures a short reflection at task close, maps any surfaced gaps to concrete
Bridge-File-Improvement-Proposals, and writes both back as structured artifacts.

The skill is **always optional and always interruptible** — every question is
skippable, and skipping all six leaves the task unchanged from today's behavior.
Default-on (per `bridge-config.yaml.learning.postmortem.enabled`) but cost-light:
fast-path through all six skips is <20 seconds.

## When this skill runs

1. **Auto, via `task-sync.md` Phase 3b** — every time a task closes, after the
   dual_doku self-check passes and before the 3-step move.
2. **Manual** — when the user says any of: "/postmortem the last hour",
   "reflect on the piece just finished", "post-mortem this", "what did we
   learn from X". In manual mode the scope is **not bound to a task folder** —
   the skill reflects on the recent activity (last log.md entries, recent
   commits, recent file edits). No frontmatter writes happen in manual mode;
   output is only the proposals.

## Inputs

**Auto mode:**
- `work/tasks/<slug>/STATUS.md` — the task being closed
- `workflow/contexts/<context>.yaml` if STATUS references a context
- recent entries from `work/log.md` (last 24h or all entries since task `created`)

**Manual mode:**
- last N log.md entries (N defaults to last 10, or "the last hour")
- recent uncommitted git diff in this Bridge repo and any other repos touched

## The six questions

(Full script in [`references/postmortem-questions.md`](references/postmortem-questions.md).)

Surface them one at a time. Accept skip-phrases from
`bridge-config.yaml.learning.postmortem.skip_phrases` — default
`["skip", "next", "—", "no", "next", "."]`. If
`cutdown_after_skips` (default 3) consecutive skips occur, switch
to **Cutdown mode** for the remaining questions: ask only the single
catch-all "anything else worth noting?". Empty answer → done.

| # | Question (EN) | Writes to |
|---|---|---|
| 1 | Time invested? | frontmatter `time_invested` |
| 2 | Estimate vs actual? | frontmatter `estimate_vs_actual` |
| 3 | What went well? | body `## Postmortem` → "What went well" |
| 4 | What burned time? | body `## Postmortem` → "What did not go well" |
| 5 | Did the bridge fail you? | frontmatter `bridge_gaps[]` + body |
| 6 | Concrete improvement? | proposal file + body |

Use the conversation language from `bridge-config.yaml.language.conversation`
(default `en`). EN fallback if missing.

## Frontmatter write rules

Use the Edit tool against `work/tasks/<slug>/STATUS.md`. All four fields
(`time_invested`, `estimate_vs_actual`, `lessons`, `bridge_gaps`) are
**optional** in the schema (`work/templates/_schema.status.yaml`) — omit
the line entirely when the user skipped that question. Never write empty
strings or `null`.

Q1 → `time_invested:` — accept any of the schema-allowed forms
(`~12h`, `P3D`, `PT4H`, `—`, `unknown`). Loose parsing OK; if user types
"about 12 hours over 3 days", record as `"~12h"` and add the prose to body.

Q2 → `estimate_vs_actual:` — match to nearest enum value: ok / 1.5x / 2x /
3x / >3x / re-scoped / —. If user says "estimate was 4h, so 3x" record
`"3x"` and add the math to body for human readability.

Q3+Q4 → body `## Postmortem` subsections. Free-form prose. Bullet each line.

Q5 → `bridge_gaps[]` array. Each entry is one of:
`{skill: NAME, why: TEXT}` / `{standing_order: NAME, why: TEXT}` /
`{rule: NAME, why: TEXT}` / `{doc: NAME, why: TEXT}` /
`{protocol: NAME, why: TEXT}` / `{memory: NAME, why: TEXT}`.
A single user answer can yield multiple `bridge_gaps` entries.

Q6 → free-text improvement. Add to body "Concrete Bridge improvements proposed"
sub-section. Each bullet there will be examined in the proposal-writing phase.

## Improvement-Scan phase

After all six questions are answered (or skipped), scan for proposal-worthy
candidates from THREE sources, in order:

1. **`bridge_gaps[]`** (Q5 structured answers) — one proposal per entry.
2. **Free-text Q6 answer** — try to map to a structured proposal; if it
   doesn't fit cleanly, write a `proposal_type: needs-triage` proposal.
3. **Touched files during this task** — `git log --diff-filter=AM --name-only`
   in the relevant repos since task `created` date. If any file changed in
   this Bridge repo (skills/, protocols/, rules/, docs/) that wasn't a planned
   edit, flag as potential trigger-or-routing miss for the postmortem.

For each candidate, write one file to:

```
work/_learning/proposals/<YYYY-MM-DD>-<task-slug>-<topic-slug>.md
```

Following the schema in
[`references/_schema.proposal.yaml`](references/_schema.proposal.yaml).

**Naming rule:** `<topic-slug>` is the gap-id from `bridge_gaps[]` if
structured, or a 3-4-word kebab-case summary if from free-text. Disambiguate
collisions with a `-2`, `-3` suffix.

## Proposal-writing rules

Use the template in
[`references/proposal-writing.md`](references/proposal-writing.md).

Default `severity: P2` for postmortem-sourced proposals. P0/P1 only when the
gap is in an actively-used path (existing skill, common standing-order) AND
the user explicitly described impact.

Default `scope: user` for postmortem-sourced proposals unless the target is
clearly a CORE file (a generic skill, a CORE standing-order, the schema).
The /bridge-learn skill (Phase 2) and /bridge-sync handle promotion to
your org overlay / open-bridge later — getting the scope right at
proposal-write time saves an audit later.

Default `status: pending`. Never write `accepted` or `implemented` from
this skill — those are /bridge-learn states.

## Output to user

After all phases complete, return a single block:

```
✅ Task <slug> postmortem complete.
   <X> answers captured (frontmatter + body)
   <N> proposals written to work/_learning/proposals/
     • <file-1>  [<severity>] <one-line summary>
     • <file-2>  [<severity>] <one-line summary>
   → review per /bridge-learn (Phase 2) — or open the files directly.
```

If all six questions skipped:

```
✅ Postmortem skipped — STATUS.md unchanged.
```

Hand control back to `task-sync.md` Phase 3c (3-step move).

## Edge cases

- **Task has no `context:` field** → skip context.yaml read, proceed.
- **Task has no `mandant:` field** → no impact on postmortem.
- **STATUS.md is malformed** → log warning, ask user to fix, exit
  gracefully (do not mv files yet).
- **Skip-phrase ambiguity** ("no" could mean "no, nothing" or "no
  I'll answer in a moment"): treat as skip; user can backfill manually.
- **User says "wait" / "hold on" / "stop"** mid-flow → suspend, do NOT
  write partial frontmatter, hand control back. User can resume by
  saying "continue postmortem" / "postmortem continue".
- **Proposals folder doesn't exist** → create on first write
  (`mkdir -p work/_learning/proposals/`).
- **Bridge-config.yaml not present** → assume defaults (postmortem enabled,
  skip_phrases as above, cutdown_after_skips=3).

## Testing the skill

Two ways to dry-run without closing a real task:

1. **Manual mode** — say "reflect on the last hour", skill runs without
   binding to a STATUS.md, just emits a sample proposal-set.
2. **Test fixture** — `work/_learning/_test/sample-task/STATUS.md` (create
   on demand) — skill runs against the fixture, writes proposals to
   `work/_learning/_test/proposals/`, asserts schema validity.

## What this skill deliberately does NOT do

- ❌ Mutate any file outside `work/tasks/<slug>/STATUS.md` and
  `work/_learning/proposals/`. The 3-step move is done by `task-sync.md`
  Phase 3c, not here.
- ❌ Auto-apply any proposal. Every proposal-file is `status: pending` —
  accept/reject is the /bridge-learn skill's job.
- ❌ Probe other repositories (customer-x, partner-project, ...). Only this Bridge repo
  + git-stats for the task duration period.
- ❌ Write to MEMORY.md. The auto-memory system is separate; a postmortem
  may *suggest* a memory entry via `bridge_gaps[].memory:` but the actual
  write happens later, human-approved.
- ❌ Decide when proposals get implemented. That's /bridge-learn.
- ❌ Run if `bridge-config.yaml.learning.postmortem.enabled: false`.

## Related

- `protocols/standing-orders/task-sync.md` § Phase 3b (invokes this skill)
- `work/templates/_schema.status.yaml` (schema for the frontmatter fields)
- `work/templates/STATUS.md` (template `## Postmortem` section)
- `work/_learning/README.md` (the aggregation layer this writes into)
- `skills/bridge-learn/SKILL.md` (Phase 2 — reviews proposals)
- `bridge-config.yaml.learning.postmortem` (config block)
- CLAUDE.md § Auto Memory (the parallel system this does NOT touch)
