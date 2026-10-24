---
summary: "File-based memory model — one fact per file, MEMORY.md as a lean index"
type: guide
last_updated: 2026-10-24
related:
  - ../rules/knowledge-growth.md
  - ../rules/operations.md
  - context-index.md
---

# Memory

The Bridge keeps a persistent, file-based memory base — the experience store that
survives across sessions. It is **not** a session log; it holds durable facts the
agent should recall later.

## Where memories come from

Two routes, both human-gated:

1. **In-session** — you or the agent notice a durable fact and save it.
2. **Distilled at archive time** — `/archive` Phase 5 reads the period's
   `work/log.md` rows before resetting them and proposes the few that carry
   lasting knowledge (a decision *and its why*, a costly diagnosis, a
   discovered constraint). Bookkeeping rows are dropped: git already records
   commits and PRs permanently.

Route 2 exists because `work/archive/` has **no reader** — no skill loads an
archived summary back into context. The memory base is the only layer that is
read every session, so distilling into it is what lets a short archive cadence
stay safe instead of amnesiac. Neither route writes without confirmation
(see [`../rules/learning-autonomy.md`](../rules/learning-autonomy.md)); a
deferred candidate becomes a `work/_learning/proposals/` entry with
`source.type: archive-distill` and `target.type: memory`, reviewed via
`/bridge-learn`.

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

The memory base is a **Bridge-owned family**: an index plus one fact per file
under `work/memory/`, read the same way on every harness. Two states exist,
and both are legitimate:

- **Default: inside the repo, at `work/memory/`.** Versioned like the rest of
  `work/`, and readable by any agent through
  [Reading it on any harness](#reading-it-on-any-harness) below. This is the
  model CORE documents and its tooling assumes.
- **Harness-managed, outside the repo.** A harness may keep its own memory in
  a tool-specific path instead. For Claude Code that is
  `~/.claude/projects/<project-hash>/memory/`, where `MEMORY.md` is the index
  and each `<type>_<slug>.md` is one fact. Other harnesses use their own
  location, or none.

`scripts/memory-location.py` resolves which of the two an instance uses, so no
reader has to reconstruct a path by hand. Its readers (`index`, `get`, `links`)
take `work/memory/` whenever that directory exists and no setting names another
one, so a fresh clone needs no setup to be read. Claude Code's `autoMemoryDirectory`
setting is an **optional per-instance convenience** that points the harness's
own auto memory at `work/memory/` (`python3 scripts/memory-location.py enable`
writes it as an absolute path into the gitignored `.claude/settings.local.json`,
see [Keeping memory inside the repo](#keeping-memory-inside-the-repo)).
`autoMemoryEnabled` stays as the harness ships it, or is turned off where an
instance wants no harness-side auto memory at all. Neither setting changes
what counts as a memory fact: the write-time gate in
[`../rules/knowledge-growth.md`](../rules/knowledge-growth.md) applies wherever
the directory lives.

A fresh clone, either way, therefore has **no memory base yet**: it is
created as you work (the first fact you save creates the directory and
index). An empty or missing memory base on a new clone is expected, not a
broken setup.

## Reading it on any harness

Codex, Gemini CLI, Cursor and Copilot read `AGENTS.md`, not a Claude Code
setting, so the memory base reaches them through Phase 1
([`../rules/operations.md`](../rules/operations.md)), the same split
[`context-index.md`](context-index.md) applies to `ecosystem.yaml`: the index
at session start, one fact when the work names it.

```bash
python3 scripts/memory-location.py index          # MEMORY.md of the resolved directory
python3 scripts/memory-location.py get <name>     # one fact, by file name or name: slug
```

Inside Claude Code with auto memory on, `index` prints a one-line note instead
of the file, because the harness has already loaded that same index; reading
it twice would only double its cost. With no index yet, it prints nothing.
Two cases print the file anyway: when the harness reads a different directory
(its legacy path, because `autoMemoryDirectory` is not set), and when the index
exceeds the load limit below, since the harness then loaded only its head. The
Claude Code test is the `CLAUDECODE` environment variable, which sub-agent and
`claude -p` shells carry too, so treat the note as a hint there.

**Sub-agents are the limit.** An ordinary sub-agent dispatch runs no Phase 1
and does not load the parent's auto memory either (Claude Code docs, Memory,
https://code.claude.com/docs/en/memory). A fact a sub-agent must know belongs
in an `@`-imported file, the same rule `AGENTS.md` states for every pointer
that must reach sub-agents. Two narrow exceptions exist and neither closes
this gap: a **forked** sub-agent inherits the parent's context including its
memory, and a sub-agent given its own `memory` field keeps a separate auto
memory directory of its own, never the parent's facts and never
`work/memory/`. Asked about a fact it cannot see, a sub-agent should say it
lacks access rather than guess.

## Keeping memory inside the repo

**Why:** a memory base under `work/memory/` is versioned (git history shows
who changed a fact and when), reviewable (a diff in a PR instead of an
invisible edit under `~/.claude`), revertable (`git checkout` undoes a bad
write the same way it undoes any other mistake), survives a repo move or a
re-clone on a new machine, and is checkable by the same tooling that already
reads the rest of the tree instead of only by the harness itself.

Readers find `work/memory/` without any setup. The steps below are for
Claude Code only, so that its **own** auto memory also reads and writes there
instead of in its legacy path.

**One-time setup:**

1. `python3 scripts/memory-location.py enable`: writes
   `{"autoMemoryDirectory": "<repo>/work/memory"}` into the gitignored
   `.claude/settings.local.json`, preserving every other key already in that
   file.
2. `python3 scripts/memory-location.py migrate`, right away: copies facts
   from the old (legacy) location into `work/memory/`, without touching or
   deleting the legacy copy. Run it before any session restarts, otherwise a
   fresh session writes a new `MEMORY.md` into the empty directory first and
   `migrate` reports that index as a conflict.
3. **Restart every running Claude Code session on this repo**, then run
   `migrate` once more. A session that was already running can keep writing
   to the old directory; the second run picks up what it wrote in between.
4. Once every session that predates step 1 has ended,
   `python3 scripts/memory-location.py stub-legacy --yes` replaces the legacy
   `MEMORY.md` with a short pointer to the new location, so a stray old
   session (or a human) never keeps reading a frozen, increasingly-stale
   index.

**Harness facts** (Claude Code; probed live with `claude -p`, or quoted from
https://code.claude.com/docs/en/memory):

- A **relative** `autoMemoryDirectory` value is silently ignored: the
  harness falls back to its default directory with no warning. The value
  must be absolute, or start with `~/`.
- The setting is keyed to the **git project**, not the working directory: one
  setting in the main checkout's `.claude/settings.local.json` also applies
  to every linked worktree and every subdirectory.
- When both `.claude/settings.local.json` and `.claude/settings.json` set it,
  the **local file wins**.
- `MEMORY.md` loads only its first **200 lines or 25 KB**, whichever comes
  first, regardless of where the directory lives.
- **Sub-agents do not load** the main session's auto memory, in either
  location.

**Privacy:** `work/memory/` is tracked **only on a private instance**. The shipped root
`.gitignore` ignores it for every clone, before anything has run in it. On a private origin,
`scripts/user-data.py arm` (run by `bin/setup` at every session start) writes `work/.gitignore`
with a negation (`!/memory/`), which re-allows it and tracks it with the rest of your commits;
a public or unknown origin gets no negation file, so it stays ignored. The pre-push content net
(`scripts/hooks/pre-push`) is the second guard regardless of tracking state: it blocks
`work/memory/` (and `work/.gitignore` itself) from reaching a public or unknown remote, the
same protection every other personal-data family under `work/` already gets. Confirm both are
in place before relying on them (`python3 scripts/user-data.py check`; the `memory/`
alternation in `scripts/hooks/pre-push`'s `USER_PATHS`).

**Trap:** on a clone whose origin is not private, `work/memory/` stays ignored by the shipped
`.gitignore`, and `git clean -x` (or `-fdx`) deletes it like any other ignored directory, with
no separate warning that you are about to delete your memory base rather than build artifacts.
Run `git clean -n` first, or exclude it explicitly (`git clean -fdx -e work/memory`). On a
private instance `work/memory/` is a tracked directory, so `git clean` never touches it
regardless.

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

## Retention

A fact may carry a **session link**: `originSessionId:` in its frontmatter
(Claude Code writes it) or a `<session-id>.jsonl` path in its body, as
[`../rules/knowledge-growth.md`](../rules/knowledge-growth.md) asks. That link
points into the harness's own transcript store, and the two stores live on
different clocks:

| What | Where | Lifespan |
|---|---|---|
| Session transcript | `~/.claude/projects/**/<session-id>.jsonl`, local plaintext | `cleanupPeriodDays`, **30 days** by default (Claude Code docs, Data usage, https://code.claude.com/docs/en/data-usage) |
| Memory fact citing it | the memory base | kept until you delete it; memory is not part of that cleanup |

So a session link is **only guaranteed to resolve inside the retention
window**, not for as long as the fact lives. It is still worth writing: for a
month it gives real traceability back to the conversation that produced the
fact. Past that, the fact has to stand on its own text.

Each instance records its choice as `work.transcript_retention_days` in
`bridge-config.yaml`, written at onboarding. Keeping the harness default counts
as a choice, as long as it is written down rather than silently inherited.
The value is a declaration, never the truth: `links` below reads the live
`cleanupPeriodDays` from the settings files and warns when the two disagree.

**Raising retention keeps more plaintext on disk.** Transcripts hold whatever
was pasted into a session, secrets included. An instance that raises
`cleanupPeriodDays` so links outlive the default should pair that with
encryption at rest for `~/.claude/projects/`; CORE does not raise the default
for you.

```bash
python3 scripts/memory-location.py links          # N of M facts carry a link, X of N unresolved
python3 scripts/memory-location.py links --json
```

It reads the local disk only, no network call, and exits 0: a dead link is a
count to watch, not an error.

## Coverage

A fact only works if a session can find it. The harness loads `MEMORY.md` and
nothing else, so a fact file that no index line names exists on disk and is
never recalled. It still costs: it shows up in searches, it can contradict a
live fact, and nobody notices it went stale.

A fact counts as **reachable** when `MEMORY.md` or `MEMORY-ARCHIVE.md` links
it (a `#section` anchor or a `"title"` after the target still counts), or when
a `[[wikilink]]` in a reachable file names its file stem or `name:` slug
(`|alias` and `#section` are ignored, and a stem wins over another fact's
slug). The walk is transitive: a fact the archive links can hand on to another
through a wikilink, and a wikilink from a fact nobody reaches reaches nothing.
Files whose stem has letters and all of them uppercase (`MEMORY.md`,
`MEMORY-ARCHIVE.md`, `README.md`, `PROVENANCE.md`) are about the memory base,
not facts in it, and are skipped. A memory base with facts but no `MEMORY.md`
reports every fact, since nothing loads them.

```bash
python3 scripts/memory-location.py check            # lint, plus a warning per unreachable fact
python3 scripts/memory-location.py check --strict   # the same, and exit 1 while any remain
```

By default an unreachable fact is a **warning**: the list and a count go to
stderr and the exit code stays whatever the index lint decides. A memory base
that grew for months before this check existed can carry dozens of orphans,
and turning that backlog into a failing exit at once would bury the index-lint
findings that matter more and break any script that already gates on `check`.
`--strict` is for an instance that has cleaned up and wants to stay clean.

**Cleaning up**, one orphan at a time, picks one of four homes:

- **Still true and worth recalling:** add an index line, or a `[[wikilink]]`
  from the fact it belongs next to.
- **Cold or closed:** an archive line in `MEMORY-ARCHIVE.md`, so a grep still
  finds it (never for a guardrail, see [Discipline](#discipline-prune-dont-accumulate)).
- **Routing or inventory** (which host, which board, which path): the fact
  belongs in the matching YAML under the cluster wrappers, where a skill reads
  it, per [`../rules/knowledge-growth.md`](../rules/knowledge-growth.md). Move
  it there, then delete the file.
- **Wrong, obsolete or a duplicate:** delete it.

## Enforcement

The ≤120-char index-line cap and the 200-line/25 KB load limit are checked by
`python3 scripts/memory-location.py check`, which `bridge-audit`'s memory pass
runs against whichever directory the memory base actually resolves to
(in-repo or legacy). The same `check` reports unreachable facts
([Coverage](#coverage)), and the audit turns that count into one finding. The
pass also runs `links` and reports the unresolved count (see
[Retention](#retention)). Treat the audit as the backstop, not a substitute for
keeping lines lean as you write them.
