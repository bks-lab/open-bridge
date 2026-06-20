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

ONE log row format, frozen: `| HH:MM | glyph | context | what |`. The date
comes from the `## {Weekday} DD.MM` header above, so each row carries
TIME-ONLY via `date '+%H:%M'` — never xx:xx or placeholders. The legacy
`| YYYY-MM-DD HH:MM |` dated variant is retired; do not reintroduce it.
Example row:
| 14:32 | 🔧 | example | fixed inbound wedge, redeployed pre |

The current day ships `<details open>`; once it is no longer today, drop the
`open` so older blocks collapse.
-->

## {Weekday} DD.MM

<details open>
<summary>Worklog (0)</summary>

| Time  | Glyph | Context | What |
|-------|-------|---------|------|

</details>
