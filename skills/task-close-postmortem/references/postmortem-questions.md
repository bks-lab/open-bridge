---
summary: "The six postmortem questions — exact phrasing in EN (DE optional), skip-handling, writes-to mapping."
type: reference
last_updated: 2026-05-13
---

# Postmortem Questions — EN

Locale-aware. Default `en`. Switch via `bridge-config.yaml.language.conversation`.
Skills MAY also surface localized variants (e.g. DE) per the same config key.

## Pre-flight

Surface a short header so the user knows what they're entering:

**EN:**
```
Postmortem (6 questions, all skippable). Keep it short or just skip.
```

Then ask the questions one at a time, waiting for each answer.

## Skip phrases

Default: `["skip", "next", "—", "no", "."]`
(from `bridge-config.yaml.learning.postmortem.skip_phrases`)

Treat any of these (case-insensitive, trimmed) as "skip this question".
Empty answer (just `<enter>`) also = skip.

## Cutdown mode

After **3 consecutive skips** (configurable via
`bridge-config.yaml.learning.postmortem.cutdown_after_skips`), switch to
**Cutdown mode** for the remaining questions:

```
EN: "Ok, dropping the rest. One last: anything worth flagging?"
```

If the user answers the Cutdown-mode question with free text → write it to
the body as a single bullet under "Concrete bridge improvements proposed".
If they skip Cutdown too → fully skip, no body section written at all.

## The six questions

### Q1 — Time invested

**EN:**
```
1. Roughly how much time? (e.g. "~4h", "3 days", "no idea — skip")
```

**Parse to `time_invested`:**
- "about 12h" → `"~12h"`
- "3 days" → `"P3D"`
- "4 hours" → `"PT4H"`
- "no idea" → `"unknown"`
- `—` / `skip` → omit field entirely

### Q2 — Estimate vs actual

**EN:**
```
2. Estimate vs reality? (ok / 1.5x / 2x / 3x / >3x / re-scoped)
```

**Parse to `estimate_vs_actual`:**
- "ok" / "in range" → `"ok"`
- "1.5x" / "one-and-a-half-times" → `"1.5x"`
- "twice as long" → `"2x"`
- "three times" / "3x" → `"3x"`
- "way more" → `">3x"`
- "scope changed" / "re-scoped" → `"re-scoped"`
- skip → omit

### Q3 — What went well

**EN:**
```
3. What went well? (1-N bullets or skip)
```

Free text. Split user answer into bullets at common separators (`,`, `;`,
`and`, newlines). Write to body `## Postmortem` → "What went well" subsection.

### Q4 — What burned time

**EN:**
```
4. What burned time / went wrong? (1-N bullets or skip)
```

Same parsing as Q3. Write to body → "What did not go well / burned time"
subsection. Bullets here are evidence-fodder for Q5/Q6 gap detection.

### Q5 — Bridge gap

**EN:**
```
5. Did the bridge fall short?
   (skill / standing-order / rule / doc / protocol / memory — or "nothing")
```

This question expects **structured** answers. Examples that should produce
structured `bridge_gaps[]` entries:

| User answer | Parsed entry |
|---|---|
| "yes — no skill that verifies research claims" | `{standing_order: "research-claim-verification", why: "research-claim-verification was missing"}` |
| "doc missing for customer-x routing" | `{doc: "customer-x-routing-guide", why: "doc missing for customer-x routing"}` |
| "skill customer-x-coordinator triggers too broadly" | `{skill: "customer-x-coordinator", why: "triggers too broadly"}` |
| "nothing" / "nope" / skip | omit `bridge_gaps[]` (don't write empty array) |

If the user types prose ("yes, something with research"), do a follow-up:
```
EN: "What kind? skill / standing-order / rule / doc / protocol / memory?"
```

After classification, ask if there are more gaps:
```
EN: "Another gap? [y/n]"
```

### Q6 — Concrete improvement

**EN:**
```
6. Concrete improvement suggestion for the bridge? (free text, optional)
```

Free text. Don't try to over-structure — the proposal-writing phase will do
the mapping. Just capture the answer verbatim into the body section
"Concrete bridge improvements proposed", one bullet per sentence.

## Post-flight

After Q6 (or earlier Cutdown), confirm what got captured:

**EN:**
```
Captured:
  Time: <time_invested or "—">
  Estimate: <estimate_vs_actual or "—">
  Lessons-good: <N bullets or "—">
  Lessons-bad: <N bullets or "—">
  Bridge gaps: <N or "—">
  Improvements: <N or "—">
```

Then proceed to the improvement-scan phase (see SKILL.md § Improvement-Scan).

## Anti-patterns (don't do these)

- ❌ Asking all 6 questions in one big block — buries answers.
- ❌ Re-asking after skip — respect the skip.
- ❌ Adding prompts like "are you sure?" after a skip — friction.
- ❌ Writing empty arrays/strings to frontmatter when skipped — omit the line.
- ❌ Re-interpreting the user's words "to be helpful" — record verbatim,
  only normalize obvious enum mappings.
