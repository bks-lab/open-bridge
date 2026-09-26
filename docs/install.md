---
summary: "Setting up your own private Bridge: the prompt that lets your agent do it, the same steps by hand, the template-button caveat, what the first session does, and which agent tools are tested."
type: guide
last_updated: 2026-09-24
related:
  - ../README.md
  - updating.md
  - ../rules/push-guard.md
  - ../skills/bridge-onboard/SKILL.md
  - tool-mapping.md
---

# Installing BKS open-bridge

This page is the long form of the README's *Set it up* section. It covers the
one decision that matters before anything else (where your private data will
live), two equivalent ways to get there, and what happens in the first session.

Just want to see it run? The demo workspace needs no setup at all: see the
README's *Or look first: the demo workspace*.

## Give your data a private home first

This repository is public. Onboarding writes your private data (personas,
client names, `work/` logs, credential reference URIs) onto a `user/{name}`
branch. A bare clone's `origin` points at the public repo, so a single
`git push` would publish that branch. Both paths below therefore make **your
own private repo** the `origin` and keep BKS open-bridge as a read-only
`upstream`. A fork does not help here: a fork of a public repo is itself public.

## Path 1: hand this prompt to your agent

Paste this into Claude Code, Codex or Copilot CLI. The agent checks your tools,
shows you its plan and waits for your go, gives the data a private home before
writing any of it, arms the push guard, shows you the proof, and then tells you
to restart it inside the new folder.

```text
Set up BKS open-bridge for me: https://github.com/bks-lab/open-bridge
It is a plain-text memory layer (markdown + YAML in a git repo) that an AI coding
agent reads at the start of every session.

First, before you touch anything: check that git is installed, check whether the
GitHub CLI (gh) is authenticated, ask me what to call my private copy
(default: my-bridge), then show me your plan and wait for my go.

Then, in this order:

1. Clone it and give it a PRIVATE home. The public repo ends up as a read-only
   "upstream", my own private repo as "origin":
       git clone https://github.com/bks-lab/open-bridge.git <name>
       cd <name>
       git remote rename origin upstream
       gh repo create <me>/<name> --private --source=. --remote=origin --push
   Use this order rather than GitHub's "Use this template" button: a template copy
   starts a fresh history, and the documented update path (git merge upstream/main)
   then refuses to run.
   No gh? Stop and ask me to create an empty PRIVATE repo on github.com, then
   continue with: git remote add origin <url> && git push -u origin main

2. Everything below runs inside <name>. Arm the safety hooks:
       ./bin/setup                      # native Windows: bin/setup.ps1

3. Record that my new origin is private. Without this the push guard cannot
   classify the target offline, and it refuses my first legitimate push:
       printf 'repo: <me>/<name>\nis_public: false\n' > .bridge-origin
   Do this only because the repo you created in step 1 is private.

4. Show me all three proofs:
       git remote -v                    # origin must be MY private repo
       git config core.hooksPath        # must be scripts/hooks
       cat .bridge-origin

5. Stop here and tell me to restart you inside <name>. A session loads this repo's
   skills and instructions from the folder it starts in, so /bridge-onboard cannot
   exist in your current session: that folder did not exist when it began.

6. In the new session it should greet me and offer the setup lanes by itself. If it
   does not, run /bridge-onboard. No slash commands? Read
   skills/bridge-onboard/SKILL.md, then skills/bridge-onboard/references/workflow.md,
   and run the phases with me inline.

Hard rules: never push anything to bks-lab/open-bridge; my user/* branch goes only
to my private origin; never write a secret into a file; ask me before anything
destructive.
```

Nothing in it is hidden. Every line is a command you can read before you
approve it.

## Path 2: the same steps by hand

```bash
# 1. Clone, then re-home the remotes: BKS open-bridge becomes a READ-ONLY
#    upstream, your own private repo becomes origin.
git clone https://github.com/bks-lab/open-bridge.git my-bridge
cd my-bridge
git remote rename origin upstream
gh repo create <you>/my-bridge --private --source=. --remote=origin --push

# 2. Tell the push guard your new origin is private, so it can classify the
#    target without asking GitHub (offline, or with no gh on PATH):
printf 'repo: <you>/my-bridge\nis_public: false\n' > .bridge-origin

# 3. Arm the guard and repair the skill discovery symlinks:
./bin/setup                 # native Windows: bin/setup.ps1
```

Then **restart your agent session inside `my-bridge`**. The session that ran
the clone started in another folder and cannot see this repo's skills. In the
new session the Bridge greets you by itself; if it does not, run
`/bridge-onboard`.

## The "Use this template" button

It works, with one caveat. A template copy is private from the first second,
which is why the button exists. But GitHub gives it a fresh, single-commit
history that shares no ancestor with this repo, so the update path aborts with
`fatal: refusing to merge unrelated histories`. Your **first** CORE update then
needs `git merge --allow-unrelated-histories upstream/main` once; every merge
after that is ordinary. The clone-and-re-home path above keeps the full history
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

- **Cursor** is tested in Agent Mode: reads `AGENTS.md`, discovers skills, and executes `/bridge-onboard` successfully.
- **Claude Code** is tested and the most complete: slash commands, hooks and
sub-agents live under `.claude/`.
- **Codex and Copilot CLI** work through `AGENTS.md` plus the skill symlinks
`.agents/skills` and `.github/skills`, both pointing at the one `skills/`
tree.
- **Other tools that read** `AGENTS.md` (Gemini CLI, Cursor, Windsurf) get the
instructions, but their skill discovery is untested here. On a tool without
slash commands, ask for the skill by name and the agent reads its `SKILL.md`.

Tool names per platform, and what a missing sub-agent API means:
[tool-mapping.md](tool-mapping.md). On native Windows a checkout can turn the
symlinks into plain files; `bin/setup.ps1` repairs them (the `bin/` row in
[structure.md](structure.md)).