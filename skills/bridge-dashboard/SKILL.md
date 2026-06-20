---
name: bridge-dashboard
description: >-
  Generates the Bridge Control Center — a single-file HTML dashboard that
  bundles Fleet (infra/remotes/), Work Board, Calendar
  (next 24h), Channels, Git activity, optional Bridge-Deck /metrics, and
  upstream drift into one view. Stands alone; the pixel-art Bridge-Deck
  renderer it can complement is not yet public (coming soon).
  Trigger: "/bridge-dashboard", "bridge dashboard", "control center",
  "ops dashboard", "open dashboard", "show me everything at a glance".
metadata:
  scope: core
---

# Bridge Dashboard

## What it does

A Python generator (`scripts/bridge-dashboard.py`, stdlib + PyYAML only) aggregates the entire Bridge state **in parallel** and renders a self-contained HTML:

| Tile | Source | Parallel probe |
|------|--------|----------------|
| Fleet | `infra/remotes/*.yaml` + ICMP ping (Tailscale > LAN) | yes, 8 workers |
| Work Board | `work/board.md` (doing/backlog/done) | yes |
| Calendar 24h | `workflow/calendars/entries.yaml` + RRULE expander | yes |
| Channels | `infra/channels/*.yaml` | yes |
| Bridge-Deck (optional) | HTTP `http://homeserver:8791/metrics` — tile shows "offline" when absent | yes, 1.5s timeout |
| Git Activity | all repos from `ecosystem.yaml` via `git log --since=24h` | yes, 6 workers |
| Upstream | `HEAD..development` | yes |
| Events | last 10 lines from `work/log.md` | yes |

Design: dark theme, cyan/amber, responsive 12-column grid. Sticky header with live counters. Auto-refresh every 30s via meta tag.

## Usage

```bash
# Generate once → work/dashboard.html
python3 scripts/bridge-dashboard.py

# Generate and open in the browser
python3 scripts/bridge-dashboard.py --open

# Continuous mode: server on :8790, regenerate every 30s
python3 scripts/bridge-dashboard.py --serve
```

Serve mode is suited for launchd/cron on homeserver. A plist template lives in `skills/bridge-dashboard/references/com.example.bridge-dashboard.plist`.

## Relationship to Bridge-Deck (optional — not yet public, coming soon)

| | Bridge-Deck :8791 | Bridge Dashboard :8790 |
|---|---|---|
| Purpose | Ambient pixel-art office view | Ops-grade situational awareness |
| Tech | Node/React/Pixi + WS live | Python → HTML, 30s refresh |
| Runs where | homeserver (launchd, always on) | on-demand or launchd (optional) |
| Scope | Agents/Channels/Calendar | Fleet + Board + integrations-ready + Git |

Both read the Bridge's YAML data read-only. No duplicate source.

## Decision Tree

```
User wants to...
├── Quick morning check                  → python3 scripts/bridge-dashboard.py --open
├── Permanently on a 2nd monitor         → --serve + keep a browser tab open
├── Fleet status right now               → generate dashboard, top left
├── Integrate an integration tile (e.g. cloud-function health) → add a tile in scripts/bridge-dashboard.py (Phase 2 — planned)
└── Customize the dashboard              → edit scripts/bridge-dashboard.py
```

## Data Sources & Invariants

- **Read-only**: The script writes exclusively to `work/dashboard.html`. No changes to YAML/log/board.
- **Fail-soft**: If a source is missing (e.g. bridge-deck offline), the tile shows "offline". Other tiles still run.
- **Timeouts**: Ping 800ms, HTTP 1.5s, Git 3s per repo — the whole dashboard builds in <4s.
- **No secrets**: The HTML contains only paths and metrics, no tokens.

## Roadmap (non-blocking)

1. Integration tile: cloud-function health + log-error count via provider CLI.
2. Mail tile: unread mail from Microsoft Graph (via an org-overlay mail skill, if your bridge has one).
3. Telegram/Signal unread count.
4. Weekly sparkline: commits/day, log events/day.
5. Dark/light toggle.
6. PWA manifest for full-screen kiosk on iPad.
