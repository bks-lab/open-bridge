---
summary: "Running multiple Bridge instances for data isolation across organizations — shared CORE upstream, separate USER data per instance."
type: guide
last_updated: 2026-06-21
related:
  - docs/structure.md
  - docs/extension-model.md
---

# Multi-Instance Setup

Run multiple Bridge instances when you work across organizations that
require data isolation. Each instance shares the same CORE upstream but
keeps its own user data separate.

## When You Need This

- You work for **multiple organizations** and their project data must not
  mix in git history
- One organization uses GitHub, another uses Azure DevOps or GitLab
- Client contracts or compliance rules prohibit storing metadata (ticket
  IDs, team names, infrastructure URLs) on external git remotes
- You want some instances pushed to a remote and others kept local-only

> **Note:** This instance uses the cluster-wrapper layout
> (`identity/`, `infra/`, `workflow/`). Other instances may stay on
> the older layout — see [`CLAUDE.md`](../CLAUDE.md) section
> "Layout — Cluster-Wrappers".

> **Related but not identical:** Multi-instance describes
> **several Bridges side by side**, all pulling from the same upstream.
> The tier model (see CLAUDE.md § Tier Model) has a different focus:
> **one** Bridge with *two* upstreams (open-bridge = OSS layer,
> `<your-org>/<your-bridge>` = your org overlay) and a multi-upstream
> promote flow (`/promote` routes `scope:core` to open-bridge,
> `scope:org` to your org overlay). Multi-instance stays orthogonal — you can still run
> multiple Bridge clones side by side after adopting the tier model.

A single Bridge instance with multiple `workflow/contexts/<id>.yaml` files is sufficient when all
projects belong to the same organization or share the same data
classification. Multi-instance is for **cross-organization isolation**.

## Instance Registry

Register every Bridge this hub should be aware of in
`infra/instances/<slug>.yaml` (template + schema:
`infra/instances/_template.yaml` / `_schema.yaml`). The registry maps
where each instance lives, what it's for, and its data/push policy —
**awareness and navigation only**: knowing an instance exists is not a
licence to reach into it. The isolation hard rule
([`rules/multi-instance-isolation.md`](../rules/multi-instance-isolation.md))
still governs: read-only from here, operate each instance in its own
session at its path.

## Architecture

```
Instance 1: ~/work/org-a/open-bridge/    Instance 2: ~/work/org-b/open-bridge/
────────────────────────────────────     ────────────────────────────────────
Pushed → org-a remote (GitHub)           LOCAL ONLY, never pushed
ecosystem: org-a projects                ecosystem: org-b projects
contexts/: client-x/, internal/          contexts/: project-y/
work/: org-a work log                    work/: org-b work log (git-backed!)
Theme: professional-de                   Theme: professional
Agents: custom preset                    Agents: default roles
          ↑                                            ↑
          └───────── shared upstream: main ───────────┘
                     git merge main → same CORE updates
```

Both instances track the same `main` branch as upstream. CORE
updates (new commands, standing orders, templates, docs) flow into both
instances identically. USER data (contexts, work logs, agents,
ecosystem.yaml) is completely independent per instance.

## Setup

### Instance 1 (pushed)

Standard setup — clone, onboard, push your user branch:

```bash
git clone https://github.com/bks-lab/open-bridge.git ~/work/org-a/open-bridge
cd ~/work/org-a/open-bridge
claude    # /bridge-onboard runs automatically
git push -u origin user/your-name
```

### Instance 2 (local-only)

Clone the same repo but never push the user branch:

```bash
git clone https://github.com/bks-lab/open-bridge.git ~/work/org-b/open-bridge
cd ~/work/org-b/open-bridge
claude    # /bridge-onboard — configure for org-b
```

To pull CORE updates without pushing user data:

```bash
cd ~/work/org-b/open-bridge
git fetch origin main
git merge origin/main
# user/ branch stays local — never git push
```

### Fork Variant

If your pushed instance is a fork of the canonical upstream:

```bash
# Instance 1 (fork from open-bridge)
git remote add upstream https://github.com/bks-lab/open-bridge.git

# Instance 2 (also fork, or direct clone)
git remote add upstream https://github.com/bks-lab/open-bridge.git
```

> **Note:** Public OSS upstream is `bks-lab/open-bridge`. Org-internal
> users may set upstream to `<your-org>/<your-bridge>` (a private fork
> that layers org-specific skills on top). See CLAUDE.md
> § Tier Model for the multi-upstream pattern.

Both instances run `git fetch upstream main` + `git merge` for
CORE updates. `/briefing` and `/archive` check upstream automatically
when `upstream.check_interval_days` is set in `bridge-config.yaml`.

## What Each Instance Gets

Every Bridge instance is a full, independent setup:

| Feature | Per instance |
|---------|-------------|
| `ecosystem.yaml` | Own project registry |
| `bridge-config.yaml` | Own theme, language, integrations |
| `workflow/contexts/` | Own project bundles |
| `work/` | Own board, log, tasks, archives |
| `.claude/agents/` | Own agent definitions or preset |
| `protocols/standing-orders/` | Shared CORE + own orders in `standing-orders/user/` |
| `infra/channels/`, `infra/remotes/` | Own messaging + remote machines |
| `identity/mandants/`, `workflow/calendars/` | Own recipients + scheduled actions |

## Data Isolation

The CORE/USER branch split ensures isolation:

- **USER paths** (bridge-config.yaml, workflow/contexts/, work/, .claude/agents/,
  infra/channels/, infra/remotes/, identity/mandants/, workflow/calendars/) live only on `user/{name}`
- If you never push `user/{name}`, none of that data leaves your machine
- CORE paths (CLAUDE.md, docs/, templates, commands) contain no
  organization-specific data

**What stays local in a local-only instance:**
- Organization names, team member names, project URLs
- Work item IDs, ticket numbers, infrastructure endpoints
- Work logs, task statuses, meeting insights
- Agent customizations with org-specific knowledge

**What is shared via CORE upstream:**
- Command definitions, protocol templates, standing orders
- Theme files, sub-agent definitions, onboarding wizard
- Documentation, examples, schemas

## Trade-offs

**What you gain:**
- Full data isolation between organizations
- Each instance has its own context window (no CLAUDE.md bloat)
- Each organization gets the full Bridge feature set independently
- Local-only instances give git-backed work tracking to projects that
  previously had no version-controlled logs

**What you give up:**
- No single board across all organizations — each instance has its own
  `work/board.md` and `work/log.md`
- `/briefing` shows only the current instance's projects
- Upstream CORE merges must be done per instance (but they're fast and
  conflict-free)

**Mitigations:**
- Use distinct terminal windows or workspaces per instance for clear
  separation
- Name instances by organization for easy identification (`org-a-bridge`,
  `org-b-bridge`)
- Set different themes per instance for visual distinction (professional-de
  for personal projects, professional for client work)

## FAQ

**Can I have more than two instances?**
Yes. Each is an independent clone with its own user branch. Three
organizations → three instances.

**Can I merge work logs between instances?**
Not automatically. The work systems are independent. If you need a
combined view, consider writing a script that reads `work/log.md` from
each instance and merges them.

**What if both organizations use GitHub?**
You still need separate instances if the data can't mix. Push each to
its own GitHub repo — `org-a/open-bridge` and `org-b/open-bridge` — or
keep one local.

**What if I only need contexts, not full isolation?**
Use a single instance with multiple `contexts/`. Multi-instance is
specifically for when project metadata must not share a git history.

**Does bridge-deck work with multiple instances?**
Each bridge-deck daemon points at one Bridge instance. You could run
two daemons on different ports, but that's unusual. Most users pick one
instance for visualization and manage the other via terminal.
