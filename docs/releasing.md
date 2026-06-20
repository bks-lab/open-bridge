---
summary: "Maintainer runbook for cutting a release — CHANGELOG bump, tag, automated validation + GitHub release"
type: guide
last_updated: 2026-06-10
related:
  - ../CHANGELOG.md
  - ../.github/workflows/release.yml
  - ../.github/workflows/validate.yml
---

# Releasing

Releases are tag-driven. The pipeline does the rest.

## Cutting a release

1. **Bump the CHANGELOG.** Add a `## [X.Y.Z]` section at the top of
   `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/) format).
   Commit it to `main` (via PR, DCO sign-off required).
2. **Tag and push.**

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

3. **The `Release` workflow** (`.github/workflows/release.yml`) then:
   - runs the full validation suite (reuses `validate.yml` via `workflow_call`),
   - verifies the tag has a matching `## [X.Y.Z]` CHANGELOG entry,
   - creates the GitHub release with that CHANGELOG section as release notes
     (`0.x` tags are marked *pre-release*).

## When the release run is red

No release is created — fix first, then re-tag:

- **Validation failure:** fix on `main` like any CI failure.
- **Missing CHANGELOG entry:** add the section, merge, re-tag.
- Re-tagging: `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`,
  then tag the fixed commit. Never re-tag a version that already produced
  a published release — bump the patch version instead.

## Versioning policy

SemVer. The `0.x` series is **public preview**: conventions and layout may
change between minor releases; breaking changes bump the minor version.
`1.0.0` starts compatibility guarantees. First public release: `v0.2.0`.
