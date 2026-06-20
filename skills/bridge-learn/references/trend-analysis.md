---
summary: "Trend-detection algorithms for /bridge-learn trends mode and the auto-recurring-proposal generation logic. Consumes work/_learning/audit-history/*.json (Phase 3) and skill-usage.jsonl (Phase 4 opt-in)."
type: reference
last_updated: 2026-05-13
---

# Trend Analysis — Aggregation Logic

`/bridge-learn trends` and the auto-recurring-proposal pipeline both rely on
the same aggregations over `work/_learning/`. This reference defines the
algorithms.

## Sources

| File | Written by | Phase | What it contains |
|---|---|---|---|
| `work/_learning/audit-history/<ts>.json` | `/bridge-audit` post-run hook | 3 | One JSON per audit run with per-check findings |
| `work/_learning/proposals/*.md` | this skill + task-close-postmortem | 1+ | Pending proposals (for status counts) |
| `work/_learning/audit-trail.md` | this skill | 2 | accept/reject history |
| `work/_learning/skill-usage.jsonl` | PostToolUse hook (opt-in) | 4 | One JSON line per skill invocation |
| `work/_learning/trigger-corrections.md` | Claude (when user corrects skill load) | 4 | Manual append on correction events |
| `work/done/YYYY-MM/*/STATUS.md` | task-close (3-step move) | 1 | Closed-task frontmatter with `estimate_vs_actual` etc. |

## Audit-history fingerprint matching

Each finding in `audit-history/*.json` has a `fingerprint` field (SHA-256 of
normalized finding-payload, computed by `/bridge-audit`). To detect recurring:

1. Load last N audit runs (default N=10) sorted by timestamp descending
2. Build `fingerprint → [run_ts...]` map across all check-categories
3. For each fingerprint with `len(run_ts) >= 3`:
   - Sort run_ts ascending
   - Compute streak: how many CONSECUTIVE most-recent runs contain this fp?
   - If consecutive_streak >= 3: this is a "recurring finding"
4. Emit recurring-findings list

Edge cases:
- Finding payload changes wording but is same root cause → fingerprint differs,
  miss. Future work: fuzzy fingerprint.
- Finding fixed but reappears 30d later → counts as new streak. OK.
- Same finding in same run (multiple subcategories) → dedupe within run before counting.

## Auto-proposal generation (recurring → proposal)

When `/bridge-learn trends` detects a recurring fingerprint that does NOT yet
have a matching proposal in `work/_learning/proposals/`:

```yaml
# Auto-generated proposal file:
# work/_learning/proposals/YYYY-MM-DD-audit-recurring-<fingerprint-short>.md

---
id: <YYYY-MM-DD>-audit-recurring-<fingerprint-short>
created: <YYYY-MM-DD>
source:
  type: audit-recurring
  evidence:
    - "work/_learning/audit-history/<oldest-ts-in-streak>.json"
    - "work/_learning/audit-history/<latest-ts-in-streak>.json"
  fingerprint: <full-sha256>

severity: <one-level-up-from-finding-severity>  # P1 finding → P0 proposal
status: pending
scope: <derived from target>

target:
  type: <from finding category>
  path: <from finding details>
  action: <edit | create — context-dependent>

proposal_type: structured
diff_preview: <if finding includes suggested fix, copy here>
---

# Proposal: <finding summary>

## Motivation

Recurring audit finding — seen in <N> consecutive `/bridge-audit` runs since
<oldest>. Has not been fixed across <N>×audit cycle.

## Vorschlag

<from finding suggested-fix if present, else "Triage needed — see evidence">

## Konkrete Wirkung

<finding's reasoning, or empty>

## Akzeptanz-Kriterien

- [ ] Next `/bridge-audit` run does NOT report fingerprint <fp-short>
```

Auto-proposals are written ONLY in `/bridge-learn trends` mode (manual) or
during a scheduled trends run. **Never silent background generation** — user
sees the proposal create at trends-time.

## Skill-usage aggregation (Phase 4)

If `work/_learning/skill-usage.jsonl` exists and has entries:

```json
{"ts": "2026-05-13T08:56:00Z", "skill": "customer-a-coordinator", "duration_ms": 12345, "outcome": "completed"}
{"ts": "2026-05-13T09:42:00Z", "skill": "task-close-postmortem", "duration_ms": 78900, "outcome": "completed"}
```

Aggregations:
- **Inactive skills** — for each skill in `skills/`, find last invocation in jsonl.
  If `last_ts < now - 30d`: flag.
- **Hot skills** — top-5 by invocation count last 30d.
- **Slow skills** — median duration > 5min in last 30d (split-candidates).
- **High-abort skills** — `outcome=aborted` rate > 30% (review trigger or workflow).

Skill-usage data is **scope:user** — never promotes to your org overlay or open-bridge.

## Trigger-correction aggregation

Parse `work/_learning/trigger-corrections.md` (free-form markdown with H2-anchored
entries). For each skill, count corrections in last 30d. If `count >= 2`: emit
trend entry.

Example correction-file entry format:
```markdown
## 2026-05-13 08:56 — customer-a-coordinator triggered, user wanted general invoice
User: "take a look at the invoice pipeline"
Loaded: customer-a-coordinator
Correction: "no, generally, not customer-a"
Lesson: trigger "invoice" alone is too broad
```

Aggregation: group by "Loaded:" value, count occurrences. Output as part of
trends mode.

## Estimate-vs-actual aggregation

Walk `work/done/YYYY-MM/*/STATUS.md`. For each STATUS with `estimate_vs_actual`
set:

- Map enum to numeric: `ok=1.0`, `1.5x=1.5`, `2x=2.0`, `3x=3.0`, `>3x=4.0`,
  `re-scoped=null (skip)`, `—=null (skip)`
- Group by closed-month
- Compute median + 90th percentile per month
- Trend: this-month vs last-month

If 90th-percentile > 2.5x: flag "estimates are systematically optimistic in
<context>" (filter by `context:` field for granularity).

## Output format for /bridge-learn trends

```
═══ Bridge Learning Trends — last 30d ═══

📊 Audit findings (from <N> runs)
   P0: 0       (stable)
   P1: 12 → 8  (improving)
   P2: 23 → 27 (slipping — investigate)
   P3: 5       (stable)

🔁 Recurring fingerprints (≥3 consecutive runs)
   1. skill-tree-drift / README ↔ skills/ — 4 runs since 2026-05-03
      → no matching proposal — auto-generate? [y/N]
   2. cross-ref-broken / docs/extension-model.md L42 — 3 runs since 2026-05-08
      → matching proposal exists: 2026-05-09-docs-fix-xref

😴 Inactive skills (>60d, candidates for review-or-delete)        [if Phase 4]
   - voice-clone-deprecated  (last seen 2026-03-04)
   - kibana-dashboard-manager  (last seen 2026-04-12, key expired)

🎯 Estimate-vs-actual (median per month)
   2026-05: 1.4x  (n=12 closed tasks)
   2026-04: 1.2x  (n=15)
   Trend: slipping. Worst-case >3x:
     - voice-customer-automation
     - engagement-planning-example

⌨  Trigger corrections (≥2 in 30d)                                 [if Phase 4]
   - customer-a-coordinator: 3 corrections
     (user wanted general invoice-related work, skill triggers on "invoice")

→ Generate proposals for the 1 ungrouped recurring finding? [y/N]
→ Or: /bridge-learn (review pending) / /bridge-learn list / quit
```

## Performance budget

Trends run reads at most:
- 10 audit-history JSONs (~50KB total)
- ~50 STATUS.md files from work/done/ (~500KB)
- skill-usage.jsonl streaming line-by-line (cap at 10MB)
- trigger-corrections.md whole file

Target: <2s wall-clock on a warm cache. If slower: profile, batch, cache.
