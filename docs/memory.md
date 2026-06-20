---
summary: "File-based memory model — one fact per file, MEMORY.md as a lean index"
type: guide
last_updated: 2026-06-19
related:
  - knowledge-growth.md
  - ../rules/knowledge-growth.md
---

# Memory

The Bridge keeps a persistent, file-based memory base — the experience store that
survives across sessions. It is **not** a session log; it holds durable facts the
agent should recall later.

## Model

- **One fact = one file.** Each memory is a single Markdown file
  `<type>_<underscore_slug>.md` in the memory directory, with frontmatter
  (`name:` = kebab slug, `description:` = one-line summary used for recall,
  `metadata.type`).
- **`MEMORY.md` is the INDEX, not the store.** It is loaded into context at the
  start of every session, so it must stay small. One line per memory, grouped by
  section. **Never put fact content directly in `MEMORY.md`** — only a pointer.
- **`[[wikilink]]`** links memory-to-memory and resolves to the other memory's
  `name:` slug. Cross-system references (config YAML, skill dirs, a wiki) use
  plain backtick paths, not `[[ ]]`.

## Filesystem location

The memory base typically lives **outside the repo**, in a tool-specific path —
it is not committed alongside the Bridge files. For Claude Code it sits under
`~/.claude/projects/<project-hash>/memory/`, where `MEMORY.md` is the index and
each `<type>_<slug>.md` is one fact. Other harnesses use their own location.

A fresh clone therefore has **no memory base yet** — it is created as you work
(the first fact you save creates the directory and index). An empty or missing
memory base on a new clone is expected, not a broken setup.

## Index-line contract (load-bearing)

Every index entry is exactly:

```
- [Title](type_slug.md) — <one hook saying WHEN to reach for it>
```

- **Hook ≤ 120 characters.** The hook is a *recall trigger*, not a summary — it
  must carry the distinguishing symptom/keyword that makes the agent open the
  fact file (e.g. a precise error phrase), never just a restated title.
- Detail (repro steps, commands, exception strings, incident dates) lives in the
  fact file, never in the index line. If the index line is richer than its fact
  file, move the surplus **into the fact file first**, then trim the index.
- A lean index is the whole point: an oversized `MEMORY.md` overflows its
  context budget and silently drops its tail — the facts then exist on disk but
  become unreachable at session start.

## Memory types

| Type | Holds |
|------|-------|
| `user` | Who the user is — role, expertise, durable preferences |
| `feedback` | How the agent should work — corrections and confirmed approaches; include the *why* and *how to apply* |
| `project` | Ongoing work, goals, constraints not derivable from code or git history; convert relative dates to absolute |
| `reference` | Pointers to external resources (URLs, dashboards, tickets) |

## Discipline (prune, don't accumulate)

- **Write when:** a mistake cost time, a non-obvious workaround was found, the
  user corrected you, a new tool/endpoint/pattern appeared, or a decision was
  made (record the *why*).
- **Don't write when:** it is already in `CLAUDE.md`/`AGENTS.md`, it is general
  knowledge, or it is one-off session-specific state (current branch, current bug).
- Before saving, check whether an existing file already covers the fact — update
  it instead of duplicating. **Delete** memories that turn out to be wrong or
  obsolete rather than letting them accumulate.
- Cold or closed facts can move to a sibling archive index
  (`MEMORY-ARCHIVE.md`), keeping `MEMORY.md` to hot recall — but a behavioural
  **guardrail** (a never-/always-/only-on-explicit-OK rule) is never "cold": it
  fires rarely *by design*, so it stays in the live index regardless of age.

## Enforcement

The ≤120-char index-line cap is checked by the `bridge-audit` memory pass (the
memory base typically lives outside the repo, so a pre-commit/CI hook cannot see
it). Treat the audit as the backstop, not a substitute for keeping lines lean as
you write them.
