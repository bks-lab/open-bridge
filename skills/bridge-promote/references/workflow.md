# /promote — Scope-Routed Cherry-Pick Workflow

Analyzes commits on the user branch and routes them to the right upstream
based on `scope:` frontmatter. Three destinations:

- `bks-lab/open-bridge:main` (OSS, MIT) — for `scope: core` commits
- `<your-org>/<your-bridge>:development` (your org overlay) — for `scope: org`
- stays local on `user/{name}` — for `scope: user` / `private`

Architecture: see CLAUDE.md § Tier Model.

## Trigger

`/promote`, `/promote --dry-run`, `/promote --repo <name>`

## Prerequisites

- Current branch must be `user/*`. Refuses on `development` or `main`.
- `bridge-config.yaml.upstreams[]` lists the available upstream repos.
- `git remote -v` shows at least `origin` (your fork). Both upstreams
  are fetched into named refs by Step 0 below — no manual `git remote
  add` required.

### Default-branch asymmetry

Each upstream has its own default branch. Hardcoding `development`
breaks against open-bridge. Read from `bridge-config.yaml.upstreams[].branch`
or query live: `gh api repos/{owner}/{repo} --jq .default_branch`.
Today (2026-05-08):

| Upstream | Default branch |
|---|---|
| `bks-lab/open-bridge` | `main` |
| `<your-org>/<your-bridge>` | `development` |

## Workflow

### Step 0: Ensure Upstream Refs Exist

For each entry in `bridge-config.yaml.upstreams[]`:

```bash
# read name + repo + branch from bridge-config.yaml; for each entry:
git fetch git@github.com:{repo}.git {branch}:refs/remotes/{name}/{branch}
```

This works whether `git remote add` was ever run — it fetches into a
named ref space. open-bridge typically isn't a configured `git remote`
(only one `upstream` slot exists by convention), so this fetch-by-URL
pattern is the safe default.

### Step 1: Find Promotable Commits

**Histories may be disjoint.** Both `bks-lab/open-bridge` and
`<your-org>/<your-bridge>` were seeded as fresh snapshots from
`<your-username>/your-bridge` rather than forked, so `git log A..B` against an
upstream may return all of `HEAD`'s history (including pre-snapshot
commits). Two strategies:

| When | Use |
|---|---|
| Histories share a merge-base with the target | `git log {upstream}/{branch}..HEAD --oneline --no-merges` |
| Disjoint histories (no merge-base) | `git log --since={snapshot-date} --no-merges HEAD` — pick a date AFTER the upstream's last common point |

Detect disjoint history: `git merge-base HEAD {upstream}/{branch}`
returns empty → fall back to `--since`.

### Step 2: Categorize Each Commit by Scope

Use the helper:

```bash
scripts/categorize-commits.py --since YYYY-MM-DD
# or
scripts/categorize-commits.py --range open-bridge/main..HEAD
# or for one commit:
scripts/categorize-commits.py --commit <sha>
```

It mirrors the path → scope table in `rules/operations.md § CORE/USER
Separation` and reports per-commit `CORE / Org / USER / MIXED` plus a
file-level breakdown for MIXED commits — required input for Step 4
(path-selective cherry-pick).

For deeper inspection of a single commit:

```bash
git diff-tree --no-commit-id --name-only -r {hash}
```

Categorization rules (also encoded in the script):

1. **Frontmatter check (mandatory for skill/agent files)** — if file is
   `skills/*/SKILL.md` or `.claude/agents/*.md`, read the YAML frontmatter
   `scope:`. For **skills** it lives under `metadata:` (`metadata.scope`);
   for **sub-agents** it stays top-level. Resolve top-level first, then
   `metadata.scope` (exactly what `categorize-commits.py`
   `read_frontmatter_scope` does). Valid values: `core`, `org`, `user`,
   `private`. **Missing field → refuse the commit** with hint "skill
   `<name>` has no `scope:` field — add a `scope:` value (`core`, `org` or `user`) under
   `metadata:`". Path-inference fallback does NOT apply for
   skill/agent files because implicit-CORE-by-default is what
   historically shipped scope:user skills to the org overlay when
   their frontmatter was missing.
2. **Path inference** — fall back to `rules/operations.md § CORE/USER
   Separation` table for all non-skill/agent files (docs, rules, root
   configs, etc.).

Commit category from its files' scopes:

| Commit category | Files | Goes to |
|---|---|---|
| `CORE` | all `core` | open-bridge **and** your org overlay |
| `Org` | only `org` (or `core+org`) | your org overlay only |
| `MIXED` | mix that includes `user` | **path-split** in Step 4 — cannot promote whole commit |
| `USER` | all `user` / `private` | stays local |

### Step 3: Per-Destination Content Safety Check (MANDATORY)

Hard gate before any cherry-pick or push — two scans, both required:

**3a. Leak scanner over the files each commit touches:**

```bash
python3 scripts/no-scrub-leak.py $(git diff-tree --no-commit-id --name-only -r {hash})
```

Loads universal classes plus your own roster from
`scripts/leak-patterns-internal.txt` (local-only, never shipped — you
maintain your customer/person regexes there; an empty roster only checks
universal patterns, warn the user once if it's missing).

**3b. Blocklist scan** from `rules/promote-safety.md` **per destination repo**:

```bash
# For commits going to open-bridge
PROMOTE_REPO=open-bridge bash -c '<scan from rules/promote-safety.md>'

# For commits going to your org overlay
PROMOTE_REPO=<your-bridge> bash -c '<scan from rules/promote-safety.md>'
```

open-bridge uses the strict blocklist (Org/customer/personal blocked).
Your org overlay uses the relaxed blocklist (customer refs OK, personal blocked).

A single commit may pass the org-overlay scan but fail open-bridge — that's
expected. Push it only to your org overlay in that case.

**REFUSE path:** a personal-PII or roster hit for a destination means the
commit is **excluded** from that destination — no override, no
rationalization (`rules/promote-safety.md § anti-rationalization`).
Offer: adapt via `/contribute --adapt` then re-scan, or drop the commit
from this promote. Clean commits in the same batch still ship.

### Step 4: Show Results

```
Promote Analysis: 5 commits on user/{name}

  ✓ abc1234  feat: add code-standards order      core    → open-bridge + org overlay
  ✓ def5678  feat: customer-a health-report      org     → org overlay only
  ⚠ ghi9012  fix: ecosystem + persona update    MIXED   → split first (1 core + 1 user)
  ─ jkl3456  update work board                  user    → stays local
  ✓ mno7890  fix briefing command                core    → open-bridge + org overlay

  Routing summary:
    → bks-lab/open-bridge   (2 commits, scope:core, scan: PASS)
    → <your-org>/<your-bridge>   (3 commits, scope:core+org, scan: PASS)
    → local only            (1 commit)

  Proceed? [y]es / [r]eview each / [n]o
```

### Step 5: Cherry-Pick (or Path-Selective Re-Apply)

Two modes — pick the right one per commit:

#### Mode A — `git cherry-pick` (simple commits, shared history)

Works only when the upstream branch shares ancestry with the source
commit. Use for `CORE` / `Org` commits when `git merge-base HEAD
{upstream}/{branch}` returns a hash:

```bash
git stash
git fetch git@github.com:<your-org>/<your-bridge>.git development:refs/remotes/org-overlay/development

# org overlay: all CORE + Org commits
git checkout -b promote-org-overlay org-overlay/development
git cherry-pick {core-commits} {org-commits}

# open-bridge: only CORE commits (default branch is `main`, not `development`)
git fetch git@github.com:bks-lab/open-bridge.git main:refs/remotes/open-bridge/main
git checkout -b promote-open-bridge open-bridge/main
git cherry-pick {core-commits}

git checkout user/{name}
git stash pop
```

#### Mode B — Path-selective re-apply (MIXED commits, disjoint history)

For MIXED commits OR when histories are disjoint (no merge-base), full
cherry-pick fails or carries unwanted user/org files. Re-apply only the
allowed paths:

```bash
git checkout -b promote-open-bridge open-bridge/main

# For each MIXED commit, check out only the CORE-scoped paths:
for commit in {mixed-commits}; do
  # categorize-commits.py --commit X --json gives the file→scope map
  CORE_FILES=$(scripts/categorize-commits.py --commit $commit --json \
               | jq -r '.files | to_entries[] | select(.value=="core") | .key')
  git checkout $commit -- $CORE_FILES
done

# Then group into one or more semantic commits with adapted messages
git commit -m "feat(...): {summary} (cherry from {short-shas})"
```

The same approach with `select(.value=="org" or .value=="core")` for
the org-overlay target.

**Why path-selective:** disjoint history means cherry-pick has no parent
to diff against and may produce empty patches or massive conflicts.
`git checkout {commit} -- {paths}` ignores history and just copies the
file contents at that commit into the working tree of the destination
branch. Re-applying as fresh commits is the honest model — the
destination repo is not "missing" the source commit, it's a different
project that wants the same content.

### Step 6: Push — fork flow for open-bridge

External contributors have **no push access to `bks-lab/open-bridge`**,
and `origin` (your Bridge instance) is usually not a GitHub fork of it —
a cross-fork PR head must live in a real fork of the base repo. So:

```bash
# org overlay: push to a repo you can write to (often the overlay itself
# or your fork of it — whatever `upstream`/your access allows)
git push origin promote-org-overlay:promote-org-overlay-{date}

# open-bridge: one-time fork, then push the branch THERE
gh repo fork bks-lab/open-bridge --clone=false
git remote add ob-fork git@github.com:{your-username}/open-bridge.git 2>/dev/null || true
git push ob-fork promote-open-bridge:promote-open-bridge-{date}
```

### Step 7: Create PRs

Use `gh pr create --repo` per destination. open-bridge requires DCO
sign-off on upstream PRs — make sure every promoted commit carries
`Signed-off-by` (`git commit -s`, or `git rebase --signoff` on the
promote branch before pushing):

```bash
# PR to your org overlay
gh pr create --repo <your-org>/<your-bridge> \
  --base development \
  --head <your-username>:promote-org-overlay-{date} \
  --title "{commit summary}" \
  --body "Cherry-picked from user branch. Commits: {list}"

# Cross-fork PR to open-bridge, head = branch in YOUR fork
gh pr create --repo bks-lab/open-bridge \
  --base main \
  --head {your-username}:promote-open-bridge-{date} \
  --title "{commit summary}" \
  --body "Cherry-picked from user branch. Commits: {list}"
```

Show PR URLs on success.

## --repo override

If `/promote --repo open-bridge` is passed:
- All scope filtering is bypassed
- ALL commits from `development..HEAD` are pushed to that repo
- The content-safety scan runs with that repo's blocklist
- Useful for: emergency contributions, manual overrides

```bash
PROMOTE_REPO=open-bridge git ...
```

## Pull from upstream

After successful PRs are merged at upstream, pull back:

```bash
git fetch upstream
git checkout user/{name}
git merge upstream/development                   # org-overlay updates
# open-bridge updates flow into your org overlay first via its sync,
# then to your fork via the merge above. No direct fetch from
# open-bridge needed unless the overlay is behind.
```

`/briefing` will surface upstream drift automatically when
`pull_interval_days` exceeds the configured threshold.
