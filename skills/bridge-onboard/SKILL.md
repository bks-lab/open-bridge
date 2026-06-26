---
name: bridge-onboard
description: >-
  New user onboarding and reconfiguration — discovery-driven setup with
  permission-gated system scan, evidence-based feature suggestions, and
  a read-only catalogue of what else Bridge can do. Six-phase wizard
  (Identity / Discovery / Suggestions / Quick-Wins / Catalog / Validate)
  with re-entry modes for targeted later activation. Works without
  GitHub. Upstreams stay empty by default and wire later when
  the OSS upstream or your own upstream is live.
  Trigger: "/bridge-onboard", "onboard", "setup", "configure bridge",
  "new user", "ecosystem scan", "set up bridge", "reconfigure",
  "reconfigure bridge", "setup wizard".
metadata:
  scope: core
---

# Bridge Onboard — Setup Wizard

Set up a new Bridge user or reconfigure an existing one.
Read the referenced file ONLY when triggered.

## Philosophy — Discover, don't Interrogate

A new user came here to configure an assistant, not to inventory their
life. Asking abstract questions like "do you file taxes for multiple
legal entities?" or "do you have a household mandant?" makes the user
defensive — they don't know yet what those features do, so they say
"skip" to everything and miss the point.

Instead, the wizard:

1. Looks at what's already on the system (with permission)
2. Proposes specific features that match the evidence
3. Shows the rest as a read-only catalogue with "when you need it"
4. Surfaces features proactively later (`feature-discovery`
   standing-order) when patterns suggest they'd help

All of this is **consent-first**: before step 1, the user picks
`discovery.mode` — **confined** (default) or **broader**. Confined means
the Bridge never scans the machine (other repos, installed apps, devices,
files, and mail stay untouched) — you still get every feature, just
enabled modularly when you want it via the Phase E catalog, `--add
<feature>`, or the feature's `enabled:` flag in `bridge-config.yaml`.
Only **broader** unlocks the permission-gated scan in step 1.

This file is the entry point; the heavy lifting lives in `references/`.

## Defaults — what the wizard assumes

- **Purpose pins a north-star (ordering, never gating).** Phase A captures one
  line — what this instance is for — into `purpose.statement` (+ a derived
  `purpose.focus`). It ORDERS the Phase C suggestions, the Phase E catalogue, and
  the `feature-discovery` standing-order, and is echoed in the greeting + preview;
  it **never** hides, gates, or removes a feature. Empty purpose = today's flat,
  general-purpose behaviour. Change anytime via `--purpose`.
- **GitHub is optional.** Onboarding completes end-to-end without a
  GitHub org, without `gh` CLI, and without GitHub-projects integration.
- **Upstreams stay empty (`upstreams: []`) by default.** Upstream
  variant choice is a separate, optional step via `--upstream`.
- **Work-system on by default.** Phase D recommends enabling — it's
  what makes Claude resume context across sessions. The wizard
  explains the trade-off but suggests `[y]`.
- **Discovery scan is opt-in per source.** Default-on sources are
  non-invasive (git config, dir listings, app list). Sensitive sources
  (mail accounts, finance-app accounts, calendar names) are default-off
  and only opt-in.
- **Nothing scanned beyond names.** Mail content, document content,
  message bodies, keychain, passwords — NEVER touched. Explicit in the
  permission prompt so trust is established.

## Privacy & Trust

Scan findings live in `work/onboarding-scan.json` (gitignored,
auto-deleted after 30 days or on `--reset`). Granted permissions are
persisted to `bridge-config.yaml.discovery.permissions` so re-runs honor
the same boundary without re-asking.

Decision history lives in `work/onboarding-state.yaml` (NOT gitignored
— useful as a record of setup choices) with statuses
`accepted | deferred | declined | silenced | nothing_found`.

The `feature-discovery` standing-order (active when `work.enabled:
true`) uses the same state file to avoid double-suggesting.

**Mirror-safety — check the origin before writing any private data.** Onboarding
writes the user's identity and `work/` to a `user/{name}` branch. Before creating
that branch (Phase A step 6), resolve where the clone pushes: `git remote get-url
origin` (and `gh repo view --json visibility,nameWithOwner` if unsure). **If
`origin` is a PUBLIC repo or a known upstream (e.g. `bks-lab/open-bridge`) — or
[`.bridge-origin`](../../.bridge-origin) says `is_public: true` — STOP and advise,
do not proceed silently.** The user's private data must not live on a public
origin. Offer to set them up on their **own private** repo first (GitHub *Use this
template → Private*, or re-home `origin` to a new private repo with open-bridge as
a read-only `upstream`), then continue. Never push the `user/*` branch to a public
origin; CORE reaches a public upstream only via `/promote`. Canonical rule:
[`../../rules/push-guard.md`](../../rules/push-guard.md).

## Modes

| Invocation | Behaviour |
|---|---|
| `/bridge-onboard` | Full wizard (Phases A–F) |
| `/bridge-onboard --rescan` | Broaden discovery (sets `discovery.mode: broader`); re-run Phase B+C with persisted permissions; surface new evidence; skip already-accepted features |
| `/bridge-onboard --reset` | Delete scan + state files; restart Phase B from scratch. Prompts to delete `bridge-config.yaml` for true clean-slate |
| `/bridge-onboard --add <feature>` | Skip A+B+D+E+F, run only the matching S-block from `smart-suggestions.md` (e.g. `--add personas`, `--add doc-system`) |
| `/bridge-onboard --add agent-soul` | Skip everything except D4 — re-pick the soul deck and reshape SOUL.md / IDENTITY.md |
| `/bridge-onboard --purpose` | Skip everything except the Phase-A purpose step — set/change `purpose.statement` + `purpose.focus` (re-derive `user_profile`), then re-render the Phase F preview ordering. Never gates a feature |
| `/bridge-onboard --features` | Read-only Phase E catalogue, interactive — explore what Bridge can do, click into entries to activate |
| `/bridge-onboard --upstream` | Skip everything except upstream wiring (see below) |

## Optional: `--upstream` mode

When invoked as `/bridge-onboard --upstream`, the wizard skips Phases
A-E, going straight to upstream configuration. Use cases:

- User already onboarded, now wants to wire `bks-lab/open-bridge` once
  it is publicly available
- Forked the Bridge into a private org and wants to push contributions

In this mode, ask:

```
Which upstream are you wiring?

  [1] open-bridge (OSS) — sets contribute: true, pull-only OSS-core
  [2] org-internal bridge — sets primary: true, push-enabled
  [3] Custom — type repo/branch/role manually
```

Each choice appends one entry to `upstreams: []` and adds a matching
`promote.content_blocklist.<name>` skeleton (user fills the strings/patterns
based on what their codebase shouldn't leak).

## Decision Tree

```
User wants to...
├── Full onboarding wizard             → Read references/workflow.md
├── Re-scan and resurface deferred     → Read references/system-discovery.md (--rescan)
├── Start fresh                        → Read references/system-discovery.md § Re-Run Modes (--reset)
├── Activate one specific feature      → Read references/smart-suggestions.md § Adding a Feature Later
├── Set or change the instance purpose → Read references/workflow.md § Phase A step 5 (--purpose)
├── Browse what Bridge can do          → Read references/feature-catalog.md (--features)
├── Wire an upstream after the fact    → This file § Optional: --upstream mode
└── Questions about setup              → Answer from references/workflow.md + CLAUDE.md § Session Start
```

## Reference Files

| File | Purpose |
|---|---|
| `references/workflow.md` | Six-phase wizard execution plan (entry point for full onboarding) |
| `references/system-discovery.md` | Phase B — what gets scanned, with which permission, what's never scanned |
| `references/smart-suggestions.md` | Phase C — evidence → recommendation mapping (S1–S12) with full advisory text |
| `references/feature-catalog.md` | Phase E + `--features` — read-only catalogue of all Bridge features |
| `references/discovery.md` | Legacy: repo-only ecosystem detection. Now a sub-case of `system-discovery.md` |
| `references/preview-generator.md` | Phase F — HTML preview with Activated + Suggested-for-later sections |

## Related Files

- `protocols/standing-orders/feature-discovery.md` — proactive feature
  suggestions in the weekly briefing window (uses
  `work/onboarding-state.yaml` to avoid double-suggesting)
- `docs/feature-tour.md` — per-cluster-wrapper "create your first X"
  guide for after onboarding
- `bridge-config.yaml.template` — every block has a comment pointing at
  the matching `--add <feature>` re-entry path

## Implementation Notes

- All wizard output is bilingual where the user's language is German
  (matches `language.conversation` from Phase A)
- Suggestions in Phase C run sequentially, not as a batch — each `[y]`
  scaffolds immediately so the user sees progress
- Errors during scan or scaffold are non-fatal; record and continue,
  surface the issue in Phase F's validation step
- Never write to `bridge-config.yaml` outside of explicit phases; the
  user must always see the current state before changes are committed
