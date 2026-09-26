---
name: spec-kickoff
description: >-
  Guides a spec-first kickoff before building anything substantial: Karpathy's
  three layers, spec, verifier, environment. Phase 1 interviews down to a
  SPEC.md with EARS requirements, Phase 2 builds a verification plan, Phase 3
  wires it into the existing environment. Trigger: "spec-kickoff", "kickoff",
  "spec this", "spec first", "before we build", "karpathy method".
metadata:
  scope: core
---

# Spec-Kickoff

A phased, checkpointed kickoff for **starting a new build the right way** — Andrej
Karpathy's three layers (**spec → verifier → environment**), expressed through Claude
Code's own primitives. You produce **one self-contained `SPEC.md` that ends in an
end-to-end verification step**, then hand off to the build.

This is **not** a new framework. It is spec-kit's discipline + Kiro's EARS/gates,
expressed through Anthropic's native *"interview → SPEC.md → verify-loop"* pattern,
wired into the environment the user already has. Conceptual depth, the verified
Karpathy sources, and the EARS / ladder / gate cheat-sheets live in
[`references/method.md`](references/method.md). The artifact you fill is
[`assets/SPEC.md`](assets/SPEC.md). A one-page visual explainer for humans (open in a
browser) ships at [`assets/spec-kickoff-explainer.html`](assets/spec-kickoff-explainer.html).

> Talk to the user in their conversation language. Keep the interview **sharp and
> short** — a handful of load-bearing questions, not a survey. This skill is opt-in:
> when invoked the structure is wanted, but never let it become a ceremony tax.

---

## Phase 0 — Frame & skip-check (≈30 seconds)

1. **Skip-gate first.** If any of these holds, say so and do NOT run the kickoff:
   - you could describe the whole change in one sentence (Anthropic: skip the plan);
   - it's a quick fix (≲10 min, <3 files);
   - you're mid-build, not starting something new.

   → Point at the normal build flow. The method is for *substantial new builds*.
2. **Autonomy level** (Karpathy's *autonomy slider*): tight / medium / wide — how much
   leash the build gets. **Default tight**; widen only as the verifier earns trust.
3. **Where the spec lives.** Copy `assets/SPEC.md` to the task's home. On a Bridge
   instance that's `work/tasks/<slug>/SPEC.md` — fold it into the reflex-pause /
   task, don't create a parallel artifact.

## Phase 1 — SPEC  (Layer 1: the human owns the goal)

Run an **interview** — use `AskUserQuestion` for branching decisions. Cover, in order:

- **1a · Goal, not task.** Separate the *task* ("build an end-of-month report") from the
  *goal* (the decision the output drives — the "done" a human must own). Karpathy: *"you
  can outsource your thinking, but you can't outsource your understanding."* Keep asking
  until the goal **and** "what 'done and correct' looks like" are crisp. → SPEC §1.
- **1b · Agile slice.** Cut the **thinnest end-to-end slice that has a verifiable check**;
  defer the rest to §5 as follow-ups. Bias small (agile, not waterfall). → SPEC §5.
- **1c · EARS requirements.** Write requirements in EARS (`WHEN`/`IF…THEN`/`WHILE`/`WHERE`
  … `SHALL`). This forces edge cases & failure modes into the open, and each line becomes
  an acceptance check in Phase 2. Cheat-sheet in `references/method.md`. → SPEC §4.
- **Mark key decisions / assumptions** you made → SPEC §7, and have the user **confirm
  them explicitly** ("make me verify key decisions"). Open items → §8.

Fill `SPEC.md` §1–§5, §7–§8. **Checkpoint: show the spec, get sign-off before Phase 2**
(approve-each-artifact gate — Kiro).

## Phase 2 — VERIFIER  (Layer 2: make it checkable before building)

*Why this layer exists:* the model is a **ghost** — an imitator of human text (Karpathy,
Dwarkesh, Oct 2025), so its output is plausible-*shaped* by default and must be checked
against a real verifier, not trusted because it sounds right. A feedback loop is the
single biggest quality lever (Boris Cherny, per Kim/Push-To-Prod: ~2–3× — cite as
practitioner-reported, not an Anthropic benchmark).

Fill `SPEC.md` §6:

- **2a · Acceptance criteria up front, precise.** Turn each EARS requirement into a
  concrete pass/fail. Not "make it good" → "the report has 3 sections, each ending in a
  recommendation."
- **2b · Verification ladder.** Map every criterion to the **strongest available check**:
  1. **deterministic** — test · build exit code · linter · typecheck · diff-against-fixture (prefer this);
  2. **external signal** — CI (`gh pr checks` per SHA) · deploy probe · a reference doc / historical report · real data;
  3. **judge** — fresh-subagent or model critic, *only* where there's no ground truth, scoped to the criteria, with the bias caveat.

  Anything that can't be checked → mark **UNVERIFIABLE** and decide: make it verifiable,
  or don't ship it (Anthropic's trust-then-verify gap).
- **2c · Gate strength** per criterion (Anthropic's four, weakest→strongest):
  one-prompt · `/goal` condition · **Stop-hook** · **fresh-subagent second opinion**.
  Match the strength to the cost of being wrong (always / ask / never).
- **2d · Adversarial review before "done".** Default: a **fresh-subagent** review of the
  diff against the acceptance criteria — *the agent doing the work isn't the one grading
  it*; the bundled `/code-review` skill works. Tell the reviewer to **flag only correctness
  / requirement gaps** (guards against over-engineering). Opt-in cross-model upgrade: the
  OpenAI **Codex plugin** (`/plugin marketplace add openai/codex-plugin-cc` →
  `/codex:adversarial-review`). Lead with the native path; Codex is a luxury, not a
  dependency (the user's stack is Claude-Code-only).

**Checkpoint: show the verification plan, get sign-off.** The spec now ends in an
end-to-end verification step — it's complete.

## Phase 3 — ENVIRONMENT  (Layer 3: point at what exists; add only what's new)

Layer 3 is the workshop the spec + verifier live in. On a built-out instance it **already
exists** — don't teach it, wire into it. Walk the `SPEC.md` §9 checklist:

- **Context loaded?** The agent needs the right context: CLAUDE.md / project rules / a
  curated knowledge folder (Karpathy's `raw → wiki → outputs` idea — the context the agent
  stands on). On a Bridge, CLAUDE.md + SOUL.md + rules already are the "constitution";
  confirm the relevant ones load.
- **Reusable?** If you'll do this repeatedly, make it a skill (skill-creator).
- **Guardrails for the new build:** bucket risky ops into **always-do** (`/permissions`
  allowlist) · **ask-first** (auto-mode / default prompt) · **never-do** (PreToolUse hook,
  `exit 2`, on the build's protected paths — `deliverables/`, client data, prod config).
  Offer to generate a scoped `protect-files.sh`. Point at the instance's existing always-on
  hooks (e.g. a Bridge's reflex-pause, scope-validate, worklog Stop hook) — don't duplicate.

## Phase 4 — Handoff

Recap: `SPEC.md` path · autonomy level · slice 1 + its verifier + gate strength. Then:

> "Start a fresh session and build slice 1 against the spec → verify with `<check>` →
> checkpoint → repeat."

Closing loop (Cherny): when you hit an anti-pattern mid-build, feed it back into
CLAUDE.md / a skill so the next session catches it automatically.

**You own the understanding; the agent does the thinking. That's the whole method.**

---

## Accuracy note

This skill is built on **verified** Karpathy sources, not the popular video's paraphrase.
Corrections it respects (full list + citations in `references/method.md`): the "car wash /
50 m, drive or walk?" example is a *community* test illustrating his verifiability thesis,
**not** a Karpathy quote; the venue is **Sequoia AI Ascent 2026** (the video's "AISN 2026"
is a mis-transcription); plan mode is *"useful, just not a substitute for a co-authored
spec"* — not "bad"; the "2–3×" figure is Cherny-via-Kim, not an Anthropic benchmark; "your
data is your moat" is a blog gloss, the `raw/wiki/outputs` concept is the real one.
