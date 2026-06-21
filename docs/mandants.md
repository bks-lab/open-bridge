---
summary: "Mandants: named recipient groups for scheduled outbound, organized by relationship type (team, family, external colleagues)."
type: guide
last_updated: 2026-06-21
related:
  - docs/calendar.md
  - docs/personas.md
---

# Mandants — Recipient Groups

A mandant is a named group of people who receive scheduled messages.
Think of it as an addressbook organized by relationship type: your
company team, your family, friends, external colleagues, etc.

## Quick start

1. Enable in `bridge-config.yaml`:
   ```yaml
   mandants:
     enabled: true
   ```
2. Copy `identity/mandants/_template.yaml` to `identity/mandants/<id>.yaml` on your user branch
3. Fill in real contacts
4. If running bridge-deck, add `collector-mandants` to your config:
   ```yaml
   collectors:
     - package: "@bridge-deck/collector-mandants"
       options:
         mandantsPath: "~/Developer/<org>/<your-bridge>/mandants"
   ```
5. Your mandants appear on the Mandants tab (grouped by type with person
   detail panels) and inform the Calendar + Timeline views

## Schema

`identity/mandants/<id>.yaml`:

```yaml
schema_version: 1
id: team
type: company                          # see types below
display_name: "My Team"
context_ref: my-project                # optional link to contexts/<name>/
default_channel: email

persons:
  - id: lead
    display_name: "Team Lead"
    role: "Lead"
    channels:
      email: "lead@example.com"
      signal: "+49..."
    defaults:
      language: de
      timezone: Europe/Berlin
      detail_level: summary            # minimal | summary | full
      preferred_time_of_day: morning   # morning | midday | evening | night
      quiet_hours: [22, 7]             # no messages 22:00 → 07:00

notes: |
  Free-text notes. Useful for documenting distribution rules,
  contact protocols, or relationship context.
```

## Types

| Type | Icon | Use case |
|---|---|---|
| `company` | 🏢 | Business entity — your org, client companies, partner orgs |
| `household` | 👨‍👩‍👧 | People living in the same home |
| `family` | 👪 | Extended family — partner, siblings, parents, cousins |
| `friends` | 🤝 | Personal friends |
| `colleagues` | 💼 | External work contacts outside your core team |
| `individual` | 👤 | A single contact not in any group |

The bridge-deck Mandants tab groups mandants by type and shows the
appropriate icon. The Calendar tab uses the mandant as the row grouping
for the 7-day forecast grid.

## Multi-mandant membership

A single person can appear in multiple mandants — this is normal and
expected. Example:

- **Carol** exists as `team/carol` (developer, work email)
  AND as `family/carol` (sibling, iMessage)
- Calendar entries reference the specific context: `recipients: [{ mandant: team, person: carol }]` for work emails

The bridge-deck Mandants tab shows each person in every mandant they
belong to, with their role-appropriate context. The Calendar tab and
`/mandants show` resolve upcoming entries by checking ALL mandant/person
pairs the entry targets.

## Person defaults

The `defaults:` block on each person is a **hint for the intent-parser**
when creating new calendar entries. Example: if a person has
`quiet_hours: [22, 7]` and the parser receives "send them something
every evening", it chooses 20:00 instead of 23:00.

The fire-loop itself ignores defaults — it reads only the concrete
`delivery_at` + `duration_estimate_min` from the calendar entry.

## File conventions

- One file per mandant: `identity/mandants/<id>.yaml`
- Files prefixed with `_` are ignored by the collector (they're CORE templates)
- The collector reads the directory on every poll tick (10s) — add/remove
  files without restarting the daemon
- Empty mandants (0 persons) are shown in the Mandants tab with a
  "placeholder bucket" hint but hidden from the Calendar grid (no noise)

## CLI management

- `/mandants list` — overview of all mandants with person counts
- `/mandants add {id}` — create a new mandant interactively
- `/mandants show {id}` — full detail with persons + upcoming entries
- `/mandants add-person {mandant}/{person}` — add a person to an existing mandant

## Relationship to contexts

Mandants and contexts are **complementary, not redundant**:

| Concept | Purpose | Example |
|---|---|---|
| `contexts/<name>/` | Project bundle — which repos, skills, infra belong together | `contexts/customer-a/` = 3 repos + Azure + Elasticsearch |
| `identity/mandants/<id>.yaml` | Recipient group — who gets scheduled messages | `identity/mandants/team.yaml` = 5 people who get health reports |

A mandant can optionally link to a context via `context_ref: customer-a`.
This is metadata for the UI — it doesn't change behavior.

**Important:** Customers can be a context WITHOUT being a mandant.
"CustomerA" has a context (repos + infra) but no mandant entry because
CustomerA doesn't receive direct messages — their reports go to the
internal team mandant. Only add a mandant when someone in that group
actually receives scheduled output.
