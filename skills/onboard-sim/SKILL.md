---
name: onboard-sim
description: >-
  Adversarial onboarding-safety simulation. Builds a leak-SAFE sandbox that
  reproduces a fresh PUBLIC-origin open-bridge clone with the push guard armed,
  drives a naive first-time-user session inside it (default: a cheap model such
  as Haiku; or a model-free scripted run for CI), then DETERMINISTICALLY asserts
  that no USER data — identity/agent, work/, client content on a user/* branch —
  reached the would-be-public upstream. The whole sandbox upstream is a local
  bare repo, so testing for a leak can never cause one. Use to verify the
  public-origin push guard (rules/push-guard.md + scripts/hooks/pre-push)
  end-to-end whenever onboarding, the hook, rules/operations.md, or session-start
  change, and as the standing pre-promote / CI gate for that surface. Trigger:
  "/onboard-sim", "onboard sim", "simulate onboarding", "run the onboarding
  simulation", "leak sim", "test the push guard", "does my bridge leak",
  "mirror-safety sim".
allowed-tools:
  - Bash
  - Read
  - Task
metadata:
  scope: core
---

# onboard-sim — adversarial onboarding-safety simulation

Proves an invariant the unit test can't: **a realistic naive first-time-user
session, walking the real onboarding → commit → push path, cannot leak private
data to a public upstream.** The block is a deterministic git hook
(`scripts/hooks/pre-push`), so it fires *below* the model — which is why the
correct driver is the **cheapest, dumbest** model available: if even that, behaving
like a real first-timer, can't leak, no agent can. Cost and speed are the bonus;
the model-independence is the actual claim.

## Why a simulation (not just the unit test)

`scripts/tests/test-push-guard.sh` checks the hook's block/allow/bypass contract
in isolation. This skill checks the thing that matters operationally: that the
guard fires on the **real** path a first-timer (or the auto-end-of-work autopilot)
takes, end to end — clone → onboard → commit USER data to `user/*` → push.

## Leak-safe by construction

The sandbox's "public upstream" is a **local bare repo**. The newcomer clone's
`origin` is set to the public URL (so the guard's slug detection sees a public
target) but all transport is redirected to that bare repo via git `insteadOf`.
So if the guard ever *fails*, the simulated leaky push lands in the local bare
repo — caught by the assert, **never on the real internet.** Testing for a leak
cannot cause one.

## How it runs (4 phases)

1. **Build** — `assets/build-sandbox.sh <open-bridge-checkout> [sandbox-dir]`
   prints the sandbox dir. It copies the live CORE (tracked + new-untracked) into
   a fresh repo, arms the guard (`core.hooksPath=scripts/hooks`), spoofs `origin`
   to the public slug with transport redirected to a local bare repo, and writes a
   sandbox `bridge-config.yaml` so the guard recognizes the bare target as public.

2. **Drive the naive newcomer** — two modes:
   - **Realistic (default):** spawn ONE subagent via the **Task** tool with a cheap
     model (`model: haiku`), tools `Bash, Read, Write`, pointed at
     `<sandbox>/newcomer`, told to set up their identity + work and back it up to
     the remote — with an explicit "do not work around or disable any safety
     check" instruction (a naive user wouldn't). It will commit USER data to a
     `user/*` branch and `git push` it; the guard blocks the push.
   - **Scripted (CI / no tokens):** `assets/run-scripted-newcomer.sh
     <sandbox>/newcomer` does the same canonical leaky sequence with no model.

3. **Assert** — `assets/assert-no-leak.sh <sandbox-dir>` inspects the bare
   "public" repo: it must carry **no `user/*` branch** and **no commit touching a
   USER instance path** (CORE templates excluded). Deterministic verdict, no LLM
   judgment. Exit 0 = PASS (guard held).

4. **Teardown** — `rm -rf <sandbox-dir>` (the sandbox is a throwaway temp tree).

## When to run

- After any change to the onboarding/guard surface: `scripts/hooks/pre-push`,
  `rules/push-guard.md`, `rules/operations.md` (auto-end-of-work), `rules/session-start.md`,
  `skills/bridge-onboard/`, `bin/setup`, `.bridge-origin`, `bridge-config.yaml.template`.
- As the **verify gate** for the dev-board's `verify_policy` on that surface.
- In CI (scripted mode) as a deterministic safety regression — see the
  `onboard-sim` job in `.github/workflows/validate.yml`.

## Hard rules

- **Never point the sandbox `origin` transport at a real remote.** The bare-repo
  redirect is the safety property; do not "simplify" it away.
- **The driver must not be told the guard exists**, and must be instructed NOT to
  bypass (`BRIDGE_PUSH_GUARD=off` / `--no-verify`). The point is naive-path realism.
- **The verdict is the deterministic assert**, never the driver's self-report.
- A PASS means the guard held; a FAIL means a leak reached the (local, safe)
  upstream — fix the guard, never the assert.
