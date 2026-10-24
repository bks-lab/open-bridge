# Archive — Workflow

Trigger: `/archive`, `/archive --force`

## Phase 1: Guard

Check bridge-config.yaml `work.enabled: true`. If not → inform and exit.

## Phase 2: Determine Period

### 2a. Resolve the cadence

Read `bridge-config.yaml` `work.archive_cadence` — one of `weekly`,
`bi-weekly`, `monthly`, `quarterly`, `yearly`. **Missing or unrecognised →
`weekly`**, which is the historical behaviour, so an untouched config
behaves exactly as before.

The cadence decides the period bucket, the destination directory, and the
filename. It is also what `/briefing` reads for its staleness warning, so
the prompt and the archiver can never disagree about what "overdue" means.

| `archive_cadence` | Bucket of a date | Directory | Summary filename |
|---|---|---|---|
| `weekly` | ISO week | `work/archive/weeks/` | `{YYYY}-W{WW}.md` |
| `bi-weekly` | ISO week pair, odd week starts | `work/archive/weeks/` | `{YYYY}-W{WW}+W{WW+1}.md` |
| `monthly` | calendar month | `work/archive/months/` | `{YYYY}-{MM}.md` |
| `quarterly` | calendar quarter | `work/archive/quarters/` | `{YYYY}-Q{Q}.md` |
| `yearly` | calendar year | `work/archive/years/` | `{YYYY}.md` |

`weeks/` keeps its existing meaning and layout, so no instance has to
migrate anything when this key is introduced.

The raw backup sits beside the summary with a `-raw` suffix
(`{stem}-raw.md`), whatever the cadence.

### 2b. Read the plan — EVERY closed period, in one run

**Do not compute this by hand.** The plan comes from one command:

```bash
python3 scripts/archive-buckets.py --json          # add --force for the open period
```

It resolves the cadence from config, parses every day-block, and returns one
entry per period present in the log — oldest first — each carrying `label`,
`dir`, `stem`, `rows`, `day_blocks`, `first`/`last` (the day-blocks present),
`start`/`end` (the period itself, inclusive), `closed` and `archive`.

**One run archives every period with `archive: true`.** That is the whole
contract, and it is worth stating plainly because the previous version of this
phase said "archive target = the oldest bucket" and Phase 6 then reset the WHOLE
log. On a log holding twelve periods that wrote one summary, filed all twelve
periods' rows under that one period's `-raw` name, and reset the rest away. The
run was not repeatable either: after the reset there was nothing left to archive.

Three properties the command owns, so this file does not have to:

- **The year comes from the rows, not from today.** A day-block header is
  `## Mon 14.04` with no year by design; the rows inside carry a full
  `| YYYY-MM-DD HH:MM |` stamp, which is why that format is frozen. Guessing the
  current year turns every January archive of a December period into a block a
  year in the future.
- **The weekday token is display-only** (`Mon` / `Mo` / `lun.`), per
  rules/language-policy.md. The date comes from the DD.MM capture.
- **An impossible date is skipped, not guessed.** `## Mon 31.02` is a typo, and
  inventing March 3rd for it would file real rows under a period they do not
  belong to.

If nothing has `archive: true` → "no closed {period} to archive; pass `--force`
to archive the current (in-progress) {period}" and exit.

**`--force` means: also take the period that is still open.** It does not change
which closed periods are taken — those are always all of them. A scheduled run
never forces: it would be archiving a half-written day.

Why content-driven beats a day-of-week heuristic: heading drift (header says
KW{N} but day-blocks reach KW{N+1}) is the common case after a missed archive,
and "Saturday → archive the CURRENT week" picks the wrong target when the old
ones are what need draining.

## The scheduled run does only the mechanical half

`scripts/archive-autorun.sh` (declared as a workload, daily) runs Phases 2, 3, 6
and a METRICS-ONLY Phase 4, then records the rest as owed. It never runs a model:
Phase 4's narrative and Phase 5's selection are judgement, and a scheduled agent
with write access to the work log is the largest unattended blast radius here.

So a scheduled archive leaves behind summaries marked *"metrics only — not
narrated"* plus an inbox item (`scripts/inbox.py`) saying the narrative and the
distillation are still owed. Nothing is lost by filling them in later: the per-period `-raw.md`
holds every row, which is what Phase 5's evidence anchors already point at.

When a human runs `/archive` and finds periods already archived that way, enrich
those summaries and run Phase 5 over their raws rather than archiving again — the
collision guard refuses to overwrite an existing archive, deliberately.

## Phase 3: Collect — once per planned period

Loop over the plan's `archive: true` entries, oldest first. For each:

1. Take that period's day-blocks (the plan names them in `day_blocks`)
2. `git log --oneline --since="{start} 00:00" --until="{end} 23:59:59"` — the
   PERIOD bounds from the plan entry, not `first`/`last`. A commit on a day with
   no log row still belongs to the period, and a bare date in `--before` cuts
   the last day off.
3. Read `work/archive/days/` for any daily insights in range
4. Read board.md done section for the month

## Phase 4: Generate Summaries — one file per period

For each planned period, create its summary at the path the plan gives
(`{dir}/{stem}.md`) using `work/templates/week-summary.md`.

**Every summary AND every raw backup is written before Phase 6 touches
`log.md`.** Verify each file exists and is non-empty first. A reset that runs
while one archive failed to write loses that period outright, and the log is the
only place those rows still exist.
- Overview metrics (commits, tasks completed, repos touched)
- Daily overview
- Completed tasks
- In-progress tasks
- Highlights and blockers
- Next period priorities

The template's headings say "week" because `weekly` is the default; under a
longer cadence, read them as "the archived period".

## Phase 5: Distill durable memory (propose-then-confirm)

**Runs before the reset, because this is the last moment the rows exist in
`log.md`.** The summary from Phase 4 is a *narrative* of a period; this
phase extracts the handful of facts that should still be true, and still
recalled, long after that period stops being interesting.

**ONE pass over every archived period, not one pass each.** Durable facts do not
respect period boundaries: an insight spanning two weeks would otherwise be
proposed twice or missed, and asking a human for N separate confirm-cycles over
the same 60 rows exhausts the judgement this phase depends on. So: gather the
candidates across all planned periods, de-duplicate, and present one list. Each
candidate's `evidence` still points at the raw file of the period it came from,
so provenance stays per-period even though the decision is not.

Expect the filter to bite harder here, not less: twelve periods of bookkeeping
still yield only a handful of durable facts.

Why it exists: `work/archive/` has **no reader**. Nothing in the Bridge
loads an archived summary back into context — not session-start, not
`/briefing`, not `bridge-curator`. Without this phase, archiving is
forgetting with a backup. The memory base *is* read every session (its
`MEMORY.md` index is loaded at start), so distilling into it is what makes
a short cadence safe.

### 5a. Select candidates

Re-read the period's rows and pick only rows carrying **durable** knowledge:

**Distil these**
- A decision **and its rationale** ("chose X over Y because Y needs a schema migration")
- A diagnosis that cost real effort ("launchd can't read `~/Documents` — macOS TCC")
- A convention or constraint discovered the hard way ("`grep -c || echo 0` double-emits")
- A stable fact about the environment (a host, a path, an ID, an ownership boundary)
- A correction of a previously held belief

**Never distil these**
- Commit/PR/push bookkeeping — git and the forge already hold it permanently
- Status transitions, CI results, "started X" / "finished X"
- Anything already superseded by a later row in the same period
- Anything already in the memory base (check `MEMORY.md` first — update the
  existing file rather than adding a near-duplicate)

Expect **few**. A busy period of 60+ rows typically yields 1–3 durable
facts. If the candidate list is longer than ~5, the filter is too loose —
re-apply it rather than proposing a pile the user must wade through.

### 5b. Propose — never write silently

Memory is one of the layers governed by
[`rules/learning-autonomy.md`](../../../rules/learning-autonomy.md): the
Bridge proposes, the human decides. **This phase never writes a memory file
on its own authority.**

Present each candidate compactly:

```
Distilled from Week 27 — 3 candidates

[1] launchd agents cannot read ~/Documents (macOS TCC)
    type: project · why: cost a full session to diagnose; recurs on any
    launchd job pathed into a protected dir
    → memory/project_launchd-tcc-protected-dirs.md
    [a] accept  [e] edit  [r] reject  [d] defer to /bridge-learn

[2] ...
```

Per candidate:

| Choice | Effect |
|---|---|
| `[a]` accept | Write the memory file **and** its one-line `MEMORY.md` index entry now |
| `[e]` edit | User rewrites the text, then accept |
| `[r]` reject | Dropped. Not proposed again for this period |
| `[d]` defer | Written as a proposal instead (below) — decided later via `/bridge-learn` |

Offer `[A] accept all` / `[R] reject all` once the list is shown, for the
common case where the filter did its job.

**Unattended runs take `[d]` for every candidate.** A scheduled archive has no
human at the prompt, and `rules/learning-autonomy.md` is not relaxed by the
absence of one: the Bridge proposes, the human decides. So the mechanical phases
complete and every candidate lands as a pending proposal, reviewed later through
`/bridge-learn` — which `/briefing` surfaces once the pending count passes
`learning.proposals.auto_surface_threshold`. Nothing is written to the memory
base on the Bridge's own authority, scheduled or not.

**Deferred candidates** become normal learning proposals in
`work/_learning/proposals/`, so the existing review surface handles them
with no parallel queue:

```yaml
id: 2026-07-05-archive-w27-launchd-tcc
created: 2026-07-05
source:
  type: archive-distill
  evidence: ["work/archive/weeks/2026-W27-raw.md#L42"]
severity: P3
status: pending
scope: user
target:
  type: memory
  path: memory/project_launchd-tcc-protected-dirs.md
  action: create
proposal_type: structured
```

`scope: user` always — a distilled memory describes *this* instance's
history and never promotes upstream.

### 5c. Memory file format

Follow [`docs/memory.md`](../../../docs/memory.md) exactly — one fact per
file, frontmatter (`name`, `description`, `metadata.type`), `[[wikilinks]]`
between related facts, and **a one-line pointer in `MEMORY.md`, never the
content itself**. The index is loaded into every session, so it must stay
lean; that discipline is the entire reason this phase can be cheap.

`metadata.type` follows the memory model's own vocabulary (`project`,
`reference`, `feedback`, `user`) — a distilled fact is usually `project`
(ongoing work, constraints) or `reference` (an external pointer).

### 5d. Evidence

Every accepted memory records where it came from — the raw archive path
plus, where useful, a line anchor. A memory whose origin can't be traced
is indistinguishable from an invented one.

**Skip this whole phase** when `--force` is combined with an empty period,
or when the memory base is unreachable — warn, continue to the reset, and
say plainly that nothing was distilled. Never block the archive on it.

## Phase 6: Reset log.md — per-period raws, then ONE reset

1. **Per planned period**, write `{dir}/{stem}-raw.md` containing **only that
   period's day-blocks**. Not the whole log under one period's name: that was
   the defect, and it is what made twelve periods of history unrecoverable as
   themselves. Verify every raw exists and is non-empty before step 2.
2. New log.md with a fresh header for the current period, **retaining the
   day-blocks of any period the plan left open** (`archive: false`) plus today's
   day-block. Only what was archived leaves the log.
3. File every unchecked `[ ]` item in the inbox with `scripts/inbox.py add`
   (one item each, a `--key` so a re-run files nothing twice) instead of
   carrying it in a TODO block; open points belong there
   ([`docs/inbox.md`](../../../docs/inbox.md)). Only when the inbox cannot be
   written do they stay in the new log under `### Carried over`.
4. **Regenerate the `**Active Focus:**` line** — don't keep the stale one
   from the archived period. Build it from the top 3-4 entries in
   `board.md` Doing lane (slug + 1-clause "what's running"), joined
   with ` · `. The previous Active-Focus line often references work
   that just shipped (e.g. a talk that was already given);
   don't carry that forward.

## Phase 7: Upstream Check (conditional)

Skip entirely unless ALL three hold:
1. `bridge-config.yaml` has an `upstreams:` list.
2. At least one entry is either `role: oss-core`, or `role: org-overlay` with a
   `materialize:` block. An org-overlay without that block is authored here, not
   consumed, and is not a subscription.
3. That channel is past its `pull_interval_days` (default 7), measured against the
   last merge from the remote (CORE) or `last_synced` in `overlays.lock.yaml`
   (overlays).

A Bridge with no `upstreams:` list skips this phase; do not load
`references/upstream-summary.md`.

If the prerequisites hold, run the inbound status check from
`references/upstream-summary.md` (the briefing skill ships this reference, archive
borrows it). It is read-only and hands off rather than merging. Nothing is written
back to config: staleness comes from git and the lockfile, never from a
hand-maintained timestamp that can drift from what actually happened.

## Phase 8: Confirmation

Show one line per archived period, then the totals:

```
Archived 9 period(s), 66 rows:
  Week 27   5 rows → work/archive/weeks/2026-W27.md
  Week 28   1 row  → work/archive/weeks/2026-W28.md
  …
  3 memories distilled, 2 deferred to /bridge-learn
  Week 39 (open, 4 rows) stays in the log
```

Name the open period that stayed, so "it was not archived" and "it was lost" can
never read the same.

`{period_label}` follows the cadence — "Week 27", "Weeks 27+28", "July 2026",
"Q3 2026", "2026". Report the distilled count even when zero, so a period
that yielded nothing durable is visibly a decision and not a silent skip.

If upstream had updates: append "Upstream has {n} new commits — merge with `/briefing`."
