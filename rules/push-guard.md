---
scope: core
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

`ci/*`, `feature/*`, and `promote-*/contrib-*` refs (CORE work) may go to a public
upstream — that is what it is for. Any push to a **private** origin you own is
unrestricted. The guard only ever bites `user/*` / USER-content → a public remote.

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
   working tree). Detection is offline-first (the
   [`.bridge-origin`](../.bridge-origin) marker + a built-in/config list;
   `gh repo view --json visibility` only escalates an unknown remote).
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
```

Just evaluating? Keep `user/*` local and never push.

## Deliberate override

A CORE maintainer who genuinely needs to push to a public upstream uses a
visible, per-push opt-out: `BRIDGE_PUSH_GUARD=off git push ...`. It is never
silent and never the default.
