---
summary: "User-Pattern-Pass procedure — synthesizes 3-8 observations about user working style from postmortems + audit-trail + corrections, appends to work/_learning/user-patterns.md."
type: reference
last_updated: 2026-05-13
---

# User-Pattern Pass — Procedure

The user-pattern pass is the local-only alternative to a cloud
dialectic-memory service. It synthesizes how the user *appears to work*
from observable Bridge state, writes the synthesis append-only to
`work/_learning/user-patterns.md`, and (only for strong-signal patterns)
emits a `target.type: memory` proposal to escalate the observation into
MEMORY.md via `/bridge-learn`.

The pass is **scope: user** end-to-end — nothing it reads or writes
ships upstream. The `work/_learning/user-patterns.md` file is gitignored
in OSS variants per `work/_learning/README.md` § Scope.

## Inputs (window = last 30 days, configurable)

In this read order:

1. `work/log.md` — last 30 days of activity rows
2. `work/done/<YYYY-MM>/*/STATUS.md` — postmortems closed in window
3. `work/_learning/audit-trail.md` — accept/reject decisions in window
4. `work/_learning/proposals/rejected/*.md` — reject reasons in window
5. `work/_learning/trigger-corrections.md` (if Phase-4 active)
6. `work/_learning/audit-history/*.json` last 10 runs (for finding-type frequency)

## Pre-flight: signal-budget check

Count: postmortems-in-window + audit-trail-decisions-in-window +
trigger-corrections-in-window.

- **< 5 total events:** abort with output "insufficient signal — wait
  for more sessions before synthesis." Append a placeholder entry to
  `user-patterns.md` noting the skip. Do NOT generate forced
  observations.
- **5-20 events:** synthesize 3-5 weak/medium observations
- **20-100 events:** synthesize 5-8 observations across strength tiers
- **> 100 events:** still cap at 8 — quality over quantity

## Synthesis prompt (internal)

When invoked, build this synthesis instruction for the LLM step:

```
You are doing a local user-pattern synthesis for the Bridge's
learning layer. Read the inputs below. Produce 3-8 observations about
how this user appears to work, in this format:

  - <Observation in 1-2 sentences>.
    Evidence: <comma-separated pointers to log entries, postmortems,
              accept/reject rows that support this>
    Strength: weak | medium | strong

Rules:
- Strength must be honest. "Strong" = ≥3 distinct evidence pointers and
  pattern visible across at least two different contexts/projects.
  "Medium" = 2 pointers. "Weak" = 1 pointer or pattern inferable.
- Do not invent observations to fill the count. If only 3 honest
  observations exist, return 3.
- Phrase positively-and-neutrally. Observations are about HOW the user
  works, not judgments about quality.
- Cite evidence by file path + anchor where possible.
- Do not name customer / project names that aren't already in the
  evidence pointers. Use placeholders if the user's privacy-mode is strict.

Inputs:
<paste log.md window, postmortem bodies, audit-trail rows,
 rejection-reason lines, trigger-correction entries>
```

## Append format

After synthesis, append to `work/_learning/user-patterns.md`:

```markdown
## <YYYY-MM-DD> — Weekly synthesis (n=<postmortems>, n=<decisions>, n=<corrections>)

Window: <YYYY-MM-DD> to <YYYY-MM-DD>
Source counts: <P> postmortems · <D> accept/reject · <C> corrections · <A> audit-runs

- <Observation 1>.
  Evidence: <pointers>
  Strength: <weak|medium|strong>

- <Observation 2>.
  ...

---
```

The `---` trailer is a visual separator so future-you can scan past runs
quickly. Newest entries at the bottom (append).

## Strong-pattern escalation to MEMORY.md

For each observation with `Strength: strong`: emit a separate proposal
with target.type=memory:

```yaml
source:
  type: curator-suggestion
  evidence:
    - "work/_learning/user-patterns.md#<this-week-anchor>"
    - <the original evidence pointers from the observation>
severity: P2
status: pending
scope: user

target:
  type: memory
  path: ~/.claude/projects/<this-project>/memory/<suggested-name>.md
  action: create
proposal_type: structured

body_excerpt: |
  Strong-pattern observation from <date> weekly synthesis:

    "<observation text>"

  Suggested memory entry name: <kebab-case-name>
  Suggested type: feedback | project | reference  (per CLAUDE.md auto-memory rules)
```

`/bridge-learn` accept on a target.type=memory proposal does NOT
auto-write to MEMORY.md (per `rules/learning-autonomy.md` § Layer C).
It surfaces the suggested entry text and asks the user to confirm
verbatim before writing. The user can edit the wording at accept-time.

## Aggregation rules

- One synthesis block per curator run. If user runs curator twice in
  one day: second run replaces the day's block (don't pile up
  duplicates).
- Append-only across runs — never delete past synthesis blocks. They
  are the history of what the system thought it knew.
- If two consecutive weekly syntheses produce the same observation
  marked strong: the second one bumps severity of the corresponding
  memory-proposal one level (P2 → P1).
- If a previously-strong observation is no longer surfaced in a later
  run: do NOT auto-delete the MEMORY entry. The user manages MEMORY
  themselves. Just stop re-proposing it.

## Privacy mode (opt-in)

If `bridge-config.yaml.learning.curator.user_patterns.privacy: strict`:

- Replace task slugs with `<task-N>` (numbered per session)
- Replace customer names with `<customer-X>` (X = letter per customer)
- Replace person names with `<person>`
- Replace specific dates with relative offsets ("3 weeks ago")

The strict-mode synthesis is safe to share. The default-mode synthesis
contains real names from the user's evidence pointers — appropriate for
private/seed Bridge instances, not for sharing.

## What this pass deliberately does NOT do

- ❌ Run automatically without user invocation (unless explicitly
  scheduled in bridge-config)
- ❌ Send any data to a remote service for synthesis
- ❌ Write to MEMORY.md directly. Always proposes; user accepts.
- ❌ Cross-reference patterns against other Bridge instances (no
  multi-instance learning by design)
- ❌ Use embeddings or semantic-similarity for "smart" recall — the
  evidence chain is always plain string pointers
- ❌ Score the user on productivity, time-of-day, etc. The
  observation strength scale is about evidence quantity, not
  user-performance judgment

## Comparison to dialectic memory services

A cloud-based dialectic-memory service (e.g. Honcho in the Hermes Agent
stack) does the same job continuously per-turn, with an LLM running on
the service side. Trade-offs vs this pass:

| Aspect | This pass (local) | Cloud dialectic memory |
|---|---|---|
| Cadence | Weekly (or on-demand) | Per-turn |
| LLM cost | One synthesis call per week | One call per turn |
| Privacy | Fully local | Conversation text uploaded |
| Audit | Markdown file, diff-able | API responses, opaque |
| Drift correction | Re-synthesize and rejected observations stop reappearing | Service self-heals "over time" with no transparency |
| Per-turn recall | None (pass writes to file, doesn't inject) | Injected into prompt |

The pass deliberately does not provide per-turn recall. Recall happens
when the user reads `user-patterns.md` or MEMORY.md, not when an
unspecified prompt-injection mechanism fires. This is the same gate-vs-velocity
trade documented in `rules/learning-autonomy.md`.

## Related

- `rules/learning-autonomy.md` § Layer C — design rationale
- `work/_learning/user-patterns.md` — output file
- `~/.claude/projects/<project>/memory/MEMORY.md` — escalation target
- `bridge-config.yaml.learning.curator.user_patterns` — config block
