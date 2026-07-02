---
summary: "scripts/okf-export.py — exports a Bridge instance's knowledge surfaces (work/, docs/, rules/, examples/) as a static Open Knowledge Format (OKF) v0.1 bundle, with a scope flag that gates what a public export may contain."
type: guide
last_updated: 2026-07-02
related:
  - ../scripts/okf-export.py
  - ../scripts/extract-frontmatter.py
  - ../scripts/gen-board.py
  - extension-model.md
  - memory.md
---

# OKF Export

`scripts/okf-export.py` walks a Bridge instance's knowledge surfaces and emits
a static [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
(OKF) v0.1 bundle — one markdown file per *concept*, a per-type `index.md`,
and a root `index.md` declaring the bundle's `okf_version`. It is read-only
against the source repo: nothing under `work/`, `docs/`, `rules/`, or
`examples/` is ever rewritten. The bundle is a **derived artifact**, disposable
and regenerable on every run.

## Why an exporter and not in-place conformance

A Bridge instance already carries most of an OKF concept's shape —
frontmatter (`title`/`summary`/`last_updated`), a markdown body, and
`[[wikilink]]`-style cross-references in Memory and docs. Rather than
rewriting hundreds of source files to a stricter shared schema, the exporter
maps what already exists onto OKF at export time: **tolerant-consume**
(loose, hand-rolled parsing of whatever frontmatter shape a file already has)
feeding a **strict-produce** bundle (every concept file carries the full OKF
frontmatter contract). The mapping logic is additive and reversible — delete
`scripts/okf-export.py` and the output directory, and the source tree is
unaffected.

## Concept mapping

| Source | OKF `type` | Notes |
|---|---|---|
| `work/tasks/<slug>/STATUS.md` | `task` | slug = the task's directory name |
| `work/streams/<slug>/STATUS.md` | `stream` | long-running, never `done` |
| `work/done/<month>/<slug>/STATUS.md` | `task` | closed tasks still map to `task` |
| `work/**/deliverables/*.md` | `deliverable` | any depth under `work/` |
| `docs/**/*.md` | `doc` | |
| `rules/**/*.md` | `rule` | |
| `examples/**/*.md` | `example` | |
| `<memory-dir>/*.md` fact files | `memory` | user scope only; see [Memory](#memory) |

For every source file:

- **`title`** — frontmatter `title` → the first `# ` H1 line in the body →
  the concept's slug (as a last-resort fallback).
- **`description`** — frontmatter `description` → `summary` → `headline`
  → empty string. Never derived from the body — a missing field means an
  honestly empty description, not a guessed one.
- **`timestamp`** — frontmatter `last_updated` → `created` → empty string.
- **`tags`** — `[status, context]` frontmatter values, only the ones present.
- **`resource`** — the concept's source: its repo-relative path
  (`docs/foo.md`), or `memory/<filename>` for memory facts. Points a
  consumer back at the underlying asset.

Frontmatter parsing is hand-rolled (no PyYAML dependency) and mirrors two
conventions already in this repo: `scripts/extract-frontmatter.py`'s
`# yaml-language-server: $schema=...` comment-prolog skip, and
`scripts/gen-board.py`'s `parse_status()` flat `key: value` scalar extraction
(quote- and inline-comment-stripping). A file with no frontmatter block at
all still exports cleanly — its title falls back to the first H1, its
description to `""`.

## Wikilink resolution

Kebab-case `[[slug]]` references (`[a-z][a-z0-9-]*` only — bash
`[[ -f … ]]` conditionals inside code blocks never match) are resolved
**at export time**, against an index built from the slugs of every concept
in the current export — never rewritten in the source repo:

- **Resolved** — `[[slug]]` becomes a bundle-root-relative markdown link:
  `[slug](/<type>/<slug>.md)` (the leading `/` is root-relative *within the
  bundle*, not the filesystem — concept files live inside `<type>/`
  subdirectories, so a plain `<type>/<slug>.md` link would resolve wrong from
  inside another `<type>/` directory). On a cross-type slug collision the
  `memory` concept wins the link target — wikilinks are memory references
  by convention.
- **Unresolved** — the `[[slug]]` text is left completely untouched (OKF
  tolerates dangling references; rewriting them would corrupt content); the
  slug is collected into the manifest's `unresolved_wikilinks` list so a
  maintainer can see what didn't resolve.

## Scope

`--scope` controls which sources are walked — this is the export's privacy
boundary, not a cosmetic filter:

- **`user`** (default) — everything: `work/` (tasks, streams, done,
  deliverables) plus `docs/`, `rules/`, `examples/`, and the instance's
  auto-memory facts. Intended for a private, full-instance export — the
  bundle will contain whatever PII the source tree contains, so treat the
  output directory exactly as sensitively as `work/`.
- **`core`** — `docs/**/*.md` and `examples/**/*.md` only. `work/`,
  `rules/`, and memory are excluded entirely. This is the shape a public
  demo export may take. **Run `scripts/no-scrub-leak.py` over the output
  directory before publishing a `core`-scope bundle** — the exporter itself
  does not scan for leaked content, it only restricts which source trees it
  reads.

## Memory

In `user` scope the exporter also walks the instance's **auto-memory**
directory — the harness's per-project store of durable facts, which lives
*outside* the repo at `~/.claude/projects/<encoded-root>/memory` (the
absolute repo path with `/` replaced by `-`). The default derivation can be
overridden with `--memory-dir`; a missing directory is skipped with a
notice, never an error (fresh instances legitimately have none).

A file qualifies as a memory fact when it carries frontmatter with a
`name:` key; that kebab-case name becomes the concept slug — which is
exactly what `[[wikilinks]]` reference, so memory links resolve naturally.
`MEMORY.md`, `MEMORY-ARCHIVE.md`, `PROVENANCE.md`, `_`-prefixed files, and
frontmatter-less strays are never exported.

## Output layout

```
<out>/
├── index.md              # okf_version, scope, concept_count
├── task/
│   ├── index.md
│   └── <slug>.md
├── stream/
│   ├── index.md
│   └── <slug>.md
├── deliverable/…
├── doc/…
├── rule/…
└── example/…
```

Only type directories with at least one concept are created — a `core`-scope
export never creates `task/`, `stream/`, `deliverable/`, `rule/`, or
`memory/`. Each concept file carries an OKF frontmatter block (`type`,
`title`, `description`, `resource`, `timestamp`, `tags`) followed by its
resolved body. `index.md` is a reserved
filename: the root `index.md` is the sole exception carrying frontmatter
(`okf_version`, `scope`, `concept_count`); every per-type `index.md` carries
no frontmatter at all, only a heading and a directory listing. `index` and
`log` are also reserved concept slugs — a source file that would otherwise
map to either is disambiguated with a numeric suffix (`index-2.md`,
`log-2.md`, ...) so it never collides with the reserved filename. The same
suffixing applies to any other same-type slug collision (e.g. two
differently-pathed `README.md` sources).

Writes are **deterministic and idempotent**: re-running against unchanged
input produces a byte-identical file set (concepts are sorted by
`(type, slug)`, the output directory is cleared and rebuilt on every run, and
nothing in the render depends on wall-clock time).

## CLI

```bash
python3 scripts/okf-export.py --out dist/okf-bundle
python3 scripts/okf-export.py --root . --out dist/okf-bundle --scope core
```

| Flag | Default | Notes |
|---|---|---|
| `--root` | `.` | the Bridge instance root to export from |
| `--out` | *(required)* | the output bundle directory |
| `--scope` | `user` | `user` \| `core` — see [Scope](#scope) above |
| `--memory-dir` | *(derived)* | memory dir override — see [Memory](#memory) |

Exit codes: `0` on success; `1` if `--root` does not exist or is not a
directory, or if `--out` points at an existing non-bundle directory (the
exporter refuses to clear anything that does not look like a previous
export); an unknown `--scope` value is rejected by `argparse` itself
(`SystemExit`, exit code `2`) before the exporter runs.

`dist/` is gitignored (see `.gitignore`) — exported bundles are a build
artifact, and a `user`-scope bundle in particular may contain the same PII
as the `work/` tree it was exported from. Never commit an export.

## Tests

`scripts/tests/test_okf_export.py` (`bash scripts/tests/test-okf-export.sh`)
is a hermetic pytest suite — every test builds its own synthetic mini-instance
under `tmp_path` and never touches the real repo tree beyond importing the
module under test. It is the authoritative contract for every function's
signature and behaviour; this document describes intent and usage, the test
file describes the exact surface.
