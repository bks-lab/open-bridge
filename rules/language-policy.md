---
scope: core
description: CORE content is authored in English (open-bridge is the international OSS upstream); runtime/output language is a separate per-fork axis; parsers are language-agnostic; CORE is never translated at promote
---
# Language Policy — CORE is English

open-bridge is the canonical English upstream that every fork inherits.
"English-only CORE" and "the orchestrator speaks German to a German user"
are not in tension — they live on different axes. This file is the source
of truth for which axis is which, and how a fork plugs in its own language
without ever editing a CORE file.

## 1. Three independent axes

Three things that all sound like "language" but never couple:

- **(A) AUTHORING** — the language CORE files are *written* in. Always
  English. Every `scope: core` file (rules, docs, skills, agents,
  scripts, templates, schemas, built-in English themes) is English from
  the first keystroke.
- **(B) OUTPUT** — what the orchestrator *speaks/writes for the user*.
  Per fork, via the box's locale plus `bridge-config.yaml`
  `language.conversation` / `language.artifacts`. A German user gets
  German conversation while every CORE file stays English. The output
  rule is [`rules/session-start.md`](session-start.md) ("Mirror the
  user's message language. German in → German out").
- **(C) DATE-DISPLAY** — weekday/month tokens in rendered output. Driven
  by the OS locale (`LC_TIME` / `LANG`) through `date '+%a'` and
  `strftime`. `date '+%a'` yields `Mon` on en, `Mo` on de, `lun.` on fr.

The three never depend on each other: authoring is fixed English, output
is per-fork config, date-display is OS locale. Changing one does not
touch the others.

## 2. What MUST be English (CORE)

Everything in the `core` tier:

- `rules/*.md` (top-level only — **not** `rules/org/**` or `rules/user/**`)
- `docs/**` and `docs/examples/**`
- `protocols/*.md` and CORE standing orders (`protocols/standing-orders/*.md`)
- `trackers/*.md`
- `scripts/**` — both comments and any help/UI strings
- `scope: core` skills (SKILL.md + `references/**`) and `scope: core`
  agents, including the frontmatter `description`
- `themes/_schema.yaml` and the built-in English theme (`professional`)
- all CORE templates, schemas, and placeholders — the weekday placeholder
  is `{Weekday}`, never `{WOCHENTAG}` or `{WEEKDAY}`

## 3. What may be in the author's language

- **USER tier** (never promoted): `rules/user/**`, `work/**`, `identity/`
  instances, `scope: user` skills/agents, `bridge-config.yaml`.
- **ORG tier**: `rules/org/**`, `scope: org` skills/agents.
- **Locale themes**: `professional-de.yaml` and any other locale theme.
  Their non-English *vocabulary values* are the entire point; the theme's
  structural keys and comments stay English.

## 4. Parsers are language-agnostic

The load-bearing section. The day-block header is `## {Weekday} DD.MM`,
produced by `date '+%a %d.%m'` (locale-driven). Two hard rules:

- **RULE 1 — every header PARSER accepts ANY weekday token.** Use
  `^## \S+ [0-9]{2}\.[0-9]{2}([^0-9.]|$)`, never a fixed weekday
  alternation. `\S+` (not `\w+`) is required for the French `lun.`
  trailing dot and accented tokens; the `([^0-9.]|$)` boundary rejects
  the forbidden long forms (`## Monday 14.04.2026`, `## 2026-04-14`).
- **RULE 2 — derive date/KW from the DD.MM digits, never the weekday
  name.** The weekday name is display-only.

The two real day-block parsers in CORE:

- [`skills/archive/references/workflow.md`](../skills/archive/references/workflow.md)
- [`skills/briefing/references/workflow.md`](../skills/briefing/references/workflow.md)

## 5. Locale-driven output (no i18n tables)

These sites *emit* locale-formatted dates — they are output, not parsers.
Do NOT add weekday/month translation tables to them:

- `work/templates/day.md` (`date '+%a %d.%m'`)
- `scripts/bridge-dashboard.py` strftime (`%a`) at the daily-render sites
- `skills/bridge-greeting/scripts/render-motd.sh` (`strftime %b` + the
  English literal `at`)

Themes carry zero date strings — that invariant keeps date-display purely
locale-driven and out of the vocabulary layer.

## 6. Plug in your language (forks)

A fork localizes by configuration and overlay, never by editing CORE:

1. Set `bridge-config.yaml` `language.conversation` / `language.artifacts`
   on the `user/*` branch — drives OUTPUT (axis B).
2. Set the box's OS locale (`LC_TIME`) — drives DATE-DISPLAY (axis C).
3. Optionally add a custom theme `extends: professional` for translated
   vocabulary — see [`CONTRIBUTING.md`](../CONTRIBUTING.md) (Themes).

NEVER edit a CORE file to translate it. Localization lives in config plus
a theme overlay, so `git merge upstream/main` stays conflict-free. Per-
language CORE files and hand-maintained weekday/month tables are
explicitly rejected — they would fork CORE and break the merge.

## 7. CORE is never translated at promote

open-bridge *is* the English upstream — there is nothing to translate when
you author here. A downstream fork that contributes CORE upward must
arrive in English (translate before it lands; open-bridge itself never
translates incoming CORE). `CLAUDE.md` and `README.md` are the only
diverged CORE files between tiers — merge them via
`git format-patch | git am --3way`, not a blind checkout.

## 8. See also

- [`rules/operations.md`](operations.md) — scope routing; language is
  the parallel tier rule
- [`rules/theme.md`](theme.md) — locale themes and resolution
- [`rules/session-start.md`](session-start.md) — the OUTPUT-axis greeting
  rule ("mirror the user's message language")
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — Themes (custom locale theme
  authoring)
- [`rules/knowledge-growth.md`](knowledge-growth.md) — where new knowledge
  belongs
