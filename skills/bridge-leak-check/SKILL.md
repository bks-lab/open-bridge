---
name: bridge-leak-check
description: >-
  Content-leak scanner with categorized classification. Different from a raw
  blocklist grep: each hit is sorted into legitimate-self-reference,
  legitimate-sister-repo, personal-PII (always leak), or internal-vocabulary
  hardcoded (OSS-strict only). Use after a sync to verify the destination is
  actually clean — catches pre-existing leaks the source-side scan won't see.
  Also runs OSS-strictness vocabulary checks (e.g. "scope: bks" hardcoded
  in OSS-shipped skill docs that should use "scope: org" placeholder).
  Trigger: "/bridge-leak-check", "leak scan", "leak check", "OSS readiness",
  "pre-existing leaks", "cleanliness check", "is this OSS clean".
metadata:
  scope: core
---

# Bridge Leak Check — Categorized Content Scan

`bridge-leak-check` runs over a *current repo state* (not a diff), greps
the configured blocklists, and **categorizes** every hit into one of four
buckets so you don't drown in false positives. It complements
`rules/promote-safety.md` (which scans a diff per-destination at promote
time) by running on the **post-merge** state.

Read the referenced file ONLY when triggered.

## Why both scans exist

| Scan | When | Scope | Strength |
|---|---|---|---|
| `rules/promote-safety.md` | At promote time | Diff only | Catches leaks introduced by the current commit |
| `bridge-leak-check` | Anytime | Whole repo state | Catches pre-existing leaks (from prior promotes, seedings, manual commits) |

The session that birthed this skill discovered that a clean source-side
scan does not guarantee a clean destination — `open-bridge` had three
pre-existing leaks (`<your-username>-bks.yaml` examples, `com.bks.my-service`,
`bks` wordmark) that no single promote scan caught because they predated
the per-repo blocklist.

## Arguments

| Argument | Effect | Default |
|---|---|---|
| `(none)` | Scan current repo with the matching blocklist (auto-detected from `.git/config` origin) | — |
| `--repo <name>` | Force which blocklist to apply (`open-bridge` / `org-overlay` / `your-bridge` / `fallback`) | auto |
| `--strict-oss` | Also flag internal-vocabulary hardcoding (uses `vocabulary_renames` from `bridge-audit/data/renames.yaml`) | false |
| `--report-only` | Only show categorized report; don't suggest fixes | false |
| `--target-dir <path>` | Scan a different working tree (e.g. `/tmp/cloned-upstream`) | `.` |

## Categories

Every hit lands in exactly one bucket:

| Category | Marker | Example | Action |
|---|---|---|---|
| **Legitimate — self-reference** | ✅ ✓ | `bks-lab/open-bridge` inside the open-bridge repo, schema `$id` URLs that point at this repo's published schemas | Skip — this is correct |
| **Legitimate — sister-repo** | ✅ ✓ | `{org}/bridge-deck` cross-link in same OSS family | Skip — this is correct |
| **Leak — personal PII** | 🔴 | `<your-username>`, `<your-username>`, `~/`, personal hostnames | Always fix — replace with `<your-username>` placeholder |
| **Leak — internal vocabulary** (OSS-strict) | 🟡 | an org-shortname scope value (e.g. `scope: acme`) in shipped skill docs, a hardcoded `org-bridge` overlay slug as the only "internal overlay" example | Generalize — see `vocabulary_renames` in `bridge-audit/data/renames.yaml` |

## Decision Tree

```
User wants to...
├── Verify a fresh clone is OSS-clean         → references/classification.md § standard scan
├── Categorize hits in current repo           → references/classification.md § standard scan
├── Run on a temp clone (post-merge verify)   → --target-dir <path>
├── Add a new self-reference exception        → edit references/classification.md § exceptions
└── Add an internal-vocabulary rename         → edit bridge-audit/data/renames.yaml § vocabulary_renames
```

## Output Shape

```
Bridge Leak Check — <repo>:<branch>  (<timestamp>)
Blocklist: open-bridge (strict)

✅ Legitimate self-reference (5 hits, no action needed)
   bks-lab/open-bridge schema $id URLs — 5 files

✅ Legitimate sister-repo (1 hit, no action needed)
   docs/calendar.md:110 → github.com/{org}/bridge-deck

🔴 Personal PII leaks (0 hits)
   None — clean ✓

🟡 Internal-vocabulary hardcoded (3 hits — strict-OSS mode)
   skills/bridge-promote/SKILL.md:24 — "scope: org" should be "scope: org"
   skills/bridge-onboard/SKILL.md:31 — "internal org-bridge" should be "<your-org>/<your-bridge>"
   infra/channels/_schema.yaml:101 — "com.bks.*" should be "com.example.*"

Verdict: 3 OSS-strict findings (yellow). No personal PII. No customer codenames.
```

## See also

- `bridge-audit` — drift detection (sibling skill; uses the same `data/renames.yaml`)
- `bridge-sync` — uses this skill in Step 11 (post-merge verification)
- `rules/promote-safety.md` — diff-time content scan (different layer, complementary)
