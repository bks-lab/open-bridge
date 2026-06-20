<!--
Week-skeleton template — the fresh-week scaffold for work/log.md.

Used in two places: bridge-onboard writes it at setup (first week + first
day-block), and /archive Phase 5 writes it when it resets log.md after
archiving the old week. Do NOT edit this template to log work — copy its
body into work/log.md and replace the placeholders.

Week header is `# Week {CW} — {DATE_FROM} to {DATE_TO}` — the /archive and
/briefing skills parse the week number via `(KW|Week) {N}`. Mirrors the
form of work/templates/week-summary.md.

Day-block header is `## {Weekday} DD.MM`, produced LOCALE-DRIVEN via
`date '+%a %d.%m'` (Mon on en, Mo on de, lun. on fr). The weekday name is
purely cosmetic — parsers and all KW/date math read DD.MM, never the
weekday name (see rules/language-policy.md). The day-block body below is
byte-identical to work/templates/day.md.

Each Worklog row uses the ONE frozen format `| HH:MM | glyph | context | what |`
— TIME-ONLY via `date '+%H:%M'` (the date comes from the day-block header). The
legacy `| YYYY-MM-DD HH:MM |` dated variant is retired.

Replace every {placeholder}: {CW}, {DATE_FROM}, {DATE_TO}, the Active
Focus areas, and today's day-block header (`date '+%a %d.%m'`).
-->

# Week {CW} — {DATE_FROM} to {DATE_TO}

**Active Focus:** {2-4 focus areas for the week, joined with ` · `}

## {Weekday} DD.MM

<details open>
<summary>Worklog (0)</summary>

| Time  | Glyph | Context | What |
|-------|-------|---------|------|

</details>
