---
scope: core
description: After every push verify CI green unprompted (SHA-cross-check); on a red run read the failure log before fixing
---

# CI Discipline

Two gates around every push. A push is not finished until CI is confirmed
green, and a red run is diagnosed from its log — not from the workflow YAML.

## Gate 1 — Verify green after every push (unprompted)

After **every** push — feature branch, user branch, or a merge to the core
branch — verify the CI status and confirm it green as part of the
end-of-work cycle. Do not wait to be asked.

```bash
gh run list --branch <branch> --limit 3
```

`gh run list` caches and sometimes does not surface a fresh run. The SHA
query is the source of truth (verify-before-claim — declared state is not
truth):

```bash
gh api 'repos/<owner>/<repo>/actions/runs?head_sha=<sha>' \
  --jq '.workflow_runs[] | "\(.name) | \(.status) | \(.conclusion)"'
```

A push without CI verification is an unfinished push. Note: trigger
branches live in `.github/workflows/*.yml` under `on.push.branches` — DCO
often runs only on PRs, not on direct pushes, so a missing DCO run on a
direct push is expected, not a failure.

## Gate 2 — Read the failure log before fixing

On a red run, **get the job log first, then fix**. The workflow YAML shows
*what* the check does — not *why* it failed. An assumption read off the YAML
is not evidence (this is verify-before-claim applied to CI: declared
workflow logic is not the failure cause; the live log is).

```bash
# 1. Find the failing check's run ID
gh pr checks <PR#> --repo <org/repo>

# 2. Read the actual failure
gh run view <run-id> --repo <org/repo> --log-failed | tail -30
# Multi-step jobs — target one job:
gh run view <run-id> --repo <org/repo> --job <job-id> --log
```

Diagnose and fix only **after** reading the log.

**Anti-pattern this replaces:** `cat .github/workflows/X.yml` → "it checks
Y, so Y must be missing" → push a fix → next run shows it was actually Z.
The same workflow code can fail for several distinct root causes (e.g. a DCO
check fails on missing sign-off *or* email-pattern mismatch *or* sign-off
format) — only the log tells you which.

Related: `promote-safety.md` for what may land on which upstream; the
SOUL.md § Verify before claim principle both gates specialize.
