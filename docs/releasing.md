---
summary: "Maintainer runbook for cutting a release — automated via release-please (conventional commits -> version + CHANGELOG + tag + GitHub release)"
type: guide
last_updated: 2026-06-24
related:
  - ../CHANGELOG.md
  - ../release-please-config.json
  - ../.release-please-manifest.json
  - ../.github/workflows/release-please.yml
  - ../.github/workflows/validate.yml
---

# Releasing

Releases are **automated from conventional commits**. You do not bump the
version or write the CHANGELOG by hand, and you do not push tags. You merge a
PR.

## How it works

[release-please](https://github.com/googleapis/release-please) watches `main`.
On every push it reads the merged commit subjects and maintains a single open
**release PR** (titled `chore(main): release X.Y.Z`). That PR:

- computes the next version from the commit types since the last release, and
- assembles the matching `CHANGELOG.md` section.

When you **merge the release PR**, release-please creates the git tag and the
GitHub release (release notes = the new CHANGELOG section; `0.x` is marked
*pre-release*). The merge is the only manual step — and the gate.

```
feat:/fix: PRs merged to main  ->  release-please opens/updates "release X.Y.Z" PR
you review + merge that PR      ->  tag vX.Y.Z + GitHub release (automatic)
```

## What you do

1. **Land work as usual** via PRs to `main`. The only requirement is a
   **conventional-commit PR title** — squash-merge uses it as the commit
   subject, and that is what release-please parses. See "Commit types" below.
2. **Review the release PR** when you are ready to ship. It shows the computed
   version and the CHANGELOG diff. Edit the PR's CHANGELOG if you want to
   reword anything; release-please respects manual edits.
3. **Merge it.** The tag and GitHub release appear automatically. The README
   release badge (reads the latest release live) updates on its own.

There is nothing to do for a version that should *not* ship yet — just leave
the release PR open. It keeps updating as more PRs land.

## Commit types -> version bump

The version adapts to what merged, per [SemVer](https://semver.org/). While in
the `0.x` series (`bump-minor-pre-major`):

| Commit type | Example PR title | Bump | 0.2.0 -> |
|---|---|---|---|
| `fix:` | `fix: correct theme fallback` | patch | `0.2.1` |
| `feat:` | `feat: add agency work board` | minor | `0.3.0` |
| `feat!:` / `BREAKING CHANGE:` | `feat!: rename config key` | minor (0.x) | `0.3.0` |
| `docs:` `ci:` `chore:` `refactor:` `test:` `style:` `build:` | — | none on their own | (no release) |

A batch of only `docs:`/`chore:`/`ci:` PRs does **not** open a release PR —
that is intentional. The version moves when there is a `feat:` or `fix:`. Those
non-bumping types still get credited in the CHANGELOG of the next release that
ships (only `docs:` is shown; the rest are hidden — see
`release-please-config.json` `changelog-sections`).

`1.0.0` starts compatibility guarantees; until then breaking changes bump the
minor version.

## When the release PR's checks are red

The release PR runs the same suite as any PR (`validate.yml` + DCO). Branch
protection blocks the merge until green:

- **Validation failure:** fix on `main` like any CI failure — the release PR
  rebases itself on the next push.
- **DCO:** release-please signs off its own commit (`signoff` input in
  `release-please.yml`), so the release PR passes DCO without intervention.

## Editing version rules

- **Bump behaviour** (pre-major handling, what counts as a release):
  `release-please-config.json`.
- **CHANGELOG section names / what is shown vs hidden:** the
  `changelog-sections` block in the same file.
- **Current version baseline:** `.release-please-manifest.json` (release-please
  updates this automatically on each release — do not edit by hand unless
  bootstrapping).

## Manual fallback

If you ever need a release outside this flow, edit
`.release-please-manifest.json` + `CHANGELOG.md` in a PR, then create the tag
and release by hand (`gh release create vX.Y.Z --notes-file …`). This is not
the normal path — prefer the release PR.
