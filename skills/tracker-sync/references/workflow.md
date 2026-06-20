---
summary: "Pull/diff/push playbook for tracker-sync + /briefing integration"
type: reference
last_updated: 2026-06-04
related:
  - scripts/tracker-sync.py
  - skills/briefing/references/workflow.md
  - skills/github-projects-manager/SKILL.md
---

# Tracker-Sync — Workflow

## The loop

```
pull (autonomous, read-only)
  → diff (cockpit: which task in which state, what's left)
    → for remote_ahead: propose STATUS edit (gated)
    → for local_ahead:  plan → push via github-projects-manager (gated)
      → re-pull → re-diff (verify in_sync)
```

GitHub is the system of record; The Bridge is the cockpit. The snapshot under
`work/trackers/` is the local mirror — git history of that dir is the dated dump.

## `/tracker-sync` (or "sync my tasks") — interactive

1. `python3 scripts/tracker-sync.py pull` — refresh snapshots (skip if a fresh
   `work/trackers/_index.yaml` `last_pull` is < ~30 min old and the user only
   wants a re-diff).
2. `python3 scripts/tracker-sync.py diff` — render the delta table.
3. Walk the actionable rows with the user (see SKILL.md table). Batch where
   `cluster.size ≥ 5` (same anti-decision-fatigue rule as /briefing Phase 3.5).
4. For approved `local_ahead` pushes:
   - `python3 scripts/tracker-sync.py plan --format json`
   - per operation, call **github-projects-manager** with the issue, project,
     field `Status`, and `to_option`. It owns the gh GraphQL mutation and the
     real field-ID lookup from `workflow/projects/<slug>.yaml`.
   - log each push in `work/log.md`; the task-sync standing-order trigger #2
     (status-change) already governs this — stay consistent with it.
5. Re-`pull` + re-`diff` the touched board → confirm the row flipped to
   `in_sync`. Never claim "synced" off the plan alone (verify before claim).

## `/briefing` integration (keeps it fresh, no daemon)

Stream B already pulls each board live and renders a per-Doing-row sync marker
(`#189!`) — but ephemerally. Add ONE side effect so the mirror stays current
for free:

- **After Stream B's live pull, persist the snapshot**: run
  `python3 scripts/tracker-sync.py pull` (it reuses the same `integrations.github`
  config). This makes every briefing refresh `work/trackers/`.
- **Surface tracker drift in Warnings**: run
  `python3 scripts/tracker-sync.py diff --exit-code`; if it returns 2, add a
  Warnings line:
  `⚠ Tracker-Drift: N actionable (M local_ahead, K remote_ahead) → /tracker-sync`.
  This generalizes the existing Phase-2 `#189!` marker from the Doing lane to
  every github-linked task, and complements task-sync.md Phase 5 (which checks
  STATUS-vs-commits drift) with the STATUS-vs-board axis.

Respect `--quick` / `--skip-trackers`: no live pull ⇒ no persist, no diff.

## Scope-policy honouring

Before pulling a board, check its `workflow/projects/<slug>.yaml` `sync_policy`:
`auto_pull: false` ⇒ `/briefing` skips that board's persist (manual
`/tracker-sync pull --project <slug>` still works). Absent ⇒ pull.

## Failure semantics (never block)

- `gh` missing/unauthed → pull warns + skips, diff runs on the last snapshot
  (stale but stamped `pulled_at` — surface the age).
- A board 404/403 → skip that board, keep the others (same as trackers contract).
- No snapshot at all → diff says "nothing to reconcile", exit 0.
