---
summary: "Detailed step-by-step workflow for the accept/reject/defer/edit actions, with explicit file moves, audit-trail format, and commit-message generation rules."
type: reference
last_updated: 2026-05-13
---

# Review Workflow — Detail

This reference complements `SKILL.md` § Per-proposal view. The SKILL document
describes WHAT happens; this document is the HOW (file paths, exact commands,
audit-trail format, validation checkpoints).

## File move conventions

Three target folders inside `work/_learning/proposals/`:

```
proposals/
├── <id>.md                   ← pending (lives here by default)
├── accepted/<id>.md          ← after accept
└── rejected/<id>.md          ← after reject

(deferred and superseded proposals STAY in proposals/ root —
 status is tracked in frontmatter only)
```

Move command (always use `git mv` so history follows the rename):

```bash
git mv work/_learning/proposals/<id>.md work/_learning/proposals/accepted/<id>.md
# or rejected/<id>.md
```

If `git mv` fails (e.g. proposal wasn't committed yet), fall back to `mv` +
re-stage:

```bash
mv work/_learning/proposals/<id>.md work/_learning/proposals/accepted/<id>.md
git add -A work/_learning/proposals/
```

## Frontmatter status update

Use Edit tool on the proposal file (after the move):

```yaml
# Before:
status: pending

# After accept:
status: accepted              # or 'implemented' if commit landed
accepted_at: 2026-05-13       # ISO date
# implemented_commit and recurrence_fingerprint: written by
# `learning-ledger.py record <id> --to implemented`, never by hand

# After reject:
status: rejected
rejected_at: 2026-05-13
reject_reason: "the underlying skill change would conflict with customer-a Phase 4"

# After defer:
status: deferred
deferred_at: 2026-05-13
defer_until: "phase-3"        # free form: ISO date OR symbolic marker
defer_reason: ""              # optional

# After superseded:
status: superseded
superseded_by: <other-proposal-id>
superseded_at: 2026-05-13
```

## audit-trail.md format

One row per state transition, appended at the bottom, **written by
`scripts/learning-ledger.py record`, never composed by hand.** Hand-typed rows
drifted on a real instance: 17 of 37 lost their commit hash, one carried a
literal `%s` as its timestamp.

```bash
python3 scripts/learning-ledger.py record <id> --to accepted --reason "<note>"
python3 scripts/learning-ledger.py record <id> --to implemented        # right after the commit
python3 scripts/learning-ledger.py record <id> --to rejected --reason "<reason>"
python3 scripts/learning-ledger.py record <id> --to deferred --until next-week
```

What the script fills in and where from:

| Column | Source |
|---|---|
| Timestamp | the clock at the moment of the call, `YYYY-MM-DD HH:MM` |
| Proposal ID | the proposal file |
| Transition | its last trail row (or `pending`) → `--to`, plus `(--until)` for defer |
| Reason | `--reason`, the human's words passed through (pipes become `/`) |
| Commit | `implemented`: HEAD's short SHA and diffstat, `4f3a2b1 (2 files, +5/-1)`; otherwise `—` |

For a `target.type: skill` proposal, `--to implemented` also appends one line
to `work/_learning/provenance/<name>.md`, in the format `SKILL.md` accept
step 8 defines. That is the skill's own record of which proposal put a rule there and why,
readable without the trail. A skill that keeps a lesson journal points at this
file from its routing block ([`docs/skill-learnings.md`](../../../docs/skill-learnings.md)).

It refuses when the file's folder or `status:` does not match `--to` yet (move
the file and set the status first), when the proposal is already recorded in
that state (a second `implemented` would overwrite the real commit with the
bookkeeping commit), and for `implemented` when HEAD touches neither the
proposal file nor its target (the change is not committed yet). `python3 scripts/learning-ledger.py
check` finds rows and files that disagree after the fact.

## Validation checkpoints

Before any destructive action:

1. **Frontmatter parses** — load YAML, must be valid
2. **Schema-compliant** — required keys present, enum values valid
3. **Target resolves** — `target.path` is in-repo, parent exists
4. **Action-specific:**
   - `create` + target exists → block (ask user: overwrite / edit / reject)
   - `edit` + target missing → block (ask: re-target / reject)
   - `delete` + target missing → block (ask: already done? mark rejected)
   - `rename` + new-name from body → must be parseable
5. **OSS-scope safety** — if `scope: core` AND target is OSS-bound:
   - run `/bridge-leak-check` on the diff_preview before accept
   - if findings: block accept, show findings, ask user (downgrade scope to user / fix proposal / reject)

## Commit-message generation

Template:

```
<prefix>(<sub-scope>): <imperative summary, ≤72 chars>

<2-4 sentence body from proposal "Motivation" or "Vorschlag" section>

<optional footer: refs / related proposals>
```

**Prefix mapping** (from `target.type`):

| target.type | prefix |
|---|---|
| skill | `skill` |
| standing_order | `standing-order` |
| rule | `rule` |
| doc | `docs` |
| protocol | `protocol` |
| memory | (skip — use auto-memory) |
| schema | `schema` |
| config | `config` |

**Sub-scope** = file-name (kebab-case) for the target file.

**Summary line rules:**
- Imperative present ("add", "tighten", "remove", "rename")
- ≤72 chars total including prefix
- No period at end
- No "Claude", "AI", "Co-Authored-By" — per your global agent instructions

**Body rules:**
- Quote 1-2 lines from proposal "Motivation" if user-verbatim
- State the concrete effect (1 sentence)
- Reference related proposal IDs if `related:` field set

**Example generated commit:**

```
skill(customer-a-coordinator): tighten trigger to disambiguate from invoice

User correction in 3 sessions ("not customer-a, generally invoice"):
broad 'invoice' trigger was firing this skill for non-Customer A work.
Now explicit 'customer-a invoice' phrases only.

Refs: proposal 2026-05-08-customer-a-coordinator-trigger-too-broad
```

## Multi-proposal-same-target conflict

When two pending proposals target the same `target.path`:

```
⚠  Conflict detected — both target skills/customer-a-coordinator/SKILL.md:
   - <id-1>  (P2, source: trigger-correction, 2026-05-08)
   - <id-2>  (P3, source: postmortem, 2026-05-11)

Treat as:
[1] accept <id-1>, mark <id-2> superseded
[2] accept <id-2>, mark <id-1> superseded
[3] merge into combined accept (manual edit)
[4] skip both for now
```

`superseded_by` field bookkeeping mandatory.

## Idle-time review

If the user has reviewed N proposals in this session and the rest are P3 or
older than 30d, after the N-th proposal offer:

```
N proposals reviewed. <M> P3-or-stale-pending remain.
[r]eview those too  [d]efer all to next-month  [q]uit
```

Default: quit. Don't push fatigue.
