---
summary: "Backup topology: sources, targets, pipelines"
type: index
last_updated: 2026-05-01
---

# backups/

Single source of truth for the user's backup topology. Three concepts:

| Concept | Means | Lives in |
|---|---|---|
| **sources** | What gets backed up (paths + sensitivity + size hint) | `topology.yaml` |
| **targets** | Where (local / NAS / cloud) with capabilities | `topology.yaml` |
| **pipelines** | How connected (source × target × tool × schedule) | `topology.yaml` |

State (what last ran when, restic snapshot IDs) lives in `_state.yaml` and is written by the skill — `topology.yaml` stays a pure configuration in git.

## Files

| File | Purpose |
|---|---|
| `topology.yaml` | Live config, maintained by the user |
| `_template.yaml` | Boilerplate with commented defaults |
| `_state.yaml` | Last-run state (written by the skill, no hand edits) |
| `volumes/<id>.md` | Layout docs per backup volume (what goes where, cleanup rules, history) |
| `README.md` | This file |

## Volume layout docs

Every backup volume registered as a target gets a markdown layout doc under `volumes/<id>.md`. The doc describes:

- the internal folder structure (class schema like `00_Snapshots/`, `01_Live/`, etc.)
- per class: content with sizes, lifecycle, retention
- cleanup rules and sub-projects
- history (what changed when)

`topology.yaml` links via `targets.<id>.layout_ref:` to the matching doc. This keeps `topology.yaml` lean (only machine-readable pipeline config), while prose knowledge about volumes has its own place.

## Who writes what

| File | Writer |
|---|---|
| `topology.yaml` | user only (by hand) |
| `_state.yaml` | skill only (`~/.claude/skills/backup/`) |
| `_template.yaml` | Bridge CORE updates |

## Sensitivity levels

| Level | Meaning | Tool requirement |
|---|---|---|
| `clear` | no special confidentiality | any tool OK |
| `encrypted-at-rest` | volume encryption at both ends + encrypted transport is enough | any tool that runs over SSH/TLS (rsync, rclone-sync via SFTP) — the sync tool does NOT need to encrypt itself |
| `encrypted-required` | the sync tool MUST encrypt itself (e.g. because target storage is untrusted, cloud without BAA) | only restic or rclone crypt backend |

Prerequisite for `encrypted-at-rest`: FileVault active on the source mac AND target volume volume-encrypted. Otherwise drift alert in the briefing.

## Schema rules (enforced by the skill)

1. `sensitivity: encrypted-required` + non-encrypting tool (rsync, rclone-sync) → **error**
2. `sensitivity: encrypted-at-rest` + target without volume encryption → **drift alert**, no crash
3. `target.capabilities: [time-machine]` → **no** other pipelines allowed against this target
4. `enabled: true` + target/source unreachable → **drift alert** in the briefing, no crash
5. `mode: scheduled` without `schedule:` → **error**
6. Pipeline IDs must be unique

## Triggers for the skill

The global skill `~/.claude/skills/backup/` triggers on:
- "backup start / status / dry-run"
- "backup PARA to Backup4T" → match a single pipeline ID
- "back up Developer / MoneyMoney / BK"
- "upload to OneDrive" / "upload archive"
- "backup status" → reads `_state.yaml`

## Change workflow

1. Edit `topology.yaml` (new source/target/pipeline; or toggle enabled)
2. `git diff backups/topology.yaml` → review
3. Commit on user branch
4. Skill invocation tests the new pipeline with `--dry-run`
5. Only then set `enabled: true` once dry-run is clean

## Roadmap

- **Phase 1 ✓** (2026-05-01): schema + topology.yaml + volume layout docs
- **Phase 2 ✓** (2026-05-01): global skill reads topology instead of hardcoded values
- **Phase 3 ✓** (2026-05-01): CLAUDE.md backup block
- **Phase 4** (in preparation): continuous sync via SSH (rsync), 15-min polling, with `--backup-dir` (30-day retention) — four pipelines:
  - `para-continuous-to-backup4t`
  - `developer-continuous-to-backup4t`
  - `onedrive-org-continuous-to-backup4t`
  - `finance-db-continuous-to-backup4t`

  All sources are `clear` or `encrypted-at-rest` — FileVault at both ends + SSH transport is enough, no application-layer encryption needed.

  Setup: SSH to homeserver is there → manual dry-run → real run → smoke test (drop in a test file + delete, check) → deploy launchd plist → observe for 24h → `enabled: true`.

- **Phase 5** (when there is room on the Synology): enable `ds-synology` for a restic repo as a second layer of backup
- **Phase 6** (when rclone-OneDrive-OAuth is ready): reactivate `onedrive-cloud` for 4_ARCHIV cloud backup as 2nd tier
- **Phase 7** (open): backup strategy for `homeserver-backups` (media volume, currently unsecured)
