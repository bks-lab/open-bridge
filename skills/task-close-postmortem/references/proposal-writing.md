---
summary: "How to write a proposal file: template, naming, severity, scope-defaulting, evidence-linking."
type: reference
last_updated: 2026-05-13
---

# Proposal-Writing Rules

A proposal lives in **`work/_learning/proposals/<YYYY-MM-DD>-<task-slug>-<topic-slug>.md`**.
One Markdown file per candidate improvement. Schema is at
[`_schema.proposal.yaml`](_schema.proposal.yaml).

## Naming

```
<YYYY-MM-DD>-<task-slug>-<topic-slug>.md
```

- `<YYYY-MM-DD>` = day of the postmortem (not task created/closed)
- `<task-slug>` = the parent task's slug, from `STATUS.md`
- `<topic-slug>` = 3-4 word kebab-case summary of what the proposal targets
  - From structured `bridge_gaps[]`: use the gap's name field
    (e.g. `bridge_gaps[0].standing_order = "research-claim-verification"`
    → topic-slug = `standing-order-research-claim-verification`)
  - From free-text Q6: distill 3-4 keywords (e.g. "should detect when I'm
    in voice-stack mode and switch back to default LLM" → `detect-voice-mode-llm-switch`)
- If file already exists, append `-2`, `-3`, …

## Frontmatter

Use the template below. All `kind`-specific blocks are optional; fill
only the target type that matches the gap.

```yaml
---
id: 2026-05-13-voice-stack-skill-mode-switch
created: 2026-05-13
source:
  type: postmortem
  task_slug: voice-stack-example
  evidence:
    - "work/done/2026-05/voice-stack-example/STATUS.md#postmortem"
    - "work/log.md#2026-05-12 ..."

severity: P2
status: pending
scope: user                              # core | org | user

target:
  type: skill                             # skill | standing_order | rule | doc | protocol | memory | schema
  path: skills/voice-mode-llm-switch/    # or "(new)" if not yet existing
  action: create                          # create | edit | delete | rename

proposal_type: structured                # structured | needs-triage

# Optional — concrete diff preview if computable
diff_preview: |
  +# Skill: voice-mode-llm-switch
  +
  +Detects when the local Twilio-15s-voice loop is active and ensures
  +the LLM endpoint is qwen3:1.7b. Switches back to qwen3:32b on
  +session-end.
---
```

## Severity defaults

| Source | Default severity | Override when … |
|---|---|---|
| `bridge_gaps[]` entry on actively-used skill/SO | P2 | User explicitly described impact ("3h verbrannt") → P1 |
| `bridge_gaps[]` entry on new skill/SO/doc | P2 | — |
| Free-text Q6 mapped to structured target | P2 | — |
| Free-text Q6 unmapped (`needs-triage`) | P3 | — |
| Touched-file analysis (unexpected edit pattern) | P3 | — |
| Recurring audit finding (≥3 runs, Phase 3 source) | escalate one level | — |
| Curator-suggestion (library pass — sleeping/overlap) | P2 or P3 | description-budget-sprenger ≥1536 chars → P1 |
| Curator-suggestion (queue pass — stale/conflict) | P2 or P3 | reject-pile-signal (≥10 same-type rejections) → P1 |
| Curator-suggestion (user-pattern strong observation) | P2 | observed in 2 consecutive runs → P1 |

Never P0 from postmortem source — P0 = immediate-action-required, reserved
for /bridge-audit recurring critical findings.

## Scope defaults

Same logic as `bridge-config.yaml.promote.content_blocklist` per-repo:

| Target characteristic | Default scope |
|---|---|
| Targets a CORE skill (no scope tag or `scope: core`) | `core` |
| Targets a CORE standing-order (e.g. task-sync.md, drift-advisory.md) | `core` |
| Targets a CORE rule (rules/*.md, no scope variation) | `core` |
| Targets a CORE doc (docs/structure.md, docs/extension-model.md, etc.) | `core` |
| Targets the proposal schema, status schema | `core` |
| Targets an org-customer skill (scope: org, e.g. customer-x-coordinator) | `org` |
| Targets a USER file (bridge-config.yaml, personas, mandants, work/) | `user` |
| Targets `memory:` (auto-memory) | `user` |
| Ambiguous | `user` (safe default — never accidentally leak to OSS) |

## Status lifecycle

```
pending  → accepted  → implemented   (user accepted via /bridge-learn, diff applied)
pending  → rejected                  (user rejected via /bridge-learn)
pending  → deferred                  (user said "later" via /bridge-learn)
pending  → superseded                (a later proposal covers same target)
```

The postmortem skill ONLY writes `pending`. Status transitions are
/bridge-learn's job, with a corresponding entry in
`work/_learning/audit-trail.md`.

## Body content (the markdown after frontmatter)

Required sections:

```markdown
# Proposal: <one-line title>

## Motivation

<2-4 sentences: where this came from, with quotes from postmortem if
strong. Use blockquotes for user-verbatim text.>

## Vorschlag

<2-4 sentences or a fenced code block: what concretely should change,
not why.>

## Konkrete Wirkung

<1-3 sentences: what is the user-observable effect after this lands?>

## Akzeptanz-Kriterien

- [ ] <concrete check #1>
- [ ] <concrete check #2>
- [ ] <concrete check #3>
```

Optional sections (add if relevant):

```markdown
## Risiken

<known risks of accepting this proposal>

## Verwandt

- <links to related proposals, MEMORY entries, prior audit findings>
```

## What evidence to include

`source.evidence` is a list of pointer-strings that show "this proposal
was not invented from thin air". Sources of evidence in priority order:

1. **STATUS.md anchor** of the closing task — always include.
2. **work/log.md timestamps** if the postmortem references specific work
   moments — include with the timestamp.
3. **MEMORY.md entries** if relevant prior wisdom exists.
4. **git commits / file paths** if the postmortem touched specific code.
5. **Audit-history hash** (Phase 3) for recurring findings.

Pointer format: relative path from repo root, plus `#anchor` if applicable.
No absolute paths, no http URLs (proposals are repo-internal).

## Anti-patterns (don't do these)

- ❌ One proposal per `bridge_gaps[]` entry that's a different aspect of the
  same target → consolidate. One proposal = one target file.
- ❌ Writing a proposal for a trivial typo fix → just fix it in the
  closing commit; not every observation needs a proposal.
- ❌ Severity P0 from postmortem → not allowed (see severity table).
- ❌ Scope `core` for anything that mentions org/customer names → must be
  `org` (or `user` if PII-heavy).
- ❌ Writing prose-rich proposals (>200 lines) — keep them scannable.
  The /bridge-learn review is fast-paced; long proposals get deferred.
- ❌ Inventing acceptance criteria when the user wasn't specific — write
  fewer, sharper criteria, or leave the section blank with a TODO marker.
