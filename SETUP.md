# Setting up BKS open-bridge: a guide for the AI agent

**You are an AI coding agent, and your user asked you to set up BKS open-bridge
for them.** Follow this file from top to bottom. It is the single source of the
setup steps; the user-facing pages ([README.md](README.md),
[docs/install.md](docs/install.md), the website) only point here.

BKS open-bridge is a plain-text memory layer (markdown + YAML in a git repo)
that an AI coding agent reads at the start of every session. This repository is
**public**. The user's private data (personas, client names, `work/` logs,
credential reference URIs) will later land on a `user/{name}` branch, so before
any of it exists the copy needs a **private home**: the user's own private repo
becomes `origin`, and BKS open-bridge stays a read-only `upstream`. A fork does
not help, because a fork of a public repo is itself public.

Talk to the user in the language they wrote to you in. Every command below is
meant to be shown to them before it runs.

## Hard rules (for the whole setup)

- Never push anything to `bks-lab/open-bridge`.
- The user's `user/*` branch goes only to their private `origin`.
- Never write a secret (token, password, key) into a file.
- Ask before anything destructive (deleting, overwriting, force-pushing).

## Before you change anything

1. Check that `git` is installed (`git --version`).
2. Check that Python 3 can load PyYAML: `python3 -c "import yaml"`. The
   Bridge's own scripts read YAML from the first session on, so this is a hard
   requirement. If it fails, tell the user and suggest the matching line below;
   run it only after their go:
   - `python3 -m pip install --user pyyaml`
   - Debian or Ubuntu: `sudo apt install python3-yaml`
   - Homebrew Python, which refuses that with `externally-managed-environment`:
     `python3 -m pip install --user --break-system-packages pyyaml` (installs
     into the user's own site-packages, not into Homebrew's)
   `bin/setup` (Step 2 below) runs the same check again.
3. Check whether the GitHub CLI is authenticated (`gh auth status`). If `gh` is
   missing or logged out, say so; step 1 has a path without it.
4. Ask the user what to call their private copy. Default: `my-bridge`. Below,
   `<name>` is that answer and `<me>` is their GitHub account or organisation.
5. Show the user your plan (the steps below, with their `<name>` and `<me>`
   filled in) and **wait for their go**. Do not run step 1 before they say go.

Already cloned this repo just to read this file (because you could not open the
link)? Then that clone is the one to keep. Skip the `git clone` line in step 1
and run the rest of step 1 inside it; if the user picked a different name than
the folder has, rename the folder to `<name>` first.

## Step 1: clone it and give it a private home

```bash
git clone https://github.com/bks-lab/open-bridge.git <name>
cd <name>
git remote rename origin upstream
gh repo create <me>/<name> --private --source=. --remote=origin --push
```

The public repo is now the read-only `upstream`, the user's own private repo is
`origin`.

Use this order rather than GitHub's "Use this template" button: a template copy
starts a fresh history, and the documented update path
(`git merge upstream/main`) then refuses to run. Background:
[docs/install.md](docs/install.md#the-use-this-template-button).

**No `gh`?** Stop and ask the user to create an empty **private** repo on
github.com and give you its URL. Then continue inside `<name>` with:

```bash
git remote add origin <url> && git push -u origin main
```

## Step 2: arm the safety hooks

Everything from here on runs inside `<name>`.

```bash
./bin/setup              # native Windows: bin/setup.ps1
```

This points `core.hooksPath` at `scripts/hooks`, which arms the `pre-push`
guard ([rules/push-guard.md](rules/push-guard.md)), and repairs the skill
discovery symlinks. It also checks for PyYAML again and prints how to install
it when it is missing.

## Step 3: record that the new origin is private

Without this marker the push guard cannot classify the new origin offline, and
it refuses the user's first legitimate push:

```bash
printf 'repo: <me>/<name>\nis_public: false\n' > .bridge-origin
```

Do this **only because** the repo you created in step 1 is private. Never write
`is_public: false` for a public origin.

## Step 4: show the user all three proofs

```bash
git remote -v              # origin must be the user's PRIVATE repo
git config core.hooksPath  # must be scripts/hooks
cat .bridge-origin         # repo: <me>/<name>, is_public: false
```

If any of the three is wrong, stop and fix it with the user before going on.

## Step 5: stop and ask for a restart

Stop here. Tell the user to **restart you inside `<name>`**. A session loads
this repo's skills and instructions from the folder it starts in, so
`/bridge-onboard` cannot exist in your current session: that folder did not
exist when it began.

## Step 6: onboarding, in the new session

The new session greets the user by itself and offers the setup lanes, one of
which is a short live demo for a user who wants to look around first
([rules/session-start.md](rules/session-start.md)). If it does not, run
`/bridge-onboard`. No slash commands in your tool? Read
[skills/bridge-onboard/SKILL.md](skills/bridge-onboard/SKILL.md), then
[skills/bridge-onboard/references/workflow.md](skills/bridge-onboard/references/workflow.md),
and run the phases with the user inline.

The setup is done when onboarding has created the user's `user/{name}` branch.
The hard rules above still apply to every session after this one.
