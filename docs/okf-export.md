---
summary: "scripts/okf-export.py — exports a Bridge instance's knowledge surfaces (work/, docs/, rules/, examples/) as a static Open Knowledge Format (OKF) v0.2 bundle, with a scope flag that gates what a public export may contain."
type: guide
last_updated: 2026-08-21
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
(OKF) v0.2 bundle — one markdown file per *concept*, a per-type `index.md`,
and a root `index.md` declaring the bundle's `okf_version`. It is read-only
against the source repo: nothing under `work/`, `docs/`, `rules/`, or
`examples/` is ever rewritten. The bundle is a **derived artifact**, disposable
and regenerable on every run.

## Background

[Open Knowledge Format (OKF)](https://okf.md/) is an open spec Google Cloud
announced in June 2026, formalizing the same markdown + YAML frontmatter
pattern that already underpins this repo's `docs/`, `rules/`, and memory
files: one file per concept, the file's path doubles as the concept ID, and a
single required `type` field says what kind of concept it is. It was created
by Sam McVeety and Amir Hormati at Google Cloud and is published under
Apache-2.0 in `GoogleCloudPlatform/knowledge-catalog`; the spec itself names
no central authority, and the licence is what keeps it forkable. The W3C
Holon Community Group (launched 2026-06-19) is a **separate** effort whose
DataBook profile layers optional formal semantics on top of OKF bundles; it
does not govern OKF, and plain OKF bundles stay valid without it.

open-bridge adopts OKF as an **interop target for the knowledge layer only**:
`work/`, `docs/`, `rules/`, `examples/`, and memory facts map cleanly onto OKF
concepts. The behaviour layer — skills, standing orders, task lifecycle — is
deliberately left un-OKF-shaped; it is process the agent executes, not a
knowledge concept to export.

Sources: https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing · https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf · https://okf.md/

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
- **`generated`** — `{ by, at }`. See [Provenance and trust](#provenance-and-trust)
  below; `by` is always written, `at` only when the source date could be
  proven.
- **`bridge_status`** — the source's Bridge workflow state (`doing`,
  `review`, …), under a namespaced key. **Never** written to OKF's own
  `status`: see [the status homograph](#the-status-homograph).
- **`tags`** — `[status, context]` frontmatter values, only the ones present.
- **`resource`** — the concept's source: its repo-relative path
  (`docs/foo.md`), or `memory/<filename>` for memory facts. Points a
  consumer back at the underlying asset.

Empty optional fields are **omitted**, never written as `""` or `[]` — OKF
states that absence carries meaning, so an empty value is a different (and
false) claim from "not recorded".

## Provenance and trust

`generated.by` names **the transformation that produced the bundle document**,
not the author of the underlying knowledge. It defaults to
`okf-export/<EXPORTER_VERSION>`; `--generated-by` overrides it with any OKF
actor (`<producer>/<version>`, `human:<id>`, `process:<id>`), and an invalid
value is rejected with exit code 1 rather than written — the value is written
verbatim into every concept, so an unconstrained string would be an unreadable
provenance claim, and one containing a newline or quote would be malformed
YAML. (Trust *tiers* derive from `verified`, which this exporter never emits,
so a wrong actor here misattributes provenance but cannot inflate a tier.)
The actor is **never** derived from `git config`, `git log` or `$USER`: a
committer is not a knowledge author, it would inject a real identity into a
`--scope core` bundle, and it would make the output depend on clone state.

`generated.at` carries the source's `last_updated` → `created`, normalized to
an ISO instant with an explicit UTC offset, as OKF requires. Bridge sources
hold bare dates, so `2026-07-02` is widened to `2026-07-02T00:00:00Z`.
**This is a documented tradeoff:** midnight is a time of day the source never
stated, but the invented component is bounded under 24h, the date is fully
recoverable, and midnight is the *earliest* instant consistent with the stated
date, so no consumer ever reads the content as fresher than the evidence
supports. A date that cannot be proven is **omitted rather than guessed** — a
partial `2026-03`, the literal `YYYY-MM-DD` that `work/templates/STATUS.md`
seeds into every new task, a calendar-impossible date, or free text. The
manifest reports how many concepts ended up without one.

### What this exporter deliberately does not emit

Each of these drives consumer *behaviour*, not just display, so a fabricated
value does not read as noise — it reads as a false claim.

| Field | Why not | What would change that |
|---|---|---|
| `verified` | Nothing in a Bridge instance is a verification event. `status: review` means a review is *pending*; `status: done` means the work finished, not that anyone confirmed the document against its sources. Trust tiers are derived purely from this field, so a synthetic entry silently promotes every concept out of `unverified`, and a `human:` actor would be an outright false claim of human sign-off. | A source file carrying a real `verified` stamp written by something that actually checked it. The exporter would pass it through; it will never synthesize one. |
| `sources` | `related:` is *see-also*, not *derived-from*, and its paths are inconsistently based, so many entries would not resolve at all — while `resource` is required per entry. A consumer may recurse into `sources` and propagate credibility, so feeding it see-also links manufactures lineage edges rather than adding inert noise. The concept's own origin is already fully expressed by `resource`. | An explicit derivation field in the source (e.g. `derived_from:`) with a resolvable target. |
| `stale_after` | No Bridge field says when a *document* stops being true. A deadline says when *work* is due, and a derived `last_updated + N days` would invent a retention policy the Bridge has never declared. It is a consumer **gate**, so a fabricated horizon suppresses content that is perfectly current. | A source carrying a real expiry instant. Note the type: an **absolute ISO instant with an offset** (`2026-09-23T00:00:00Z`), never a bare `YYYY-MM-DD` and never a TTL like `90d`. |
| `status` | See below. | — |
| Attested Computation | `runtime` is required for that type and the Bridge has no runtime, parameters, executor or attester. A consumer *executes* an attested computation, so a half-populated contract would turn a documentation bundle into something a consumer tries to run. | Nothing foreseeable. |

### The status homograph

OKF's `status` is **document readiness** (`draft` | `stable` | `deprecated`).
A Bridge `status` is **work state** (`backlog` | `doing` | `review` | `done`).
The two are orthogonal axes that happen to share a field name, and `draft` is
a homograph across them: a Bridge task in draft state is not a document that
is "not yet reviewed, possibly incomplete". A finished task's write-up is the
*most* current document in the bundle, not the least.

So no concept ever carries a top-level `status`, not even behind an
enum whitelist. Absent `status` already means `stable` in OKF, which is the
true claim about an exported Bridge write-up. The Bridge value travels under
`bridge_status` (and, unchanged from v0.1, in `tags`).

Frontmatter parsing is hand-rolled (no PyYAML dependency). It keeps
`scripts/extract-frontmatter.py`'s `# yaml-language-server: $schema=...`
comment-prolog skip and reads flat `key: value` scalars.

`parse_frontmatter` is this repo's reference implementation of that job, and
it has a second consumer: `scripts/gen-board.py` imports it rather than
parsing frontmatter itself. That script used to carry its own copy, the two
drifted, and the board silently rendered a YAML comment as a task's
description. The five rules below are each a place a hand-rolled parser goes
wrong, and each one cost real content before it was fixed:

- **Quoting is resolved before inline comments**, the order YAML itself uses.
  A `#` inside a quoted scalar is a literal character, so
  `headline: "... in review as PR #214"` keeps its issue number. On an
  *unquoted* scalar a ` #` after a space or a tab still opens a comment and is
  still stripped, and `value#nospace` (no whitespace in front of the hash)
  stays whole.
- **A quote closes a quoted scalar only where a quote may close one**: with
  nothing behind it, or an inline comment. Anything else means that quote was
  a character inside the value, and the value then falls back to the plain
  path rather than being cut at it. `title: 'Alex's bridge'` yields
  `Alex's bridge`, and `title: "He said "stop" once"` yields
  `He said "stop" once`: every character between the outer quotes survives,
  and only that orphaned outer pair is dropped. PyYAML rejects both of those
  lines outright, so there is no conformant reading to defer to; keeping a
  malformed value whole is the lesser failure. Doubling the inner apostrophe
  (`'Alex''s bridge'`) or switching quote style still makes the line legal
  YAML, which is worth doing for any consumer that is not this exporter.
- **An unquoted value keeps its last character, whatever it is.** The
  orphaned-pair strip above applies only to a value that *opens* with a quote,
  because a YAML plain scalar cannot. So `title: monitor is 12"`,
  `title: The so-called "bridge"` and `title: it is 'fine'` reach the bundle
  whole. All three are ordinary prose that PyYAML round-trips unchanged; an
  earlier version of this exporter stripped quotes off both ends of every
  fallen-through value and ate the last character of each.
- **The opening `---` fence counts only at column 0; the closing one is judged
  by block-scalar state.** A block-scalar continuation line is blank or
  indented by definition, so an indented `---` inside a `title: |` block is
  content, not the end of the frontmatter block. Outside a block scalar an
  indented `---` still closes, because a file that merely indents its closing
  fence would otherwise have the body below it read as frontmatter, up to the
  next column-0 `---`, or no frontmatter recognised at all. A file whose
  *first* non-blank line is an indented `---` has no frontmatter (it is an
  indented code block).
- **Only `\r\n`, `\r` and `\n` end a line, and a leading UTF-8 BOM is
  ignored.** Python's `str.splitlines` also breaks on U+2028, U+2029 and five
  more characters, which cut a scalar in half at a character PyYAML accepts
  inside a double-quoted value; and `str.rstrip` does not remove U+FEFF, so a
  BOM-prefixed file used to read as having no frontmatter at all. Whitespace
  is trimmed as YAML trims it, spaces and tabs only, so a pasted U+00A0 is
  content and stays.

None of these rules raises. Measured rather than asserted: over 21,144
well-formed frontmatter lines (each probe value spelled plain, double quoted
and single quoted, every line accepted by PyYAML), the parser agrees with
PyYAML on all of them.

A file with no frontmatter block at all still exports cleanly: its title falls
back to the first H1, its description to `""`.

### Where the parser still differs from a real one

Three shapes remain where PyYAML reads more than this parser does. None of
them raises, and in each case the source is what has to change if the
difference matters:

- **A block scalar loses blank lines and extra indentation.** A
  `description: |` holding two paragraphs and an indented code line arrives as
  three space-normalised lines joined by `\n`, where PyYAML keeps the blank
  line and the four extra spaces. A folded `>-` block collapses its blank line
  too: PyYAML's `one two\nthree` becomes `one two three`. Frontmatter values
  here are one-line summaries by convention, so this shapes the formatting
  inside a description rather than deciding which text reaches the bundle.
- **Double-quoted escapes outside a small table come back verbatim.** The
  table is `\\`, `\"`, `\/`, `\n`, `\r`, `\t`: exactly what this exporter
  emits, plus YAML's `\/`. Anything else is left as its two literal characters
  rather than guessed at, so `"\d+"` keeps its backslash, and a
  PyYAML-*emitted* `"a\L b"` (its spelling of U+2028) or `"a\x41 b"` arrives
  with the escape intact instead of the character. Sources here are
  hand-written, and hand-written frontmatter uses the six in the table.
- **U+2028/U+2029 are ordinary characters here and line breaks to PyYAML.**
  PyYAML implements YAML 1.1, where those are breaks, so it folds the
  whitespace next to one; this parser follows YAML 1.2 and keeps the value
  exactly as written. The two therefore agree on the content and can differ by
  a space beside a separator character. Every mismatch left in the fuzz above
  is of that shape.

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

- **`user`** (default): everything: `work/` (tasks, streams, done,
  deliverables) plus `docs/`, `rules/`, `examples/`, and the instance's
  auto-memory facts. Intended for a private, full-instance export — the
  bundle will contain whatever PII the source tree contains, so treat the
  output directory exactly as sensitively as `work/`.
- **`core`**: `docs/**/*.md` and `examples/**/*.md` only, without the docs
  tier folders `docs/user/`, `docs/org/` and `docs/personal/`, which hold an
  instance's own documents ([kernel.md](kernel.md)). `work/`, `rules/`, and
  memory are excluded entirely. This is the shape a public
  demo export may take. **Run `scripts/no-scrub-leak.py` over the output
  directory before publishing a `core`-scope bundle** — the exporter itself
  does not scan for leaked content, it only restricts which source trees it
  reads.

## Memory

In `user` scope the exporter also walks the instance's **auto-memory**
directory, the harness's per-project store of durable facts. Its default is
resolved via `scripts/memory-location.py`: a configured `autoMemoryDirectory`
(e.g. an in-repo `work/memory/`) wins when one is set, otherwise the
harness's own legacy default applies, *outside* the repo at
`~/.claude/projects/<encoded-root>/memory` (the absolute repo path with `/`
replaced by `-`). Either way the default can be overridden with
`--memory-dir`; a missing directory is skipped with a notice, never an error
(fresh instances legitimately have none). See [`docs/memory.md`](memory.md)
for the full resolution model.

A file qualifies as a memory fact when it carries frontmatter with a
`name:` key; that kebab-case name becomes the concept slug — which is
exactly what `[[wikilinks]]` reference, so memory links resolve naturally.
`MEMORY.md`, `MEMORY-ARCHIVE.md`, `PROVENANCE.md`, `_`-prefixed files, and
frontmatter-less strays are never exported.

**The store is read in one scope and protected in every scope.** The exporter
is strictly a reader of it, so `--out` may never point inside it, whichever
`--scope` is running (see [the `--out` rules](#cli)). A `name:` also has to be
one path segment and short enough to be a filename: a name that is not is
replaced by the filename-derived slug, and a slug past the filesystem's
255-byte limit is refused before anything is cleared rather than crashing
half-way through the write.

## Output layout

```
<out>/
├── index.md              # okf_version (the only key OKF permits here)
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
`title`, `description`?, `resource`, `generated`, `bridge_status`?, `tags`?,
in that order, with the optional ones omitted when empty) followed by its
resolved body. `index.md` is a reserved
filename: the root `index.md` is the sole exception carrying frontmatter, and
it carries **`okf_version` alone** — the one key OKF permits in an index file
— with scope and concept count stated in the body prose instead. Every
per-type `index.md` carries no frontmatter at all, only a heading and a
directory listing in the spec's `* [Title](slug.md) - description` form.
`index` and
`log` are also reserved concept slugs. A source file that would otherwise map
to either, and any other same-type slug collision (e.g. two differently-pathed
`README.md` sources), is disambiguated with a numeric suffix: the **lowest one
not already claimed** by another concept of the same type. A concept keeps its
own natural slug wherever it can, so the colliding duplicate is the one that
moves, and the suffix is appended to that duplicate's own slug (a second
`overview-2` becomes `overview-2-2`, never `overview-3`). The familiar
`index-2.md` and `log-2.md` are what you get whenever those names are
otherwise free.

A claim is measured in the FILESYSTEM's namespace rather than the byte
string's, because a slug becomes a filename. Two slugs are one claim when they
name one file: the comparison normalizes to NFC and case-folds, so `readme` and
`README`, and the NFC and NFD spellings of `café`, collide and the second one
takes a suffix. The reserved names are compared the same way, which is why a
source named `Index.md` is written to `<type>/Index-2.md` instead of being
destroyed by the generated `<type>/index.md` that lands after it. Only the
comparison folds: the file keeps the concept's own slug, capitals, accents and
normalization intact, so a case pair leaves the bundle as `readme.md` beside
`README-2.md`. One consequence is deliberate. On a case-sensitive filesystem
that pair would not have collided at all, and it is suffixed there too, so
*which* concepts collide is the same question on every platform.

That is the only axis folding closes, and it is worth being exact about the
rest. Because the emitted filename keeps the source's own spelling, the same
logical concept named in NFC and in NFD produces different bundle filename
bytes, and normalization spelling is a per-tree property (APFS preserves
whichever bytes were written; macOS git's default `core.precomposeunicode`
hands them back as NFC). Two clones of one repo can still differ there.

The suffix rule carries one limit of its own: a bumped path is not a stable
identifier across runs. `overview-2.md` belongs to whichever concept holds the
lowest free claim on the day of the export, so adding a source that owns
`overview-2` naturally moves the previous holder to `overview-3`. Key a
consumer off a concept's `resource:` field, not off its bundle filename.

**Every index lists exactly as many entries as it has things to list**, one
per line, and every entry's link points at that entry's own concept file: a
type index one entry per concept of that type, the root index one per
populated type directory. A type index is the only generated file that puts
source text into markdown, and **three** of the values in an entry are
source-derived, not two: the `title`, the `description`, and the slug, which
is a source *filename*.

- The two text fields are rendered as inline **text**, not as markup. Every
  control character (line breaks included, plus U+2028/U+2029) becomes a
  space, and `[`, `]`, `\` and `<` are backslash-escaped. That is visible in
  the raw file: a title containing a bracket shows as `\[`, which a markdown
  renderer displays as the bare character.
- The slug is percent-encoded into a relative URL, which is the form OKF
  section 8 asks for. Only what a link destination cannot carry raw is
  touched (space, parentheses, `<`, `>`, `#`, `?`, `%` and the RFC 3986
  exclusions), so an ordinary slug reaches the entry byte for byte as the file
  is named on disk, accents and capitals included.

Four ways a value could otherwise leave its own entry, none of which raised.
A newline broke the bullet across two lines, so the overflow read as an entry
the count above it did not admit (a newline reaches a description from a
`description: |` block scalar, or from a `\n` escape inside a double-quoted
one, which the parser now reads back). An unescaped `]` closed the link text
early, handing the `(…)` behind it to the source as a link destination without
needing a newline at all. Raw inline HTML, which CommonMark passes straight
through, opened list items of its own: a title of
`a</li><li><a href='…'>evil</a>` rendered as four list items under a header
claiming three. And a *filename* containing a space produced a bullet
CommonMark does not read as a link at all, one containing `)` pointed the link
at a file the bundle does not contain, and one containing U+2028 split its own
bullet.

Measured with a real CommonMark parser rather than by inspection: each index
renders as exactly N list items carrying N hrefs, every one of which resolves
(after URL-decoding) to one of that type's own concept files.

The guarantee stops there, and stopping is deliberate. Other inline markdown
inside an entry still renders, exactly as it does inside a concept body, which
is markdown by design: emphasis around a `*`, a code span between backticks,
an HTML entity such as `&auml;`. None of those can move an entry's link or
fabricate a second entry. The concept files need none of this: every
source-derived value there is written as an escaped double-quoted scalar.

Writes are **deterministic and idempotent**: re-running against unchanged
input produces a byte-identical file set, in a fresh interpreter too (concepts
are sorted by `(type, slug)`, the output directory is cleared and rebuilt on
every run, and nothing in the render depends on wall-clock time). The largest
way to lose that property is refused rather than merely documented: an `--out`
inside a directory any scope walks exits `1`, because the walk would otherwise
read the previous run's own output back in as source material and the concept
count would climb on every run. See [the `--out` rules](#cli) for what counts
as inside.

## CLI

```bash
python3 scripts/okf-export.py --out dist/okf-bundle
python3 scripts/okf-export.py --root . --out dist/okf-bundle --scope core
python3 scripts/okf-export.py --out dist/okf-bundle --generated-by human:alice
```

| Flag | Default | Notes |
|---|---|---|
| `--root` | `.` | the Bridge instance root to export from |
| `--out` | *(required)* | the output bundle directory |
| `--scope` | `user` | `user` \| `core` — see [Scope](#scope) above |
| `--memory-dir` | *(derived)* | memory dir override — see [Memory](#memory) |
| `--generated-by` | `okf-export/<version>` | OKF actor for `generated.by` — see [Provenance and trust](#provenance-and-trust) |

Exit codes: `0` on success; `1` if `--root` does not exist or is not a
directory, if `--out` is refused, if a concept cannot be written, or if
`--generated-by` is not a valid OKF actor; an unknown `--scope` value is
rejected by `argparse` itself (`SystemExit`, exit code `2`) before the
exporter runs.

An `--out` is refused when it exists and is not a directory, when it is
`--root` or an ancestor of it, when it sits inside a directory any scope walks
or contains one (see below), when it overlaps the memory dir *in either
scope*, or when it points at an existing non-empty directory that does not
look like a previous export (the exporter refuses to clear anything it does
not recognise as its own output). A concept cannot be written when two of one
type name a single file, or when a slug is longer than the filesystem's
255-byte filename limit. All of those are checked before the destination is
cleared, so a refused run costs an error message and leaves the sources and
any previous bundle exactly as they were.

**`--out` must lie outside what *every* scope walks, not just the current
one.** That means outside `docs/`, `examples/`, `work/` and `rules/`, in both
scopes, and outside the memory dir. The guard reads the union rather than the
running scope because the bundle outlives the run that wrote it: `core` walks
only `docs/` and `examples/`, so `--out rules/bundle --scope core` would land
happily, and the next `--scope user` run would glob `rules/**/*.md` and ingest
that bundle as `rule` concepts. The memory clause follows the same rule for
the same reason: `core` scope never *reads* the memory store, but a bundle
written there is still rmtree'd over on the next run of either scope, fact
files and all, so a `core` run is refused a destination inside it too.
`dist/okf-bundle` is outside every scope and outside the memory dir, which is
what makes it the documented default.

The refusal is raised before the walk and before the destination is cleared,
so a mistaken `--out` costs an error message and nothing else. The scanned set
is derived from the same pattern list the walk itself globs, so adding a source
pattern extends the guard automatically. Each pattern contributes two things:

- its **fixed leading path** (`docs/**/*.md` gives `docs`), which covers a
  directory that does not exist yet and is scanned the moment it appears;
- the resolved result of running **the walk's own glob** over the pattern's
  parent (`work/**/deliverables/*.md` gives `work/**/deliverables`), which
  covers a directory reached through a symlink at a literal segment *after*
  the globbed part. `Path.glob` follows those, and the fixed prefix of that
  pattern is only `work`, so a link named `deliverables` pointing into the
  bundle was invisible to a prefix-only guard while the walk read straight
  through it.

Containment is judged segment-wise on **resolved** paths, in the same
case-folded namespace the exporter uses for filenames:

- `dist/../docs/bundle` is refused exactly like `docs/bundle`;
- `DOCS/okfbundle` is refused like `docs/okfbundle`, because on the macOS
  default filesystem those are one directory;
- a repo whose `docs/` is itself a symlink is compared on where that link
  really reads, not on the link path, and so is a symlinked `deliverables`
  reached through a glob;
- the sibling `docs-bundle` stays **legal**: segments are compared whole, so a
  shared name prefix is not containment.

The converse also fires: an `--out` that *contains* a scanned directory is
refused, because clearing it would delete source data rather than a previous
bundle. A `docs/` symlink pointing into the destination is how that is reached.

**The guard refuses more than it strictly has to, on purpose.** Three
widenings are deliberate, because the failure being guarded against is silent
data corruption and the answer to a refusal is simply another destination:

- it covers scopes the current run is not in, as above;
- prefix derivation takes each pattern's fixed leading path, and
  `work/**/deliverables/*.md` collapses to `work`. So **all** of `work/` is
  refused, `work/exports/okfbundle` included, even though that pattern needs a
  literal `deliverables` segment and the bundle's type directory is named
  `deliverable`, so nothing written there could ever be globbed back in;
- on a **case-sensitive** filesystem the fold refuses a `Docs/` that really is
  a separate directory from `docs/`. The refusal names the comparison it made
  for exactly that case, so the containment it states is never something the
  operator can see is false in `ls`.

Every refusal about *where* `--out` points names `dist/okf-bundle`, a
destination that works. The two refusals that are not about the path (two
concepts of one type naming a single file; a slug past the filename limit)
name the source that has to change instead, since moving `--out` would not
help.

This is a **behaviour change**: a command that pointed `--out` into a directory
any scope walks used to exit `0` and quietly produce a corrupted bundle, each
run re-ingesting the last. It now exits `1`. Move `--out` to a directory
outside the scanned tree.

**A failed run leaves a destination the next run can still use.** The root
`index.md` is written first, before any concept file, because that file is
what marks a directory as a previous export. Written last, any mid-write
failure (a full disk, a permission error) left a non-empty directory that no
longer looked like a bundle, and every later run then refused to clear it:
the only way out was deleting the directory by hand. The partial bundle from a
crashed run is still incomplete and should be regenerated, but regenerating it
is now one command.

## Migrating from v0.1

One intentional, consumer-visible break: **`timestamp` is gone**, superseded
by `generated.at`. It is not dual-emitted. The spec's legacy fallback applies
only when `generated` is absent, and `generated.by` is always written, so no
conformant v0.2 consumer would ever read it; carrying it would also re-ship
exactly those raw date strings the normalizer just refused. The bundle
self-declares its dialect via `okf_version`, which is the spec's own
mechanism for this.

Nothing else breaks. Bundles are regenerated by one command, `dist/` is
gitignored, and the `--out` guard still recognises a v0.1 bundle directory as
safe to clear, so a re-export over an existing bundle works unchanged.

`dist/` is gitignored (see `.gitignore`) — exported bundles are a build
artifact, and a `user`-scope bundle in particular may contain the same PII
as the `work/` tree it was exported from. Never commit an export.

## Tests

`scripts/tests/test_okf_export.py` (`bash scripts/tests/test-okf-export.sh`)
is a pytest suite in which every test builds its own synthetic mini-instance
under `tmp_path`, so no test reads or writes real instance content. Two tests
deliberately read repo files rather than fixtures: the exporter source (to
assert no wall-clock, git or environment call appears in the render path) and
this guide plus the suite's own docstring (to assert the documentation was
migrated alongside the code). Both read only; neither touches `work/` or a
memory directory.

The suite is the authoritative contract for every function's signature and
behaviour; this document describes intent and usage, the test file describes
the exact surface.
