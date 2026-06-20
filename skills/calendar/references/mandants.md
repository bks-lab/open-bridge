# /mandants — Mandant Management

Manage recipient groups (mandants) in `identity/mandants/*.yaml`. Each mandant is a
group of people who receive scheduled messages — a company team, a family,
a friend group, external colleagues, or an individual contact.

## Guard

`mandants.enabled` must be `true` in bridge-config.yaml. If not set, tell
the user how to enable it.

## Arguments

- `(none)` or `list` — show all mandants with person counts
- `add {id}` — create a new mandant interactively
- `show {id}` — detailed view with all persons + their upcoming calendar entries
- `add-person {mandant}/{person}` — add a person to an existing mandant

## Workflow: List

1. Read all `identity/mandants/*.yaml` (skip `_*.yaml` templates)
2. For each mandant show: id, type icon, display_name, person count
3. Render:

```
Mandants (4)
════════════
  🏢 company        Company (Internal Team)  5 persons
  👪 family         Example Family           4 persons
  🤝 friends        Friends                  0 persons (placeholder)
  💼 colleagues     Colleagues (external)    0 persons (placeholder)
```

Type icons:
  🏢 company   👨‍👩‍👧 household   👪 family   🤝 friends   💼 colleagues   👤 individual

## Workflow: Add

1. Ask: id (slug, e.g. `freunde`)
2. Ask: type — present the 6 options with icons
3. Ask: display_name
4. Ask: default_channel (email, telegram, signal, imessage, whatsapp)
5. Create `identity/mandants/{id}.yaml` with schema_version: 1, empty persons list
6. Optionally ask: "Add first person now?" → runs add-person flow
7. Confirm: "Mandant created. Add people with `/mandants add-person {id}/{person_id}`."

## Workflow: Show

1. Read `identity/mandants/{id}.yaml`
2. Read `workflow/calendars/entries.yaml` (if exists) to find all entries where
   any recipient matches this mandant
3. For each person show:
   - display_name, role, channels, defaults (language, timezone, detail_level, quiet_hours)
   - Upcoming calendar entries where they appear as recipient (title, delivery_at, status)
4. Render:

```
🏢 Company (Internal Team)
═══════════════════════════
  alice             Founder / Lead    email: alice@example.com
    📅 Hourly Task Digest            Thu 09.04 20:00  queued
    📅 Daily Health Report           Fri 10.04 06:30  queued
    📅 Weekly Newsletter             Sun 12.04 10:00  queued

  bob               Team              email: bob@example.com
    📅 Daily Health Report           Fri 10.04 06:30  queued

  carol             Developer         email: carol@example.com
    📅 Hourly Task Digest            Thu 09.04 20:00  queued

  ...
```

## Workflow: Add-Person

1. Parse `{mandant}/{person_id}` from argument
2. Read `identity/mandants/{mandant}.yaml`
3. Check person_id doesn't already exist
4. Ask: display_name
5. Ask: role (optional)
6. Ask: channels (at least one — e.g. `email: name@example.com`)
7. Ask: defaults — language, timezone, detail_level (all optional, sensible defaults)
8. Append person to `persons:` array in `identity/mandants/{mandant}.yaml`
9. Confirm: "Person added. They can now be referenced in calendar entries as `{mandant}/{person_id}`."

## Multi-Mandant Pattern

A person can exist in multiple mandants simultaneously:
- "Carol" in `company/carol` (developer, work email) AND `family/carol` (sibling, iMessage)
- Calendar entries reference the specific mandant/person context:
  `recipients: [{ mandant: company, person: carol }]` for work emails

This is intentional — it models the real world where the same human
has different roles in different contexts.

## Notes

- The `/mandants show` view mirrors what bridge-deck shows in the Mandants tab
- Changes to YAML files are picked up by bridge-deck within 10 seconds (one poll tick)
- The mandant schema supports `notes:` free text — use it for distribution rules or context
