# Work Log — Acme Dev (example)

> Append-only daily log. One row per substantive unit of work, the moment it lands:
> `| Time | Glyph | Context | What |`. The date comes from the `## {Weekday} DD.MM`
> header, so rows carry time only. Glyphs are the activity types from bridge-config.yaml
> (💻 dev · 🔬 analysis · 📋 planning · 📝 docs · 🔧 devops · 🐛 bug · 🧪 test · …).
> This is example data; see board.md for the matching task snapshot.

## Tue 24.06

<details open>
<summary>Worklog (4)</summary>

| Time  | Glyph | Context | What |
|-------|-------|---------|------|
| 09:02 | 📋 | acme | morning briefing — 3 in Doing, board reviewed; focus = ship the onboarding flow |
| 10:18 | 💻 | startupxyz | onboarding flow — wired the email-verification step, 6 tests green |
| 11:47 | 🐛 | bigcorp | payment webhooks failing in prod → opened bigcorp-api-payment-retry (incident, P1) |
| 14:30 | 📝 | bigcorp | logged the Stripe webhook-secret root cause + next steps in the task STATUS |

</details>

## Mon 23.06

<details>
<summary>Worklog (2)</summary>

| Time  | Glyph | Context | What |
|-------|-------|---------|------|
| 15:40 | 🔧 | platform | bumped CI runners and pinned deps (platform-maintenance stream) |
| 16:55 | 📋 | startupxyz | closed dark-mode-toggle → done; persisted via localStorage |

</details>
