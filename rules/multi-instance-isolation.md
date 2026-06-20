---
scope: core
description: Inbound isolation between Bridge instances — never pull another instance's content in, branding is advised-not-assumed, skill copies are per-instance
---

# Multi-Instance Isolation — the inbound side

A user may run several Bridge instances for data isolation (separate clones,
each on its own `user/*` branch). [`docs/multi-instance.md`](../docs/multi-instance.md)
covers the **outbound** rule: don't reach into another instance's files. This
rule is the **inbound** complement: don't let another instance's content flow
*into* this one. Same isolation, opposite direction.

The instance boundary only holds if it holds both ways.

## Gate 1 — never pull another instance's content in

One instance's customers, personas, work, contexts, calendar tags, and logos
stay in **that** instance. Never copy them here — not into CORE/promotable files
(skills, themes, `DESIGN.md`, docs), not into example blocks, not into a render
sample.

- CORE/promotable files stay **generic and instance-agnostic** — at most this
  instance's own org, never a sibling instance's customers or names.
- A sibling instance's pre-existing tasks/categorization are **theirs** — read
  them only in their own repo, never re-create or mirror them here.
- Adding a feature here that *touched* another instance's data while developing
  is the classic leak: scrub it back out before committing. The fix is always
  "only my own content stays; the foreign content goes back to its instance."

This is the inbound mirror of `docs/multi-instance.md` § don't-touch-other-instances:
**don't pull in** is as load-bearing as **don't reach out**.

## Gate 2 — branding is advised, not assumed

Per-instance presentation (wordmark, subtitle, colour mode, calendar tags) is a
taste choice and lives in **each instance's own** theme `branding:` block, not in
a CORE file. Setup/onboarding **advises** a branding choice — it does not pick one
for the user (Bridge stance: propose, the user decides).

When wiring branding for an instance, ask rather than assume:
- wordmark + subtitle,
- colour mode (`monochrome` | one uniform colour | two-tone),
- calendar tags.

Smart defaults are fine to *offer*; baking a specific palette or label into CORE
is not. See `skills/bridge-greeting` § "Setup — advise, don't assume".

## Gate 3 — skill copies are per-instance

Each instance carries its **own copies** of the CORE skills under its own
`skills/` directory. Claude Code resolves skills from the **cwd instance**, so an
edit to a skill here does **not** propagate to a sibling instance — its copy may
be older or already diverged.

Consequence: a change to a shared skill that should also take effect in another
instance must be **ported directly into that instance's copy** (on its own
`user/*` branch). When porting:

- **Port only the generic mechanism, never PII.** A sibling that follows the OSS
  tier carries the *generic* placeholder versions of these skills. Copy the
  behaviour/wiring, not org/customer specifics — otherwise a PII leak lands in a
  tier that promotes to the public upstream. Instance-local context files
  (real rosters, client data) are a separate, instance-only concern.
- **Verify before claiming it works for both.** Check that the other instance
  actually has the copy (`ls <other-instance>/skills/<name>`) before asserting
  "this is fixed for both." A divergent or absent copy means the edit reaches
  one instance only. This is SOUL § Verify before claim applied to cross-instance
  edits: confirm the live target, don't assume propagation.

> Concrete instance paths, branch names, and context mappings are
> instance-specific and stay out of this CORE file (and out of the public
> upstream). They belong in `rules/user/**` or the relevant instance's own repo.

## See also

- [`docs/multi-instance.md`](../docs/multi-instance.md) — the outbound rule + the
  full multi-instance model.
- [`rules/operations.md`](operations.md) § Scope-Routing — how scope/folder
  decides which upstream a file can reach.
