---
name: briefing
description: >-
  Daily briefing from your own profile (workflow/briefings/<id>.yaml: sections, trackers incl. GitHub/Jira/GitLab/ADO/Linear, inbox rules): inbox first, then steer the day (approve, defer, drop, open agent tabs). /briefing <id> picks a profile. Trigger: "/briefing", "briefing", "good morning", "daily standup", "what needs me", "which briefings do I have".
metadata:
  scope: core
---

# Briefing

Daily and on-demand briefing. Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Full briefing of the default profile: Phase 0.5 inbox, the profile's sections, the remaining streams + Phase 2 board.md sync | — |
| `<id>` | Run the profile `workflow/briefings/<id>.yaml` instead of the default | default profile |
| `--quick` | Focus box + Stream A only (Phase 0.5 inbox still runs); **skips** trackers, companion data, channels, Phase 2 | false |
| `--skip-trackers` | All streams except Stream B (offline-friendly); Phase 2 still runs | false |
| `--commits YYYY-MM-DD` | Detailed commit analysis for one day (sessions, time est., types) — see `references/commit-analysis.md` | — |
| `--style <s>` | Show this run as `sources`, `triage`, `brevity` or `plan` instead of the profile's `view.style` (`briefing.py render --style`) | profile's view |
| `--html` | After terminal output, open the cockpit (`/cockpit`), the live web page of the Bridge | false |

### Mode × Phase matrix

| Phase | default | `--quick` | `--skip-trackers` |
|-------|---------|-----------|-------------------|
| Phase 0 (smart detection + day block) | ✅ | ✅ | ✅ |
| Phase 0.5 (inbox: check + run released) | ✅ | ✅ | ✅ |
| Stream A (local state) | ✅ | ✅ | ✅ |
| Stream B (trackers fan-out) | ✅ | ❌ | ❌ |
| Stream C (companion: calendar, imports) | ✅ | ❌ | ✅ |
| Stream D (channels) | ✅ | ❌ | ✅ |
| Phase 2 (board.md sync) | ✅ | ❌ | ✅ |
| Phase 3 (log entry) | ✅ | ✅ | ✅ |
| Phase 4 (terminal output) | ✅ | ✅ | ✅ |

## Prerequisites

- `bridge-config.yaml` with `work.enabled: true`. If not: offer setup.
- Standing orders are loaded at session start (per AGENTS.md, for every agent). If `/briefing`
  is invoked **standalone** (e.g. via cron or a long-running session), manually
  load `protocols/standing-orders/*.md` **and `protocols/standing-orders/user/*.md`**
  before Phase 1 — the `applications` surface logic in Stream C depends on them, and
  an applications order is user-tier (a `*.md` glob alone does not reach `user/`).

## Decision Tree

```
User wants to...
├── Full daily briefing              → Read references/workflow.md, then
│                                       references/control.md (inbox first,
│                                       one thing first, levers). With a view:
│                                       the render is the shape, not the whole
│                                       run; uncovered streams still run, end
│                                       with the receipt line
├── Quick local-only briefing        → Read references/workflow.md (--quick path)
├── Change how mine LOOKS (triage, brevity, plan, bucket titles,
│   "not this again")                → the profile's `view:` / `mutes:`,
│                                       docs/briefings.md § Views; then
│                                       `briefing.py validate`
├── Which briefings do I have / set one up / change what mine shows
│                                    → `python3 scripts/briefing.py list`;
│                                       new or changed profile: copy
│                                       workflow/briefings/_template.yaml,
│                                       keys in docs/briefings.md, then
│                                       `briefing.py validate`
├── Steer: yes/later/drop, "yes once green", open the day's tabs,
│   status of all tabs, tell a tab   → Read references/control.md
├── Detailed commit analysis         → Read references/commit-analysis.md
├── Are we behind on anything?       → Read references/upstream-summary.md
│                                       (covers BOTH inbound channels: CORE from
│                                       the `role: oss-core` upstream, and every
│                                       subscribed org overlay. Needs an
│                                       `upstreams:` list in bridge-config.yaml;
│                                       a Bridge with none skips)
└── Questions about briefing         → Answer from this file
```

## Sister skills (don't duplicate)

| For… | Use |
|------|-----|
| Memory drift, doc-link health, branch/config sanity | `/bridge-status` |
| Live service status of channels/remotes (launchd, processes, ports) | `/remote` |
| Detailed GitHub/ADO board view (per-project) | `/dashboard` |
| Live web view of the whole Bridge (work, tabs, machines, tokens) | `/cockpit` (also the target of `--html`) |
| Weekly archive | `/archive` |

`/briefing` is a **daily** rollup. The skills above are deeper dives into
a single dimension; cross-link rather than re-implement.

## Activity Types (log entries)

These describe **what kind of work** happened — used as the `Type` column
in `work/log.md` activity-log tables.

| Symbol | Name |
|--------|------|
| 🧪 | Testing |
| 💻 | Development |
| 🔬 | Analysis |
| 📋 | Planning |
| 📝 | Documentation |
| 🔧 | DevOps |
| 📅 | Meeting |
| 📧 | Communication |
| 📁 | Documents |
| 🐛 | Bug / Incident |
| 🎓 | Talk / Teaching |
| 🧠 | Insight / Sequential-thinking |

Distinct from the **commit-message classification** taxonomy in
`references/commit-analysis.md` — that one is for analyzing git history
(🐛 Bug Fixing, 🎯 Feature, 🔧 Code Refactoring, …). The taxonomies overlap
on a few icons but address different artefacts; don't try to unify them.
