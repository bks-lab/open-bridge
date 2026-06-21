---
summary: "Calendar system: scheduled outbound actions (emails, messages, reports) as structured entries with recipients, timing, and origin."
type: guide
last_updated: 2026-06-21
related:
  - docs/mandants.md
  - docs/channels.md
---

# Calendar System

The calendar tracks every scheduled outbound action — emails, messages,
reports, notifications — as a structured entry with recipients, timing,
and origin. It's the **what gets sent, to whom, when, and why** layer.

## Quick start

1. Enable in `bridge-config.yaml`:
   ```yaml
   calendar:
     enabled: true
   ```
2. Create `workflow/calendars/entries.yaml` on your user branch (copy from
   `workflow/calendars/_template.yaml`)
3. Add your first entry — see the schema below or use `/calendar add`
4. If running bridge-deck, add `collector-calendar` to your config:
   ```yaml
   collectors:
     - package: "@bridge-deck/collector-calendar"
       options:
         calendarPath: "~/Developer/<org>/<your-bridge>/workflow/calendars/entries.yaml"
   ```
5. Your entries appear on the Timeline (with origin badges) and the
   Calendar tab (7-day forecast grid) within 10 seconds

## Schema

`workflow/calendars/entries.yaml`:

```yaml
schema_version: 1
entries:
  - id: weekly-team-report             # deterministic slug
    title: "Weekly Team Report"
    owner: your_username
    recipients:                         # ARRAY — one entry, many recipients
      - mandant: team
        person: lead
        channel: email
        address: "lead@example.com"
      - mandant: team
        person: manager
        channel: email
        address: "manager@example.com"
    action:
      type: wrapper                     # wrapper | skill | http | claude-prompt
      script: "~/scripts/weekly-report.sh"
      timeout_sec: 600
    delivery_at: "2026-04-14T09:00:00+02:00"
    duration_estimate_min: 15           # fire-loop starts 15 min early
    repeat:                             # optional
      spec: "Monday 09:00"             # human-readable
      rrule: "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"
    origin:
      source: manual                    # email | chat | manual
      snippet: "Weekly update to the team"
      parsed_at: "2026-04-09T14:00:00+02:00"
    status: queued                      # draft | queued | fired | failed | cancelled | done
    created_at: "2026-04-09T14:00:00+02:00"
    updated_at: "2026-04-09T14:00:00+02:00"
```

### Fields

| Field | Required | Description |
|---|---|---|
| `id` | yes | Deterministic slug: `slug(title)-YYYY-MM-DD-HHMM`. Must be unique. Re-parsing the same intent produces the same id (dedup on retry). |
| `title` | yes | Human-readable title for UI display |
| `owner` | yes | Who created/owns this entry |
| `recipients` | yes (min 1) | Array of `{ mandant, person, channel, address }`. References `identity/mandants/{mandant}.yaml` persons. |
| `action.type` | yes | `wrapper` (shell script), `skill` (Claude skill), `http` (webhook), `claude-prompt` (LLM-generated) |
| `action.script` | for wrapper | Shell script path to execute |
| `action.timeout_sec` | no | Max execution time (default 120s) |
| `delivery_at` | yes | ISO 8601 with timezone — when the user wants it delivered |
| `duration_estimate_min` | yes | How long generation takes. Fire-loop starts `delivery_at − duration` minutes early. 0 = fire exactly at delivery_at. |
| `repeat` | no | `spec` (human-readable) + optional `rrule` (machine-readable). Fire-loop advances `delivery_at` after each fire. |
| `origin.source` | yes | How the entry was created: `email` (intent-parser), `chat`, `manual` (user typed) |
| `origin.snippet` | yes | The natural-language phrase that triggered creation |
| `status` | yes | Lifecycle state (see below) |

### Status lifecycle

```
  [intent-parser]     [user confirms]     [fire-loop runs]
  ───── draft ──────── queued ──────────── fired ──→ (repeat? → queued)
                                              └───→ failed
         ├──── cancelled (user aborted)
         └──── done (non-repeating, successfully completed)
```

- **draft** — Parser created it, awaiting user confirmation. Fire-loop ignores drafts.
- **queued** — Active, fire-loop will execute when `effective_at` arrives.
- **fired** — Successfully executed. If `repeat` is set, fire-loop computes `next_occurrence` and resets to queued.
- **failed** — Execution failed (non-zero exit). Fire-loop retries on next tick.
- **cancelled** — User cancelled via `/calendar cancel {id}` or email reply.
- **done** — Non-repeating entry, successfully completed. Garbage-collected after 30 days.

### Duration-aware scheduling

The fire-loop computes `effective_at = delivery_at − duration_estimate_min × 60s`
on every tick. If a user says "I want the report at 17:00" and generation takes
15 minutes, the fire-loop starts the wrapper script at 16:45.

### Stable slot IDs

The bridge-deck collector emits jobs as `scheduled:calendar:${entry.id}:slot-${N}`.
Each poll tick overwrites the same slot in the daemon's store — no accumulation,
no orphan jobs. This is a critical invariant — re-emitting an entry updates
its job in place rather than creating a duplicate.

## Fire-loop

The fire-loop is an out-of-process Python script
(`bridge-deck/scripts/calendar-fire-loop.py`) that ships with the optional
[Bridge-Deck companion](bridge-deck.md) (**not yet public — coming
soon**), not with open-bridge. Once deployed, it runs every 5 minutes
via launchd and:

1. Reads `workflow/calendars/entries.yaml`
2. For each queued entry where `effective_at ≤ now + 5min`: executes the action
3. Updates `status`, `fire_history`, `last_fired_at`
4. Computes `next_occurrence` from RRULE for repeating entries
5. Writes back atomically (`.tmp` + `os.replace`)
6. Garbage-collects old entries (>30 days) to `calendar/archive/`

The fire-loop is **optional**. Without it, calendar entries are
data-only — skills (`/calendar`, `/briefing`) read them, but nothing
fires automatically. You can start with the data layer now and add the
fire-loop once Bridge-Deck is available.

## Intent-parser (planned)

A Haiku-based parser that reads incoming emails for scheduling intents
("a short note every 2 days at 17:40") and creates draft entries.
The user confirms via email reply. See the prompt template at
`bridge-deck/scripts/calendar-intent-parser-prompt.md` for the full
system-prompt and examples.

## CLI management

- `/calendar list` — show all entries by status
- `/calendar add` — interactive entry creation
- `/calendar show {id}` — full detail view
- `/calendar cancel {id}` — cancel an entry
- `/calendar confirm {id}` — activate a draft
- `/calendar status` — summary counts + next 3 upcoming

## Relationship to `/schedule`

`/schedule` manages the legacy `infra/channels/_scheduled.yaml` format (one cron
line per message, single recipient). `/calendar` manages the new
`workflow/calendars/entries.yaml` format (multi-recipient, duration-aware,
fire-history tracking, bridge-deck visualization). Both coexist.
New entries should use `/calendar`.
