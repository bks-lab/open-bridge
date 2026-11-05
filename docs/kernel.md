---
summary: "The kernel of a Bridge: every file, command and listing a session reads before its first answer, where each lives and at which tier, when it is read, which file links it and who sees it. Recorded once in kernel/manifest.yaml and held to the tree by scripts/check-kernel.py; docs/ is tiered by folder like rules/."
type: reference
last_updated: 2026-11-05
related:
  - ../kernel/manifest.yaml
  - ../scripts/check-kernel.py
  - ../scripts/migrate-docs-tier.py
  - ../scripts/migrate-kernel.py
  - ../kernel/families.yaml
  - extension-model.md
  - context-index.md
  - data-model.md
  - updating.md
  - ../rules/knowledge-growth.md
  - ../context-budget.yaml
---

# The kernel

The kernel is what a session carries before it has done anything: the entry
file, what that file imports, what the harness injects, and what Phase 0 and
Phase 1 read. It is also the small set of files that define that surface. Every
piece of it costs context in every session, so every piece is written down once,
in one place, with four answers: **where** it lives, **when** it is read, **how**
it is linked, and **who** sees it.

That place is [`kernel/manifest.yaml`](../kernel/manifest.yaml).
[`scripts/check-kernel.py`](../scripts/check-kernel.py) holds each answer to the
source that actually decides it, so the manifest cannot drift into a wish list.

## What belongs to the kernel

Exactly two kinds of thing:

1. **Everything that reaches a session before its first answer.** The entry
   file (`AGENTS.md`), every file it imports with an `@`-line, the listings the
   harness injects, and the files and commands Phase 0
   ([`rules/session-start.md`](../rules/session-start.md)) and Phase 1
   ([`rules/operations.md`](../rules/operations.md)) read.
2. **The files that define that set**: the family model, the context budget,
   their schemas and the manifest itself. Only scripts read these.

A guide a route points at is not kernel. It is read when the work names its
subject, and that is what `docs/` is for.

## Where it lives: one place per tier

| Place | Tier | Holds |
|---|---|---|
| `AGENTS.md` at the root | core | The entry file. It stays at the root because every agent looks for it there. |
| `kernel/` | core, enumerated | The manifest and the family index `kernel/families.yaml`, which `AGENTS.md` imports. Only the files the router names ship; any other file there stays user and `check-kernel.py` fails on it. Never an instance file. |
| `identity/agent/` | user | The instance's always-on slots `IDENTITY.md`, `SOUL.md`, `INSTANCE.md`, imported by `AGENTS.md`. |
| `context-budget.yaml` / `context-budget.user.yaml` | core / user | The caps on everything always-on, CORE's and the instance's. |
| `docs/` | core | Guides, read when named. Not kernel. |
| `docs/user/`, `docs/org/`, `docs/personal/` | user, org, personal | Docs of those tiers. The folder is the tier. |

**The CORE/USER rule behind this table.** A CORE folder holds no instance file.
Where an instance must extend a CORE folder, the folder has a tier subfolder and
the **folder** decides: `rules/user/`, `protocols/standing-orders/user/`,
`docs/user/` (each with `org/` and `personal/` siblings where the tier exists).
A `scope:` line in such a file is a backstop that must agree with the folder;
it never moves a file between tiers by itself. The router is
`classify_file()` in [`scripts/categorize-commits.py`](../scripts/categorize-commits.py);
the full table of path rules is [extension-model.md § Scope model](extension-model.md#scope-model).

Until 2026-11-05 `docs/` had no tier folders. An instance doc therefore lay in
`docs/` beside the CORE guides with `scope: user`, and that one line was all
that kept it from the public upstream: a typo or a deleted line shipped it. A
doc outside the tier folders that declares another tier is still honoured, so
nothing leaks while a fork catches up, but `validate-bridge.py` now fails it and
names the fix ([updating.md](updating.md#once-docs-is-tiered-by-folder)).

## When it is read: six values

| `read` | When | Reaches | Linked by (`via`) | Checked against |
|---|---|---|---|---|
| `import` | before the first answer, by the harness | session and every sub-agent | the importing file's column-0 `@`-line, or `harness` for an entry file the tool finds by name | the `@`-line exists; `measure-context.py` sees the import |
| `harness` | before the first answer, injected without a file line (skill and agent listings, memory index) | session and every sub-agent | `harness` | `measure-context.py` counts it |
| `start` | Phase 0 or Phase 1 reads the file | the main session only | the file that instructs the read names the path | that file names it; `measure-context.py` counts it; its folder is not one the data model reads only when named |
| `command` | Phase 1 runs a command; its output is the context | the main session only | the file that instructs the run names the command | that file names it; `measure-context.py` counts it |
| `named` | when the work names the subject | whoever opens it | a route or link | not kernel; listed only when a kernel file must say where it went |
| `tool` | never by an agent at start; scripts read it | nobody's context | the script that reads it names the path | that script names it |

A sub-agent runs neither Phase 0 nor Phase 1. Anything it must see therefore
has to be an `import` or a `harness` listing; a pointer placed in a standing
order or the work log never reaches it (AGENTS.md § Standing Orders). The
manifest records this in `reaches`, and the checker refuses a `start` or
`command` entry that claims to reach a sub-agent.

## The manifest

One entry per file, glob, command or listing. The header of
[`kernel/manifest.yaml`](../kernel/manifest.yaml) repeats this table.

| Field | Meaning |
|---|---|
| `path` · `glob` · `command` · `harness` | exactly one: what is read. A glob matches segment by segment, so `a/*.md` never matches `a/b/x.md`. |
| `exclude` | a glob only: matching paths it does not mean (the CORE template `ecosystem.example.yaml`) |
| `tier` | `core`, `org`, `personal` or `user`, and for a path or glob match it must equal the router's answer. A file has exactly one tier, so an entry never mixes them: a glob that would span two tiers is two entries. Only a listing or a command's output, assembled from several tiers when the session starts, says `mixed`. |
| `role` | what it is, in a few words |
| `read` | one of the six values above |
| `via` | the file or files that link or instruct it, or `harness` |
| `reaches` | `session`, `subagent` |
| `optional` | true when a fresh clone does not have it (the identity slots, `work/board.md`) |
| `expect: absent` | the file must not exist (a legacy `CLAUDE.md` would shadow `AGENTS.md`) |
| `generated_by`, `source` | for a generated file: its generator and the input it renders |
| `debt` | a known contradiction: `kind`, `reason`, `until` (below) |
| `note` | one line on why, when the fields do not already say it |

Two lists sit beside `entries:`, for what a fork has to put right after an update:

| List | Each item | What happens |
|---|---|---|
| `retired:` | `file` (a path or a glob), `key`, `reason`, `fix` | a top-level key nothing reads any more but a session still carries (`work_system` in every `ecosystem*.yaml`); `check-kernel.py` names each non-core file that still has it, and an instance card in `context-budget.user.yaml` that still keeps it; `scripts/migrate-kernel.py --write` removes both. A CORE file (the template) is upstream's to change |
| `moved:` | `old`, `new` | a kernel path that moved (`docs/families.md` to `kernel/families.yaml`); `check-kernel.py` names an instance's own live file that still names the old path, `scripts/migrate-kernel.py --write` rewrites it, in `identity/agent/` and `work/memory/` too where git ignores them. CORE files come with the update, records of the past and code are never edited, and a file an org overlay ships is named so its source gets the same change |

## What check-kernel.py holds

- **where:** a required file exists, an `expect: absent` file does not, the
  router puts every path and glob match at the declared tier, a CORE checkout
  holds no instance file, and `kernel/` holds nothing the manifest omits
- **when:** every `@`-import and every item `measure-context.py` counts as
  always-on has an entry (or the instance caps it itself in
  `context-budget.user.yaml`); every always-on entry is counted; no `import` or
  `start` file lies in a folder `docs/data-model.yaml` marks `read: named`
- **how:** each `via` file exists and names what it links, an `@`-line for an
  import, the path, glob prefix or command for the rest
- **who:** imports and listings reach sub-agents, `start` and `command` reads
  never do
- **leftovers:** no file carries a `retired:` key, and no instance file of its
  own names a `moved:` path

It runs in `scripts/check-all.py`, in CI, in the check net of the daily
upstream update (`scripts/upstream-autoupdate.sh`). That job keeps a merge
that changed the checker or the manifest it reads and files what it finds, so a
retirement that only edits `retired:` or `moved:` reaches a fork as an inbox
item, never as a rollback.

## Debts: what is known to be wrong

Some contradictions cannot be fixed in the same change that finds them. Such an
entry carries a `debt:` with a `kind` (`placement`, `unmeasured`,
`uninstructed`), a `reason` and an `until`. The checker prints every open debt on
every run instead of failing, and fails a debt whose contradiction is gone, so
the list can only shrink. `python3 scripts/check-kernel.py` shows the current
list; this page does not copy it, because a copy would drift.

## The road from here

1. **Done (#633):** the manifest describes the kernel, and `docs/` is tiered by
   folder.
2. **Done (2026-11-05):** the family index lives in `kernel/` as
   `kernel/families.yaml`. An `@`-line imports YAML as text, the same as
   Markdown (checked with a fresh session); the file is about 440 bytes larger
   than the Markdown table because every entry repeats its keys, the price of a
   file readers and tests take as data. `rules/session-start.md` and
   `rules/operations.md` have caps. `work_system` in `ecosystem.yaml` is
   retired: nothing read it, the registry card showed it to every session, and
   the template claimed it switched the work system on.
3. **Next:** the family model (`docs/data-model.yaml`) follows the index into
   `kernel/`, and the caps of `context-budget.yaml` fold into the manifest, so
   one file says where, when, how and how much.
4. **Then the instance side:** an instance's own families move from
   `work/data-model.yaml` to `identity/agent/`, and their always-on index is
   generated like CORE's, never kept by hand.

## When you pull this into a fork

Nothing has to be done by hand unless your tree breaks a rule, and then you are
told. After the merge, `validate-bridge.py` fails every doc of yours that sits
in `docs/` with a non-core `scope:` line; the daily update job keeps the merge
and files an inbox item for it. One command moves the docs and rewrites the
links: [updating.md § Once: docs/ is tiered by folder](updating.md#once-docs-is-tiered-by-folder).
`check-kernel.py` names any always-on item of yours that neither the manifest
nor your `context-budget.user.yaml` declares; `python3 scripts/measure-context.py
--init` declares it there. It also names a retired key your `ecosystem.yaml`
still carries and any file of yours that still links a moved kernel path; one
command puts both right: [updating.md § Once: the family index moved to kernel/](updating.md#once-the-family-index-moved-to-kernel).

## Adding to the kernel

Rarely the right answer: [`rules/knowledge-growth.md`](../rules/knowledge-growth.md)
decides where knowledge goes, and most of it is read when named. When a new
file really must be read at start:

1. add its entry to `kernel/manifest.yaml`, with a `via` that names it,
2. give it a cap in `context-budget.yaml` (CORE) or `context-budget.user.yaml`
   (an instance),
3. run `python3 scripts/check-kernel.py` and `python3 scripts/measure-context.py`.

An instance never edits the manifest. Its own always-on text goes into
`identity/agent/INSTANCE.md`, which is already an entry.
