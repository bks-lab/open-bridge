# Changelog

This file is not hand-maintained release notes. Every merge to `main` ships
as a release automatically, version and notes computed from the merged PR
titles ([how it works](docs/releasing.md)), so the authoritative history
always lives on GitHub, not here:

- **[Releases](https://github.com/bks-lab/open-bridge/releases)**, the
  source of record, one entry per merge, notes auto-generated.
- **[Changelog page](https://bks-lab.github.io/open-bridge/changelog.html)**,
  a browsable live view of the same feed.

What follows is a periodically refreshed, hand-picked summary for someone
scanning the repo on GitHub who has not clicked through: the themes behind
the last several weeks of releases, not a complete list. It can go stale
between updates; the two links above never do.

## Recent themes

**AGENTS.md is the only entry file.** CLAUDE.md is gone; Claude Code 2.1.281+
reads AGENTS.md directly, the instance layer loads through fixed imports
(`identity/agent/IDENTITY.md`, `SOUL.md` and the new `INSTANCE.md`), org
registries are indexed instead of imported (`scripts/context-index.py
--registries`), and `scripts/migrate-entry-file.py` moves a fork's CLAUDE.md
lines (docs/updating.md).

**Secrets, as references instead of values.** A broker that resolves a
`vault://`/`keychain://`-style reference at read time and never prints the
value ([#222](https://github.com/bks-lab/open-bridge/pull/222)), placement
rules for where a new secret belongs and a write path that never passes one
through `argv` ([#223](https://github.com/bks-lab/open-bridge/pull/223)), and
an audit that collapsed three drifting pattern lists into one
([#224](https://github.com/bks-lab/open-bridge/pull/224)).

**Object storage, named as its own family.** Where content belongs when a
repository must not hold it, with one resolver and a grammar guard so every
reference is written the same way
([#225](https://github.com/bks-lab/open-bridge/pull/225),
[#228](https://github.com/bks-lab/open-bridge/pull/228)).

**The learning loop closing.** Cross-harness memory with a declared retention
policy ([#230](https://github.com/bks-lab/open-bridge/pull/230)), verified
improvement proposals with prior-rejection checks, a git-written audit trail
and skill provenance
([#231](https://github.com/bks-lab/open-bridge/pull/231)), and a skill-local
lesson journal so a workaround a skill needed lives with the skill
([#232](https://github.com/bks-lab/open-bridge/pull/232)).

**Finding your way around the docs.** A question-to-location map with a
check that keeps it honest against the tree
([#233](https://github.com/bks-lab/open-bridge/pull/233)), a documentation
pass that made the roadmap, commands reference, feature tour and landing
page match what actually ships
([#235](https://github.com/bks-lab/open-bridge/pull/235)), and a README
rewritten as a front door instead of a manual
([#234](https://github.com/bks-lab/open-bridge/pull/234)).

**A second worked example.** The portfolio operator: one person, several
personas, a managed client service and a household on the same instance
([#236](https://github.com/bks-lab/open-bridge/pull/236)).

**Overlay sync hardening.** A guarded auto-merge with a conflict gate that
fails closed ([#187](https://github.com/bks-lab/open-bridge/pull/187)),
unattended sync for every subscribed overlay that never deletes on its own
([#214](https://github.com/bks-lab/open-bridge/pull/214), by
[@avondiel-dev](https://github.com/avondiel-dev)), and a fix for a sync that
overwrote a merged edit by reading it as pristine
([#210](https://github.com/bks-lab/open-bridge/pull/210)).

**Workload declarations getting more honest.** Declaring which system a run
belongs to and sectioning the report by it
([#178](https://github.com/bks-lab/open-bridge/pull/178)), stating a finding
once and making "needs a person" a filter
([#180](https://github.com/bks-lab/open-bridge/pull/180)), and a fix for a
root-owned unit that had been blinding the report for its own host
([#219](https://github.com/bks-lab/open-bridge/pull/219)).

**One place for what needs you.** An inbox where findings, questions from
agents and drafts wait until the live source says they are done, a ready-made
owner approver for Bridge-Agents, a workplace that opens one agent tab per task
through a driver, the briefing reading the inbox first, and an `arm`
capability for the always-on machine that fills the inbox while you are away
([#287](https://github.com/bks-lab/open-bridge/pull/287)).

**New contributors.** [@avondiel-dev](https://github.com/avondiel-dev) landed
the overlay auto-merge and auto-sync work above, and
[@mkupermann](https://github.com/mkupermann) opened the Codex and Mistral
Vibe hook integration for the Bridge drift check
([#198](https://github.com/bks-lab/open-bridge/pull/198)), their first
contribution to the repo.

For anything older, or the day-by-day list this summary is drawn from: the
[Releases](https://github.com/bks-lab/open-bridge/releases) page.
