# Week Archive — Workflow

Trigger: `/archive`, `/archive --force`

## Phase 1: Guard

Check bridge-config.yaml `work.enabled: true`. If not → inform and exit.

## Phase 2: Determine Week

**Content-driven, not calendar-driven.** Look at what's actually in
`work/log.md`, not at today's weekday:

1. Parse the header — `# Week {N}` (or legacy `# KW {N}`).
2. Parse all day-block headers — `^## \S+ ([0-9]{2})\.([0-9]{2})([^0-9.]|$)`
   (any locale weekday token — see rules/language-policy.md). The weekday
   name is display-only; derive the date from the DD.MM capture, never the
   token.
3. Compute the KW for each day-block date.
4. **Archive target = `min(header_KW, min(day-block KWs))`** — the
   oldest week with content still in the log.
5. If `target_KW < TODAY_KW` → archive `target_KW`.
6. If `target_KW == TODAY_KW` → "no older week to archive; pass `--force`
   to archive the current (in-progress) week" — exit unless `--force`.

Why this beats the day-of-week heuristic: heading drift (header says
KW{N} but day-blocks reach KW{N+1}) is the common case after a missed
Sunday archive. The heuristic "Saturday → archive CURRENT week" picks
the wrong target when the user actually wants the old one drained out
first.

`--force` overrides everything and archives whatever the header says.

## Phase 3: Collect

1. Parse log.md day-blocks for target week
2. `git log --oneline --after="{monday}" --before="{sunday}"`
3. Read `work/archive/days/` for any daily insights
4. Read board.md done section for the month

## Phase 4: Generate Summary

Create `work/archive/weeks/{YYYY}-W{CW}.md` from `work/templates/week-summary.md`:
- Overview metrics (commits, tasks completed, repos touched)
- Daily overview
- Completed tasks
- In-progress tasks
- Highlights and blockers
- Next week priorities

## Phase 5: Reset log.md

1. Backup to `work/archive/weeks/{YYYY}-W{CW}-raw.md`
2. New log.md with fresh week header + today's day-block
3. Carry over only unchecked `[ ]` items
4. **Regenerate the `**Active Focus:**` line** — don't keep the stale one
   from the archived week. Build it from the top 3-4 entries in
   `board.md` Doing lane (slug + 1-clause "what's running"), joined
   with ` · `. The previous Active-Focus line often references work
   that just shipped (e.g. last week's talk that was already given);
   don't carry that forward.

## Phase 6: Upstream Check (conditional)

Skip entirely unless ALL three hold:
1. `bridge-config.yaml` has an `upstream:` block.
2. A git remote named `upstream` exists.
3. `(now - upstream.last_check) ≥ upstream.check_interval_days`.

For Seed-repo instances (no `upstream:` block) this phase is a no-op —
don't load `references/upstream-summary.md`.

If all three hold:
1. Run semantic diff analysis from `references/upstream-summary.md`
   (briefing skill ships this reference; archive borrows it).
2. Update `bridge-config.yaml` → `upstream.last_check` with current timestamp.

## Phase 7: Confirmation

Show: "Archived Week {kw}: {n} commits, {n} tasks. Summary: work/archive/weeks/{file}."
If upstream had updates: append "Upstream has {n} new commits — merge with `/briefing`."
