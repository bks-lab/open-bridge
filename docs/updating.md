---
summary: "Keeping a Bridge current: the manual CORE merge, the unattended daily auto-update and its fail-closed guards, org overlay sync, and how a CORE fix you made flows back without leaving a permanent divergence."
type: guide
last_updated: 2026-10-30
related:
  - install.md
  - org-overlays.md
  - ../rules/core-fix-workflow.md
  - ../scripts/upstream-autoupdate.sh
  - ../scripts/install-upstream-autoupdate.sh
  - ../scripts/migrate-entry-file.py
---

# Updating your Bridge

A Bridge has up to three inbound channels and one outbound one:

| Direction | What moves | How |
|---|---|---|
| CORE to you | skills, rules, scripts, docs, templates from `bks-lab/open-bridge` | `git merge upstream/main`, by hand or by the daily job |
| org to you | your organisation's shared config, if you subscribe to an overlay | the `bridge-overlay` skill, by hand or by the daily job |
| you to CORE | a generic fix you made to a CORE file | `/bridge-promote` or `/bridge-contribute`, as a fork PR |

Why the first one is safe at all: CORE and your USER data touch disjoint paths.
Your data lives on `user/{name}` in files CORE never ships, so a CORE merge does
not meet your edits. The split is described in
[extension-model.md](extension-model.md).

## Manually

On your `user/{name}` branch:

```bash
git fetch upstream
git merge upstream/main
```

That is the whole update. It stays conflict-free as long as you have not edited
a CORE file and kept the edit (see *Fixing CORE* below).

A copy made with GitHub's *Use this template* button shares no history with this
repo, so its **first** merge needs `git merge --allow-unrelated-histories
upstream/main` once. Details: [install.md](install.md).

Before a merge, `python3 scripts/bridge-divergence-check.py` lists every CORE
file you changed locally and flags the ones upstream changed too.

**If your instance is private**, there is nothing to hand-edit after a merge. The shipped
root `.gitignore` ignores instance data for every clone, and on a private origin
`scripts/user-data.py arm` (run by `bin/setup`) re-allows your own by writing
`identity/.gitignore`, `infra/.gitignore`, `workflow/.gitignore` and `work/.gitignore`
([`docs/structure.md`](structure.md#gitignore-policy)). If your own `.gitignore` had blocks
commented out from an earlier version of this policy, a merge of an update to this file may
conflict in that region: resolve it by taking upstream's version, then run `bin/setup` (it
writes the four negation files) and commit them. `python3 scripts/user-data.py check`
confirms nothing of yours is still ignored afterward.

## Once: upstream removed CLAUDE.md

Upstream no longer ships a root `CLAUDE.md`. Claude Code (2.1.281 or newer) reads
`AGENTS.md` directly, the same file Codex, Cursor, Copilot and Gemini read. A
root `CLAUDE.md`, `CLAUDE.local.md` or `.claude/CLAUDE.md` beside it makes Claude
Code load only that file and never `AGENTS.md`, so none of them may stay.

The instance's own always-on text now lives in `identity/agent/INSTANCE.md`,
which `AGENTS.md` imports next to `IDENTITY.md` and `SOUL.md`. It is yours: CORE
and overlays never ship it, so nobody has to edit `AGENTS.md`.

### You edited CLAUDE.md

Onboarding imports, overlay imports and your own prose all count as edits. The
next `git merge upstream/main` then stops with a modify/delete conflict on
`CLAUDE.md`, and the daily job holds the merge with the same pointer. Resolve it
in one command, dry run first:

```bash
python3 scripts/migrate-entry-file.py            # the plan, nothing changes
python3 scripts/migrate-entry-file.py --write    # carry, edit the budget, git rm
```

Then run the `git add` line the script prints and `git commit`, which concludes
the merge. On a public origin `INSTANCE.md` is ignored: the script says so, leaves
it out of that line, and the file stays local until the private-home step.

The script drops what `AGENTS.md` now covers (`@AGENTS.md`, the identity
imports, `@ecosystem*.yaml`, which Phase 1 indexes with
`context-index.py --registries`) and every paragraph equal to a CORE version of
the file. Everything else moves to `INSTANCE.md` under a dated heading, with
imports rewritten relative to that file. It removes the `CLAUDE.md` item from
`context-budget.user.yaml` and prints the projected size of `INSTANCE.md`
against its cap. A re-run never duplicates a carried paragraph.

Migrate mid-merge, not before it. The script checks that the `AGENTS.md` in
force (upstream's side while merging, else your working tree's) imports
`INSTANCE.md`. An older `AGENTS.md` does not, so removing `CLAUDE.md` before the
merge would lose `IDENTITY.md`, `SOUL.md` and the carried lines until the merge
lands; `--write` refuses that with "merge upstream first, then migrate
mid-merge". If the merge stops before the script exists in your tree, run
upstream's copy while still merging:

```bash
git show MERGE_HEAD:scripts/migrate-entry-file.py | python3 - --repo-root .
```

A `CLAUDE.md` that is a symlink to `AGENTS.md` (one manual for both tools) is
not a legacy entry: the script and the meter leave it alone.

`python3 scripts/migrate-entry-file.py --check` exits 1 while any of the three
files exists, which is what `bridge-audit` runs.

### You edited AGENTS.md

A fork that wrote its own lines into `AGENTS.md` conflicts on every upstream
change to it. Move them out once:

```bash
python3 scripts/migrate-entry-file.py --file AGENTS.md            # dry run
python3 scripts/migrate-entry-file.py --file AGENTS.md --write
```

Only the lines you added or changed go to `INSTANCE.md`, each under the CORE
heading it sat beneath, so one added table row carries that row and not the
table. `AGENTS.md` is restored to the CORE version the rest of your tree is on,
the merge base, never a newer ref tip. Mid-merge, your lines are your side
compared with the common ancestor, and the restore takes upstream's side, so a
CORE line upstream rewrote is never carried as yours. The version restored must
import `INSTANCE.md`; an older one makes `--write` refuse until you merge. CORE history
comes from the ref and from every remote with the same URL, so a stale
`upstream/main` next to a fresh `open-bridge/main` is no false verdict. The dry
run lists your commits that touched `AGENTS.md`; one that is a CORE change
headed upstream belongs in `/bridge-promote`, not here.

Plain `--check` only warns about `AGENTS.md`, because a pending CORE change or an
unfetched ref looks the same; `--check --file AGENTS.md` exits 1.

### Merge upstream before your next /bridge-sync

A branch that still carries a root `CLAUDE.md` must not sync it onto an
upstream: it would hide `AGENTS.md` for every fork. Merge and migrate first, then
sync; the sync prefilter skips a path the destination no longer has and says so.

### An org tier migrates its core branch before its instances

An org overlay or org fork with its own core branch runs the migration there
first. Its instances merge from it, so they meet the `CLAUDE.md` deletion once,
from one source. The org's own lines must not land in `INSTANCE.md`: that file is
each instance's own and no core branch or overlay ships it. Pass `--to` a file
the org does ship, such as a rule under `rules/org/`, and have each instance's
`INSTANCE.md` import it. Where an org's shared always-on text lives by default
is still open.

### Folders that bring their own CLAUDE.md

Claude Code started inside a folder that has its own `CLAUDE.md` (a workspace
member under `.bridge/workspaces/`, an example under `examples/`) loads only
that file. The same holds for a `CLAUDE.md` or `CLAUDE.local.md` in any parent
folder of the repo; `bin/setup` warns about those. Start Claude Code at the repo
root to get `AGENTS.md`.

## Unattended, once a day

[`scripts/upstream-autoupdate.sh`](../scripts/upstream-autoupdate.sh) merges
upstream CORE into your branch only when it can show the merge is safe. Every
guard fails closed: an error or an unknown state skips the merge instead of
risking a bad one. All three must pass:

1. the current branch is a `user/*` branch;
2. nothing is staged, and no uncommitted change touches a file the merge touches;
3. `git merge-tree` predicts zero conflicts (read from its exit code), or
   [`scripts/upstream-resolve.py`](../scripts/upstream-resolve.py) proves each
   predicted conflict is one a machine may decide.

A held conflict is named file by file, with the local commits behind it. A
commit whose change to that file upstream already carries is left out of that
list, since it was promoted: its patch-id for the file matches a commit in
upstream's history of the file, still pending or merged down long ago. A promote
squashed together with other changes has no such twin and is still named. A path
you declared in `bridge-config.yaml` `promote.local_adaptations` (a list of
`{path, reason}`, fnmatch globs, where `*` also matches `/`) is reported as a
*declared local adaptation*, so a deliberate divergence reads differently from a
forgotten promotion. It is still held: you merge upstream's change into it.

A skip is a guard doing its job, but a skip every morning is a merge nobody
does. Once a skip, or a merge that failed and was aborted, has kept upstream out
for `AUTOUPDATE_STALE_DAYS` days (default 2, counted from the oldest upstream
commit the branch lacks), the job files one inbox item. It closes on its own once `upstream/main` is an ancestor
of your branch again.

It writes the outcome to `work/upstream-status.md` (up to date, merged, skipped
with the reason, or failed and aborted). Independently of the job, `/briefing`
reports how far behind CORE and each subscribed overlay you are, when your
`bridge-config.yaml` lists `upstreams:`.
After a successful merge it also fast-forwards the core branch on your private
`origin`, so the mirror keeps pace with what was merged; the push goes through
the normal `pre-push` guard. Set `SIGNAL_ACCOUNT` and `SIGNAL_RECIPIENT` and it
sends a short Signal message per outcome.

Install it as a daily job with one command:

```bash
scripts/install-upstream-autoupdate.sh           # CORE, daily at 07:00
scripts/install-upstream-autoupdate.sh --print   # show the job, install nothing
```

The installer binds to wherever the repo currently is (re-run it after moving
the repo), loads the job, and then runs it once in the real scheduler context to
prove it works instead of assuming so. It targets macOS launchd. On another OS,
schedule `scripts/upstream-autoupdate.sh` with cron or a systemd timer, or
declare it as a workload ([workloads.md](workloads.md)).

## Org overlays

If your organisation publishes an overlay, the `bridge-overlay` skill subscribes
to it by git URL and materialises its files as copies, never touching CORE and
never overwriting your own edits (a 3-way merge decides). Updating is
`/bridge-overlay sync` in Claude Code.

The unattended counterpart runs after the CORE job:

```bash
scripts/install-upstream-autoupdate.sh --overlays   # daily at 07:15
```

It applies an overlay only when the whole plan needs nobody. A conflict with a
local edit, or a file it would delete, holds that overlay untouched until you
resolve it interactively. A behavioural file (a skill, an agent, a standing
order) arriving for the first time waits for one explicit yes. The full table
and the reasoning: [org-overlays.md](org-overlays.md).

## Fixing CORE without lasting divergence

The conflict-free guarantee breaks the moment you edit a CORE file on your
`user/*` branch and keep the edit: every upstream change to that file becomes a
conflict, and the daily job starts skipping. The rule that keeps it intact:
**CORE paths are developed on a branch of open-bridge, and reach `user/*` only
by `git merge upstream/main`.** Not by a cherry-pick: a picked commit comes back
a second time with the merge, under another hash. The discipline is in
[`rules/core-fix-workflow.md`](../rules/core-fix-workflow.md), in short:

- **Promote and reconverge (default).** Make the fix, send it upstream with
  `/bridge-promote` (commits) or `/bridge-contribute` (files). Once it is merged
  there, the next `git merge upstream/main` brings back identical content and
  your divergence dissolves.
- **Feature branch.** For a larger change, branch off the core branch, build and
  PR from there, and keep `user/*` free of the edit until it lands.
- **Need different behaviour only for you?** Add a `scope: user` or `scope: org`
  skill, rule or config knob that the generic CORE reads, instead of forking the
  CORE file.

Both promote paths run a mandatory content-safety scan and open a fork-based PR
with a DCO sign-off; they never push to the public repo directly. See
[`rules/promote-safety.md`](../rules/promote-safety.md).
