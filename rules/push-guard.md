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
> `identity/agent/{IDENTITY,SOUL}.md`, every non-`_` file directly under an
> `identity/<family>/`, `infra/<family>/` or `workflow/<family>/` folder, the four
> `identity|infra|workflow|work/.gitignore` negation files, `bridge-config.yaml`,
> `bridge-deck.config.yaml`, `ecosystem*.yaml`, `overlays.lock.yaml`, `workspaces.lock.yaml`,
> `context-budget.user.yaml`, `edges.yaml`, `reachability-scenarios.yaml`) must **never** be
> pushed to a **public** upstream.

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

## One classifier, two callers

The logic above lives in exactly one place, [`scripts/lib/remote-class.sh`](../scripts/lib/remote-class.sh):
`scripts/hooks/pre-push` sources it, and `scripts/user-data.py` (the tool that decides whether
your instance data is tracked at all, see [`docs/structure.md`](../docs/structure.md#gitignore-policy))
asks it the same question, so the two can never disagree about the same origin. Before this
file existed the logic lived inline in `pre-push`, and a second copy would have been the drift
that decides whether a persona file gets backed up or published.

The content net (`USER_PATHS` in `scripts/hooks/pre-push`) matches every cluster-wrapper
family **generically** (`(identity|infra|workflow)/([^/]+/[^_]|\.gitignore$)`), rather than
naming each folder. A hand-kept list of family names fell behind the tree by four:
`identity/vehicles/`, `infra/secret-stores/`, `infra/object-stores/`, and the root
`ecosystem.yaml` + `context-budget.user.yaml` were all missing from it, unnoticed while the
shipped `.gitignore` kept those files out of every commit anyway. Now that a private instance
tracks its own data by default, this net is the only thing standing between that data and a
public remote, so it has to know every family the tree has, including the next one. The net
also matches `identity/.gitignore`, `infra/.gitignore`, `workflow/.gitignore` and
`work/.gitignore` themselves: those four files carry the negation that makes a private origin's
instance data trackable, so promoting one to a public remote would re-allow instance data in
every clone that later merges it.
[`scripts/tests/test_push_guard_paths.py`](../scripts/tests/test_push_guard_paths.py) holds it
to the tree.

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
# Re-home the clone you already have. (A fork of a public repo is itself
# public, so it cannot hold your data privately.)
git remote rename origin upstream            # public open-bridge becomes read-only
gh repo create <you>/my-bridge --private --source=. --remote=origin   # no push yet

# Record the new origin as private and commit the marker, so every push
# classifies PRIVATE even offline (gh absent or unauthenticated):
{ grep '^#' .bridge-origin; printf 'repo: <you>/my-bridge\nis_public: false\n'; } > .bridge-origin.new
mv .bridge-origin.new .bridge-origin          # keeps the shipped comment header
git add .bridge-origin && git commit -m "Record the private origin for the push guard"

git config core.hooksPath scripts/hooks      # armed already if Phase 0 or bin/setup ran
git push -u origin main                      # first push, through the armed guard
git fetch upstream && git merge upstream/main   # pull CORE updates anytime
```

No `gh`: create an empty private repo by hand and `git remote add origin <url>`
in place of `gh repo create`. Nothing then confirms the repo is private, so check
before writing the marker: `curl -s -o /dev/null -w '%{http_code}'
https://api.github.com/repos/<you>/my-bridge` must answer `404` (anonymous requests
cannot see a private repo; `200` means public, stop), and `git ls-remote origin` must
succeed. A fresh setup from nothing follows the same order
in [`SETUP.md`](../SETUP.md).

**Write `.bridge-origin` (`is_public: false`) ONLY after the origin is confirmed
private** — never for a still-public origin. The marker vouches only for its matching
`repo:` slug; the public upstream still BLOCKs. Without it, a re-homed clone whose slug no
longer matches the CORE-shipped marker falls through to `gh repo view`, and offline/
unauthenticated that resolves **unknown → fail-closed**, refusing a legitimate first push
to the user's own brand-new private repo. Committing it before the first push means the
guard already knows the origin when it first runs, and a second clone of the private repo
inherits the marker. Onboarding runs this sequence as part of the re-home (see
`skills/bridge-onboard/references/workflow.md` Phase A step 6).

GitHub's "Use this template" button is not part of this path: its copy starts a fresh
history, so the first `git merge upstream/main` stops with `refusing to merge unrelated
histories` ([`docs/install.md`](../docs/install.md#the-use-this-template-button)).

Just evaluating? Keep `user/*` local and never push.

## Deliberate override

A CORE maintainer who genuinely needs to push to a public upstream uses a
visible, per-push opt-out: `BRIDGE_PUSH_GUARD=off git push ...`. It is never
silent and never the default.
