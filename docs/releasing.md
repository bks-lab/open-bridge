---
summary: "How releases work — fully automatic, conventional-commit-driven (push to main -> version computed -> tag + GitHub release)"
type: guide
last_updated: 2026-06-24
related:
  - ../.github/workflows/release.yml
  - ../.github/workflows/validate.yml
---

# Releasing

Releases are **fully automatic**. There is no release PR, no manual version
bump, no tag to push. You merge ordinary PRs into `main`; the release workflow
cuts the release.

## How it works

On every push to `main`, [`release.yml`](../.github/workflows/release.yml):

1. Finds the latest version tag (`vX.Y.Z`).
2. Reads the commit subjects since that tag and computes the next version from
   their conventional-commit types.
3. If there is a releasable change, creates the tag and a GitHub release with
   notes auto-generated from the merged PRs. Otherwise it does nothing.

```
feat:/fix: PR merged to main  ->  release.yml computes next version
                              ->  tag vX.Y.Z + GitHub release (auto notes)
```

The README release badge reads the latest release live, so it updates on its
own. The "what changed" lives on the **GitHub Releases page** (there is no
hand-maintained CHANGELOG file).

## What you do

**Land work via PRs with a conventional-commit title.** That is the only rule —
squash-merge turns the PR title into the commit subject, and that is what the
workflow parses. Nothing else: the release appears within a minute of merge.

To hold a release back, just don't merge releasable work yet — a stream of
`docs:`/`chore:` PRs never cuts a release.

## Commit type -> version bump

The version adapts to what merged, per [SemVer](https://semver.org/). While in
the `0.x` series the middle (minor) digit moves **only** on `feat:` or an
explicit breaking change — ordinary fixes bump the patch:

| PR title prefix | bump | `0.3.0` -> | from `1.0.0` |
|---|---|---|---|
| `fix:` | patch | `0.3.1` | patch |
| `feat:` | minor | `0.4.0` | minor |
| `feat!:` / `BREAKING CHANGE:` | minor (0.x) | `0.4.0` | **major** |
| `docs:` `ci:` `chore:` `refactor:` `test:` `style:` `build:` | none | — | none |

While `major == 0`, a breaking change bumps the **minor**, not the major, so it
never jumps to `1.0.0` by accident. From `1.0.0` on, a breaking change bumps the
major and starts the usual compatibility guarantees.

## Editing the bump rules

All of it lives in [`release.yml`](../.github/workflows/release.yml) — the
`Compute next version` step is a small, readable shell block. Change the regexes
or the bump arithmetic there. The version is always derived from the latest
git tag; there is no version file to keep in sync.

## Manual fallback

To force a specific version, create the tag + release by hand:

```bash
gh release create vX.Y.Z --target main --generate-notes --latest
```

The next automatic run computes from whatever the latest tag is, so a manual
release slots in cleanly.
