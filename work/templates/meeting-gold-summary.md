<!--
  Gold-standard meeting protocol — template for /debrief (customer call + optional internal follow-up).
  Section order is FIXED: Contents → Short Summary → Detailed Summary → Facts → Recommended Tasks → Sources.

  Evidence: EVERY claim carries a one-click link into the CO-LOCATED, anchored transcript:
      [↪ Speaker +mm:ss](transcript-call.md#c-NNN)
  Anchors + relative timestamps are produced by the tool:
      python skills/debrief/scripts/anchor_transcript.py <home>/transcript-call.md <home>/transcript-internal.md --prefix c i
  The anchor IDs (c-NNN / i-NNN) live in the sidecar <transcript>.index.tsv — look up the
  statement there and take over ID + relative time + speaker.

  Transcripts sit CO-LOCATED in the same folder:
      transcript-call.md      = customer call
      transcript-internal.md  = internal follow-up (optional)
  Raw audio stays in the external archive (the record: frontmatter points to it).
  Interpretation = in-session (hard rule); anchoring = mechanical bridge-side transform
  (the worker's merge step stays untouched).
-->
> ⚠️ Context-aware generated summary. **Every fact is backed by the exact quote, one click away** —
> the `↪` links jump into the co-located, anchored transcript at the precise statement.

---
type: meeting-summary
date: {{YYYY-MM-DD}}
title: "{{Title}}"
participants: [{{names}}]
context: {{ctx}}
scope: {{core|org|user}}
record:
  call:                              # customer call
    audio:      "{{archive path .mp3}}"
    transcript: "{{archive path .md}}"
    local:      ./transcript-call.md
  internal:                          # optional — only if a follow-up exists
    audio:      "{{archive path .mp3}}"
    transcript: "{{archive path .md}}"
    local:      ./transcript-internal.md
wiki: { status: pending }            # → done + url, once mirrored to a knowledge repo (optional)
tasks: { status: pending }           # /briefing surfaces open items from this flag
related: []
---

# {{Title}} — {{YYYY-MM-DD}}

**Participants:** {{...}}
**Referenced, not present:** {{...}}

## Contents
1. [Short Summary](#short-summary)
2. [Detailed Summary](#detailed-summary)
3. [Facts](#facts)
4. [Recommended Tasks](#recommended-tasks)
5. [Sources](#sources)

## Short Summary
{{3–5 sentences, the essentials. Load-bearing statements carry a one-click evidence link.}}

## Detailed Summary
{{Prose, structured by topic/thread. EVERY claim with evidence:
   … statement [↪ Speaker +mm:ss](transcript-call.md#c-NNN). }}

## Facts

| # | Fact / Decision | Evidence |
|---|-----------------|----------|
| F1 | {{fact}} | [↪ {{Speaker +mm:ss}}](transcript-call.md#c-NNN) |

## Recommended Tasks

> The **Issue/Task** column is filled when the task is created via `github-projects-manager` (bidirectional: protocol ↔ issue).

| # | Recommended Task | Owner | Evidence | Issue/Task |
|---|------------------|-------|----------|------------|
| T1 | {{task}} | {{owner}} | [↪](transcript-call.md#c-NNN) | — |

## Sources
- **Transcripts (co-located, anchored):** [`transcript-call.md`](./transcript-call.md) · [`transcript-internal.md`](./transcript-internal.md)
- **Raw audio (external archive, backed up):** {{paths}}
- **Knowledge-repo protocol:** {{url, once mirrored (optional)}}
- **Tracking:** {{work/tasks/<slug>/ …}}
