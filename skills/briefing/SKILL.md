---
name: briefing
description: 'Daily briefing — board, ecosystem activity, tracker sync, goals. Parallel 4-stream collection. Modes: --quick, --html. Trigger: "/briefing", "briefing", "good morning", "daily standup", "checkin", "morning briefing". (Bare "status" → bridge-status; bare "what is up" → dashboard.)'
metadata:
  scope: core
---

# Briefing

Daily and on-demand briefing. Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Full briefing — all 4 streams + Phase 2 board.md sync | — |
| `--quick` | Focus box + Stream A only; **skips** trackers, companion data, channels, Phase 2 | false |
| `--skip-trackers` | All streams except Stream B (offline-friendly); Phase 2 still runs | false |
| `--commits YYYY-MM-DD` | Detailed commit analysis for one day (sessions, time est., types) — see `references/commit-analysis.md` | — |
| `--html` | After terminal output, delegate to `/bridge-dashboard` to render the operational HTML dashboard | false |

### Mode × Phase matrix

| Phase | default | `--quick` | `--skip-trackers` |
|-------|---------|-----------|-------------------|
| Phase 0 (smart detection + day block) | ✅ | ✅ | ✅ |
| Stream A (local state) | ✅ | ✅ | ✅ |
| Stream B (trackers fan-out) | ✅ | ❌ | ❌ |
| Stream C (companion: calendar, imports) | ✅ | ❌ | ✅ |
| Stream D (channels) | ✅ | ❌ | ✅ |
| Phase 2 (board.md sync) | ✅ | ❌ | ✅ |
| Phase 3 (log entry) | ✅ | ✅ | ✅ |
| Phase 4 (terminal output) | ✅ | ✅ | ✅ |

## Prerequisites

- `bridge-config.yaml` with `work.enabled: true`. If not: offer setup.
- Standing orders are loaded at session start (per CLAUDE.md). If `/briefing`
  is invoked **standalone** (e.g. via cron or a long-running session), manually
  load `protocols/standing-orders/*.md` before Phase 1 — the `applications`
  surface logic in Stream C depends on them.

## Decision Tree

```
User wants to...
├── Full daily briefing              → Read references/workflow.md
├── Quick local-only briefing        → Read references/workflow.md (--quick path)
├── Detailed commit analysis         → Read references/commit-analysis.md
├── Check for upstream CORE updates  → Read references/upstream-summary.md
│                                       (only if `upstream:` block exists in
│                                       bridge-config.yaml AND a git remote
│                                       named `upstream` is configured;
│                                       Seed-repo instances skip)
└── Questions about briefing         → Answer from this file
```

## Sister skills (don't duplicate)

| For… | Use |
|------|-----|
| Memory drift, doc-link health, branch/config sanity | `/bridge-status` |
| Live service status of channels/remotes (launchd, processes, ports) | `/remote` |
| Detailed GitHub/ADO board view (per-project) | `/dashboard` |
| Visual ops dashboard (Fleet + Board + Calendar + Channels) | `/bridge-dashboard` (also the target of `--html`) |
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
