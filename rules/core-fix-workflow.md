---
scope: core
description: How to fix or improve a CORE file (skill, rule, script) without creating a permanent user-branch divergence that conflicts on every upstream merge
---
# Fixing CORE without lasting divergence

CORE and USER touch disjoint paths, so `git merge upstream/main` is normally
conflict-free. That guarantee **breaks the moment you edit a CORE file on your
`user/*` branch and keep it** — that file now diverges, and every upstream change
to it becomes a merge conflict. This rule is the discipline that keeps CORE fixes
from rotting into conflicts.

## The reflex: a CORE fix does not *live* on your user branch

When you find a bug or improvement in a CORE file (`skills/**`, `rules/*.md`,
`scripts/**`, `docs/**`, templates/schemas, `CLAUDE.md`/`AGENTS.md`,
`.claude/agents/**`, `protocols/standing-orders/*.md`), pick one of two paths —
never "edit on `user/*` and forget":

### Path A — promote-and-reconverge (default)
1. Make the fix.
2. `/promote` it as a fork PR to the upstream (`bks-lab/open-bridge`).
3. When it merges upstream, the **next `git merge upstream/main` brings back
   identical content** — git sees no difference, and your local divergence
   *dissolves*. Zero lasting conflict.

This is the intended flow: your improvement helps everyone AND leaves your branch
clean. Small generic fixes (a typo, a bug, a new check) belong here. So does a
service adapted to a provider it could not run, as
[`docs/ai-services.md`](../docs/ai-services.md) § A service your provider cannot run describes.

### Path B — feature branch off the core branch
For a larger change you want to iterate on:
1. `git checkout main && git checkout -b feature/<slug>`
2. Build + PR upstream from there.
3. Keep `user/*` free of the CORE edit until it lands upstream, then merge down.

## What NOT to do
Do not edit a CORE skill on `user/*` and keep the divergence indefinitely — and
do **not** let an org overlay ship a skill that already exists in CORE (it
overwrites the tracked CORE file → the same divergence, self-inflicted). If you
need instance-specific behaviour, add a `scope: user`/`org` skill/rule/config
knob that the generic CORE reads — don't fork the CORE file.

## The safety net: the divergence sentinel
`scripts/bridge-divergence-check.py` lists every CORE file you've changed locally
and flags which the upstream also changed (`--json` for machines). Run it before a
merge; the daily `scripts/upstream-monitor.sh` runs it every morning and writes
`work/upstream-status.md` (surfaced by `/briefing`) + a Signal ping.

**When the sentinel flags a conflict-risk CORE file, resolve it before merging:**
- The fix is generic → `/promote` it, then merge (it reconverges).
- You no longer need the local change → `git checkout <ref> -- <file>` (revert to
  CORE), then merge.
- The divergence is intentional and instance-specific → accept a one-time 3-way
  merge on that file (and reconsider whether it should be a config knob instead).

## Related
- `rules/operations.md` (promote routing) · `rules/promote-safety.md`
- `scripts/bridge-divergence-check.py` · `scripts/upstream-monitor.sh`
- `skills/bridge-audit` Check 13 (skill-shadowing detection)
