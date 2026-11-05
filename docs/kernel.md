---
summary: "The kernel of a Bridge: every file, command and listing a session reads before its first answer, where each lives and at which tier, when it is read, which file links it and who sees it. Recorded once in kernel/manifest.yaml and held to the tree by scripts/check-kernel.py; docs/ is tiered by folder like rules/."
type: reference
last_updated: 2026-11-05
related:
  - ../kernel/manifest.yaml
  - ../scripts/check-kernel.py
  - ../scripts/migrate-docs-tier.py
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
| `kernel/` | core, enumerated | The manifest. Only the files the router names ship (today `kernel/manifest.yaml`); any other file there stays user and `check-kernel.py` fails on it. Never an instance file. |
| `identity/agent/` | user | The instance's always-on slots `IDENTITY.md`, `SOUL.md`, `INSTANCE.md`, imported by `AGENTS.md`. |
| `context-budget.yaml` / `context-budget.user.yaml` | core / user | The caps on everything always-on, CORE's and the instance's. |
| `docs/` | core | Guides, read when named. Not kernel, with one known exception (below). |
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

It runs in `scripts/check-all.py`, in CI, in the check net of the daily
upstream update (`scripts/upstream-autoupdate.sh`), and in `bridge-audit`.

## Debts: what is known to be wrong

Some contradictions cannot be fixed in the same change that finds them. Such an
entry carries a `debt:` with a `kind` (`placement`, `unmeasured`,
`uninstructed`), a `reason` and an `until`. The checker prints every open debt on
every run instead of failing, and fails a debt whose contradiction is gone, so
the list can only shrink. `python3 scripts/check-kernel.py` shows the current
list; this page does not copy it, because a copy would drift.

## The road from here

1. **Now:** the manifest describes the kernel as it is, and `docs/` is tiered by
   folder. The family index `docs/families.md` is the one always-on file in a
   folder read when named; it carries a `placement` debt.
2. **Next:** the family index moves into `kernel/` as `kernel/families.yaml`
   (an `@`-line imports a YAML file as well as Markdown, and the bytes are the
   same), the family model follows it, the caps of `context-budget.yaml` fold
   into the manifest, and the Phase 0 and Phase 1 files get caps of their own.
3. **Then the instance side:** an instance's own families move from
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
--init` declares it there.

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
