---
summary: "A lesson about one skill lands in that skill: an append-only LEARNINGS.md journal, a routing block in SKILL.md, and a curator pass that promotes matured entries into references/"
type: guide
last_updated: 2026-09-24
related:
  - ../rules/knowledge-growth.md
  - ../rules/learning-autonomy.md
  - ../skills/bridge-curator/references/learnings-pass.md
  - memory.md
---

# Skill learnings

When work surfaces a lesson about **one specific skill** (a trap, a convention,
a worked example, a wrong assumption that cost time), it belongs in that skill.
Global memory is detached from the skill: the next run of the skill does not
read it, and a sub-agent running the skill never sees it. A `/bridge-learn`
proposal is right for a reviewed change to the skill's specification, and too
heavy for "note this before it is forgotten".

**Tier: the journal is USER, always.** It holds this instance's lessons, even
inside a `scope: core` skill folder, so it never promotes or syncs upstream
(`scripts/categorize-commits.py` and the pre-push guard both treat
`skills/*/LEARNINGS.md` as USER; the provenance record lives under
`work/_learning/provenance/`, USER by folder). A lesson reaches other
instances only by maturing into `references/`, which ships with the skill's
tier.

**Moving an old provenance record.** Earlier versions wrote the record to
`skills/<skill>/references/provenance.md`. An instance that still has one
moves it with `git mv skills/<skill>/references/provenance.md
work/_learning/provenance/<skill>.md`; the lines keep their format. Until then
`learning-ledger.py record` warns and `check --provenance` reports the file
with its new path.

The convention is **opt-in per skill.** A skill without a journal is not in
violation. A convention that sits empty in a hundred places is worse than none.

## Two tiers, on purpose

| Tier | File | Bar | Written by |
|---|---|---|---|
| Journal | `skills/<name>/LEARNINGS.md` | Low: dated, unfiltered, may turn out wrong or one-off | The session that learned it, when the user names the lesson |
| Specification | `skills/<name>/references/*.md` | High: curated, what the skill routes to | `/bridge-learn` accept of a curator proposal |

A low bar at capture and a high bar at spec time is the point. Every lesson
going straight into `references/` means most lessons are never written down; a
flat journal with no promotion step turns into a log nobody reads before acting.

The journal is **not a behaviour contract.** It is never loaded when the skill
runs; the routing block points at it, so a reader opens it when the step at hand
is the one it covers. That is why a journal entry needs no proposal
([`rules/learning-autonomy.md`](../rules/learning-autonomy.md) § Layer B), and
why promoting one into `references/` does.

## Which lesson goes where

Decide by who needs it next. One destination, never a broadcast to three:

- **The next run of this one skill** needs it → `LEARNINGS.md`.
- **Every session**, whatever it runs, needs it, or it is a fact about the
  world rather than about a skill → memory
  ([`memory.md`](memory.md)).
- **A change to how a skill, rule or standing order behaves**, or anything
  touching more than one skill → a `/bridge-learn` proposal.

The same decision is stated in
[`rules/knowledge-growth.md`](../rules/knowledge-growth.md) § A lesson about one
skill.

## Templates

**Journal**, `skills/<name>/LEARNINGS.md`, created with the first entry:

```markdown
# Learnings: <skill name>

Append-only journal of lessons about this skill. Not loaded when the skill
runs; SKILL.md § Where lessons go points here. Matured entries move into
references/ via `/bridge-curator --pass learnings <skill>`.

## YYYY-MM-DD: <the lesson in one line>
What: <what happened, the command or step, the symptom>
Why it matters: <what goes wrong for the next run that does not know this>
```

Every entry heading is `## YYYY-MM-DD: <lesson>`. The date lets the curator tell
a fresh entry from one that has held up.

**Routing block**, appended to the end of `SKILL.md` in the same change:

```markdown
## Where lessons go
<!-- lessons-routing -->
- A trap, convention or example of this skill, not yet proven: append to
  [`LEARNINGS.md`](LEARNINGS.md), dated.
- A lesson that has held up: the matching `references/*.md`, promoted by
  `/bridge-curator --pass learnings <this skill>`, accepted in `/bridge-learn`.
- Which accepted proposal put a rule here: `work/_learning/provenance/<this skill>.md`
  (written by `scripts/learning-ledger.py`).
- Anything beyond this skill: memory for a fact, a `/bridge-learn` proposal for
  a behaviour change.
```

The `<!-- lessons-routing -->` marker is what the check looks for.

## Keeping the pair honest

`python3 scripts/check-skill-learnings.py` fails when a skill has a journal but
no routing block, a routing block but no journal, or a journal heading without
its date. CI runs it, and `bridge-audit` reports it as a check of its own.

## Promotion

`/bridge-curator --pass learnings <skill>` reads one skill's journal and the
global memory base
([`../skills/bridge-curator/references/learnings-pass.md`](../skills/bridge-curator/references/learnings-pass.md)):

1. Journal entries that have held up become proposals targeting the fitting
   `references/*.md`. On accept, the entry is trimmed from the journal.
2. Global memory facts that name this skill become proposals to move them into
   its journal. The memory fact stays until that proposal is accepted.

Entries that never mature stay in the journal or get dropped. Promotion is a
judgement call and never automatic.
