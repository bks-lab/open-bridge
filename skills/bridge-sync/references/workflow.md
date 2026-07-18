# /bridge-sync — Batch sync workflow

End-of-sprint operation: push **all** pending scope:core + scope:org
commits from `user/*` to both `bks-lab/open-bridge:main` and
`<your-org>/<your-bridge>:development` in one go, with per-destination
scrubbing and parallel PR creation.

> **Destination resolution — read from config, never hardcode.** Each destination's
> target repo + base branch come from `bridge-config.yaml.upstreams[]` (`.repo` /
> `.branch`), and the scrub / content-blocklist / override key is the upstream
> **logical `name`** (e.g. `open-bridge`), **not** the repo basename. This lets a
> *pre-public* instance temporarily point its `open-bridge` upstream at a private
> work/archive repo until the public repo is cut fresh — strict OSS scrubbing still
> applies (keyed by the name), so the eventual public cut stays clean. The
> `bks-lab/open-bridge:main` / `<your-org>/<your-bridge>:development` literals in the
> examples below are illustrative defaults — resolve the real target from config.

## Workflow

### Step 0: Pre-sync drift audit

Before classifying commits, run cross-repo skill-tree drift detection
against each target's trunk. This catches forward-drops (CORE skills
missing in target) and reverse-leaks (scope:core skills present in
target) that survive across windows because they're file-state, not
commit-state, drift.

Full algorithm + recipes: [`drift-detection.md`](drift-detection.md).

```bash
git fetch <each-upstream> <each-base-branch> --quiet
# Compare source skills/*/ (with current scope frontmatter) against
# each target's git ls-tree of skills/. Build forward_drops and
# reverse_leaks per target. Surface the matrix and ask before fixing.
```

If drift is found, fixes land as **side-PRs** alongside the main
sync — never bundled with the commit-based sync PR. Forward-drops
use per-file cherry-pick (drops the user-scope paths from a MIXED
commit); reverse-leaks use a `git rm -r` cleanup branch on the
target's trunk.

If `[n]` (surface only) is chosen — or if Step 0 runs non-interactively
— log the matrix to `work/log.md` and continue with Step 1. The drift
will resurface on the next sync.

### Step 1: Determine sync window

```bash
# Default: since the last bridge-sync tag (created by Step 9)
SINCE=$(git tag --list 'bridge-sync-*' --sort=-creatordate | head -1)
[ -z "$SINCE" ] && SINCE="upstream/development"   # first sync ever

# Or override with --since <ref>
git log "$SINCE..HEAD" --oneline --no-merges
```

### Step 2: Per-commit scope classification

For each commit in the window, classify:

```bash
git diff-tree --no-commit-id --name-only -r {hash}
```

For each file → scope (`core` / `org` / `user`/`private`):
1. **Skill/agent files (`skills/*/SKILL.md`, `.claude/agents/*.md`)** —
   require explicit `scope:` frontmatter. **Refuse the commit** if any
   skill/agent file in it lacks the field. Hint: "skill `<name>` has no
   `scope:` field — add a `scope:` value (`core`, `user` or `org`) to the frontmatter and
   re-commit". Implicit-CORE-by-default is the bug that produced the
   `expense-tracker`/`test-fanout`/`voice-memos` reverse-leaks (a
   scope-less skill defaulted to CORE and got shipped). Step 0
   reverse-leak detection catches it after the fact; refuse-on-missing
   prevents it at the source.
2. Path inference for all other files from `rules/operations.md`
   § Scope-Routing table (docs, rules, root configs, etc. —
   these have no frontmatter, so path is the only signal).

Then classify the **commit**:

| Files in commit | Commit category |
|---|---|
| All `core` | `CORE` — goes to open-bridge AND your org overlay |
| All `org` (or core+org) | `ORG` — goes to your org overlay only |
| Mixed `core`+`org` | `MIXED-CB` — split required (`/promote` instead) |
| Mixed `core`/`org` + `user` | `MIXED-CU` — per-file cherry-pick (drop user-scope paths) |
| All `user`/`private` | `LOCAL` — skip |

`MIXED-CB` (core+org) commits: refuse with hint "split this commit
before running /bridge-sync, or use /promote per-commit". Bundling
core and org fixes into one upstream commit is wrong because they
go to different repos.

`MIXED-CU` (core/org + user) commits: do **not** skip. Use the
**MIXED-CU recipe** below. The resulting commit on the target only
contains the core/org files. This prevents forward-drops like `e5c1697`
(which mixed `skills/bridge-audit/*` user-files with a USER-scope
standing order and was historically skipped). See `drift-detection.md`
§ "Forward-drop bucket" for more context.

#### MIXED-CU recipe (apply per-commit during Step 5)

```bash
# Stage everything from the source commit
git cherry-pick -n "$hash"

# DU conflicts will appear if user-paths were deleted in the destination.
# That's fine — we're about to drop them all anyway. Reset everything,
# then re-checkout ONLY the core/org paths from the source commit.
git reset HEAD -- .

# Clean working-tree leftovers from -n cherry-pick (user-scope dirs
# that got added but are now unstaged). Hard-coded list of USER roots:
git clean -fdq work/ identity/personas/ identity/accounts/ \
                identity/mandants/ workflow/calendars/entries.yaml 2>/dev/null

# Re-checkout only the CORE/org paths from the source commit.
# Two cases — most files are identical between seed and destination
# (safe full checkout); files that INTENTIONALLY diverge (CLAUDE.md,
# README.md — per-tier framing differs) must get the COMMIT'S DIFF
# applied, not the whole seed file.
DIVERGED_FILES="CLAUDE.md README.md"   # files that differ seed ↔ upstream
for path in $CORE_ORG_PATHS_IN_THIS_COMMIT; do
  if echo " $DIVERGED_FILES " | grep -q " $path "; then
    # Apply only this commit's diff for the file (preserves the
    # destination's own divergent content). --3way escalates to a
    # real conflict if the destination also touched these lines.
    git --git-dir="$SEED_REPO_PATH/.git" format-patch -1 --stdout "$hash" -- "$path" \
      | git am --3way --keep-non-patch
  else
    # Identical between seed and destination → safe to take the seed copy.
    git checkout "$hash" -- "$path"
  fi
done

# Commit the non-diverged paths preserving original author + message.
# (Diverged files were already committed by `git am` above; if every
# path was diverged, there is nothing left to stage and this is skipped.)
git diff --cached --quiet || git commit -C "$hash"
```

**Why the split — never `git checkout <hash> -- file` for a diverged file.**
`git checkout <hash> -- file` is "get the file *out of* that commit", not
"apply that commit's *diff*". For `CLAUDE.md` / `README.md` the seed and the
upstream hold the file differently on purpose (per-tier framing), so a blind
checkout replaces the upstream's whole file with the seed's — the symptom is a
single commit reporting e.g. `1 file changed, 179 insertions(+), 305
deletions(-)` when the original commit only added ~70 lines. `format-patch -1
| git am --3way` applies just the diff and lets git 3-way-merge it onto the
destination's version; a resulting `UU` conflict is a genuine semantic conflict
to escalate (Conflict recipe **B**), not something to silently overwrite.

Don't use `git cherry-pick "$hash"` (without `-n`) on a MIXED-CU commit
— it produces "DU" conflicts on every user-path because the destination
never had those files. The `-n` + selective-checkout pattern sidesteps
the noise.

### Step 3: Per-destination content-safety scan

This runs in **two passes** per destination — first apply `scrub_rules`
(auto-rewrites configured in `bridge-config.yaml.promote.scrub_rules.<dest>`),
then run the `content_blocklist` scan on what remains.

```bash
# For commits going to open-bridge
for hash in $CORE_COMMITS; do
  # Pass 1 — simulate scrub_rules and check remaining hits
  PROMOTE_REPO=open-bridge bash <(echo "$(cat rules/promote-safety.md scan-block)")
done

# For commits going to your org overlay
for hash in $CORE_COMMITS $ORG_COMMITS; do
  PROMOTE_REPO=<your-bridge> bash <(echo "$(cat rules/promote-safety.md scan-block)")
done
```

The scan classifies each hit into three buckets (see `promote-safety.md`
§ "Three remediation paths"):

| Bucket | Meaning | Sync behavior |
|---|---|---|
| **scrubable** | Hit matches a `scrub_rules.<dest>` pattern (auto-rewrite exists) | Proceed to Step 5 — scrub applies during cherry-pick |
| **adaptable** | Hit is semantic content with no auto-rewrite (e.g. concrete repo refs, customer names embedded in examples) | **Defer this commit for that destination** — surface in matrix as 🟡 with "needs /contribute --adapt" |
| **personal-PII** | Hit is real personal data with no fix-in-place (real names in examples, ID numbers) | **Refuse the commit** — user must rework the source |

If a destination ends up with zero clean commits and only adaptable
ones, route the matrix to "🟡 partial — N commits clean, M deferred"
rather than aborting the sync wholesale. The other destination (if
its strictness is lower) may still take all commits.

### Step 4: Show routing matrix

```
Bridge Sync — window: bridge-sync-2026-04-26 .. HEAD (12 commits)

  → bks-lab/open-bridge   (8 commits, all scope:core)
     a1b2c3d  feat: add code-standards order          PASS
     e4f5g6h  fix: yamllint commas-config              PASS
     i7j8k9l  refactor: validate-bridge surface map    PASS
     ...
     [scrub-target list: 3 pattern matches in 2 files — auto-replace before push]

  → <your-org>/<your-bridge>   (12 commits, 8 core + 4 org)
     a1b2c3d  (same as above)
     ...
     m0n1o2p  feat: customer-a health-report v3        PASS
     q3r4s5t  feat: doc-routing context update          PASS

  → local only            (0 commits)

  Open-bridge scrub preview (3 hits):
     skills/bridge-sync/SKILL.md:42     "<bks-lab>" → "{org}/" in code-fences (1×)
     docs/feature-tour.md:88            "<your-username>" → "{user}" (2×)

  Proceed?
    [y]es        Push to both, create 2 PRs
    [r]eview     Show full diffs first
    [o]b only    Sync only to open-bridge
    [g] org only Sync only to your org overlay
    [n]o         Abort
```

### Step 5: Parallel cherry-pick + scrub

Two independent temp clones in `/tmp` for parallel operation. Within
each clone, walk the commits in chronological order and apply the
right recipe per category.

```bash
TMP_ORG=$(mktemp -d)/org-overlay
git clone -q -b development git@github.com:<your-org>/<your-bridge>.git "$TMP_ORG"
cd "$TMP_ORG"
git remote add saat "$SEED_REPO_PATH"
git fetch -q saat user/<name>
git checkout -b "sync-$(date +%Y-%m-%d-%H%M)"

# Per-commit dispatch
for hash in $WINDOW_COMMITS_CHRONOLOGICAL; do
  case "${CAT[$hash]}" in
    CORE|ORG)        cherry_pick_full "$hash"     ;;
    MIXED-CU)        cherry_pick_partial "$hash"  ;;  # see § Step-2 MIXED-CU recipe
    LOCAL|MIXED-CB)  continue                     ;;
  esac
  apply_scrub_rules "$DEST_REPO"     # see § scrub_rules below
  add_dco_signoff_if_open_bridge
done
```

Same flow for `TMP_OB=$(mktemp -d)/open-bridge` with `git clone … open-bridge`,
branch from `main`, and DCO sign-off enabled.

#### Conflict recipes (apply during cherry-pick as needed)

Three conflict types come up in practice; each has a deterministic recipe.

**A) `DU` — destination doesn't have the file the source modifies**

```bash
# Source commit modifies a file that doesn't exist in destination.
# Resolution: take theirs (add the file from the source).
git checkout "$hash" -- "$conflicted_file"
git add "$conflicted_file"
git cherry-pick --continue --no-edit
```

Common cause: the destination diverged and removed the file earlier
(e.g. open-bridge dropped `bridge-config.yaml.template` once), or the
file is new and the destination simply never had it.

**B) `UU` — both sides modified, divergent structure**

```bash
# Source and destination both edited the file in incompatible ways
# (e.g. seed's 10-step onboarding workflow vs OSS variant's 7-step
# workflow). Auto-merge fails.

# Decision: can the source's intent land in destination's structure?
if SOURCE_CHANGE_FITS_DESTINATION_STRUCTURE; then
  # Take theirs verbatim
  git checkout "$hash" -- "$conflicted_file"
  git add "$conflicted_file"
else
  # Drop the file from this cherry-pick — keep destination's version
  git checkout HEAD -- "$conflicted_file"
  git add "$conflicted_file"
  DEFERRED_FILES+=("$conflicted_file")  # accumulate for commit-message note
fi

git cherry-pick --continue --no-edit

# After cherry-pick succeeds, if files were deferred, amend message:
if [ ${#DEFERRED_FILES[@]} -gt 0 ]; then
  git commit --amend -m "$(git log -1 --format=%B)

Note: ${#DEFERRED_FILES[@]} file(s) deferred — destination has divergent
structure that needs manual adaptation: ${DEFERRED_FILES[*]}"
fi
```

**C) `AA` / merge conflicts in shared content** — escalate to user.
These mean genuine semantic conflict; don't auto-resolve.

#### scrub_rules application (between cherry-pick and commit-finalize)

The `scrub_rules.<destination>` block in `bridge-config.yaml` defines
auto-rewrites. The skill compiles them into a single `perl -i -pe`
expression and runs it over files touched by the cherry-pick.

```bash
apply_scrub_rules() {
  local dest="$1"
  # Compile scrub_rules.<dest> into a perl substitution chain
  local perl_expr
  perl_expr=$(yq -r "
    .promote.scrub_rules.\"${dest}\" // []
    | map(\"s|\" + .pattern + \"|\" + .replacement + \"|g;\")
    | join(\" \")
  " "$BRIDGE_REPO_PATH/bridge-config.yaml" 2>/dev/null)

  [ -z "$perl_expr" ] && return 0

  # Apply over the just-cherry-picked diff (not the whole tree)
  git diff HEAD~1 --name-only --diff-filter=ACMR -z | \
    xargs -0 -I{} sh -c '[ -f "$1" ] && [ ! -L "$1" ] && perl -i -pe "$2" "$1"' \
                  _ {} "$perl_expr"

  # Fold scrub changes back into the cherry-picked commit
  if ! git diff --quiet; then
    git add -A
    git commit --amend --no-edit
  fi
}
```

Notes:
- Skip symlinks (`! -L`) — perl `-i` errors on directory-symlinks
  (`.claude/skills/`) and aborts the xargs entry.
- Run scrub AFTER cherry-pick, BEFORE the final commit (or `--amend`
  immediately after) so scrub changes don't appear as a separate commit
  in the upstream history.
- DCO sign-off (`git commit --amend -s --no-edit`) happens AFTER scrub
  on open-bridge.

### Step 6: Post-cherry-pick safety scan + residual-leak fixup

Re-run the safety scan on the **post-scrub** state of each destination
clone — but distinguish new leaks (introduced by our cherry-picks)
from pre-existing leaks (already in the destination branch tip).

```bash
# Scan files that our cherry-picks touched, not the whole tree.
TOUCHED=$(git log origin/<base-branch>..HEAD --name-only --format= | sort -u | grep -v '^$')

for f in $TOUCHED; do
  [ -f "$f" ] || continue
  hits=$(scan_file_against_blocklist "$f" "$DEST")
  if [ "$hits" -gt 0 ]; then
    # Is this leak in lines our cherry-picks added, or already there?
    added_by_us=$(git log origin/<base-branch>..HEAD -p -- "$f" | \
                  grep -E "^\+" | grep -EcI "$BLOCKLIST_PATTERN")
    if [ "$added_by_us" -gt 0 ]; then
      RESIDUAL_NEW_LEAKS+=("$f")
    else
      PRE_EXISTING_LEAKS+=("$f")
    fi
  fi
done
```

**Residual new leaks** (something the scrub_rules didn't catch — typo
in the rule, missed pattern variant): apply the **fixup-and-rebase
pattern** to fold the fix into the original cherry-picked commit so
upstream sees a single clean commit.

```bash
# Manual scrub on residual files
for f in "${RESIDUAL_NEW_LEAKS[@]}"; do
  perl -i -pe "$EXTRA_SCRUB_EXPR" "$f"
  git add "$f"
done

# Find which of our cherry-picked commits introduced the offending line
LEAK_ORIGIN_HASH=$(git log origin/<base-branch>..HEAD --format=%H -- "$f" | head -1)

# Create a fixup commit + autosquash-rebase to fold it in
git commit --fixup="$LEAK_ORIGIN_HASH" --no-edit
git -c sequence.editor=true rebase -i --autosquash "origin/<base-branch>"
```

This produces a history where the leak never appeared — important
because the commit message ends up in the upstream `git log` permanently.

**Pre-existing leaks** (already on the destination branch tip before
our sync): don't block the sync. Log them, surface for a follow-up
`cleanup/scrub-pre-existing-leaks` PR (see Step 12).

Hard-fail only if there are residual NEW leaks AFTER fixup, or if the
fixup pattern wasn't applicable (e.g. leak is in commit message — that
requires `git rebase -i --edit` + reword, which is interactive and
should escalate to user).

### Step 7: Push branches to user fork

```bash
cd "$TMP_ORG"
git push origin sync-$(date +%Y%m%d-%H%M):sync-$(date +%Y%m%d-%H%M)
cd "$TMP_OB"
git push origin sync-$(date +%Y%m%d-%H%M):sync-$(date +%Y%m%d-%H%M)
```

### Step 8: Create PRs

```bash
# PR to your org overlay
gh pr create --repo <your-org>/<your-bridge> \
  --base development \
  --head {your-username}:sync-{date}-{time} \
  --title "Bridge sync ${SINCE}..HEAD ($(echo $ALL_COMMITS | wc -w) commits)" \
  --body "$(cat <<'EOF'
End-of-sprint batch sync from <your-username>/your-bridge.

## Commits ($(echo $ALL_COMMITS | wc -w))
{list of commits with scope tags}

## Safety
- Content-safety scan: PASS (PROMOTE_REPO=<your-bridge>)
- Per-destination blocklist applied
EOF
)"

# PR to open-bridge (DCO required)
gh pr create --repo bks-lab/open-bridge \
  --base main \
  --head {your-username}:sync-{date}-{time} \
  --title "Bridge sync ${SINCE}..HEAD ($(echo $CORE_COMMITS | wc -w) commits)" \
  --body "$(cat <<'EOF'
End-of-sprint batch sync from <your-username>/your-bridge.

Only scope:core commits included; user-specific changes are in
<your-org>/<your-bridge> in the matching sync branch.

## Commits ($(echo $CORE_COMMITS | wc -w))
{list of commits, all DCO-signed}

## Safety
- Per-destination scrub applied
- Content-safety scan: PASS (PROMOTE_REPO=open-bridge)
- DCO sign-off on every commit (`git commit -s`)
EOF
)"
```

### Step 9: Tag the sync point

After both PRs are created (not necessarily merged):

```bash
git tag "bridge-sync-$(date +%Y-%m-%d-%H%M)"
git push origin "bridge-sync-$(date +%Y-%m-%d-%H%M)"
```

The tag is the marker for the next `/bridge-sync --since`.

### Step 10: Show summary

```
Bridge Sync complete.

  → bks-lab/open-bridge   PR #42  https://github.com/bks-lab/open-bridge/pull/42
  → <your-org>/<your-bridge>   PR #15  https://github.com/<your-org>/<your-bridge>/pull/15

  Tag: bridge-sync-2026-05-03-1130
  Next sync window starts here.

  Merge order recommendation:
    1. Merge your org overlay first (internal review is usually faster)
    2. Then open-bridge (DCO + Closed-Beta-review may take longer)
    3. After both merged, /bridge-sync re-uses the tag for the next batch
```

### Step 11: Post-merge verification (after both PRs land)

After the user merges both PRs, the source-side scan that ran in Step 3
+ Step 6 only proves THIS sync was clean. It does NOT prove the
destination is overall clean — pre-existing drift may still be there
from prior promotes, manual edits, or seedings.

For each merged destination:

```bash
# Fresh shallow-clone the merged state
TMP_VERIFY=$(mktemp -d)/verify-<repo>
git clone --depth=1 -b <base-branch> git@github.com:bks-lab/<repo>.git "$TMP_VERIFY"

# Run categorized leak check
bridge-leak-check --repo <repo> --strict-oss --target-dir "$TMP_VERIFY"
```

The `bridge-leak-check` skill (sibling to this one) sorts hits into:
- ✅ legitimate self-reference (skip)
- ✅ legitimate sister-repo (skip)
- 🔴 personal PII (always leak — propose follow-up PR)
- 🟡 internal-vocabulary hardcoded (OSS-strict only — propose follow-up PR)

If only the legitimate buckets have hits → done.
If 🔴 or 🟡 hits exist → proceed to Step 12.

### Step 12: Optional follow-up PR for pre-existing leaks

For any 🔴 / 🟡 hit found in Step 11:

1. Surface the categorized list to the user.
2. Ask: "These are pre-existing leaks (not from this sync). Should I
   create a follow-up `cleanup/scrub-pre-existing-leaks` PR?"
3. If yes:
   - Branch from the merged HEAD of the destination
   - Apply suggested scrubs (per category):
     - 🔴 personal PII → replace with `<your-username>` placeholders
     - 🟡 internal-vocabulary → use canonical replacements from
       `skills/bridge-audit/data/renames.yaml § vocabulary_renames`
   - Re-run `bridge-leak-check` to confirm clean
   - Push + PR + standard merge cycle
4. If no: log the hits to `work/log.md` so they don't get forgotten.

**Why this exists:** the session that birthed this rule found 3
pre-existing leaks in the OSS upstream (a launchd-label example
hard-coded `com.{org}.my-service`, an org wordmark in DESIGN.md, a
discovery example using a personal-username-prefixed filename) that
no source-side scan would have caught — they predated the safety
blocklist. Step 11+12 close that gap.

## --repo override

`/bridge-sync --repo open-bridge`:
- Same flow, only pushes to open-bridge
- All scope:org commits in the window are warned about (silently skipped)
- Tag still created (with `-ob` suffix)

`/bridge-sync --repo <your-bridge>`:
- Same, only the org-overlay target
- scope:core commits go too (because the org overlay merges open-bridge regularly anyway)
- Tag suffix `-user`

## Recovery from failed sync

If Step 5 cherry-pick conflicts (rare — disjoint paths usually prevent this):
1. Resolve in `$TMP_OB` / `$TMP_ORG` manually
2. `git cherry-pick --continue`
3. Resume from Step 6

If Step 6 safety scan fails:
1. Note the offending pattern + file
2. Add to `bridge-config.yaml.promote.content_blocklist.<repo>.strings`
   OR adapt the source commit on the user branch
3. Re-run `/bridge-sync` (it will re-scan from scratch)

If Step 8 PR creation fails (rate limits, network):
- Branches are already pushed — just retry `gh pr create` manually
- Or rerun `/bridge-sync` — it detects existing branches and skips Step 5+7

If `gh pr merge` fails AFTER Step 8 with a stale-ancestor error (squash-merge
of a prior PR against the same base broke the new PR's ancestry — not a
conflict a human resolution in the GitHub UI can fix): see
[`pr-recovery-patterns.md`](pr-recovery-patterns.md) Pattern 1.
