---
name: capability-broker
description: >-
  Turns a capability gap into a gated acquisition: when no skill, CLI, MCP, or
  account covers a need, offers (never auto-acts) to research and provision a
  tool, or scaffold a skill. Trigger: "the bridge can't do that", "there's no
  skill for this", "build a skill for this", "capability gap", "self-extend".
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

# Capability Broker

The **acquisition** arm of the Bridge learning loop. The other arms look
backward and refine what exists (`task-close-postmortem`, `bridge-audit`,
`bridge-curator`); this one looks forward and **gains a new capability** — a
tool or a skill — when the user hits something the Bridge can't do yet.

It **proposes, it never auto-acts.** Every install, every outward step, every
persistent write is propose-then-confirm. Same human-gate-at-every-layer posture
as `rules/learning-autonomy.md` — this skill is bound by that rule, not an
exception to it.

Read this file only when triggered. Full procedures live in `references/`
(progressive disclosure) — load the one you need, not all four.

## When this skill runs

| Entry | Mode |
|---|---|
| The `capability-gap-offer` standing-order detects a true gap | **Auto-offer** — surface the 4-way offer, then route |
| User says "the bridge can't do X", "build a skill for this", "is there a tool that…" | **Direct** — same flow, user-initiated |
| User picks a route from a prior offer (`r`/`s`/`o`/`d`) | **Route** — jump to the chosen branch |

## The flow (one screen)

1. **Guard** — confirm it's a *true* gap, not a false one. → `references/gap-detection.md`
2. **Offer** — one question, four routes. Never silently fail or silently one-off.
3. **Route**:
   - `[r]` research + provision a tool → `references/research-playbook.md` → decision tree
   - `[s]` scaffold a skill → decision tree → hand to `skill-creator`
   - `[o]` one-off → do it now, ledger note only
   - `[d]` decline → ledger note, cooldown
   - decision tree (provision vs skill vs both) → `references/provision-vs-skill.md`
4. **Capture** — write the learning so it compounds. → `references/learning-capture.md`

## 1. Guard — true gap vs false gap

Before offering, run the cheap guard (full steps in
`references/gap-detection.md`). Five outcomes:

- **T1 true gap** — no skill, no wired tool, not native → **offer** (step 2).
- **T2 dormant skill** — a skill plausibly covers it but didn't fire → load it;
  if it mis-triggered, log a `trigger-correction` (existing loop). **Stop —
  not this skill's job.**
- **T3 native** — Claude can already do it with built-in tools → just do it.
- **T4 one-off** — real but single-use → do it ad-hoc, ledger note.
- **T5 declined/policy** — declined this session or must-not-do → silent / refuse.

The skill sweep (grep `skills/*/SKILL.md` for the capability's keywords) is the
critical guard: err toward "a skill might cover this → load it, don't offer."

## 2. Offer

On T1, surface exactly one offer — never more than one per gap:

```
🧩 Capability gap: <one line — what you asked for that I can't do yet>.
   I can make this stick, or just do it once. Your call:

   [r] Research + provision a tool   — find the right CLI/MCP/service, install & wire it
   [s] Scaffold a dedicated skill    — build a reusable Bridge skill for it
   [o] One-off, don't persist        — do it this once, no new capability
   [d] Not now / decline             — drop it (won't re-offer this session)
```

The offer is non-destructive. Everything after it is gated (step 3).

## 3. Route — gates

- **Research** is read-only (web + local inspection). Nothing installed, nothing
  sent outward beyond search queries. → `references/research-playbook.md`.
- **Provision** needs a **per-action `[y]`** for *each* install / wire / auth
  step. Credential creation and other outward/irreversible steps stay behind the
  Bridge's existing hard gates — this skill routes to them, never bypasses them.
- **Scaffold** writes only under `skills/<new>/`, only after `[s]` (or
  research→tree→skill), and hands authoring to the `skill-creator` skill.
- The **provision-vs-skill** call (infrastructure vs procedure vs both) is in
  `references/provision-vs-skill.md`. BOTH = provision the tool first, then the
  skill that wraps it.

## 4. Capture — make it compound

Every outcome writes a learning (full shapes in `references/learning-capture.md`):

- A **proposal** in `work/_learning/proposals/` with `source.type: capability-gap`,
  an evidence chain, a `target` (the new skill / tool / account file), and a
  `scope` (`core` if generic → open-bridge roadmap candidate via `/bridge-sync`;
  `user`/`org` if instance-specific).
- A **ledger row** in `work/_learning/capability-gaps.md` (append-only) with the
  disposition and a recurrence counter — a one-off gap seen ≥ N times escalates
  to a "persist now" proposal.
- The **artifact** (the scaffolded skill / wired tool) is the durable gain.
- Optionally a **memory** (a non-obvious tool-choice decision or auth gotcha) via
  the existing `proposal target.type: memory` path — human-approved.

Acceptance of any proposal stays with `/bridge-learn`. This skill writes
`pending` proposals only; it does not accept its own.

## Configuration

`bridge-config.yaml.learning.capability_broker` (default-on, like
`feature-discovery` — works before the block exists):

```yaml
learning:
  capability_broker:
    enabled: true                  # false = never offer
    research: { max_sources: 4, default_paid: true }
    recurrence_escalate_after: 2   # one-off seen N+ times → persist proposal
    decline_cooldown_sessions: 1
```

## What this skill deliberately does NOT do

- ❌ Install, wire, authenticate, or send anything outward without a per-action
  `[y]`. The offer is the only un-gated step.
- ❌ Edit any other Bridge file directly — capability lands via `skill-creator`
  (skills) or the provisioning route (tools), and is reviewed via `/bridge-learn`.
- ❌ Re-implement skill scaffolding (that's `skill-creator`), deep research
  (that's `deep-research`), or feature suggestions for features that already
  exist (that's `feature-discovery`).
- ❌ Offer when a skill already covers the need (false gap → load it).
- ❌ Accept its own proposals or auto-promote to upstreams.

## Related

- `rules/learning-autonomy.md` — the gate doctrine this skill is bound by
- `protocols/standing-orders/capability-gap-offer.md` — the always-on detector
- `protocols/standing-orders/feature-discovery.md` — complementary (existing-feature) surface
- `skills/task-close-postmortem/`, `skills/bridge-audit/`, `skills/bridge-curator/`
  — the retrospective proposal generators
- `skills/bridge-learn/` — the review surface that closes the loop
- `work/_learning/README.md` — the aggregation layer this writes into
- `work/_learning/capability-gaps.md` — the recurrence ledger
- `skill-creator` (plugin), `deep-research`, `checkup` — the executors
