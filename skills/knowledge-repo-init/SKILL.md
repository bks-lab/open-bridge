---
name: knowledge-repo-init
description: >-
  Guided wizard for connecting or scaffolding an optional knowledge /
  documentation repo to a Bridge instance. Walks the user through layout
  choice, area picks, frontmatter conventions, optional dual-doku
  contracts, Bridge wiring (ecosystem.yaml + workflow/contexts/), and
  copies template skeletons from docs/examples/knowledge-repo/.
  Trigger: "/knowledge-repo-init", "knowledge repo", "knowledge-repo",
  "set up wiki", "set up docs", "scaffold wiki", "add knowledge repo",
  "connect knowledge repo", "docs repo", "documentation repo", "wiki setup".
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, AskUserQuestion
metadata:
  scope: core
---

# Knowledge Repo Init — Guided Wizard

Sets up an **optional** knowledge/documentation repo paired with this
Bridge instance. Bridge works without one — this skill is for users who
have outgrown a flat `work/log.md` and want a durable place for
protocols, decisions, and customer documentation.

**Pattern overview:** [`docs/knowledge-repo-pattern.md`](../../docs/knowledge-repo-pattern.md)
— read it first if you're unsure whether you want this. The wizard
itself does **not** repeat the pattern explanation; it executes it.

## Before you start

The wizard performs filesystem writes (creates folders, copies
templates) and edits Bridge configs (`ecosystem.yaml`,
`workflow/contexts/<slug>.yaml`). It does **not** touch your knowledge
repo's Git history without confirmation. Every destructive or
externally-visible step is gated by an explicit `[y]` prompt.

## Inputs the wizard collects

| Phase | Question | Default |
|---|---|---|
| 0 | What's the state? new repo / existing repo / both | — |
| 1 | Slug + display name + (optional) org | — |
| 2 | Path on disk + remote URL (if any) | local-only OK |
| 3 | Top-level areas (customers/internal/leads/partners/projects) | `internal/` |
| 4 | Dual-doku contract for any area? | no |
| 5 | Bridge integration: register in `ecosystem.yaml`? | yes |
| 6 | Scaffold a starter project folder? | optional |
| 7 | Commit + push? | confirm |

Use AskUserQuestion for branching choices. Bundle related fields into
the same prompt when they're not branching (slug + display name + org
together, areas as multi-select).

## Phase 0 — State detection

Ask:

> Do you already have a knowledge repo, or are we creating one fresh?
> [1] Fresh — create a new directory + (optional) GitHub repo
> [2] Existing — wire up a repo that already lives somewhere on disk
> [3] Both — point at an existing folder AND scaffold a new project inside it

For [1] and [3], the wizard will create folders and write files.
For [2], the wizard reads the existing layout and only **proposes**
template additions — it never overwrites existing files.

If [2] and the directory doesn't contain a single markdown file with
frontmatter, warn the user that the pattern assumes structured
markdown and ask whether to proceed.

## Phase 1 — Identity

Bundle:
- **Slug** (kebab-case, used in paths) — propose from display name
- **Display name** (human-readable)
- **Org** (optional, e.g. GitHub org if remote will be created)

Validation: slug must match `[a-z0-9-]+` and not collide with an
existing entry in `ecosystem.yaml`.

## Phase 2 — Location

Ask for:
- **Local path** — default `${projects_root}/<slug>` if `projects_root`
  is set in `bridge-config.yaml`, else `~/Developer/<slug>`
- **Remote URL** — optional; if empty, leave the repo local-only

If the local path exists and is non-empty, switch to existing-repo mode
(Phase 0 → [2]).

If creating fresh, run:
```bash
mkdir -p "$path" && cd "$path" && git init -b main
```
Only after the user confirms the resolved path.

## Phase 3 — Areas

Multi-select prompt:

> Which top-level areas should the repo have? (pick all that apply)
> [ ] customers/   — per-customer documentation
> [ ] internal/    — internal projects, organisation, services
> [ ] leads/       — sales pipeline / prospects
> [ ] partners/    — partner / vendor docs
> [ ] projects/    — flat project list (no per-area split)

For each selected area, scaffold:
```
<repo>/<area>/
├── index.md      # from docs/examples/knowledge-repo/project-template/index.md, retitled
└── (no _MOC.md yet — created on demand at 5+ files)
```

## Phase 4 — Dual-documentation contract

Ask per-area:

> Should every touchpoint in this area require BOTH a GitHub issue
> AND a knowledge-repo markdown file?
> [y] Yes — set up dual-doku contract (recommended for paying customers)
> [n] No  — knowledge-repo writes only

If yes, the wizard will later (Phase 5) include the `dual_doku.required: true`
block in the matching `workflow/contexts/<slug>.yaml`.

Skip this prompt if the user selected only `internal/` or `leads/`.

## Phase 5 — Bridge integration

Two sub-steps, both opt-in:

### 5a — Register in `ecosystem.yaml`

Append under a top-level group (default `base:` for general-purpose
knowledge repos, or `customers:` / `partners:` if the repo is
domain-specific):

```yaml
<slug>:
  github: <org>/<slug>          # omit if local-only
  description: "<one-line description>"
  type: docs
  areas:                         # only the ones picked in Phase 3
    <area-1>: "<area-1>/"
    <area-2>: "<area-2>/"
  templates_dir: "templates/"
  standards_dir: "standards/"    # if user wants a conventions folder
```

Show the diff before writing.

### 5b — Create `workflow/contexts/<slug>.yaml`

Only if the user wants per-context routing right away. Copy
`workflow/contexts/_template.yaml` to `workflow/contexts/<slug>.yaml`
and pre-fill from the answers so far. Uncomment the `sync.wiki.*`
block. If Phase 4 said yes for any area, set `sync.dual_doku.required: true`.

This step can be deferred — the user can run `/bridge-onboard reconfigure`
or hand-edit later. Default: defer.

## Phase 6 — Scaffold starter project (optional)

If the user wants a first concrete project to start writing into:

1. Ask: which area, what slug, what display name?
2. Copy `docs/examples/knowledge-repo/project-template/` to
   `<repo>/<area>/<area-slug>/projects/<project-slug>/`
3. Rewrite `{{Project Name}}` / `{{YYYY-MM-DD}}` placeholders in the
   copied files
4. Add the new project to the area's `index.md`

## Phase 7 — Commit + push

In the **knowledge repo**:

```bash
cd <knowledge-repo>
git add -A
git commit -m "chore: initial scaffold from knowledge-repo-init"
# only if remote was set in Phase 2:
git remote add origin <remote-url>   # (idempotent — skip if already set)
git push -u origin main
```

In the **Bridge repo** (this one):

```bash
cd <bridge-root>
git add ecosystem.yaml workflow/contexts/<slug>.yaml  # only the touched ones
git commit -m "chore(<slug>): register knowledge repo"
# do NOT auto-push — the Bridge has CORE/USER branch rules; leave that
# to the user (they may want to /bridge-sync or just push user/<name>).
```

Confirm each `git push` separately.

## Conventions the wizard enforces

- **No files outside the scaffolded structure** without confirmation
- **No editing of files that already exist** — propose changes as diffs,
  let the user apply them manually if they want
- **All copied files keep their original frontmatter format** (the
  `summary:` / `type:` / `last_updated:` triplet is mandatory)
- **`last_updated:` is set to today's date** when copying templates
- **No secrets, no credentials** written into any scaffolded file

## Output to the user at the end

A short summary:

```
✓ Knowledge repo: <slug> @ <path>
  Areas:         <area-1>, <area-2>
  Dual-doku:     <area-1>: yes / <area-2>: no
  Registered in: ecosystem.yaml
  Context file:  workflow/contexts/<slug>.yaml (or deferred)
  First project: <area>/<slug>/projects/<project>/ (or none)

Next steps:
  1. Read docs/knowledge-repo-pattern.md if you haven't yet
  2. Start writing into <repo>/<area>/<slug>/
  3. Run /bridge-sync at end-of-sprint to push Bridge changes upstream
```

## When to use a different skill instead

- **"Add a new task to an existing knowledge repo"** → just create the
  file directly. This skill is for *first-time setup*.
- **"Reconfigure my Bridge with a new variant"** → use `/bridge-onboard
  reconfigure`. This skill assumes the Bridge is already configured.
- **"Migrate from a different wiki tool"** → that's a one-off migration,
  not covered here. Read the pattern doc, then move content manually.

## See also

- [`docs/knowledge-repo-pattern.md`](../../docs/knowledge-repo-pattern.md)
  — the conceptual overview this skill implements.
- [`docs/examples/knowledge-repo/`](../../docs/examples/knowledge-repo/README.md)
  — the templates this skill copies.
- [`workflow/contexts/_template.yaml`](../../workflow/contexts/_template.yaml)
  — the context schema the wizard pre-fills.
- [`protocols/standing-orders/task-sync.md`](../../protocols/standing-orders/task-sync.md)
  — the resolver that honors `sync.wiki.*` and `dual_doku.required`.
