---
summary: "Agent identity — the Bridge orchestrator's own voice and self"
type: readme
last_updated: 2026-05-24
related:
  - _template.SOUL.md
  - _template.IDENTITY.md
  - ../../themes/_schema.yaml
---

# `identity/agent/` — The Agent's Own Identity

This folder holds the Bridge orchestrator's own identity — distinct from
the user's identities (`personas/`) and outgoing recipients (`mandants/`).

Two files express the agent, and a third carries the instance:

| File | Purpose |
|---|---|
| `IDENTITY.md` | Name, role, backstory — *who am I* |
| `SOUL.md`     | Voice, posture, defaults — *how I behave* |
| `INSTANCE.md` | This instance's own always-on text: routes, families and vocabulary CORE cannot name |

The `SOUL.md` convention was pioneered by Peter Steinberger (creator of
OpenClaw) and standardized by the [SoulSpec convention](https://soulspec.org/);
the Bridge also drew on Nous Research's Hermes agent (which uses a
`~/.hermes/SOUL.md`), adapted to the Bridge's cluster-wrapper layout. See
[`ACKNOWLEDGMENTS.md`](../../ACKNOWLEDGMENTS.md).

## Loading order

`AGENTS.md` § Loaded with this file imports `IDENTITY.md`, `SOUL.md` and
`INSTANCE.md` near its top, so they load before Required Reading and Rules
at session start; identity (who) precedes mechanics (what). The import lines
ship with CORE and never change. A fresh clone has none of the three files,
and Claude Code skips an import whose file is missing. Onboarding (Phase D4)
only creates `IDENTITY.md` and `SOUL.md`. Agents that do not resolve
`@`-imports (Codex, Copilot, Gemini) read the files because AGENTS.md tells
them to.

Instance-specific routing that CORE cannot name (families only this
instance has, extra registries, search vocabulary in the instance's
language) belongs in `INSTANCE.md`, never in an entry file: it is imported,
so it reaches sub-agents, which Phase 1 never does. `INSTANCE.md` is USER
and never shipped by CORE or an org overlay (an overlay may ship
`IDENTITY.md` and `SOUL.md`), it may `@`-import further instance files, and
it is the only place a fork adds always-on text, so nobody edits
`AGENTS.md` downstream.

## CORE/USER split — like personas

Like `personas/` (CORE ships templates only, USER fills the instances),
`identity/agent/` ships the `_template.*` files on CORE; the live
`SOUL.md`/`IDENTITY.md` are USER instances seeded from those templates at
onboarding (Phase D4) and kept on your `user/*` branch — they carry
`scope: user` and never promote upstream.

| File | Layer |
|---|---|
| `_template.SOUL.md`     | CORE — pattern for new instances or merges |
| `_template.IDENTITY.md` | CORE — pattern for new instances or merges |
| `_soul-deck.yaml`       | CORE — pickable principle library for onboarding Phase D4 |
| `_soul-deck.schema.yaml`| CORE — schema for the deck |
| `_schema.yaml`          | CORE — frontmatter schema |
| `SOUL.md`               | USER — seeded from `_template.SOUL.md` at onboarding |
| `IDENTITY.md`           | USER — seeded from `_template.IDENTITY.md` at onboarding |
| `INSTANCE.md`           | USER, written by the instance itself when it needs one; never shipped |

When CORE evolves the default voice, the change lands in
`_template.SOUL.md`. Users diff-merge into their instance manually.

## Size cap — SOUL.md

**80 lines / 4 KB hard cap.** SOUL.md is loaded into every session;
bloat degrades signal. When the cap is approached, consolidate or split
into more focused principles. The `bridge-audit` skill enforces this.
(The byte figure is 4 KB rather than 3 to stay consistent with the
80-line cap for UTF-8 German content — umlauts cost 2 bytes each. Lines
are the primary metric.)

`IDENTITY.md` has no hard cap. Depth is a per-instance choice: a
**minimal** version (~15-25 lines: name, role, one-line backstory,
self-intro) gets a Bridge running fast; a **rich** version (~60-90
lines: lineage, design philosophy, relationship arc)
gives the orchestrator a fuller sense of self. It is `@`-imported every
session, so depth trades against context budget — keep it meaningful,
never padded.

## Relation to other surfaces

| Surface | Carries |
|---|---|
| `themes/<theme>.yaml`       | `assistant_name` — vocab slot, *what to call myself* |
| `identity/agent/IDENTITY.md`| Name (refers to theme), role, backstory |
| `identity/agent/SOUL.md`    | Cross-cutting voice principles |
| Auto-memory `feedback_*.md` | Episodic, raw, recent — promoted into SOUL.md by `bridge-curator` |
| `rules/*.md`                | Mechanical guarantees (file-creation gates, deploy-reconciliation) |
| Skill `SKILL.md`            | Domain-specific behaviour |

## Anatomy — character above discipline

A SOUL.md has two layers, rendered in this order:

1. **Character** (the *why*) — temperament and stance in the agent's
   first person. Character generalizes: an agent that knows *why* it
   verifies can decide what to do when the rulebook is silent.
2. **Discipline sections** (the *what*) — Verify, Posture, Execution,
   Audience, Output: concrete behavioural rules, each ideally traceable
   to real feedback.

**Non-redundancy rule:** a character line says what the rules don't —
never restates one. Duplication burns cap lines and leaves it unclear
which wording wins. A character line with no behavioural consequence
anywhere in the file is decoration; prune it.

## What belongs in SOUL.md

- Cross-cutting principles (apply across all skills and tasks)
- Character: temperament and stance (the why-layer, non-redundant)
- Voice/tone defaults
- Verification habits, posture stance, output discipline
- *"if it should apply everywhere, put it in SOUL.md"* (Hermes guidance)

## What does NOT belong in SOUL.md

- Repo-specific or domain-specific rules → `rules/` or `skills/`
- File paths, ports, commands → `rules/`, skill references, or the config family that owns them (instance-only routing: `INSTANCE.md`)
- Project context → `workflow/contexts/`
- Persona/recipient routing → `identity/personas/` or `identity/mandants/`

## Seeding & the living soul

A fresh instance does not start blank. Onboarding Phase D4 offers the
**soul deck** (`_soul-deck.yaml`) — a curated library of universal
voice/posture principles. The user picks a starter set (pre-selected by
work-type), rewords any card, and can add their own lines. That seeds
`SOUL.md` with a small, honest voice.

The soul then **grows by being used** — this is the deliberate design,
not an afterthought:

1. Feedback memories (`feedback_*.md`) capture corrections and patterns episodically.
2. `bridge-curator` Pass 3 synthesises them into `work/_learning/user-patterns.md`.
3. `/bridge-learn` walks the proposals; accepted lessons fold into `SOUL.md`.
4. New *universal* defaults land in `_template.SOUL.md` and `_soul-deck.yaml`;
   users diff-merge.

So D4 seeds and wires — it never tries to author the finished voice
upfront. Re-pick anytime via `/bridge-onboard --add agent-soul`.

## Provenance

Consolidates what is otherwise a scattered set of voice/posture
preferences — repeated corrections, remembered do's and don'ts —
into a single inspectable, versionable, portable identity layer.

## References

- [Hermes SOUL.md docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality)
- [SoulSpec — Open Standard](https://soulspec.org/)
- [`themes/_schema.yaml`](../../themes/_schema.yaml) — `assistant_name` SoT
