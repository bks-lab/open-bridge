# Contributing to open-bridge

Sub-agents, standing orders, themes, bug fixes — all welcome.

> **Project status.** open-bridge is open source and free to use and fork
> today — see the [releases page](https://github.com/bks-lab/open-bridge/releases)
> for the current version. The contribution workflow is still being built:
> pull requests are reviewed and merged **manually** for now, so external PRs
> may take time and larger changes are best discussed in an issue first. Bug
> reports, ideas, and questions are very welcome.

---

## Getting Started

1. **Fork and clone** the repo
2. **Skill-discovery symlinks** (`.claude/skills`, `.agents/skills`,
   `.github/skills`) ship committed, so a fresh clone works on macOS /
   Linux / WSL out of the box. Only if your checkout dropped them (native
   Windows, or a git without symlink support) run `./bin/setup` (Windows:
   `powershell -File bin\setup.ps1`) to recreate them — without them your
   agent won't find the skills.
3. **Run `/bridge-onboard`** in Claude Code — the wizard creates your
   `user/your-name` branch and sets up ecosystem and preferences
4. **Test commands:** `/briefing` (daily status), `/bridge-status` (dashboard),
   `/debrief` (transcript processing), `/archive` (weekly archive)

Something broken? Open an issue with your `bridge-config.yaml` (redact
secrets) and the error output.

### Validation toolchain (for contributors)

CI runs several checks on every PR — DCO sign-off, YAML lint, schema
validation, a content-leak scan, skill-scope, and frontmatter checks (see
[`.github/workflows/validate.yml`](.github/workflows/validate.yml)).
`pre-commit` covers most of them; the main ones to run locally first:

```bash
pipx install check-jsonschema       # schema validation (validate-bridge.py)
pip install pyyaml yamllint         # ecosystem cross-checks + YAML lint
pre-commit install                  # the repo ships .pre-commit-config.yaml
yamllint -c .yamllint.yml .
python3 scripts/validate-bridge.py
python3 scripts/validate-skill-scope.py
python3 scripts/no-scrub-leak.py    # content-leak / PII scan
```

All validators fail gracefully with install instructions if a tool is
missing — but a green local run saves a CI round-trip.

---

## What to Contribute

| Area | Examples |
|------|----------|
| **Sub-agents** | Medieval, space western, SRE team, consulting firm (one .claude/agents/*.md per character) |
| **Themes** | Company vocabulary, locale translations (fr, es, ja, ...) |
| **Standing orders** | New always-on rules for common patterns |
| **Documentation** | Improvements to docs/, examples, or this file |
| **Bug fixes** | Broken commands, YAML schema issues, template gaps |

---

## Contributing a Theme

Themes control vocabulary — the system stays the same, only wording changes.

1. **Copy the template:**
   ```bash
   cp themes/_template.yaml themes/your-theme.yaml
   ```
2. **Set metadata** — `name`, `display_name`, `locale` (BCP 47), `extends`
   (inherit from `professional`, `professional-de`, or `null`).
3. **Override vocabulary** — only keys you want to change; the rest
   inherits from the parent. See `themes/_schema.yaml` for all keys.
4. **Test** — set `theme: your-theme` in `bridge-config.yaml`, run
   `/briefing` and `/bridge-status` to verify vocabulary.
5. **Submit a PR** to `main`.

---

## Contributing a Standing Order

Standing orders are always-on rules in `protocols/standing-orders/`.

1. **Copy the template:**
   ```bash
   cp protocols/standing-orders/_template.md protocols/standing-orders/your-order.md
   ```
2. **Define frontmatter** — `name`, `scope` (always/per-repo/per-context),
   `enforcement` (advisory/blocking), `applies_to` (sub-agent names;
   empty = all agents).
3. **Write the body** — the rules, injected verbatim into the agent's
   prompt.
4. **Test:** start a session with `work.enabled: true` and verify the
   order is loaded and respected.
5. **Submit a PR** to `main`.

---

## Contributing a Sub-Agent

Sub-agents are native Claude Code sub-agents. Each one is a single
markdown file at `.claude/agents/<name>.md` — flat, no subdirectory.
Claude Code auto-discovers them at session start; no registration step.

1. **Create the file:**
   ```bash
   touch .claude/agents/your-agent.md
   ```
2. **Add YAML frontmatter** — `name` and `description` are required;
   `tools` and `model` are optional:
   ```yaml
   ---
   name: your-agent
   description: When to spawn this agent and what it handles.
   tools: [Bash, Read, Grep]
   model: sonnet
   ---
   ```
   There is no `role` field. `name` is the identifier you pass to the
   `Task` tool via `subagent_type`; `description` is what Claude Code
   matches against to decide when to dispatch it.
3. **Write the body** — this is the agent's system prompt. Give it a
   distinct voice and personality here; describe how it works, what it
   returns, and the conventions it follows.
4. **Set scope for /promote** — add `scope:` so the promote routing knows
   where the file belongs (`core` for a generic, reusable agent; `user`
   to keep it local). Generic, on-topic agents are the ones worth
   upstreaming.
5. **Test:** spawn it via the `Task` tool with `subagent_type: your-agent`
   and confirm it returns a structured summary rather than raw output.
6. **Submit a PR** with the new `.claude/agents/your-agent.md` file.

Want to contribute a themed set (the equivalent of an old "preset", like
a medieval court or an SRE team)? Just include several `.claude/agents/*.md`
files in the same PR — one file per character — each with its own voice in
the body. There is no preset directory; the set is simply the collection of
files.

---

## PR Guidelines

All PRs target the `main` branch. Before submitting:

- [ ] PR title is a [conventional commit](https://www.conventionalcommits.org/)
      (`feat:`, `fix:`, `docs:`, `ci:`, …) — see "PR title" below
- [ ] Every commit is signed off (`git commit -s`) — see "Legal" section below
- [ ] No absolute paths — use `${variables}`
- [ ] No secrets or credentials
- [ ] No company-specific terms in CORE files
- [ ] Works with both `professional` and `professional-de` themes
- [ ] YAML frontmatter has all required fields
- [ ] Existing commands and standing orders still work

See `.github/PULL_REQUEST_TEMPLATE.md` for the full checklist.

### PR title

PRs are squash-merged, so the **PR title becomes the commit subject on `main`**
— and releases are driven from it. Use a
[conventional commit](https://www.conventionalcommits.org/) prefix:

- `feat: …` — a new capability (bumps the minor version)
- `fix: …` — a bug fix (bumps the patch version)
- `feat!: …` or a `BREAKING CHANGE:` footer — a breaking change
- `docs:` / `ci:` / `chore:` / `refactor:` / `test:` / `build:` — no release on
  their own, but credited in the release notes

The release workflow reads these titles on every push to `main` to compute the
next version and cut the tag + GitHub release automatically — no manual version
bump, tag, or release PR. Full flow: [`docs/releasing.md`](docs/releasing.md).

---

## Legal

By contributing, you accept the terms below. The CI rejects PRs that miss a
sign-off, so it is easier to get this right the first time.

### Licensing of contributions

- **All contributions** — code and content alike (Python, shell, JavaScript,
  YAML logic, Markdown skill bodies, standing orders, docs, templates,
  schemas) — are licensed under the [MIT License](LICENSE).
- **Trademarks** (project name, logo, brand) are governed by
  [TRADEMARK.md](TRADEMARK.md) and are not affected by your contribution.

Your contribution carries the same MIT license as the rest of the repository.

### Developer Certificate of Origin (DCO)

Every commit in a PR must include a `Signed-off-by:` trailer. This is the
[Developer Certificate of Origin](https://developercertificate.org/), the same
mechanism used by the Linux kernel, Docker, and GitLab.

Sign off with:

```bash
git commit -s -m "your message"
# or, if you forgot, amend the last commit:
git commit --amend --signoff
# or, for a whole PR branch:
git rebase --signoff main
```

The sign-off is your assertion that:

> *I certify that I have the right to submit this contribution under the
> open-source license shown in the file. The full text is at
> https://developercertificate.org/.*

There is no built-in git setting that auto-appends `Signed-off-by` to a
plain `git commit`, so make `-s` a habit. If you want a shortcut, alias it:

```bash
git config alias.cs 'commit -s'   # then commit with: git cs -m "…"
```

### Patent grant

By submitting a contribution, you also grant a perpetual, worldwide,
non-exclusive, no-charge, royalty-free, irrevocable patent license to the
project maintainers and downstream users to make, use, offer for sale, sell,
import, and otherwise transfer your contribution and any project version
that incorporates it. This grant covers only patent claims that are
necessarily infringed by your contribution alone or by combination with the
project at the time of submission. If you assert a patent claim against
anyone alleging that the project infringes your patents, this license
terminates as of the date of that assertion.

This closes the patent-grant gap inherent to MIT. It does not turn this
project into Apache 2.0 — only your contribution is covered.

### EU contributors — §31a UrhG carve-out

For contributors subject to German copyright law: by submitting a
contribution, you grant rights of use that explicitly include presently
unknown forms of use (§31a Abs. 1 S. 2 UrhG), to the extent allowed for
non-exclusive license grants to the public free of charge. This avoids the
otherwise-applicable three-month revocation window for novel uses.

### No CLA

We deliberately do not require a separate Contributor License Agreement.
The DCO sign-off plus the licensing terms above are the agreement.

---

## Bug Reports & Feature Requests

**Bugs:** Use the GitHub issue template. Include `bridge-config.yaml`
(redact secrets), steps to reproduce, and error output.

**Features:** Describe the problem you are solving, not just the solution.

---

## Code of Conduct

Be kind. Be constructive. Help others succeed. Participation is governed
by our [Code of Conduct](CODE_OF_CONDUCT.md) (Contributor Covenant).

## Security

Found a vulnerability? Please **do not** open a public issue — follow the
private disclosure process in [SECURITY.md](SECURITY.md).
