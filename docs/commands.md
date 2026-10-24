---
summary: The slash commands each shipped CORE skill registers, and what invokes them.
type: reference
last_updated: 2026-10-24
related:
  - AGENTS.md
  - docs/skill-distribution-architecture.md
  - scripts/check-commands-doc.py
---

# Commands

In Claude Code every skill registers a slash command, and the command is the
skill's name: the `bridge-promote` skill is `/bridge-promote`. There are no
separate files in `.claude/commands/`, and invoking a skill via the Skill tool
is equivalent to typing its command. Other tools find the same skills through
`.agents/skills` or `.github/skills`, or load them from `skills/` by path, and
pick one up from the trigger phrases in its `description:`.

Some skills also declare a shorter slash word among those trigger phrases
(`/overlay`, `/contribute`, `/postmortem`). That short form is a phrase the
agent recognises when you write it in a message. It is not a second registered
command, so the Short form column lists only what the skill itself declares.

This page is the CORE set: every `scope: core` skill whose description
declares a quoted slash trigger, plus `/remote` and `/workload`, which are
commands by name but declare no slash trigger. An instance carries more, and
which ones is per-instance, so the live list is the skill listing itself.
`scripts/check-commands-doc.py` holds these tables to the tree in CI.

## Daily work

| Command | Short form | Backing skill | Action |
|---------|------------|---------------|--------|
| `/briefing` | | `briefing` | Daily briefing: the inbox first (what needs you, with approve, defer, drop and agent tabs to steer the day), then board, git activity, goals, alerts |
| `/bridge-status` | | `bridge-status` | Status dashboard: ecosystem, agents, work, remotes |
| `/dashboard` | | `dashboard` | Project dashboard for the current project: GitHub or ADO tasks, git activity, deployment status (`--all`, `--html`) |
| `/cockpit` | | `cockpit` | The cockpit: a local web page (127.0.0.1) that watches and steers the whole Bridge, with the briefing, your work, agent tabs and sessions, workers, machines and tokens |
| `/archive` | | `archive` | Archive the current period: summary, durable facts distilled into memory, `work/log.md` reset |
| `/debrief` | | `debrief` | Process transcripts: 7-category insights, tasks, protocols (full / `--quick` / `--all` / `--date`) |
| `/task-close-postmortem` | `/postmortem` | `task-close-postmortem` | Postmortem at task close: six optional questions, frontmatter back into STATUS.md, improvement proposals |
| `/tracker-sync` | | `tracker-sync` | Snapshot GitHub Project boards and reconcile them with local tasks; pushes local changes only after you confirm |
| `/doc-system` | | `doc-system` | Document intake: scan import sources, categorise, rename, tag, file, audit |
| `/bridge-explorer` | | `bridge-explorer` | Ecosystem, repo-layout and constellation visualizations |
| `/bridge-greeting` | | `bridge-greeting` | Terminal greeting per instance: logo, palette, today's calendar, the Doing board |
| `/html-slides` | `/slides` | `html-slides` | Single-file HTML slide deck: DESIGN.md or a style preset, speaker notes, tracks, live stages; PDF export and an anonymity check before sending |

## Setup and configuration

| Command | Short form | Backing skill | Action |
|---------|------------|---------------|--------|
| `/bridge-onboard` | | `bridge-onboard` | New user setup or reconfiguration |
| `/workspace` | | `workspace` | Bind code repos and config overlays into a named workspace: `create`, `subscribe`, `list`, `status`, `validate`, `unsubscribe` |
| `/bridge-overlay` | `/overlay` | `bridge-overlay` | Subscribe to org overlays and materialize `scope: org` content into the live tree (the downstream inverse of `/bridge-promote`) |
| `/knowledge-repo-init` | | `knowledge-repo-init` | Connect or scaffold an optional knowledge or documentation repo |
| `/calendar` | | `calendar` | Calendar entries: list, add, cancel, confirm, show, status |
| `/mandants` | | `mandants` | Mandant management: list, add, show, add-person |
| `/secrets` | | `secrets` | Secrets: `refs`, `check`, `run`, `where`, `store`, `stores`, `audit`. Resolves a reference and never prints a value, writes one without it passing through argv, and finds the plaintext that never became a reference |
| `/object-store` | | `object-store` | Object stores: `stores`, `stat`, `path`, `fetch`, `put`, `init`, `forget`. Resolves `object://<store>/<key>` to a path and never to content; a failed read names why, a write never queues |

## Machines and runs

| Command | Short form | Backing skill | Action |
|---------|------------|---------------|--------|
| `/remote` | | `remote` | Remote machines: inventory, wake, SSH or RDP, reachability, health, logs, restart, deploy |
| `/workload` | | `workload` | Declared runs: `declare`, `validate`, `render`, `provision`, `list`, `show`, `reconcile`, `view`, `publish`, `adopt`, `retire` |
| `/schedule` | | `schedule` | Scheduled tasks: list, create, deploy, disable |
| `/channel` | | `channel` | Channel management: list, health, deploy, start/stop |
| `/board-pilot` | | `board-pilot` | Board-driven pipeline: arms an item a person drags into the trigger column, advances it one stage per tick, stops at a draft PR for review |

## Upstream and quality

| Command | Short form | Backing skill | Action |
|---------|------------|---------------|--------|
| `/bridge-promote` | | `bridge-promote` | Promote CORE changes upstream (`scope: core` to `bks-lab/open-bridge`, `scope: org` to your optional org overlay). Refuses a flat-mirror overlay (a manifest whose `source_root` is not the repo root): preview with `scripts/overlay-export.py --target <checkout> --scope <tier> --dry-run`, then run it without `--dry-run` ([org-overlays.md](org-overlays.md#authoring-an-overlay)) |
| `/bridge-contribute` | `/contribute` | `bridge-contribute` | Scan the user branch for upstream-worthy files and open a fork-based PR behind the content-safety gate |
| `/bridge-sync` | | `bridge-sync` | End-of-sprint batch sync of all pending `scope: core` and `scope: org` commits to both upstreams. Same flat-mirror refusal as `/bridge-promote`; open-bridge still syncs |
| `/bridge-leak-check` | | `bridge-leak-check` | Content-leak scan with every hit classified (self-reference, sister repo, personal data, internal vocabulary) |
| `/bridge-audit` | | `bridge-audit` | Drift audit between docs and reality, reported as P0 to P3 findings with fix proposals |
| `/bridge-curator` | | `bridge-curator` | Periodic consolidation pass over skills, proposals and user patterns; proposes, never applies |
| `/bridge-learn` | | `bridge-learn` | Review pending learning-loop proposals: accept, reject, edit or defer each one |
| `/onboard-sim` | | `onboard-sim` | Adversarial onboarding simulation in a sandbox that asserts no user data reached a would-be public upstream |
