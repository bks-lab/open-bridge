---
name: bridge-contribute
description: >-
  Contribute features and improvements from your Bridge back to the
  open-bridge OSS upstream (or your org overlay) as a fork-based pull
  request. Scans your user branch for upstream-worthy files, classifies
  them by scope, adapts org-specific content, runs the MANDATORY
  two-layer content-safety gate (leak scanner + per-repo blocklist,
  refuses on PII/customer hits), and opens the cross-fork PR with DCO
  sign-off — no upstream push access needed.
  Trigger: "/contribute", "contribute", "upstream contribution",
  "contribute to upstream", "contribute upstream", "submit improvement",
  "share my skill", "send this to open-bridge", "PR to upstream",
  "PR to overlay", "give back", "submit a feature".
metadata:
  scope: core
---

# Bridge Contribute — give improvements back upstream

This is the skill the open-bridge community uses to feed features and
improvements back: it turns work on your `user/*` branch into a clean,
reviewed pull request against `bks-lab/open-bridge` (or your org's
overlay repo) — and it **refuses to ship anything the content-safety
gate flags**. Protecting your own customer names, personal data, and
internal paths is a hard gate, not a checkbox.

Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Scan and categorize all contributable files | — |
| `{path}` | Analyze a specific file or directory | — |
| `--adapt` | Generalize org-specific content before contributing | false |
| `--repo <name>` | Only consider candidates for one destination | all |

## Decision Tree

```
User wants to...
├── Scan branch for contributions            → references/workflow.md
├── Contribute a specific file/dir           → references/workflow.md ({path})
├── Adapt/generalize content first           → references/workflow.md § Adapt mode
├── Promote whole commits by scope           → use the bridge-promote skill (/promote)
└── Questions about scope routing            → CLAUDE.md § tier model
```

## Safety (MANDATORY — the reason this skill exists)

No PR is created until the two-layer gate passes for the exact outgoing
file set:

1. `python3 scripts/no-scrub-leak.py {files}` — universal classes
   (absolute user paths, key/token shapes, merge-conflict markers) plus
   **your own roster** from `scripts/leak-patterns-internal.txt`
   (local-only, never shipped — you maintain your customer/PII regexes
   there; the shipped scanner cannot know them).
2. The per-destination blocklist scan from `rules/promote-safety.md` —
   the OSS upstream uses the strictest list.

**REFUSE path:** personal-PII or roster hits exclude the affected files
— no override flag, no "it's just an example". Remediation: `--adapt`,
re-scan, only a clean re-scan unblocks. Clean files in the same batch
still ship.

## Relationship to /promote

`/promote` (bridge-promote skill) moves **whole commits** by `scope:`
routing — the lightweight path when your branch has clean per-commit
scope discipline. `/contribute` works **file-level**, with adaptation
and always ending in a PR — the path for mixed branches and for
first-time community contributions. Full comparison table:
[`references/workflow.md`](references/workflow.md) § Relationship.

## See also

- `bridge-promote` — commit-level scope-routed promote to upstreams
- `rules/contribute-advisor.md` — proactive "this looks upstream-worthy" nudges
- `rules/promote-safety.md` — the content-scan rules this skill enforces
- `CONTRIBUTING.md` — repo-side contribution policy (DCO, licenses)
