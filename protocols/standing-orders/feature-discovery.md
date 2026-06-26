---
name: feature-discovery
scope: always
enforcement: advisory
applies_to: [ops]
---
# Feature Discovery — Proactive Bridge-Feature Suggestions

The onboarding wizard intentionally avoids quiz-style questions about
the user's life ("do you file taxes for multiple entities?"). Instead,
this standing-order watches for **evidence over time** that a Bridge
feature would now be useful, and surfaces ONE suggestion at most per
briefing-window.

**Default:** enabled when `work.enabled: true`. Disable via
`bridge-config.yaml.feature_discovery.enabled: false`.

## Rules

- **Honour `discovery.mode` — this is the master gate.** When
  `discovery.mode: confined` (the template/absent default), the
  evidence heuristics below **never run**: no scanning, no
  heuristic-driven suggestions, not now and not later. In confined
  mode this order may surface ONLY features the user explicitly
  deferred during onboarding (`deferred` in `onboarding-state.yaml`)
  or asked for via `/bridge-onboard --add`. When `discovery.mode:
  broader`, behave as documented below — heuristics run, each still
  subject to its own Phase-B per-source permission (see Configuration).
  The choice is reversible: `/bridge-onboard --rescan` to broaden, or
  edit `discovery.mode` in `bridge-config.yaml`.
- **Max one suggestion per `/briefing`.** Never overwhelm.
- **Surface day default: Wednesday.** Configurable via
  `feature_discovery.surface_day` (cron weekday name).
- **Snooze logic.** Each suggestion is recorded in
  `work/onboarding-state.yaml`:
  - `accepted` → never re-suggest
  - `deferred` → recheck after `remind_after` (default +30 days)
  - `declined` once → wait 60 days
  - `declined` 3× total → mark `silenced`, never surface again
- **Respect the user.** If the user says "stop suggesting features" in
  any briefing, set `feature_discovery.enabled: false` and confirm.

## Triggers — Evidence Heuristics

> **Only in `discovery.mode: broader`.** In `confined` mode none of the
> heuristics below execute (see the master gate under Rules) — the
> Bridge stays inside its own folder and never scans repos, apps,
> devices, files, or mail.

Each heuristic checks recent activity (last 30 days unless noted).
If a heuristic fires, generate a suggestion using the matching S-block
from `skills/bridge-onboard/references/smart-suggestions.md`.

### H1 — Doc Sensor (PDFs accumulating in inbox)
- **Check:** `~/Downloads` or detected `inbox`-like folder contains
  ≥10 PDFs not opened in the last 14 days
- **Suggest:** Enable doc-system to auto-route

### H2 — Mandant (recurring recipient)
- **Check:** Mail to the same address ≥3× in 30 days
  (data source: mail-client account list + sent-folder counts;
  requires `mail_accounts` permission from Phase B)
- **Suggest:** Create a mandant or add this person to an existing one

### H3 — Remote (new SSH host)
- **Check:** New hostname appears in `~/.ssh/known_hosts` not in any
  `infra/remotes/*.yaml`
- **Suggest:** Scaffold a remote file

### H5 — Backups (new external drive)
- **Check:** `/Volumes/*` includes a drive not in
  `infra/backups/topology.yaml` targets, present for ≥3 sessions
- **Suggest:** Add as backup target

### H6 — Calendar (recurring scheduled outbound)
- **Check:** User asked Bridge to send "every X" messages ≥2× in 30
  days without using `/calendar`
- **Suggest:** Move to `workflow/calendars/entries.yaml`

### H7 — Knowledge Repo (doc growth)
- **Check:** `work/tasks/<slug>/STATUS.md` count exceeds 30 with
  recurring cross-links to similar topics
- **Suggest:** Spin up a separate wiki via `/knowledge-repo-init`

### H8 — Personas (Steuerberater traffic)
- **Check:** Mail traffic with addresses matching `steuerberater`,
  `stb`, or `kanzlei` patterns, ≥2× in 30 days
- **Suggest:** Add a persona to clarify which entity this filing belongs to

### H9 — Voice Messages (user mentioned audio repeatedly)
- **Check:** User asked Bridge to "send audio" or "voice message" ≥2×
  in 30 days and the bridge has no voice skill
- **Suggest:** Building a private voice skill (caveat: needs a
  separately-prepared voice clone; open-bridge ships none)

### H10 — Bridge-Deck (multi-agent activity) — SKIP until bridge-deck is public (coming soon)
- **Check:** Sub-agent count in `.claude/agents/*.md` is ≥3 AND user
  spawned sub-agents in ≥3 distinct sessions
- **Suggest:** Bridge-Deck visualiser (separate repo, not yet public)

## Suggestion Format

Surfaced as part of the daily/weekly briefing under a clearly-labelled
section:

```
🌱 Feature Discovery

I noticed: {evidence_sentence}.

Bridge has a feature for this: {feature_name}.
{one_paragraph_from_smart_suggestions}

  [y] Walk me through it now (runs /bridge-onboard --add {feature})
  [l] Later  (recheck in 30 days)
  [n] Not interested  (decline; 3 declines = never again)
```

The choice updates `onboarding-state.yaml.suggestions.<feature>` per
the schema in `skills/bridge-onboard/references/system-discovery.md`.

## Violations

This is an advisory standing-order — no hard violation. Soft violations:

- Surfacing more than one suggestion per briefing-window → noisy
- Re-surfacing `accepted` features → annoying, breaks trust
- Surfacing a `silenced` feature → bug
- Not respecting `feature_discovery.enabled: false` → bug
- Running any heuristic while `discovery.mode: confined` → bug
  (privacy violation — the user declined broader scanning)

All of the above should be caught by reading `discovery.mode` and the
`enabled:` flag before running heuristics, and `onboarding-state.yaml`
before surfacing.

## Configuration

Add to `bridge-config.yaml` (defaults shown):

```yaml
feature_discovery:
  enabled: true
  surface_day: wednesday      # weekday name | daily | never
  max_per_briefing: 1
  defer_days: 30              # how long to wait after [l] Later
  silence_after_declines: 3   # mark silenced after N declines
  heuristics:
    # individual heuristics can be disabled by name
    # H2_mandant: false
    # H8_personas: false
```

Heuristics that require Phase-B permissions (mail accounts, calendar)
silently skip if the permission is not granted in
`bridge-config.yaml.discovery.permissions`.
