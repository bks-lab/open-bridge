---
scope: core
description: "Suggest contributions when new CORE-eligible files are created on user branches"
---

# Contribute Advisor — Proactive Detection

When on a user/ branch, watch for new files in CORE-eligible paths.

## Trigger conditions

Suggest /contribute when:
- User creates a new standing order in protocols/standing-orders/ (not _template.md)
- User creates a new theme in themes/
- User creates a new agent preset directory
- User significantly improves a CORE template (>20 lines changed)

## Suggestion format

At the end of a work block (not mid-task):
```
protocols/standing-orders/health-check.md looks like it could benefit other Bridge users.
[c] /contribute protocols/standing-orders/health-check.md  [n] Not now
```

## Do NOT suggest when

- File is clearly work-in-progress (<20 lines)
- User said "no" for this file (remember per session)
- File contains obvious personal data
- User is mid-incident or mid-task
- Within 10 minutes of the last suggestion
