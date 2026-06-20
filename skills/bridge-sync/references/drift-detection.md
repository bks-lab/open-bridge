# /bridge-sync — Cross-repo skill-tree drift detection

A commit-based sync misses two failure modes that survive across runs:

1. **Forward-drop** — a CORE skill exists in source but never reached
   the target. Cause: the originating commit was MIXED scope (e.g.
   `core` + `user`), and the cherry-pick step skipped it whole.
2. **Reverse-leak** — a `scope: user`/`private` skill ended up in a
   public/internal target. Cause: a manual port commit, or a skill
   without `scope:` frontmatter at port-time that was inferred as
   CORE.

Both are invisible to `git log "$SINCE..HEAD"` — the commits in the
window may all be "synced" while the actual file state still drifts.
This document defines the detection + self-correction recipes; Step 0
of `workflow.md` runs them before any cherry-pick happens.

## When this runs

- **Step 0 of `/bridge-sync`** — before classifying commits in the
  current window.
- Manually via `/bridge-audit --check skill-tree-sync` (Check 9).

## Detection

### Build the source truth

For each `skills/*/` directory in the source repo (the seed repo /
local user branch):

```bash
# scope_for(skill) — read scope from SKILL.md frontmatter.
# Skills nest scope under metadata: (metadata.scope) for skill-creator
# conformance; prefer top-level, then metadata.scope. The metadata guard
# avoids false-matching a `scope:` mention inside a description block-scalar.
scope_for() {
  local skill="$1"
  awk '
    /^---$/{f++; next}
    f==1 && /^scope:[[:space:]]/{print $2; exit}
    f==1 && /^metadata:[[:space:]]*$/{m=1; next}
    f==1 && /^[^[:space:]]/{m=0}
    f==1 && m && /^[[:space:]]+scope:[[:space:]]/{print $2; exit}
  ' "skills/$skill/SKILL.md" 2>/dev/null
}
```

A missing `scope:` defaults to `core` (matches `bridge-promote`'s
path-inference). If the skill ships in CORE-allowlisted paths but
has no explicit scope, the audit also raises a P2 in `bridge-audit`
Check 6 — fix that first.

### Build the target truth

Each upstream is checked against its own trunk:

```bash
# your org overlay: development
git ls-tree -d origin/development skills/ | awk '{print $4}' | sed 's|skills/||'
# open-bridge: main
git ls-tree -d origin/main skills/ | awk '{print $4}' | sed 's|skills/||'
```

Run from a fresh `git fetch` of each remote. Working-branch state is
not authoritative — use the merged trunk.

### Compare

For each target repo:

```
expected = { s for s in source if scope_for(s) is allowed_in(target) }
actual   = { s in target's skills/ }

forward_drops = expected - actual   # in source, missing in target
reverse_leaks = actual - expected   # in target, shouldn't be there
```

Allowed-scope-per-target:

| Target | Allowed scopes |
|---|---|
| `open-bridge` | `core` |
| (your org overlay) | `core`, `org` |
| (seed repo / user fork) | all |

A skill currently scoped `user` in source but **present** in
your org overlay is a reverse-leak even if it was originally pushed when
its scope was `core`. The current-state scope is what matters — that
is what governs whether it should ship today.

## Self-correction

The skill surfaces a drift report and offers per-bucket actions. No
auto-apply without user confirmation — the operations are cross-repo
mutations.

### Forward-drop bucket

For each forward-drop:

```
forward-drop: skills/bridge-audit/  → <your-bridge>:development
  Last modified in source: e5c1697 (2026-05-09)
  Why missed: that commit also touched protocols/standing-orders/* (scope: user)
  Action: per-file cherry-pick (drop the user-scope paths)
```

Recipe — per-file cherry-pick that strips user-scope files from a
mixed commit:

```bash
TMP_TARGET=$(mktemp -d)/<target-repo>
git clone -b <branch> <target-url> "$TMP_TARGET"
cd "$TMP_TARGET"
git checkout -b sync-<date>-<time>

# For each MIXED commit that contains forward-drop files:
HASH=<mixed-commit>
git cherry-pick --no-commit "$HASH"

# Drop everything that's not core (or not core+org for your org overlay)
git diff --cached --name-only | while read f; do
  scope=$(determine_scope_in_source "$f")
  case "$scope" in
    user|private) git reset HEAD -- "$f" && git checkout -- "$f" ;;
  esac
done

git commit -C "$HASH"  # reuse original message
```

`determine_scope_in_source` reads the source repo's current scope for
that file (frontmatter for skill/agent files, path-inference for the
rest from `rules/operations.md` § Scope-Routing).

### Reverse-leak bucket

For each reverse-leak:

```
reverse-leak: skills/voice-memos/  in  <your-bridge>:development
  Current source scope: user
  Originally entered target via: 8710175 (2026-05-08)
  Action: remove from target (PR), no source change
```

Recipe — cleanup commit on the target trunk:

```bash
cd "$TMP_TARGET"
git checkout -b cleanup/remove-scope-user-leaks-<date>
for skill in $REVERSE_LEAKS; do
  git rm -r "skills/$skill"
done
git commit -m "chore: remove scope:user skill leaks ($(echo $REVERSE_LEAKS | tr ' ' ', '))

These skills are scope:user in the seed repo and should not have been
synced to <target>. They originally entered via <original-commit-list>
when the scope filter wasn't active. Source state is unchanged.

Detected by: /bridge-sync Step 0 drift-audit."
```

PR title pattern: `chore: remove scope:user skill leaks (N skills)`.
PRs go to the same upstream that owns the leak; never close as
"won't fix" without confirmation — the user may want to re-classify
the source skill instead.

## Surface format

Step 0 always prints the matrix even when there's no drift, so a
clean run leaves a positive trail in the work log:

```
Bridge Sync — Pre-sync drift audit
  Source: user/<your-username> @ a1b2c3d
  Targets:
    open-bridge:main         @ HEAD=e4f5g6h  (fetched <timestamp>)
    <your-bridge>:development @ HEAD=i7j8k9l  (fetched <timestamp>)

  Forward-drops (CORE/org skills missing in target):
    bridge-audit       → open-bridge, <your-bridge>  [from MIXED e5c1697]
    bridge-leak-check  → open-bridge, <your-bridge>  [from MIXED e5c1697]

  Reverse-leaks (scope:user skills present in target):
    expense-tracker    in  <your-bridge>  [via 8710175]
    test-fanout        in  <your-bridge>  [via 8710175]
    voice-memos        in  <your-bridge>  [via 8710175]

  Proceed?
    [y]   Run forward-drop fixes + reverse-leak cleanup as side-PRs alongside the regular sync
    [f]   Forward-drops only — skip reverse-leak cleanup
    [r]   Reverse-leaks only — skip forward-drop fixes
    [n]   Surface only, do nothing (default if non-interactive)
```

Each fix lands as its own PR — never bundled into the main sync PR,
so review can happen independently.

## Why this catches what `git log` misses

The two known failure modes that produced this drift in real life:

1. **Mixed-scope commit `e5c1697`** (2026-05-09): touched 6 files in
   `skills/bridge-audit/` + `skills/bridge-leak-check/` (all
   `scope: core`) **plus** `protocols/standing-orders/drift-advisory.md`
   (`scope: user` per Scope-Routing path-inference). The sync
   workflow (pre-Step-0) classified the commit as MIXED, treated it
   like the `core+org` MIXED case, and skipped it. Step 0 detects
   the file-level drop next time `/bridge-sync` runs even though the
   commit is no longer in the window.

2. **Manual port commit `8710175`** (2026-05-08): direct port of
   `expense-tracker/`, `test-fanout/`, `voice-memos/` to
   the org overlay. `expense-tracker` had no `scope:` field at port time
   (defaulted to CORE), the other two had `scope: user` but the
   port script didn't filter on it. Step 0 catches this on the
   next sync regardless of when it happened.

## Failure modes the recipe still won't catch

- **In-place scope downgrade**: a skill is `scope: core`, gets synced,
  is later changed to `scope: user`. Step 0 flags it as a reverse-leak
  on the next sync — correct. But if `/bridge-sync` doesn't run for
  weeks, the leak persists. Mitigation: also expose this via
  `/bridge-audit --cross-repo` so it surfaces in audits, not just
  syncs.
- **Renamed skill in source, not in target**: a directory rename in
  source produces forward-drop on the new name + reverse-leak on the
  old name. Surface both, let the user decide whether it's a rename
  PR (`git mv` in target) or a fresh forward-drop.
- **Target has a skill scoped differently**: rare, but if the *target*
  repo's copy of a skill has different scope frontmatter, that's a
  separate cross-repo divergence — out of scope here, handled by
  `bridge-audit --cross-repo` content diff.
