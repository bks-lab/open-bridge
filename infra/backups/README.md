---
summary: "Backup topology: sources, targets, pipelines — the data model + schema open-bridge ships (the executor skill is user-supplied)."
type: readme
last_updated: 2026-06-21
---

# backups/

Single source of truth for your backup topology. Three concepts:

| Concept | Means | Lives in |
|---|---|---|
| **sources** | What gets backed up (paths + sensitivity + size hint) | `topology.yaml` |
| **targets** | Where (local / NAS / cloud) with capabilities | `topology.yaml` |
| **pipelines** | How connected (source × target × tool × schedule) | `topology.yaml` |

> **What open-bridge ships here:** the **data model + schema** (`_template.yaml`,
> `_schema.yaml`, and these conventions). It does **not** ship an executor. The
> actual backups are run by a *backup skill you supply* — a topology-reader +
> tool-dispatcher (e.g. a globally installed `~/.claude/skills/backup/`) — or by
> an org overlay. Everywhere below, "the backup skill" means that user-supplied
> executor. You create `topology.yaml` (your instance config) from `_template.yaml`.

State (what last ran when, restic snapshot IDs) lives in `_state.yaml`, written by
the backup skill — `topology.yaml` stays pure configuration in git.

## Files

| File | Purpose |
|---|---|
| `_template.yaml` | Boilerplate with commented defaults (ships in CORE) |
| `_schema.yaml` | JSON Schema for `topology.yaml`, validated in CI (ships in CORE) |
| `topology.yaml` | Your live config (you create + maintain it; USER-scope) |
| `_state.yaml` | Last-run state (written by the backup skill, no hand edits) |
| `volumes/<id>.md` | Layout docs per backup volume (what goes where, cleanup rules, history) |
| `README.md` | This file |

## Volume layout docs

Every backup volume registered as a target gets a markdown layout doc under
`volumes/<id>.md`. The doc describes:

- the internal folder structure (class schema like `00_Snapshots/`, `01_Live/`, etc.)
- per class: content with sizes, lifecycle, retention
- cleanup rules and sub-projects
- history (what changed when)

`topology.yaml` links via `targets.<id>.layout_ref:` to the matching doc. This keeps
`topology.yaml` lean (only machine-readable pipeline config), while prose knowledge
about volumes has its own place.

## Who writes what

| File | Writer |
|---|---|
| `topology.yaml` | you only (by hand) |
| `_state.yaml` | the backup skill only (user-supplied executor) |
| `_template.yaml` / `_schema.yaml` | open-bridge CORE updates |

## Sensitivity levels

| Level | Meaning | Tool requirement |
|---|---|---|
| `clear` | no special confidentiality | any tool OK |
| `encrypted-at-rest` | volume encryption at both ends + encrypted transport is enough | any tool that runs over SSH/TLS (rsync, rclone-sync via SFTP) — the sync tool does NOT need to encrypt itself |
| `encrypted-required` | the sync tool MUST encrypt itself (e.g. because target storage is untrusted, or cloud without a data-processing agreement) | only restic or rclone crypt backend |

Prerequisite for `encrypted-at-rest`: disk encryption active on the source machine
AND the target volume encrypted. Otherwise a drift alert surfaces in the briefing.

## Schema rules (for the backup skill / validator to enforce)

1. `sensitivity: encrypted-required` + non-encrypting tool (rsync, rclone-sync) → **error**
2. `sensitivity: encrypted-at-rest` + target without volume encryption → **drift alert**, no crash
3. `target.capabilities: [time-machine]` → **no** other pipelines allowed against this target
4. `enabled: true` + target/source unreachable → **drift alert** in the briefing, no crash
5. `mode: scheduled` without `schedule:` → **error**
6. Pipeline IDs must be unique

## Triggers (for a user-supplied backup skill)

A backup skill typically triggers on natural language such as:

- "backup start / status / dry-run"
- "back up &lt;source&gt; to &lt;target&gt;" → match a single pipeline ID
- "upload &lt;source&gt; to &lt;cloud target&gt;"
- "backup status" → reads `_state.yaml`

## Change workflow

1. Edit `topology.yaml` (new source/target/pipeline; or toggle `enabled`)
2. `git diff infra/backups/topology.yaml` → review
3. Commit on your user branch
4. The backup skill tests the new pipeline with `--dry-run`
5. Only then set `enabled: true` once the dry-run is clean

## Wiring an executor

open-bridge ships the topology + schema only. To make backups actually run, supply
a backup skill (or org overlay) that:

1. reads `topology.yaml` and resolves the enabled pipelines,
2. dispatches the matching tool per pipeline (rsync / rclone / restic / time-machine —
   Time Machine is configured in macOS; the skill only documents the intended state),
3. honours the sensitivity rules above (refuse `encrypted-required` on a non-encrypting tool),
4. tests new pipelines with `--dry-run` before flipping `enabled: true`,
5. writes results to `_state.yaml`; drift (unreachable source/target, missing
   encryption) surfaces in the daily briefing rather than crashing.
