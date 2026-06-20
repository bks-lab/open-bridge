# PR Recovery Patterns (GitHub)

Generic Git/GitHub patterns for recovering from common PR failures that hit
during fast-iteration sprints (multiple PRs against the same base). Lives in
the `bridge-sync` skill because that's where you most likely hit them, but
the patterns are useful for ANY PR work.

## Pattern 1 — Stale-Ancestor After Squash-Merge

### Symptom

```
$ gh pr merge 13 --repo X/Y --squash --delete-branch
X Pull request X/Y#13 is not mergeable: the merge commit cannot be cleanly created.
To have the pull request merged after all the requirements have been met, add the `--auto` flag.
```

Even though the PR shows no actual file conflicts in the UI.

### Cause

When GitHub squash-merges PR-A onto `main`, it creates a NEW commit on main
that contains all of PR-A's diff. That commit's SHA is not a true ancestor
of PR-A's original commits. PR-B that was branched from `main` BEFORE PR-A's
squash-merge then has no clean ancestor with current main — even if there are
no file-level conflicts. GitHub's merge UI often can't auto-resolve this.

### Recovery — Variant A: rebase + force-push

When the feature branch is local and not too divergent:

```bash
cd <repo>
git checkout <feature-branch>
git fetch origin <base>                # default 'main' or 'development'
git rebase origin/<base>               # resolve any conflicts, rebase --continue
                                       # OR: commits may be "skipped previously
                                       # applied" — that's fine, the squash
                                       # already absorbed them
git push --force-with-lease origin <feature-branch>
gh pr merge <num> --squash --delete-branch
```

`--force-with-lease` is critical — protects against parallel pushes to the
branch by someone else.

### Recovery — Variant B: fresh branch + cherry-pick

When rebase produces too many conflicts or you want a clean history:

```bash
git fetch origin <base>
LAST_GOOD_SHA=$(git rev-parse <feature-branch>)   # save the commit you care about

git checkout <base>
git pull --ff-only
git checkout -b <feature-branch>-v2
git cherry-pick $LAST_GOOD_SHA

git push -u origin <feature-branch>-v2

# Close old PR, open new
gh pr close <old-num> --comment "Stale ancestor. Recreated as #<new>."
gh pr create --base <base> --head <feature-branch>-v2 \
  --title "..." --body "..."
gh pr merge <new-num> --squash --delete-branch
```

### What NOT to do

- **`gh pr merge --auto`** — waits for CI checks, but the ancestor conflict
  doesn't resolve itself by waiting
- **`gh pr update-branch` / GitHub UI "Update branch"** — sometimes works,
  often doesn't because the conflict is at history-level not file-level

## Pattern 2 — Preventing Stale-Ancestor in Sequential PRs

If you're shipping multiple PRs against the same base in quick succession:

1. **Branch each feature ALWAYS from `origin/<base>`** — not from another
   feature branch
2. **After each PR-merge, rebase remaining open branches IMMEDIATELY:**
   ```bash
   git fetch origin <base>
   for br in $(git branch --list 'feat/*' 'fix/*' --format '%(refname:short)'); do
     git checkout $br
     git rebase origin/<base> || git rebase --abort
   done
   ```
3. **Or use a stacked-PR tool** (graphite, ghstack, spr) if you have many
   sequential PRs — those tools handle the ancestor walk automatically

## Pattern 3 — Branch / Local State Diverged from Remote

### Symptom

```
$ git pull --ff-only origin main
fatal: Not possible to fast-forward, aborting.
```

Or:

```
$ git push origin user/<name>
! [rejected] user/<name> -> user/<name> (non-fast-forward)
```

### Cause

A daemon, hook, or concurrent CLI session pushed to the remote while you
were working locally.

### Recovery

```bash
git fetch origin
git log --oneline origin/<branch>..HEAD   # what's local-only
git log --oneline HEAD..origin/<branch>   # what's remote-only

# Decide: rebase, merge, or reset
# Most common: rebase your local commits onto remote
git rebase origin/<branch>
git push origin <branch>
```

If your local changes weren't important and remote is authoritative:
```bash
git reset --hard origin/<branch>           # destructive — only when sure
```

## Pattern 4 — Commit on the Wrong Branch

### Symptom

You committed to a feature branch but actually wanted main, or vice-versa.

### Recovery

```bash
# Get the commit SHA you want to move
WRONG_SHA=$(git rev-parse HEAD)

# Switch to the right branch
git checkout <target-branch>
git pull --ff-only

# Cherry-pick the commit
git cherry-pick $WRONG_SHA

# Clean up the wrong branch (reset to before the commit)
git checkout <wrong-branch>
git reset --hard HEAD~1   # destructive — verify with git log first
```

If the commit was already pushed to the wrong branch:
- For unmerged feature branches: `git push --force-with-lease`
- For protected main: don't try to delete the commit, push a revert instead

## Heuristic — when to use which variant

| Situation | Recovery |
|---|---|
| 1 small commit, want clean history | Variant B (fresh branch + cherry-pick) |
| Multi-commit feature, complex changes | Variant A (rebase + force-with-lease) |
| `--auto` worked / will work after CI | Just `--auto` |
| Concurrent push you didn't expect | Pattern 3 (fetch + decide) |
| Wrong branch | Pattern 4 (cherry-pick + reset) |

## Real-world frequency

In a static-site → Cloudflare Pages migration (2026-05-24), Pattern 1 hit
4 times across two repos in an 8-hour sprint:

- web-repo PR #45 → closed, recreated as #46
- docs-repo PR #13 → closed, recreated as #14
- web-repo PR #51 → rebased + force-push (Variant A)
- One more iteration during workflow fixes

Documented as a memory entry in `~/.claude/.../memory/reference_pr_stale_ancestor_recovery.md`
and surfaced here for ship-via-bridge-sync to all variants.

## Cross-references

- [[bridge-sync workflow.md]] — Step 5 conflict resolution patterns
- `feedback_default_branch_via_gh_api` (memory) — always `gh api repos/X --jq
  .default_branch` before PR to avoid base-mismatch
- `feedback_bridge_sync_diverged_files` (memory) — `format-patch -1 | git am
  --3way` for CLAUDE.md/README.md that diverged at the file level
