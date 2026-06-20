---
name: bridge-learn
description: >-
  Review surface for Bridge Learning-Loop proposals — lists pending improvement
  suggestions from work/_learning/proposals/, groups by severity (P0 → P3),
  walks the user through each proposal with accept/reject/edit/defer decisions.
  Accept applies the diff_preview (or asks the user for the patch), moves the
  proposal file to proposals/accepted/, logs to audit-trail.md, and suggests a
  commit message. Reject asks for a one-line reason, moves to
  proposals/rejected/, logs. Optional trends section shows audit-history
  recurring findings and sleeping skills (Phase 3+4 data). Auto-surfaces in
  /briefing on Fridays when N+ pending (threshold in
  bridge-config.yaml.learning.proposals.auto_surface_threshold).
  Trigger: "/bridge-learn", "bridge learn",
  "review proposals", "learn review", "what did we learn", "pending proposals",
  "improvement queue", "review improvements", "check proposals",
  "review improvements", "what have we learned".
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

# Bridge Learn — Review Surface for Improvement Proposals

`/bridge-learn` is the **Layer-3 edge** of the Bridge Learning-Loop architecture
(see `work/_learning/README.md`). It consumes proposals written by
`task-close-postmortem` (Phase 1) or `/bridge-audit` recurring findings
(Phase 3) and walks the user through accept/reject decisions.

**Never auto-apply.** Every accepted proposal is materialized through a git
commit on `user/<name>`, audit-trail.md records it, `git revert` is always
the rollback path.

## When to use

| Trigger | Mode |
|---|---|
| User says `/bridge-learn` / "review proposals" / "learn review" | **Interactive** — full walk-through |
| /briefing skill invokes (Fridays, when pending ≥ threshold) | **Summary** — count + 1-line list, no walk |
| User says `/bridge-learn list` | **List-only** — no actions, just an overview |
| User says `/bridge-learn trends` | **Trends** — recurring + sleeping skills, no proposals |
| User says `/bridge-learn <proposal-id>` | **Single** — go directly to that proposal |

## Inputs

- `work/_learning/proposals/*.md` — all pending proposals
- `work/_learning/audit-trail.md` — lifecycle log (for statistics)
- `work/_learning/audit-history/` — Phase 3, for trends section
- `bridge-config.yaml.learning` — thresholds (auto_surface_threshold etc.)
- (Optional) `work/_learning/skill-usage.jsonl` — Phase 4, for "sleeping skills"

## Interactive walk-through

### Header

```
═══ Bridge Learning Review — 2026-05-13 ═══

📋 Pending Proposals (N)
  P0  <id-1>                 (<source-type>)
  P1  <id-2>                 (<source-type>)
  P2  <id-3>                 (<source-type>)
  ...

📈 Trends (last 30d)              [if audit-history populated]
  Audit findings:  P0=0  P1=12→8  P2=23→27  P3=5
  Skills inactive: <N> of <total>  [if skill-usage populated]
  Task estimate-vs-actual: median 1.4x (vs 1.2x last month)

🔁 Recurring patterns (≥3 occurrences)
  - <pattern-1>  [→ proposal/audit-recurring exists]
  - <pattern-2>  [new — consider Standing-Order]

→ Review proposals one by one? [y/N]
→ Or: trends / list / quit
```

Sort proposals by:
1. Severity (P0 first, then P1, P2, P3)
2. Within severity: oldest `created` first
3. Within same date: alphabetical by id

### Per-proposal view

```
╭─ Proposal: <id> ──────────────────────────────────────╮
│                                                       │
│ Severity: <P0-P3>   Status: pending   Scope: <scope>  │
│ Source: <type> (<task-slug or audit-ref>)             │
│ Created: <YYYY-MM-DD>                                 │
│                                                       │
│ Evidence:                                             │
│   <list of source.evidence pointers>                  │
│                                                       │
│ Target: <type>/<action> — <path>                      │
│                                                       │
│ Body (excerpt or full if <50 lines):                  │
│   <markdown body of proposal>                         │
│                                                       │
│ Proposed diff (if diff_preview set):                  │
│   <diff_preview block>                                │
│                                                       │
╰───────────────────────────────────────────────────────╯

[a]ccept  [r]eject  [e]dit  [d]efer  [s]kip  [q]uit
```

### Action: accept

1. If `diff_preview` is set AND is a literal diff/patch:
   - Resolve `target.path` against repo root
   - For `action: create`: write file from diff body
   - For `action: edit`: apply diff
   - For `action: delete`: remove file
   - For `action: rename`: parse new path from body, git mv
2. If `diff_preview` is descriptive prose (not literal diff):
   - Ask user: "Should I write the patch now? [y/n/edit]"
   - If yes: generate patch based on proposal body, show preview, then apply
   - If edit: user can refine the patch interactively
3. Verify target file is valid (syntax-check YAML if YAML, schema if defined)
4. `git mv work/_learning/proposals/<id>.md work/_learning/proposals/accepted/<id>.md`
5. Append to `work/_learning/audit-trail.md`:
   ```
   | 2026-05-13 14:30 | <id> | pending → accepted | <user-supplied note or ""> | <commit-hash-or-staged> |
   ```
6. Suggest a commit message (short, in the proposal's style):
   ```
   Suggested commit: <type>(<scope>): <one-line summary from proposal>
                     <2-3 line body>

   Commit now? [y/n/edit]
   ```
7. If user accepts commit: run `git commit -m ...` on the staged changes
   PLUS the moved proposal file. Capture commit hash, update audit-trail.md
   row to point at the real hash.
8. Mark status: `accepted` in proposal's frontmatter (Edit tool).
   If commit succeeded: transition to `implemented` and update frontmatter again.
9. **Upstream hint (scope: core only):** if the accepted proposal has
   `scope: core`, the improvement is by definition generic — offer it to
   the community:
   ```
   💡 This improvement is scope:core — consider contributing it upstream
      via /bridge-promote → contribute (fork-based PR to the OSS upstream,
      content-safety gate runs first). Run now? [y/N]
   ```
   If yes: hand off to `skills/bridge-contribute/references/workflow.md`
   with the just-created commit as the candidate. Never auto-submit —
   the contribute flow has its own gates (leak scan + DCO + user confirm).

### Action: reject

1. Ask: "One-line reason? (why reject — will be logged in audit-trail)"
2. `git mv work/_learning/proposals/<id>.md work/_learning/proposals/rejected/<id>.md`
3. Update proposal frontmatter: `status: rejected` + append `reject_reason:` field
4. Append to `audit-trail.md`:
   ```
   | <ts> | <id> | pending → rejected | <reason> | — |
   ```

### Action: defer

1. Ask: "Defer until when? (e.g. 'next-week', '2026-06-01', 'phase-3')"
2. Update proposal frontmatter: `status: deferred` + `defer_until: <user-input>`
3. Leave file in `work/_learning/proposals/` (don't move — defer means "still pending later")
4. Append to `audit-trail.md`:
   ```
   | <ts> | <id> | pending → deferred (<defer_until>) | <reason or ""> | — |
   ```

### Action: edit

1. Open the proposal file for user edit (`$EDITOR work/_learning/proposals/<id>.md`)
2. After edit: re-validate frontmatter against `_schema.proposal.yaml`
3. Return to per-proposal view with updated content
4. User can then accept/reject/defer/skip again

### Action: skip

No state change. Move to next proposal.

### Action: quit

Save progress (which proposals were touched), exit cleanly. Print summary:

```
✅ Reviewed N proposals: <a> accepted, <r> rejected, <d> deferred, <s> skipped.
   <X> commits staged (run /commit or git commit to push).
   <Y> still pending — run /bridge-learn anytime.
```

## Summary mode (called by /briefing on Fridays)

When invoked by /briefing or `/bridge-learn summary`:

```
🧠 Learning Loop — Pending Review (<N>)
   P0: <count>   P1: <count>   P2: <count>   P3: <count>
   Oldest pending: <YYYY-MM-DD> (<id>)
   → /bridge-learn to review
```

No interactive walk. Just numbers + pointer.

## List mode

`/bridge-learn list` — one line per proposal, no walk:

```
📋 Pending Proposals (<N>)
   P1 2026-05-08 <id>    skill customer-a-coordinator triggers too broad
   P2 2026-05-13 <id>    standing-order research-claim-verification (NEW)
   P3 2026-05-10 <id>    memory: tahoe sleep behavior
   ...
```

Useful when user just wants to scan, not act.

## Trends mode

`/bridge-learn trends` — focuses on Layer-2 aggregated signal:

**Audit history (Phase 3):**
- Per-check severity trend: "skill-tree-drift P1 went 12 → 8 over 30d"
- Recurring fingerprints (≥3 runs same finding): list with first/last seen dates
- New-this-week findings: list

**Skill usage (Phase 4, opt-in):**
- Inactive >30d: list
- Inactive >60d: list (review-or-delete candidates)
- Most-used (top 5): "for context, not action"
- Time-spent: skills with median duration >5min (split candidates)

**Task estimate-vs-actual:**
- From `work/done/YYYY-MM/*/STATUS.md`: parse `estimate_vs_actual` field
- Median + worst-case last month
- Flag: ">3x" tasks (where did time go?)

**Trigger corrections (Phase 4):**
- Skills with ≥2 corrections in 30d: list with example mismatches

## Friday auto-surface (called by /briefing)

In `/briefing`, after Stream B (board) but before Stream D:

```python
threshold = config.learning.proposals.auto_surface_threshold  # default 5
trigger_day = config.learning.proposals.auto_surface_in_briefing  # default "friday"

if today == trigger_day and pending_count >= threshold:
    invoke bridge-learn in summary mode
```

The summary lands as a /briefing block. User can drill in with `/bridge-learn`.

## Schema validation

Before any action, validate the proposal file:
- Frontmatter parses as YAML
- Required fields present (id, created, source, severity, status, scope, target, proposal_type)
- `status` is one of the enum values
- `target.path` is a non-empty string
- If `target.action: edit` or `delete`: target file must exist
- If `target.action: create`: target file must NOT exist

If validation fails: show clear error + offer to repair via `edit` action.

## Commit-message conventions

The skill suggests commit messages following repo convention:

| Target type | Commit prefix |
|---|---|
| skill | `skill(<skill-name>):` |
| standing_order | `standing-order(<name>):` |
| rule | `rule(<name>):` |
| doc | `docs(<area>):` |
| protocol | `protocol(<name>):` |
| memory | `memory:` (or skip commit — memory edits go via auto-memory) |
| schema | `schema(<name>):` |
| config | `config(<scope>):` |

Use imperative present tense ("add", "tighten", "remove") — never "added" or "adding".

## What this skill deliberately does NOT do

- ❌ Auto-accept based on pattern (e.g. "all P3 from postmortem → reject")
- ❌ Auto-write proposals (that's task-close-postmortem and /bridge-audit Phase 3)
- ❌ Push commits (user runs `git push` separately if desired)
- ❌ Cross-instance reasoning (only this repo's proposals)
- ❌ Edit MEMORY.md directly (proposal can suggest a memory entry, but the
  actual memory write goes through the auto-memory system — `target.type: memory`
  proposals produce a suggested entry text + path, user copy-pastes)
- ❌ Notify externally (no Slack, no email — `/briefing` is the surface)

## Edge cases

- **No pending proposals** → print "✅ No pending proposals. Run a task close or `/bridge-audit` (Phase 3) to generate signal."
- **Proposal file malformed** → show validation error + `[e]dit` action; do not act on broken file.
- **Two proposals target same file** → flag both, ask user "these overlap — pick one?" (one accept implicitly supersedes the other; mark loser as `superseded`).
- **`target.action: create` but file exists** → ask user: accept-and-overwrite / convert-to-edit / reject.
- **Proposal `scope: core` but content mentions org/customer names** → block accept until /bridge-leak-check passes. (Run leak-check inline before move.)
- **User runs out of time mid-walk** → `[q]uit` saves progress. Resume any time.

## Related

- `skills/task-close-postmortem/SKILL.md` — Layer 1 source of proposals
- `skills/bridge-audit/` — Phase 3 source of recurring-finding proposals
- `work/_learning/README.md` — aggregation layer documentation
- `work/_learning/_schema.proposal.yaml` — proposal frontmatter schema
- `protocols/standing-orders/task-sync.md` — close-out flow that feeds proposals
- `bridge-config.yaml.learning.proposals` — thresholds + Friday-surface config
- `skills/briefing/` — invokes bridge-learn in summary mode on Fridays
