<!--
Day-block template — one block per working day inside work/log.md.

The Task Management system creates a fresh day-block from this file at session
start when today has no block yet (see CLAUDE.md § Task Management and
rules/operations.md). Do NOT edit this template to log work — copy its body
into work/log.md under the current week.

Header MUST be `## {Weekday} DD.MM` (e.g. `## Mon 18.05`). The /archive and
/briefing skills parse exactly that pattern — no separators, no week suffix.
Replace {Weekday} and DD.MM with today's values (`date '+%a %d.%m'`).

The weekday token is locale-driven (`%a` → Mon on en, Mo on de, lun. on
fr) and purely cosmetic — /archive and /briefing match it as
`^## \S+ DD.MM` and derive any date/KW from DD.MM, never from the weekday
name.

ONE log row format, frozen: `| YYYY-MM-DD HH:MM | glyph | context | what |`.
Every row carries a full-ISO date+time via `date '+%Y-%m-%d %H:%M'`, so it
SELF-DATES — a stale or unarchived log is never ambiguous — never xx:xx or
placeholders. The `## {Weekday} DD.MM` header above stays a display anchor for
the parsers; do not add a year there. The legacy time-only `| HH:MM |` row is
retired; do not reintroduce it. Example row:
| 2026-05-18 14:32 | 🔧 | example | fixed inbound wedge, redeployed pre |

The current day ships `<details open>`; once it is no longer today, drop the
`open` so older blocks collapse.
-->

## {Weekday} DD.MM

<details open>
<summary>Worklog (0)</summary>

| Timestamp        | Glyph | Context | What |
|------------------|-------|---------|------|

</details>
