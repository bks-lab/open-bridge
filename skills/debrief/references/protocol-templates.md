# Protocol Templates — Depth-Based Output

Select template based on classification depth from `references/classification.md`.

## Full Protocol

For team weeklies, customer weeklies, important meetings:
- YAML frontmatter (date, type, participants, duration)
- Topic table with owner and status
- Action items table (who, what, deadline)
- Next meeting date

```yaml
---
type: meeting-protocol
meeting_type: {classified_type}
date: {YYYY-MM-DD}
participants: [{names}]
duration_minutes: {N}
---
```

## Workshop Protocol (deep processing)

For workshops with actionable output:
- Standard protocol PLUS:
- **Goals & Tasks document**: identified goals with success criteria
- **Phase-structured tasks**: Phase 0 (prep), Phase 1 (impl), Phase 2 (operate)
- **Constraints table**
- **Business Model Canvas** (if discussed)
- **GitHub Issues** proposed per task (see Phase 6 in SKILL.md)

### Workshop Field Mapping (for GitHub Issues)

| Phase | Priority | Stage |
|-------|----------|-------|
| Phase 0 (prep) | High | Planning |
| Phase 1 (impl) | Medium | Planning |
| Phase 2 (operate) | Low | Planning |

## Standard Protocol

For regular internal meetings:
- YAML frontmatter
- Summary (3-5 key points)
- Action items list

## Minimal Protocol

For short syncs (< 15 min):
- YAML frontmatter
- 3-5 bullet points

## Protocol Path — Wiki First, Bridge Archive Second

**Rule (hard):** the formal protocol lives in the **shared knowledge
base / wiki repo**, not in `work/archive/days/`. The Bridge-side
`{DD}_insights.md` is a *companion* that captures Whisper-corrections,
reconciliation steps, and proposed tasks — never a replacement.

If you don't operate a separate knowledge repo, the destination is still
inside this Bridge — but in a dedicated `knowledge/` or `docs/protocols/`
tree, not in `work/archive/days/`. The point is: **protocols live where
people read them next week**, archives live where transcripts age.

### Routing table

| Meeting type | Protocol path (shared wiki / knowledge repo) |
|---|---|
| **Team weekly (internal)** | `wiki/<your-org>/protocols/weekly-meetings/{YYYY-MM-DD}-{weekly-slug}.md` |
| **Internal sync** (no external participants) | `wiki/<your-org>/protocols/{YYYY-MM-DD}-{slug}.md` |
| **Strategy meeting** (long-form session) | `wiki/<your-org>/protocols/strategy-meetings/{YYYY-MM-DD}-{slug}.md` |
| **Decision** (single-decision capture) | `wiki/<your-org>/protocols/decisions/{YYYY-MM-DD}-{slug}.md` |
| **Customer touchpoint** (call / workshop / agreement) | `wiki/customers/{customer}/protocols/meetings/{YYYY-MM-DD}-{slug}.md` |
| **Customer touchpoint, project-scoped** | `wiki/customers/{customer}/projects/{project}/protocols/meetings/{YYYY-MM-DD}-{slug}.md` |
| **Customer touchpoint, internal-prep slice** | `wiki/customers/{customer}/projects/{project}/documentation/{YYYY-MM-DD}-{slug}.md` |
| **Lead / sales-interview** | `wiki/leads/{slug}/meetings/{YYYY-MM-DD}_{HHMM}_{name}.md` |

Adapt the `wiki/` root to whatever your knowledge repo is mounted at
(e.g. `docs/`, `knowledge/`, or a sibling repo path). The structural
distinction — internal protocols vs customer-namespaced vs lead-namespaced
— is the substance; the literal `wiki/` prefix is just convention.

**Cross-cutting meeting** (e.g. a weekly that touches multiple customers):
write the **full protocol** at the team-weekly path; write a **slice
document** for each customer at the customer-touchpoint path (linking
back to the full protocol). MOC update in both locations.

### MOC updates (mandatory)

After writing the protocol, bump:
- For team-weeklies → `wiki/<your-org>/protocols/weekly-meetings/_MOC.md`
  (or the index next to the protocol category).
- For customer touchpoints → `wiki/customers/{customer}/_MOC.md`
  *and* `wiki/customers/{customer}/projects/{project}/_MOC.md` if project-scoped.
- Bump `last_updated:` frontmatter in the touched MOC files.

### Bridge-side companion (always)

In addition to the wiki protocol, write the per-meeting insights block at
`work/archive/days/{YYYY-MM}/{DD}_insights.md` (or
`{DD}_{HHMM}_{slug}-insights.md` for prominent stand-alone meetings).
This file is private to the Bridge instance, contains:
- name_corrections list (Whisper artifacts)
- ambiguous_terms_flagged list
- reconciliation notes (which active task each item ties into)
- proposed tasks (decision pending)

### Transcript / audio archive

Independent of protocol routing, raw transcript + audio move to
`work/archive/days/{YYYY-MM}/{DD}_{HHMM}_{slug}.{txt,_Voice_Chat.mp3}`.
Customer-specific transcripts can override the default (e.g. routed into
a per-customer Bridge instance or a sibling repo).

### Why "wiki first, archive second"

The archive path stores **what was said**; the wiki path stores **what
was decided + what's tracked**. People look up the wiki entry next sprint;
nobody re-reads the raw transcript. If the formal protocol only exists
in `work/archive/days/`, it's effectively invisible to anyone but the
person who debriefed the meeting.
