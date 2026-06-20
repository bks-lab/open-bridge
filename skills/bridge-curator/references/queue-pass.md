---
summary: "Queue-Pass procedure — scans work/_learning/proposals/ for stale pending, same-target conflicts, supersede candidates, and reject-pile signal."
type: reference
last_updated: 2026-05-13
---

# Queue Pass — Procedure

## Inputs

- `work/_learning/proposals/*.md` (pending — root level)
- `work/_learning/proposals/accepted/*.md`
- `work/_learning/proposals/rejected/*.md`
- `work/_learning/audit-trail.md` (decisions log)
- `git log` for proposal-touched files (to detect drift in target.path)

## Checks

### Check 1 — Stale pending

Pending proposals are `status: pending` and live in
`work/_learning/proposals/` root (not in accepted/ or rejected/).

For each: `now - created > 30 days` → stale.

Emit one meta-proposal per stale:

```yaml
source:
  type: curator-suggestion
  evidence: ["work/_learning/proposals/<stale-id>.md"]
severity: P3
target:
  type: ...                 # mirrors the stale proposal's target
  path: ...
  action: ...
proposal_type: structured
body_action: defer | reject  # curator's suggestion, user decides
```

Body: surfaces the stale, suggests either explicit defer-with-reason
(moves to a deferred-pile with date) or reject-with-reason (move to
`proposals/rejected/`).

### Check 2 — Same-target conflict

Group pending proposals by `target.path`. Clusters of size ≥2 are
candidates.

For each cluster:

- Same target + same action: likely duplicates → one wins, others mark
  superseded
- Same target + incompatible action (`edit` vs `delete` vs `rename`):
  hard conflict → user must pick

Emit one meta-proposal per cluster:

```yaml
source:
  type: curator-suggestion
  evidence: ["work/_learning/proposals/<id1>.md", "work/_learning/proposals/<id2>.md"]
severity: P2
target:
  type: ...                 # the shared target
  path: ...
  action: ...               # the conflict
proposal_type: structured
body_action: pick-one | merge | reject-all
```

### Check 3 — Likely supersede

For each pair (newer, older) of pending proposals where:
- `newer.target.path == older.target.path`
- `newer.created > older.created + 7 days`
- `newer.source.evidence` is a strict superset of `older.source.evidence`
  (in count and type) OR newer is `audit-recurring` with the same
  fingerprint as the older's source

Mark the older as supersede-candidate. Emit a curator-suggestion that
asks `/bridge-learn` to set `older.status = superseded` and
`older.superseded_by = newer.id`.

### Check 4 — Source-file drift since proposal-write

For each pending proposal: run
`git log --since=<proposal.created> -- <proposal.target.path>`.

If the target file has changed since the proposal was written:
- The `diff_preview` in the proposal may be stale
- Surface as a curator-suggestion that `/bridge-learn` should re-validate
  the diff or re-write it before accept

```yaml
source:
  type: curator-suggestion
  evidence:
    - "work/_learning/proposals/<id>.md"
    - "git:<target.path>@<recent-commit-hash>"
severity: P2
target:
  type: ...                 # mirrors the proposal's target
  path: ...
  action: edit              # re-validate proposal
proposal_type: structured
```

### Check 5 — Reject-pile signal

Read all `proposals/rejected/*.md`. Group by `target.type` and check
the `reject_reason` field. If ≥10 rejections in the last 90 days
share a target.type AND a common rejection theme (regex on
reject_reason words): the underlying proposal generator may be
producing low-signal proposals.

Emit a meta-proposal that asks `/bridge-learn` to either:
- Tighten the proposal-generator (e.g. raise severity threshold)
- Add an opt-out filter (skip this target.type for postmortem-sourced)
- Disable a specific generator phase

```yaml
source:
  type: curator-suggestion
  evidence: ["work/_learning/proposals/rejected/<id1>.md", "...", "<id10>.md"]
severity: P1                # this is "the system is wasting your time"
target:
  type: skill               # the proposal generator itself
  path: skills/<generator-name>/SKILL.md OR similar
  action: edit
proposal_type: needs-triage
```

### Check 6 — Accept-with-no-implement

For each `proposals/accepted/<id>.md` where:
- `status: accepted` (not yet `implemented`)
- `accepted_at` exists, more than 7 days ago
- `implemented_commit` field empty

The proposal was accepted but the diff never landed as a commit. Either
the apply step failed silently, the user forgot, or the commit was lost.

Emit a curator-suggestion: re-surface the accepted proposal for
implementation. `/bridge-learn` can replay the apply step.

```yaml
source:
  type: curator-suggestion
  evidence: ["work/_learning/proposals/accepted/<id>.md"]
severity: P2
target:
  type: ...                 # mirrors the accepted proposal
  path: ...
  action: edit
proposal_type: structured
```

## Aggregation rules

- One meta-proposal per finding. Don't bundle different findings into one.
- Bound output: ≤10 queue-pass proposals per run. If overflow: surface
  highest-severity, defer the rest.
- Queue-pass proposals always have `proposal_type: structured` except
  Check 5 (reject-pile) which is `needs-triage` because the underlying
  cause requires user judgment.

## What NOT to check

- The semantic correctness of a proposal's diff_preview. That's
  `/bridge-learn`'s job at accept-time.
- Whether a proposal is "good idea" — the curator measures only mechanical
  health of the queue, not idea quality.
- Privacy/leak content of proposals — `/bridge-leak-check` owns OSS-safety.
