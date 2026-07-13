---
scope: core
description: Push-boundary gate blocking user/* branches and USER-instance content from reaching a public upstream — fail-closed on unknown remotes, enforced behaviourally and via pre-push hook
---

# Push Guard — never publish your private data to a public upstream

**This rule runs before any `git push`, and especially before the
auto-end-of-work cycle ([`operations.md`](operations.md)) and onboarding
([`skills/bridge-onboard/`](../skills/bridge-onboard/)).** It prevents the single
most damaging failure mode of a Bridge cloned from a public repo: publishing a
`user/*` branch — your identity, your `work/` log, your clients — to the world.

## Why this rule exists

A Bridge cloned directly from the **public** open-bridge has `origin` pointing at
that public repo. Onboarding then commits your identity and `work/` to a
`user/{name}` branch. From there, a single push publishes it — and the push is
easy to trigger by accident:

- the **auto-end-of-work cycle** pushes the user branch when "a unit is done";
- a copy-pasted `git push -u origin user/...` from the docs;
- muscle memory, or an IDE "Publish Branch" button.

A server-side branch ruleset does **not** save you: it exempts the repo
owner / org-admin — i.e. the exact person most likely to trip the wire. The only
checkpoint that holds for the autopilot, the human, and a non-Bridge tool alike
is a deterministic check at the push boundary.

## The invariant

> A `user/*` branch — or any USER *instance* content (`work/`,
> `identity/agent/{IDENTITY,SOUL}.md`, `identity/personas|mandants|accounts/<id>`,
> `infra/remotes|channels|backups/<id>`, `workflow/calendars/`,
> `bridge-config.yaml`) — must **never** be pushed to a **public** upstream.

Your private data lives on a **private `origin`**. CORE improvements reach a
public upstream **only** through `/promote` — a content-scanned, fork-based PR —
never a direct branch push.

## What is allowed

`ci/*`, `feature/*`, and `promote-*/contrib-*` refs (CORE work) may go to **any**
remote — public, private, or unverified — because they carry no USER data; that is
what the public upstream is for. Any push to a **confirmed-private** origin you own
is unrestricted. The guard only ever bites a **sensitive payload** (`user/*`
destination, or pushed commits carrying USER instance content).

## Three target states (fail-closed for sensitive payloads)

The guard classifies the push **target** before inspecting the payload, and a
sensitive payload is gated on that state:

| Target state | How it's decided (offline-first) | Sensitive payload |
|---|---|---|
| **private** | target in `push_guard.private_remotes`, **or** `.bridge-origin` `is_public:false` with a `repo:` slug matching the target, **or** `gh repo view` reports `PRIVATE` | **ALLOW** |
| **public** | built-in `bks-lab/open-bridge`, **or** `push_guard.public_upstreams`, **or** `.bridge-origin` `is_public:true` matching the target, **or** `gh` reports `PUBLIC` | **BLOCK** |
| **unknown** | none of the above — `gh` offline / absent / repo visibility unresolved | **BLOCK** (fail-closed) |

The `unknown → BLOCK` rule is the 2026-06-26 hardening: an earlier build *failed
open* (unknown ⇒ allow), so re-homing `origin` to a *different* public repo not on
the list — while `.bridge-origin` still said `is_public:false` and `gh` was offline —
let a `user/*` push leak. Now an unverifiable target withholds USER data and tells
you exactly how to mark it private. A **CORE-clean** push is unaffected — it flows
to all three states.

## Enforcement (defense in depth)

1. **Behavioural (primary).** Onboarding and the auto-end-of-work cycle resolve
   origin visibility *before* creating, committing toward, or pushing a `user/*`
   branch, and refuse to push it to a public/upstream origin — advising the
   re-home below instead.
2. **Deterministic (backstop).** [`scripts/hooks/pre-push`](../scripts/hooks/pre-push)
   blocks the push at the git layer regardless of what the agent does. Armed via
   `core.hooksPath` — set by `/bridge-onboard` (Phase A, before the `user/*` branch
   exists) and by `./bin/setup` on any OS; session-start warns if it is unset while
   the hook is present. The decision keys on the **destination** ref (`remote_ref`),
   so `git push origin HEAD` / a sha push / a detached-HEAD push can't dodge the
   `user/*` rule; the content backstop inspects the pushed **commits** (not the
   working tree). Detection is offline-first and sorts the target into
   **private / public / unknown** (the [`.bridge-origin`](../.bridge-origin) marker —
   `is_public:false` + matching `repo:` is the deterministic "this is my private
   origin → allow" signal — plus a built-in/config list; `gh repo view --json
   visibility` only escalates a still-unknown remote). A sensitive payload is allowed
   to **private**, blocked to **public**, and blocked to **unknown** (fail-closed);
   CORE-clean pushes flow to all three.
3. **Verification.** The [`onboard-sim`](../skills/onboard-sim/) skill proves the
   invariant end-to-end against a naive newcomer (a leak-safe sandbox, a cheap
   model or a model-free CI run, a deterministic no-leak assertion).

## Remediation — what to advise (offer, never auto-run)

The newcomer should end up with **their own private repo as `origin`** and
open-bridge as a read-only `upstream`:

```bash
# Cleanest: GitHub "Use this template" → create a PRIVATE repo, clone THAT.
# (A fork of a public repo is itself public — it cannot hold your data privately.)

# Or re-home an existing clone:
git remote rename origin upstream            # public open-bridge becomes read-only
gh repo create <you>/my-bridge --private --source=. --remote=origin --push
git fetch upstream && git merge upstream/main   # pull CORE updates anytime

# Then record the new origin as private, so the first user/* push classifies
# PRIVATE even offline (gh absent/unauthenticated) instead of fail-closing:
printf 'repo: <you>/my-bridge\nis_public: false\n' > .bridge-origin
```

**Write `.bridge-origin` (`is_public: false`) ONLY after the origin is confirmed
private** — never for a still-public origin. The marker vouches only for its matching
`repo:` slug; the public upstream still BLOCKs. Without it, a re-homed clone whose slug no
longer matches the CORE-shipped marker falls through to `gh repo view`, and offline/
unauthenticated that resolves **unknown → fail-closed**, refusing a legitimate first push
to the user's own brand-new private repo. Onboarding writes this marker automatically as
part of the re-home (see `skills/bridge-onboard/references/workflow.md` Phase A step 6).

Just evaluating? Keep `user/*` local and never push.

## Deliberate override

A CORE maintainer who genuinely needs to push to a public upstream uses a
visible, per-push opt-out: `BRIDGE_PUSH_GUARD=off git push ...`. It is never
silent and never the default.
