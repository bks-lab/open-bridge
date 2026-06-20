---
scope: core
description: Three-phase parallel-agent review engine for strategic/high-stakes written communication — evidence, role-reflection, synthesis
---

# Multi-Agent Review — strategic written communication

When the user asks to have a strategic, high-stakes piece of written
communication **reviewed properly** — *"discuss with the team"*, *"get all
perspectives"*, *"second opinion"*, *"have it checked"*, *"review through
several eyes"* — do **not** keep stacking more draft variants yourself. Run
the three-phase review engine instead.

The engine is generic — any Bridge can drive it. The typical caller is a
customer-correspondence skill from your org overlay (open-bridge ships
none) — a commercial or legal customer mail, a recruiter/lead reply with
money or contract terms on the table — but the same pattern fits any
irreversible, externally-facing message where one more solo variant adds
no signal.

## When to run it

**Run** when both hold:
- The message has a **commercial or legal dimension** — a number, a rate, a
  contract clause, an acceptance/deadline, a negotiation stance — or another
  irreversible external consequence.
- The user gave a **review trigger** (the phrases above) or signalled depth
  (e.g. "ultrathink" + "team" + a named external recipient).

**Do not run** for plain factual questions, internal team notes, or
low-stakes replies — there the cost (~5 agents) outweighs the gain. Worth it
for negotiations at five-figure-plus volume or comparable irreversibility.

## Phase 1 — Evidence (parallel)

Spawn several sub-agents in **one** message block, each with **one** sharply
scoped fact-finding job. Examples:

- Contract / agreement search (document store, knowledge repo): clauses,
  rate, acceptance terms, change rules.
- Mail archive: concrete prior announcements, the backstory, date + subject
  in quotable form.
- File content (spreadsheet, PDF): figures, line-items, top-N, deltas against
  the expected version.

Each evidence agent returns **quotable findings with a path**, no
interpretation. Report under ~400 words.

## Phase 2 — Role reflection (parallel)

After the evidence is back, spawn two to three role agents in parallel — each
simulates **one stakeholder lens** over the same set of variants:

- The recipient (with their biography, constraints, what their leadership
  thinks).
- Your own negotiator (with the briefing from notes/transcript, target
  figure, tactic).
- Optional: a lawyer / negotiation strategist when a legal dimension is in
  play.

Each role agent gets: (a) the variants verbatim, (b) the Phase-1 evidence,
(c) its role character + context + **explicit evaluation questions** (*"Which
variant triggers a YES?"*, *"Which one reads as a legal-escalation trigger?"*)
— never open-ended "rate this". Report under ~400 words.

## Phase 3 — Synthesis

**You** (not an agent) read both role votes and build one new variant that
hits the convergence. Name the divergences explicitly and justify the
compromise. The convergence between independent role lenses is the signal —
where they agree is usually the safe move; where they split is where you
decide and say why.

## Discipline

- **No agent confetti.** Each agent needs a sharp task, an output format, and
  a word cap — otherwise the return is too mushy to synthesize.
- Evidence agents are facts-only; role agents are perspective-only. Don't let
  a role agent invent facts the evidence phase didn't surface.
- Phase 1 fans out together, Phase 2 fans out together once evidence is in,
  Phase 3 is single-threaded synthesis.

This is the verification complement to `rules/operations.md`
§ Pre-"done" independent review — that one checks *whether something is done*;
this one stress-tests *what to send* before it goes out.
