# Inbound Status: are we behind on anything?

A Bridge receives content on **two independent channels**, and being behind on
either one is invisible until someone looks. This file is the read-only check that
looks, for `/briefing` and `/archive`.

| Channel | Source | Arrives as | Managed by |
|---------|--------|------------|------------|
| **CORE** | the `role: oss-core` upstream | git commits merged into the current branch | git |
| **Overlays** | every `role: org-overlay` upstream that carries a `materialize:` block | file copies tracked in `overlays.lock.yaml` | `scripts/overlay.py` |

> **Read-only.** This check fetches and predicts. It never merges, never
> materializes, never edits config. Every action it offers is a handoff to the
> tool that owns that channel.

## Prerequisites

Resolve these from config; skip whatever does not apply. A Bridge with no
upstreams at all (a fresh clone, or the OSS seed repo itself) skips the whole file.

1. `bridge-config.yaml` has an `upstreams:` **list**. Each entry carries `name`,
   `repo` (`owner/name`), `branch`, and `role`.
2. **CORE channel** applies when exactly one entry has `role: oss-core`. More than
   one is a config error: report it and skip the channel rather than guessing.
3. **Overlay channel** applies per entry with `role: org-overlay` **and** a
   `materialize:` block. An org-overlay without that block is one this instance
   *authors*, not consumes. Skip it silently; it is not a subscription.

### Resolving the git remote (do not match on the remote's name)

The remote for the CORE upstream is whatever remote **points at that repo**. Its
name is arbitrary and frequently is not `upstream`. Match on the URL:

```bash
# $REPO is upstreams[].repo for the role:oss-core entry, e.g. "acme/their-core"
git remote -v | awk '/\(fetch\)$/ {print $1, $2}' | while read -r name url; do
  norm=$(printf '%s' "$url" | sed -E 's#^git@[^:]+:##; s#^https?://[^/]+/##; s#\.git$##')
  [ "$norm" = "$REPO" ] && printf '%s\n' "$name"
done
```

No match means the upstream is configured but has no remote. Report that as the
finding (it is one) and offer the fetch-only remote as a fix. Do not invent a name.

## Step 1: CORE channel

```bash
git fetch --no-tags "$REMOTE" "$BRANCH"

BEHIND=$(git rev-list --count "HEAD..$REMOTE/$BRANCH")
AHEAD=$(git rev-list --count "$REMOTE/$BRANCH..HEAD")
```

`BEHIND` is the backlog, and it is the number this check exists to surface.

`AHEAD` is **not** "commits waiting to be promoted", and reporting it that way is
actively misleading. On a Bridge where CORE and USER share one branch it counts the
entire divergence, which is overwhelmingly USER work that must never go up: four
figures is normal and means nothing. Classify it before showing it, or leave it out:

```bash
python3 scripts/categorize-commits.py --range "$REMOTE/$BRANCH..HEAD" --json
```

Count only the CORE tier (and mention MIXED separately, since those carry both and
need a per-file decision). The gap between the raw number and the classified one is
usually an order of magnitude, which is exactly why the raw one must not be printed
next to the words "not yet promoted".

Whatever survives that filter is **context, never a blocker**. Pulling before
pushing is what makes the round trip safe, so unpromoted local CORE is a reason to
route the user to `/promote` afterwards, not a reason to withhold the pull.

If `BEHIND` is 0, the channel is current. Say so in one line and move on.

### Predict the merge without touching the working tree

```bash
git merge-tree --write-tree --name-only --messages HEAD "$REMOTE/$BRANCH"
```

This writes a tree into the object store and prints the conflicting paths plus
git's own labels (`CONFLICT (content)` versus `CONFLICT (add/add)`). The working
tree is not touched, so this is safe to run inside a read-only briefing.

> On git older than 2.38 the `--write-tree` form does not exist. Fall back to
> `git merge-tree $(git merge-base HEAD "$REMOTE/$BRANCH") HEAD "$REMOTE/$BRANCH"`
> and grep for `CONFLICT`, or state that conflict prediction is unavailable.
> Never claim "clean merge expected" from a check that did not run.

### Group the incoming files

```bash
git diff --name-only "HEAD...$REMOTE/$BRANCH"
```

Map each path to a category by **first matching** prefix:

| Path prefix | Category |
|---|---|
| `protocols/standing-orders/` | Standing Orders |
| `skills/` | Skills |
| `rules/` | Rules |
| `themes/` | Themes |
| `scripts/` | Scripts |
| `docs/` | Documentation |
| `examples/` | Examples |
| `AGENTS.md`, `README.md`, `CONTRIBUTING.md` | Core Docs |
| `CLAUDE.md` deleted upstream | legacy entry removed; forks run scripts/migrate-entry-file.py |
| `.github/` | CI/CD |
| *(anything else)* | Other |

For per-category detail use the basename without extension
(`protocols/standing-orders/drift-advisory.md` becomes `drift-advisory`). Beyond
three files in a category, show two and `+N more`.

### The echo case, worth naming explicitly

An instance that also **authors** CORE will see its own promoted commits come back
down. Those often change nothing locally, because the local copy already carries
them. Detect it cheaply: a path in the incoming diff that does not appear in
`git diff --name-only HEAD` after a `--no-commit` merge was an echo. Reporting
"4 commits behind, 1 file actually changes" is far more useful than "4 commits
behind", and it stops a routine round trip from reading like a backlog.

## Step 2: Overlay channel

Per subscription, one call. The engine owns this channel; do not reimplement it.

```bash
python3 scripts/overlay.py status "$NAME"
```

Read from its output: `resolved_sha` versus `cache HEAD` (cache ahead means a sync
is pending), `last_synced`, and the file counts
`clean · locally-modified · upstream-ahead · conflict · orphan`.

`locally-modified` deserves a second look rather than a number. It means the
materialized copy on disk differs from what the lockfile recorded. Two very
different situations produce it:

- **Echo.** The local edit was promoted up and has come back. The file is now
  byte-identical to the source, and a sync is pure lockfile bookkeeping.
- **Divergence.** The local copy is deliberately different (an instance-specific
  value where the published copy carries a placeholder). A sync would try to
  replace it.

Tell them apart by comparing bytes, not by trusting the label:

```bash
# The cache path lives in bridge-config.yaml under the subscription's
# materialize block, NOT in overlays.lock.yaml.
CACHE=$(python3 - "$NAME" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open("bridge-config.yaml"))
for u in cfg.get("upstreams") or []:
    if u.get("name") == sys.argv[1]:
        print(((u.get("materialize") or {}).get("cache") or "").rstrip("/"))
        break
PY
)
# then, per locally-modified dest ($SRC_ROOT is the manifest's source_root,
# conventionally "tree"):
cmp -s "$DEST" "$CACHE/$SRC_ROOT/$DEST" && echo "echo" || echo "divergence"
```

Report the two counts separately. A divergence is a decision waiting to happen;
an echo is noise.

## Step 3: Staleness

Each upstream may declare `pull_interval_days` (default 7). Compare it against the
last time that channel actually moved:

- **Overlays:** `last_synced` from `overlays.lock.yaml`, which the engine writes.
- **CORE:** there is no equivalent field, so derive it. The question is *when this
  Bridge last pulled*, which is a **local** commit date. Do not read the date off
  `$REMOTE/$BRANCH` or off the merge-base: both give you when the *upstream* commit
  was authored, which can be hours or months away from when it arrived here.
  Find the most recent local merge that has a parent contained in the remote branch:
  ```bash
  git rev-list --merges HEAD --max-count=80 | while read -r c; do
    for p in $(git rev-list --parents -n1 "$c" | cut -d' ' -f3-); do
      if git merge-base --is-ancestor "$p" "$REMOTE/$BRANCH" 2>/dev/null; then
        git log -1 --format=%ci "$c"; exit 0
      fi
    done
  done | head -1
  ```
  Empty output means this Bridge has never pulled from that remote. Say exactly
  that. Never substitute a date from the other side of the channel.

Past the interval, mark the channel; do not nag below it.

## Step 4: Present

One block, both channels, newest signal first. Numbers only where they were
actually measured.

```
Inbound status

  CORE      acme/their-core        4 commits behind · 1 file actually changes
                                   clean merge predicted · last pull 5d ago (interval 7)
                                   Skills 1 · Scripts 1 · Core Docs 2

  Overlay   their-org-config       cache ahead of lock · 4 upstream-ahead
                                   11 locally-modified: 10 echo, 1 divergence
                                     identity/accounts/<redacted>.yaml

  Local     7 commits not yet promoted (context, not a blocker)

  [c] pull CORE   [o] sync overlays   [d] show the diff   [s] skip
```

When a channel is current, collapse it to one line. When a prerequisite failed,
say which one; a check that silently did not run must never render as a clean result.

## Actions

Every action hands off. This file executes none of them.

| Choice | Handoff |
|---|---|
| `[c]` | The CORE pull procedure: verify the incoming set does not intersect uncommitted work, then `git merge --no-commit --no-ff "$REMOTE/$BRANCH"`, resolve, commit. Tag `HEAD` first so the merge is reversible. |
| `[o]` | `python3 scripts/overlay.py sync <name>`, once per subscription. Never pass `--yes`: the behavioural gate and the large-prune guard are the point. Snapshot the affected dests first, since managed dests sit in `.git/info/exclude` and `git reset --hard` does not reach them. |
| `[d]` | `git diff "HEAD...$REMOTE/$BRANCH"` for CORE, `python3 scripts/overlay.py diff <name>` for an overlay. |
| `[s]` | Nothing. There is no timestamp to update; staleness is derived from git and the lockfile, never from a hand-written field that can drift from reality. |

> **Order matters.** CORE first, overlays second, and only once the tree has no
> unmerged paths. An overlay plan computed against a tree that still carries
> conflict markers writes garbage into the lockfile.

## What this check does not do

It does not merge, and it does not decide. It also does not catch the quiet case
where an upstream edit lands cleanly in a region no local edit touched and carries
a genericized placeholder into a spot where this instance needs its real value.
That is a property of the tree rather than of a pull, and it belongs in an audit
that runs on its own schedule.
