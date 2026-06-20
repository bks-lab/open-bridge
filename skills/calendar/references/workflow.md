# /calendar — Calendar Entry Management

Manage scheduled outbound actions in `workflow/calendars/entries.yaml`. Each entry
represents a timed delivery to one or more recipients (mandants/persons).
The optional Bridge-Deck companion (not yet public — coming soon)
visualises these on the Timeline, Calendar, and Mandants tabs and ships
the fire-loop (`bridge-deck/scripts/calendar-fire-loop.py`) that executes them at
the scheduled time. Without it, entries are data-only — skills read
them, nothing fires automatically.

## Guard

`calendar.enabled` must be `true` in bridge-config.yaml. If not set, tell
the user how to enable it.

## Arguments

- `(none)` or `list` — show all entries grouped by status
- `add` — interactive creation of a new calendar entry
- `show {id}` — full detail view of one entry
- `cancel {id}` — set status to cancelled
- `confirm {id}` — flip a draft entry to queued (after intent-parser created it)
- `status` — summary: queued / draft / fired / failed counts + next 3 upcoming

## Workflow: List

1. Read `workflow/calendars/entries.yaml` (if file missing, show empty + hint to create)
2. Group entries by status: queued → draft → fired → failed → cancelled → done
3. For each entry show: id, title, primary recipient (mandant/person), delivery_at, status
4. If recipients > 1, show `+N more`
5. Render:

```
Calendar Entries (6)
════════════════════
  queued
    ✓ customer-a-daily-health   → org/alice +1   Fri 10.04 06:30
    ✓ compliment-family-daily  → family/sam               Fri 10.04 08:00
    ✓ telegram-morning-digest  → org/alice       Fri 10.04 08:00
    ✓ org-hourly-task-digest   → org/alice +3   Thu 09.04 20:00
    ✓ customer-a-midday-report  → org/alice +1   Fri 10.04 12:30
    ✓ org-weekly-newsletter    → org/alice       Sun 12.04 10:00
  draft
    (none)
```

## Workflow: Add

1. Read `identity/mandants/*.yaml` to know available mandants + persons
2. Ask: title
3. Ask: recipients — suggest from known mandants, allow multiple (`org/alice, org/bob`)
4. Ask: when (natural language → parse to `delivery_at` ISO 8601 + optional `repeat.spec`)
5. Ask: action type — wrapper (provide script path), or claude-prompt (provide prompt text)
6. Ask: duration_estimate_min (default 5)
7. Generate entry with:
   - Deterministic `id` from `slug(title)-YYYY-MM-DD-HHMM`
   - `status: queued` (immediate, not draft)
   - `origin: { source: manual, snippet: "<user's description>", parsed_at: now }`
8. Append to `workflow/calendars/entries.yaml` (atomic write via temp file + rename)
9. Confirm: "Entry added. Next delivery: {delivery_at}." (If Bridge-Deck is running, the entry appears within one poll tick, ~10 s.)

## Workflow: Show

1. Find entry by id in `workflow/calendars/entries.yaml`
2. Print all fields: title, owner, all recipients with mandant/person/channel/address, action details, delivery_at, duration_estimate_min, effective_at (computed), repeat spec + rrule, origin with snippet + source, status, fire_history (last 5), created_at, updated_at
3. If status=draft, hint: "Run `/calendar confirm {id}` to activate."

## Workflow: Cancel

1. Find entry by id
2. Set `status: cancelled`, `updated_at: now`
3. Atomic write
4. Confirm

## Workflow: Confirm

1. Find entry by id
2. If status is not `draft`, warn and abort
3. Set `status: queued`, `origin.confirmed_by: <user>`, `origin.confirmed_at: now`, `updated_at: now`
4. Atomic write
5. Confirm: "Entry confirmed and queued." (If the Bridge-Deck fire-loop is deployed, it picks the entry up within 5 minutes.)

## Workflow: Status

1. Read `workflow/calendars/entries.yaml`
2. Count entries by status
3. Find next 3 entries by `delivery_at` where status=queued
4. Show summary:

```
Calendar Status
═══════════════
  6 queued · 0 draft · 0 fired · 0 failed
  Next up:
    Thu 09.04 20:00  Org Hourly Task Digest (4 recipients)
    Fri 10.04 06:30  CustomerA Daily Health Report (2 recipients)
    Fri 10.04 08:00  Compliment for Mom (1 recipient)
```

## Relationship to /schedule

`/schedule` manages the legacy `infra/channels/_scheduled.yaml` cron entries.
`/calendar` manages the new `workflow/calendars/entries.yaml` multi-recipient entries.
Both can coexist. Over time, entries should migrate from `/schedule` to
`/calendar` because the calendar format supports multi-recipient, duration-
aware scheduling, and — if you run the optional Bridge-Deck companion —
visualization.
