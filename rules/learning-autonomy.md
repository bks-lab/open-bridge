---
description: Where the Bridge concentrates learning-autonomy across its four layers, and the deliberate human-gate at every layer
scope: core
---
# Learning Autonomy Boundaries

The Bridge separates "what the agent can change about itself" into four
discrete layers, and applies an explicit human gate at every one of them.
This is a deliberate philosophical choice — measured against competing
designs (e.g. Hermes Agent) that concentrate autonomy at one layer and
trust the agent there. We do not.

## The four layers

```
Layer A — In-context        prompt additions; vanish on session reset
Layer B — Skill file        skills/*/SKILL.md, protocols/standing-orders/*.md, rules/*.md
Layer C — User profile      MEMORY.md + work/_learning/user-patterns.md
Layer D — Model weights     LoRA adapters, fine-tunes (consumed, not trained)
```

| Layer | Persistence | What changes | Bridge gate |
|---|---|---|---|
| A | Single session | Loaded skill content + working memory | Implicit (context resets) |
| B | Across sessions | Behavior contracts (triggers, references, rules) | `/bridge-learn` accept |
| C | Across sessions | Stated preferences + inferred user patterns | Explicit edit / `/bridge-learn` accept |
| D | Across model versions | Token-probability distribution itself | Consume-only — no training in-tree |

## The rule

**Every persistent change to a Bridge file goes through a human-readable
proposal in `work/_learning/proposals/` and an explicit accept in
`/bridge-learn`.** No skill writes directly to another skill. No automated
process writes directly to MEMORY.md. Trends and observations *propose*,
they do not *apply*.

### What this prevents

- **Skill drift.** An agent that edits its own behavior contract during a
  session removes itself from the user's mental model. Tomorrow's run
  is different from today's and the user cannot reproduce yesterday's
  behavior without a diff log.
- **Memory poisoning.** An agent that writes "user prefers X" without
  the user confirming X locks in a belief that is hard to detect and
  hard to remove once embedded.
- **Reversibility loss.** A weight update (Layer D) is irreversible
  without retraining; a skill auto-edit is reversible only if the writer
  preserved a backup. The bridge keeps reversibility cheap (`git revert`)
  by making every change a commit, and every commit a human decision.

### What this costs

- **Latency.** Improvements take a user-review step instead of landing
  immediately. The /bridge-learn surface is the bottleneck.
- **User effort.** The user is in the loop for every learned change.
  This is the trade.
- **No emergent capability gains.** The Bridge does not get better
  without the user actively saying "yes, get better in this specific
  way". That's the point.

## Per-layer doctrine

### Layer A — in-context

Acceptable to mutate freely *within* a session. Examples: loading a
skill, adding a reference doc, building a temporary plan, refining a
draft. None of this persists. No gate needed.

### Layer B — skill files, standing-orders, rules, docs

Mutation requires:
1. A proposal file under `work/_learning/proposals/<id>.md` with the
   schema in `skills/task-close-postmortem/references/_schema.proposal.yaml`.
2. Evidence chain (at least one source pointer — postmortem anchor,
   audit-history JSON, trigger-correction line, or curator finding).
3. User accept in `/bridge-learn` (or a documented `--auto-apply` mode
   on a future flag that we explicitly do not provide today).
4. Resulting git commit on `user/<name>` — `git revert` is rollback.

The proposal-generators are `task-close-postmortem` (Phase 1),
`bridge-audit` recurring-finding scan (Phase 3), and `bridge-curator`
(Phase 6). All three produce proposals — none of them edit Bridge files
directly.

### Layer C — user profile

Two artefacts:

- **`MEMORY.md`** — explicit, user-curated, narrative memory. Manual
  writes only. Skills may *suggest* a memory entry via
  `bridge_gaps[].memory:` in a postmortem, but they do not auto-write.
- **`work/_learning/user-patterns.md`** — periodic LLM-synthesized
  observations from log.md and accepted proposals. Append-only by
  `bridge-curator` user-pattern pass. The user reviews; entries can be
  escalated to MEMORY.md or pruned. The synthesis is local — no cloud
  user-model service.

The asymmetry is intentional. MEMORY.md is what the user *knows they
believe*. user-patterns.md is what the system *thinks it observed*. The
distance between them is honest signal.

### Layer D — model weights

The Bridge has no in-tree training pipeline and does not plan to ship
one. Fine-tuned models are **consumed via model-provider configuration**
in `bridge-config.yaml.models` — the Bridge swaps endpoint, not weights.

This is the one layer where we accept a third-party gate (the upstream
fine-tuner, e.g. NousResearch, Anthropic) instead of an explicit user
review. The reason is pragmatic: there is no useful user-review surface
for a 30k-token-per-step training run with stochastic gradients.

If the ecosystem ships fine-tuned adapters that improve specific
behaviors (tool-calling accuracy, JSON-schema adherence), wire them as
named model providers and let the user pick per-skill. Do not import
training infrastructure. Do not auto-swap adapters at runtime.

## Comparison to autonomy-maximalist designs

A common competing design is to concentrate autonomy at exactly *one*
layer and grant the agent free authority there:

- **Layer B autonomy.** The agent reads its own skill files, decides
  during a session that one is wrong, and writes the new version.
  No proposal, no review.
- **Layer C autonomy.** An inferred user-model updates after every
  turn from observed conversation. No audit trail of which observation
  produced which belief.

These designs trade auditability for velocity. They produce visible
gains in low-stakes personal-agent contexts where wrong learnings cost
little. They are wrong for an orchestrator that runs customer work,
financial operations, or any process where a wrong belief silently
applied is more expensive than a slow review.

This rule names the trade-off so future-bridge-users can re-decide it
deliberately rather than drift into it.

## Where this rule applies

- Every new skill that proposes "the agent learns X automatically" must
  show its gate. If it has none, refer the author here.
- Every config flag that includes the word `auto_apply`, `autonomous`,
  or `self_*` must be reviewed against this rule before landing.
- Every observation that an agent in another framework "just learns
  on its own" is *evidence about the trade-off*, not a feature to copy.
  The trade-off is documented; copy only with eyes open.

## Related

- `work/tasks/bridge-learning-loop-concept/CONCEPT.md` § Three Layers — the
  full architecture this rule formalizes.
- `skills/task-close-postmortem/SKILL.md` — Layer B + Layer C proposal generator.
- `skills/bridge-audit/SKILL.md` — Layer B proposal generator via
  recurring-finding detection.
- `skills/bridge-curator/SKILL.md` — Layer B + Layer C consolidation pass
  (proposes, never applies).
- `skills/bridge-learn/SKILL.md` — the accept surface that closes the loop.
- `work/_learning/README.md` — the aggregation layer where proposals live.
