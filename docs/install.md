---
summary: "Setting up your own private Bridge: the short prompt that hands your agent SETUP.md, the template-button caveat, what the first session does, and which agent tools are tested."
type: guide
last_updated: 2026-10-24
related:
  - ../SETUP.md
  - ../README.md
  - updating.md
  - ../rules/push-guard.md
  - ../skills/bridge-onboard/SKILL.md
  - tool-mapping.md
---

# Installing BKS open-bridge

This page is the long form of the README's *Set it up* section. It covers the
one decision that matters before anything else (where your private data will
live), the one prompt that gets you there, and what happens in the first session.

Just want to see it run? The demo workspace needs no setup at all: see the
README's [*Not ready to set anything up? Look at a running one first*](../README.md#not-ready-to-set-anything-up-look-at-a-running-one-first).

**What you need:** `git`, and Python 3 with PyYAML (`python3 -c "import yaml"`
must succeed). The Bridge's own scripts read YAML from the first session on;
the system Python on macOS ships without PyYAML. SETUP.md lists the install
commands, and `bin/setup` checks for it and prints them.

## Give your data a private home first

This repository is public. Onboarding writes your private data (personas,
client names, `work/` logs, credential reference URIs) onto a `user/{name}`
branch. A bare clone's `origin` points at the public repo, so a single
`git push` would publish that branch. The setup therefore makes **your
own private repo** the `origin` and keep BKS open-bridge as a read-only
`upstream`. A fork does not help here: a fork of a public repo is itself public.

## Hand this prompt to your agent

Paste this into Claude Code, Codex or Copilot CLI:

```text
Set up BKS open-bridge for me by following this guide:
https://github.com/bks-lab/open-bridge/blob/main/SETUP.md
Read all of it first, then show me your plan and wait for my go
before you change anything.
If you can't open links: git clone https://github.com/bks-lab/open-bridge.git my-bridge,
then read my-bridge/SETUP.md and follow it.
```

The steps themselves live in one file, [SETUP.md](../SETUP.md), written for the
agent to follow top to bottom. The agent checks your tools, asks what to call
your private copy, shows you its plan and waits for your go, gives the data a
private home before writing any of it, arms the push guard, shows you the
proof, and then tells you to restart it inside the new folder.

Why the prompt still says "wait for my go" although the guide says it too: an
agent without web access clones the repo before it can read the guide, so the
one rule that has to hold before the first change travels in the prompt itself.

Nothing in the guide is hidden. Every step is a command you can read before you
approve it.

## After the setup

**Start your agent session inside the new folder.** A session that started in
another folder cannot see this repo's skills. In the new session the Bridge
greets you by itself; if it does not, run `/bridge-onboard`.

## The "Use this template" button

SETUP.md does not use it, for one reason. A template copy is private from the
first second, which is why the button exists. But GitHub gives it a fresh, single-commit
history that shares no ancestor with this repo, so the update path aborts with
`fatal: refusing to merge unrelated histories`. Your **first** CORE update then
needs `git merge --allow-unrelated-histories upstream/main` once; every merge
after that is ordinary. The prompt above keeps the full history
and needs no such exception. Updating in general: [updating.md](updating.md).

## What the first session does

On first run the Bridge reports what it detected (a fresh clone, your git name,
your tool), arms the safety guard, and offers four ways in: see it run first,
describe what you will use it for (and it tailors the setup), make it private
first, or bind a workspace across repos. The detection and the greeting are
specified in [`rules/session-start.md`](../rules/session-start.md).

`/bridge-onboard` then walks the guided setup: identity and purpose, optional
ecosystem detection, the work-system config, and your own `user/{name}` branch.
It arms the `pre-push` guard ([`rules/push-guard.md`](../rules/push-guard.md))
*before* creating that branch. That guard is the git-layer backstop that blocks
publishing the branch to a public remote by accident.

Onboarding asks one privacy question, `discovery.mode`, default **confined**:
your Bridge stays inside its own folder and never scans your other repos, apps,
devices or mail unless you opt in per item. You can change it later in
`bridge-config.yaml`.

If you skip the wizard, run `./bin/setup` once on any OS (`bin/setup.ps1` on
native Windows). It arms the same guard and repairs the discovery symlinks.

## Which agent tools work

- **Claude Code** is tested and the most complete: slash commands, hooks and
  sub-agents live under `.claude/`.
- **Codex and Copilot CLI** work through `AGENTS.md` plus the skill symlinks
  `.agents/skills` and `.github/skills`, both pointing at the one `skills/`
  tree.
- **Cursor** (agent mode) was tested by a contributor on Windows: it reads
  `AGENTS.md`, runs the first-session check on its own, finds skills when asked
  for them by name, and runs `/bridge-onboard` through to the private-home step.
- **Other tools that read `AGENTS.md`** (Gemini CLI, Windsurf) get the
  instructions, but their skill discovery is untested here. On a tool without
  slash commands, ask for the skill by name and the agent reads its `SKILL.md`.

Tool names per platform, and what a missing sub-agent API means:
[tool-mapping.md](tool-mapping.md). On native Windows a checkout can turn the
symlinks into plain files; `bin/setup.ps1` repairs them (the `bin/` row in
[structure.md](structure.md)).
