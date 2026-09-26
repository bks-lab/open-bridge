---
name: bridge-audit
description: >-
  Finds drift between docs and reality in Bridge repos: license badge vs LICENSE,
  README skill list vs skills/ dir, broken cross-refs, cross-instance skill
  shadowing. Returns a P0-P3 report with fix proposals. Trigger: "/bridge-audit",
  "audit", "drift check", "find drift", "are my skills shadowed".
metadata:
  scope: core
---

# Bridge Audit — Drift Detection

`bridge-audit` is the systematic version of "let me re-read the README
and see what doesn't match anymore". It runs 15 categorical checks
against the current repo state and returns a stratified report.
Check 9 only runs with `--cross-repo` (it fetches sister-repo trunks);
Check 10 (agent-identity health), Check 11 (gate-shaped memory),
Check 12 (config-driven CORE skills), Check 13 (user-level skill
shadowing), Check 14 (skill learnings pairing) and Check 15 (question
map) always run.

Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Full audit, all checks | — |
| `--check <name>` | Run only one check (license / skill-tree / protocol-count / renames / xrefs / scopes / routing-sot / typos / agent-identity / memory-gate / config-driven / skill-shadowing / skill-learnings) | all |
| `--cross-repo` | Also clone configured upstreams and compare README/AGENTS for divergence | false |
| `--strict-oss` | When run on an OSS variant: flag hardcoded internal vocabulary (delegates to `bridge-leak-check`) | false |
| `--fix` | Where unambiguous, apply the suggested fix | false (advisory only) |
| `--no-history` | Skip writing the post-run JSON to `work/_learning/audit-history/` | history written by default if `learning.enabled` |
| `--no-recurring-scan` | Skip the trend-detection step that auto-generates proposals for recurring findings | scan runs by default |

## The 13 Checks

| # | Check | What it compares | Severity hint |
|---|---|---|---|
| 1 | License consistency | README badge ↔ LICENSE file ↔ README footer ↔ CLAUDE.md license claim ↔ MEMORY mentions | P0 if any disagree |
| 2 | Skill-tree truth | README skill table/tree ↔ AGENTS.md skill table ↔ `skills/*/SKILL.md` actual | P1 |
| 3 | Standing-order count | "N standing orders" claims ↔ `protocols/standing-orders/*.md` count (excluding `_template.md`, `README.md`) | P1 |
| 4 | Renamed-everywhere | `data/renames.yaml` old-name greps in tracked content (excluding listed exceptions) | P1 |
| 5 | Cross-reference validity | Markdown `[text](path)` and `` `path` `` references resolve to existing files | P2 |
| 6 | Scope coverage | Group A: `skills/*/SKILL.md` have explicit `scope:` under `metadata:` (`metadata.scope`); `.claude/agents/*.md` have explicit top-level `scope:` (P2); `rules/*.md` scope is REQUIRED + hard-gated by `validate-bridge.py` (P1). Group B: every `identity/{mandants,accounts,personas}/*.yaml` + `workflow/{contexts,projects}/*.yaml` + `infra/{remotes,channels}/*.yaml` has the required top-level `scope:` (P1 — schema-enforced, routing-critical) | P1/P2 |
| 7 | Routing-SoT conflicts | Multiple files claim authoritative status for the same routing domain (heuristic: same path appears in multiple "source of truth" tables with different rules) | P2 |
| 8 | Typo lint | Bridge-corpus typo patterns from `data/typo-patterns.yaml` | P3 |
| 9 | Skill-tree sync coverage (`--cross-repo` only) | Local `skills/*/` scope ↔ each upstream's `skills/` directory listing — forward-drops + reverse-leaks | P1 (P0 if outstanding >2 sync windows) |
| 10 | Agent-identity health | `identity/agent/SOUL.md` present + ≤80 lines / ≤4 KB · `IDENTITY.md` present · both carry valid frontmatter (`schema_version`/`type`/`scope`/`last_updated`) | P1 if SOUL.md missing, else P2 |
| 11 | Gate-shaped memory without a `rules/` home | Memory files whose body uses gate language (imperative + always/never/immer/nie, or "when X → do Y" routing) but have NO corresponding rule in `rules/` (core/bks/user) — a behavioral rule trapped in the private store. Also runs the index lint and the session-link count (`memory-location.py check`, `links`) | P2 (index lint P1, dead session links P3) |
| 12 | Config-driven CORE skills | `scope: core` skill files (`SKILL.md` + `references/`) that hardcode instance specifics — org/project IDs, tracker queries, persona names, pipeline IDs, absolute instance paths — instead of reading them from `bridge-config.yaml` / `workflow/` / `infra/` / `identity/` (CLAUDE.md § Generic CORE Skills) | P2 |
| 13 | User-level skill shadowing | `~/.claude/skills/` (resolved) ↔ this repo's `skills/` — the user level overrides the project level, so a pointer at a Bridge repo silently serves one instance's skills to every other instance (AGENTS.md § Skills). Both directions: this instance shadowing others, and others shadowing this one (with `diff -rq` drift per colliding name). Also reports scripts that resolve the path as a filesystem location | P0 if own skills are shadowed or instance-bound skills (scope org or user) leak machine-wide, else P1 |
| 14 | Skill learnings pairing | `python3 scripts/check-skill-learnings.py`: a skill with `LEARNINGS.md` but no routing block in SKILL.md, a routing block without a journal, or an undated journal heading (`docs/skill-learnings.md`) | P2 |
| 15 | Question map | `python3 scripts/check-where-things-live.py`: a row of `docs/where-things-live.md` or the instance's `work/where-things-live.md` that is a topic instead of a question, a link or `#section` that does not resolve, or a question asked twice | P2 |

## Decision Tree

```
User wants to...
├── Full audit                          → references/checks.md
├── Single check                        → references/checks.md § the named check
├── Cross-repo divergence               → references/checks.md § cross-repo mode
├── OSS-strictness pass                 → delegate to bridge-leak-check
├── Auto-fix unambiguous findings       → references/checks.md § --fix mode
└── Add/extend a rename to track        → edit data/renames.yaml directly
```

## Output Shape

```
Bridge Audit — <repo>:<branch>  (<timestamp>)

P0 — License (1 finding)
  README badge says "MIT", LICENSE file is Apache 2.0, README footer says "Apache 2.0 — see LICENSE"
  → Pick one. Suggested fix: replace LICENSE + footer with MIT.

P1 — Skill tree (3 findings)
  README lists `cockpit-office/`, `bks-context/`, `bridge-bks-export/` — none exist in skills/.
  Existing but unlisted: `bridge-dashboard`, `bridge-sync`.
  → Update README skill tree.

...

P3 — Typo (1 finding)
  docs/structure.md:121 "gepushtdurch" — missing space.
  → Fix.
```

## Post-run JSON history (Phase 3 — Learning Loop integration)

After every audit run, if `bridge-config.yaml.learning.enabled` is `true`
(default) and `--no-history` is NOT set, write a structured JSON dump of all
findings to `work/_learning/audit-history/<YYYY-MM-DD-HHMM>.json`. The file
format is defined in [`references/audit-history-format.md`](references/audit-history-format.md).

Why: a single audit run prints findings to the terminal and they're gone.
Persisting findings lets `/bridge-learn trends` detect **recurring** drift
— the same finding appearing in 3+ consecutive runs is a stronger signal
than a one-off P2 in a single report.

The JSON write is the LAST step of the audit run, after the human-readable
output. It runs even if `--fix` applied some fixes (the JSON reflects state
before fixes, so the next run can show the diff).

### Fingerprint computation

Each finding has a `fingerprint` field — a stable SHA-256 hash of the
finding's identity, NOT its prose. Use this normalized payload:

```
SHA-256 of utf8(
  check_name + "\n" +
  target_path + "\n" +
  normalize(summary)
)
```

Where `normalize(s)` = lowercase, collapse whitespace, replace absolute
paths with repo-relative, strip timestamps, strip line numbers within ±5.

This is what makes "the same finding" stable across runs even if README
content shifts.

## Learning-ledger consistency (read-only)

Run `python3 scripts/learning-ledger.py check` once per audit. Each line it
prints (a proposal whose folder, frontmatter `status` and last audit-trail row
disagree, a placeholder timestamp, an implemented row without a commit, a row
with no proposal file) is one **P2** finding with the line as its text. The
audit never repairs them: `/bridge-learn` owns those files. Exit 0 means no
finding.

Optional, off by default: `learning-ledger.py check --provenance` also compares
each skill's `references/provenance.md` with the trail's implemented rows, both
ways. Run it only when asked; it starts opt-in because the convention starts
at zero adoption. Report its lines as P3.

## Recurring-findings auto-proposal (Phase 3)

After writing the history JSON, scan the **last 10 history files** for
fingerprints that appear in **≥3 most-recent consecutive runs**. For each
recurring fingerprint:

1. Check if `work/_learning/proposals/*.md` already has a proposal whose
   frontmatter `source.fingerprint` matches. If yes: skip (proposal exists).
   Then widen the lookup to `proposals/rejected/`: run
   `python3 scripts/learning-ledger.py prior-rejections <target.path>` for the
   path the new proposal would target. On a hit, carry `prior_rejections:` and
   argue the difference in the body, or skip writing. Never neither.
2. If no proposal exists: write a new proposal file
   `work/_learning/proposals/<YYYY-MM-DD>-audit-recurring-<fp-short>.md`
   using the template in `skills/bridge-learn/references/trend-analysis.md`.
3. Severity = ONE-LEVEL-UP from the finding's severity (P1 finding → P0
   proposal, P3 finding → P2 proposal). Rationale: recurring P1 is worse
   than fresh P0 — it's been left.
4. `source.type: audit-recurring`, `evidence:` points to oldest + latest
   history JSON in the streak.
5. Surface to user at end of audit run:
   ```
   🔁 1 recurring finding auto-generated as proposal:
     work/_learning/proposals/2026-05-13-audit-recurring-3f2a8b1c.md
     (skill-tree-drift / README ↔ skills/ — 4 consecutive runs)
   → Review at /bridge-learn
   ```

This skip-able with `--no-recurring-scan` for cases where you're audit-
debugging the audit itself (avoid feedback loop).

## Maintenance contract

- New rename happens in repo? → add to `data/renames.yaml`, audit catches future drift.
- New typo pattern noticed twice? → add to `data/typo-patterns.yaml`.
- New cross-doc invariant? → add a check to `references/checks.md` and a row to the table here.
- A gate-shaped memory keeps reappearing in Check 11? → promote it to `rules/<tier>/` (memory stays as dated provenance); see `rules/knowledge-growth.md` for where behavioral rules belong.
- Audit-history files getting large (>365)? → roll up oldest 30 days into monthly aggregates;
  see `references/audit-history-format.md` § Retention.

## See also

- `bridge-leak-check` — content-blocklist scan + OSS-strictness pass (legitimate vs leak categorization)
- `bridge-sync` — cross-repo propagation of fixes (uses bridge-audit + bridge-leak-check internally)
- `bridge-learn` — Phase 2 review surface; consumes the audit-history JSON via trend mode
- `task-close-postmortem` — Phase 1 proposal-writer (different source: postmortem instead of audit)
- `work/_learning/README.md` — the aggregation layer this writes into
- `rules/operations.md` — CORE/USER path discipline
- `rules/promote-safety.md` — content scan rules
