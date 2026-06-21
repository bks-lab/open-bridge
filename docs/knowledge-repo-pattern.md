---
summary: "Pattern for connecting an optional knowledge/documentation repo to a Bridge instance"
type: reference
scope: core
last_updated: 2026-05-13
related:
  - ../workflow/contexts/_template.yaml
  - ../protocols/standing-orders/task-sync.md
  - examples/knowledge-repo/README.md
---

# Knowledge Repo Pattern

A Bridge instance can be paired with an optional **knowledge repo** — a
separate Git repository that holds documentation, customer protocols,
internal processes, leads, and strategic notes. The Bridge instance itself
keeps short, structured records (tasks, configs, logs); the knowledge repo
keeps long-form prose and durable history.

This is a **pattern**, not a requirement. Bridge works without it. Use this
doc as a blueprint if you want to set one up.

## When to add a knowledge repo

You probably want one when any of these are true:

- You generate **meeting protocols** or **decision records** that future-you
  needs to find by topic, not by date.
- You serve **multiple customers or domains** and want a single place to
  diff their history.
- You need to **share documentation with collaborators** through Git rather
  than a wiki platform.
- Your `work/log.md` keeps growing because it's the only place to write
  *anything* — it's a log, not a knowledge base.

If you only need short task notes, the in-Bridge `work/` system is enough.

## Decision tree (where does each piece of content go?)

```
Is it for a PUBLIC audience?
├── YES → public-site repo (marketing, blog, showcase)
└── NO → Is it CODE or REUSABLE TOOL?
    ├── YES → code repo
    └── NO → knowledge repo (protocols, decisions, customer docs, leads)
```

Three repo types, one decision rule. Keep them distinct.

## Recommended layout

```
<knowledge-repo>/
├── index.md                  # Top-level navigation
├── CLAUDE.md                 # Conventions for AI assistants (optional)
├── <area-1>/                 # e.g. customers/, internal/, leads/
│   ├── index.md              # Area inventory
│   ├── _MOC.md               # Area "what's important" (5+ items)
│   └── <slug>/               # Customer, project, lead, etc.
│       ├── index.md
│       ├── _MOC.md
│       ├── projects/         # Sub-projects
│       └── protocols/        # Meeting/decision protocols
├── templates/                # Reusable skeletons
└── standards/                # Your conventions (the source-of-truth)
```

Areas are your top-level slicing — common picks: `customers/`,
`internal/`, `leads/`, `partners/`. Pick what matches your work shape.

## MOC + Index pattern

Every directory with **5+ files** gets two entry points:

| File | Question | Character | Max |
|---|---|---|---|
| `_MOC.md` | "What is **important**?" | Curated, with judgment | 50 lines |
| `index.md` | "What **exists**?" | Inventory, no judgment | Clean table |

**Reading order:** `_MOC.md` first (AI entry point), `index.md` only for
obscure lookups. Follow `related:` links in frontmatter rather than
scanning folders.

**Update rules:**

| Change | `_MOC.md` | `index.md` |
|---|---|---|
| New important topic / project / incident | Update | — |
| Status change (phase, severity) | Update summary line | — |
| New / deleted file | — | Update inventory row |
| New subdirectory | Maybe add link | Add row |
| Routine edit (typo, meeting protocol) | Skip | Skip |

## Standard project structure

Every project folder under `<area>/<slug>/projects/<project>/`:

```
<project>/
├── project.yaml          # Metadata (REQUIRED)
├── _MOC.md               # Curated entry (REQUIRED at 5+ files)
├── index.md              # File inventory (REQUIRED)
├── documentation/        # Technical docs
├── requirements/         # Requirements
├── milestones/           # Timeline (optional)
└── attachments/          # Files
```

Templates for each of these live in
[`docs/examples/knowledge-repo/`](examples/knowledge-repo/README.md).

## Frontmatter conventions

Every standalone markdown file:

```yaml
---
summary: "One-line description — max 100 chars, used as AI triage hook"
type: protocol | decision | reference | moc | index
last_updated: YYYY-MM-DD
related:
  - relative/path/to/related-file.md
status: active | reference | archive  # optional
---
```

**Why:** Claude (and humans) read frontmatter before deciding to read the
body. A good `summary:` + `related:` array lets the reader skip irrelevant
files and follow useful threads. **`summary:` is mandatory.**

## Twelve principles for what to write (P1–P12)

| # | Principle | Meaning |
|---|---|---|
| P1 | Outcome over process | Document the decision, not the discussion path |
| P2 | Relevance first | Only actions, decisions, risks, scope changes |
| P3 | Structure over brevity | Tables for structured data, prose only for reasoning |
| P4 | Get it right once | No fact duplicated across summary + detail + actions |
| P5 | Skip known context | Project background, team structure → omit or link |
| P6 | Substance is never cut | Verbatim quotes, exact numbers, dates stay full-length |
| P7 | Legal mode is exempt | `type: legal` in frontmatter → completeness over brevity |
| P8 | One canonical location | A fact lives in one place; everywhere else links to it |
| P9 | YAML for facts, markdown for reasoning | Lists, metadata → frontmatter; explanation → body |
| P10 | Explicit linking | `related:` array, not "see the other file in this folder" |
| P11 | Project MOCs | Every project gets a curated `_MOC.md` entry point |
| P12 | Actionability flag (optional) | `status: active \| reference \| archive` |

## Relevance filter (first hit wins)

When deciding whether to write something down:

1. Is it a **decision / action item / risk / scope-or-budget change**?
   → Table row. Done.
2. Will it still be relevant in **2+ weeks**, or is it a deliberate
   non-decision?
   → One short sentence. Done.
3. Is it **already documented elsewhere** (project.yaml, issue, code)?
   → Link if critical, otherwise skip.
4. None of the above?
   → Skip.

## Optional dual-documentation pattern

For customers or projects where every touchpoint must be **fully
traceable**, enforce dual documentation: every analysis, decision, or
escalation appears in **both** (a) a GitHub issue/comment, and (b) a
markdown file in the knowledge repo.

Declare this in your context config:

```yaml
# workflow/contexts/<slug>.yaml
sync:
  defaults:
    github:
      repo: my-org/my-customer-issues
      project: { ref: workflow/projects/my-customer.yaml }
    wiki:                              # rename freely — "wiki" is just the key
      root: knowledge-repo/customers/my-customer/
      moc_update: knowledge-repo/customers/my-customer/_MOC.md
  dual_doku:
    required: true
  event_type_map:
    incident:      { wiki_subpath: incidents/, label: incident }
    customer-comm: { wiki_subpath: incidents/, label: business }
```

The `task-sync` standing-order then resolves routing per-task and runs a
self-check at task close. See
[`protocols/standing-orders/task-sync.md`](../protocols/standing-orders/task-sync.md).

Skip this for low-stakes contexts (internal notes, leads pipeline) — it's
overhead that only pays off when audit-trail-against-the-customer is the
goal.

## Bridge integration points

The Bridge connects to a knowledge repo through three surfaces — all
optional, mix as needed:

| Surface | File | Purpose |
|---|---|---|
| **Registration** | `ecosystem.yaml` → top-level entry | Lists the repo so `/bridge-status` sees it |
| **Routing** | `workflow/contexts/<slug>.yaml` → `sync.wiki.*` | Per-context knowledge-repo defaults |
| **Conventions** | `rules/<your>-principles.md` (path-triggered) | Auto-loads when working under your knowledge repo's path |

If you also want a slim version of these principles to auto-load when
Claude touches knowledge-repo files, create `rules/<your>-principles.md`
with `paths: ["**/<your-knowledge-repo>/**"]` in the frontmatter. See
how this Bridge instance does it for its own internal knowledge repo if
you want a working example to crib from.

## Source-of-truth split

Conventions live in **two** places by design:

- **In the knowledge repo itself** (`<knowledge-repo>/standards/`): the
  authoritative version. Edited by humans who know the domain.
- **In the Bridge** (`rules/<your>-principles.md`): a slim mirror for
  fast loading + cross-references. Points back to the authoritative
  source.

When conventions change, edit the authoritative source first, then
update the Bridge mirror if the change affects behavior.

## When to skip this pattern

- **You have fewer than 50 documents total.** A flat folder works fine.
- **You already use Obsidian, Notion, Logseq, etc.** Those tools have
  their own conventions; don't fight them. Use the Bridge for routing
  context and leave the knowledge tool alone.
- **Your knowledge is all in code comments / commit messages / PR
  descriptions.** That's a code-only org. Document the few exceptions
  in the Bridge's `docs/` folder directly.

## See also

- [`docs/examples/knowledge-repo/`](examples/knowledge-repo/README.md) —
  template skeletons for project metadata, MOC, index, and the context
  sync stub.
- [`skills/knowledge-repo-init/`](../skills/knowledge-repo-init/SKILL.md)
  — guided wizard that scaffolds these files for a new knowledge repo.
- [`workflow/contexts/_template.yaml`](../workflow/contexts/_template.yaml)
  — the context schema, including the `sync.wiki.*` block.
