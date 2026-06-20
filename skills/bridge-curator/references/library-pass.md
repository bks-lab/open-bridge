---
summary: "Library-Pass procedure — scans skills/, protocols/, rules/, docs/ for drift (sleeping skills, trigger overlap, budget overruns, umbrella candidates) and emits one proposal per finding."
type: reference
last_updated: 2026-05-13
---

# Library Pass — Procedure

## Inputs

- `skills/*/SKILL.md` (frontmatter + description)
- `protocols/standing-orders/*.md` (frontmatter)
- `rules/*.md` (frontmatter)
- `docs/*.md` (`last_updated:` and cross-refs)
- `work/_learning/skill-usage.jsonl` if Phase-4 telemetry exists
- `work/_learning/audit-history/*.json` last N runs (for recurring-finding cross-ref)
- `work/log.md` last 60 days (heuristic skill-name matching when no telemetry)

## Checks

### Check 1 — Sleeping skill

For each `skills/<name>/SKILL.md`:

1. If `work/_learning/skill-usage.jsonl` exists: find last `{skill: <name>}`
   timestamp. If `now - last > 30d`: candidate.
2. Else: grep `work/log.md` last 60d for `<name>` or distinctive trigger
   phrase from description. If no match: candidate.

Output per candidate:

```yaml
source:
  type: curator-suggestion
  evidence:
    - "skills/<name>/SKILL.md"
    - "<usage-file-or-log-file>"
severity: P3
target:
  type: skill
  path: skills/<name>/
  action: edit   # update trigger phrases OR archive
proposal_type: structured
```

Body suggests: review trigger phrases, narrow scope, or archive. Don't
auto-recommend delete — sleeping ≠ obsolete.

### Check 2 — Trigger overlap

For all pairs of skills, compute the Jaccard similarity of their
trigger-phrase sets (extracted from description field after the "Trigger:"
marker). If ≥0.4: candidate.

For each pair:

- Compare the two skills' actual purposes (description first sentence)
- If purposes are clearly different but triggers overlap: propose
  trigger-tightening on the less-specific one
- If purposes are the same: propose umbrella merge

```yaml
source:
  type: curator-suggestion
  evidence:
    - "skills/<a>/SKILL.md"
    - "skills/<b>/SKILL.md"
severity: P2
target:
  type: skill
  path: skills/<less-specific>/SKILL.md
  action: edit
proposal_type: structured
```

### Check 3 — Description budget

Skills 2.0 budget: combined description + when_to_use ≤ 1536 chars. Per
skill, count `description` length.

- `>= 1536`: P1 — will get truncated; must fix
- `>= 1200`: P2 — risky, propose trim
- `<= 200`: P3 — possibly under-described, may trigger poorly

```yaml
source:
  type: curator-suggestion
  evidence: ["skills/<name>/SKILL.md"]
severity: P1 | P2 | P3
target:
  type: skill
  path: skills/<name>/SKILL.md
  action: edit
```

### Check 4 — Umbrella candidate

Cluster skills by shared phrases in their description (n-grams of length
3-5 words, weighted by rarity). Clusters of ≥3 skills with strong shared
phrases (top quartile) are umbrella candidates.

Output one proposal per cluster:

```yaml
source:
  type: curator-suggestion
  evidence: ["skills/<a>/SKILL.md", "skills/<b>/SKILL.md", "skills/<c>/SKILL.md"]
severity: P3
target:
  type: skill
  path: (new umbrella skill name to be decided)
  action: create
proposal_type: needs-triage
```

Body lists the cluster and notes that the user needs to decide the
umbrella name + which subset actually belongs together. Don't propose
deletions of the originals — the umbrella may end up obsoleting only
some of them.

### Check 5 — Stale doc

For each `docs/*.md` with frontmatter `last_updated: YYYY-MM-DD`:

1. Resolve cross-refs in the doc (markdown links to other repo files)
2. Find the latest `git log -1 --format=%ad` for each linked file
3. If `latest_linked_mtime > doc.last_updated + 30 days`: candidate
4. Drift severity = ceil(months-of-drift / 3) inverted to P-scale (P3 ≤3mo, P2 ≤6mo, P1 >6mo)

### Check 6 — Recurring audit finding without proposal

Read last 10 audit-history JSONs. For each recurring-detected fingerprint
that does NOT have a matching proposal in `work/_learning/proposals/`:
emit a curator-suggestion to write that proposal manually.

This is a safety-net for the case where Phase-3 recurring-detection
itself stopped writing proposals (e.g. wrong fingerprint mismatch, write
permission issue). Severity = severity of underlying finding + 1 level.

### Check 7 — Empty scope

`/bridge-audit` Check 6 catches missing `scope:`. If the same skill
appears in two consecutive audit JSONs without it: curator emits a
higher-severity proposal forcing the issue.

## Aggregation rules

- One finding per skill per check. Don't double-fire.
- If a skill triggers ≥3 checks: emit ONE compound proposal that lists
  all sub-issues instead of three separate ones. Body: nested bullets
  per check.
- Bound output: ≤15 library-pass proposals per run. If overflow:
  surface top-15 by severity, defer the rest to next curator run with a
  "library pass exceeded budget — see next run" log entry.

## What NOT to check

- Code-quality of skill bodies (markdown style, typos) — that's
  `/bridge-audit` Check 8.
- Cross-reference validity (broken `[text](path)` links) — that's
  `/bridge-audit` Check 5.
- License / footer / README skill-tree drift — that's `/bridge-audit`
  Checks 1-3.

Don't reproduce `/bridge-audit`'s job. The curator is about library
*shape* (drift, fragmentation, redundancy), not file-level correctness.
