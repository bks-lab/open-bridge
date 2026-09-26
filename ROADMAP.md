# Roadmap

**Honest status:** BKS open-bridge is built and used day to day by the
BKS-Lab team on its own instances. Besides those, the team runs closed
instances for other companies. Outside contributors have started to test it
and add to it, but nobody outside those instances has reported using it for
daily work yet. This roadmap is a *direction*, not a set of dated promises.
Priorities move with what people actually need. **Every open item below links
to its issue: react 👍 on the issues you want most**; that's the signal
ordering gets decided by. Discuss use-cases in
[Discussions](https://github.com/bks-lab/open-bridge/discussions).

Nothing below is a commitment to a date, and "Later" means exactly that.

## What's proven, what's a bet, what's open

This ledger lives here and nowhere else; the README and the site link to it.

**Evidence base:** everything marked PROVEN is built into BKS open-bridge and
used on real workdays by the BKS-Lab team, on the team's own instances and on
the closed instances it runs for other companies. Nobody outside those
instances has reported using it for daily work yet, so none of this is a
market test.

**PROVEN: built and in daily use on those instances:**

- The three-cluster layout (`identity/` · `infra/` · `workflow/`), Task
  Management (board, log, per-task STATUS), the CORE/USER branch split,
  personas, standing orders and the skills layer all run from a fresh clone
  today.
- Scope routing works in practice: each file carries a scope (`core` / `org` /
  `user`), and `/bridge-promote` routes per scope. Organisation overlays close
  the loop in the other direction: `/bridge-overlay` subscribes an instance to
  an organisation's config by git URL, without a fork.
- GitHub task sync works for the team's own use: the agent knows whether a
  task also exists in GitHub and syncs it. There is no Jira provider.

**BET: falsifiable wagers:**

- Markdown + YAML + git is the substrate successive agent-runtime generations
  keep reading natively, because models read text, not a vendor API.
  *Falsified if* the dominant agent stack later forces a schema vendor (for
  example Notion MCP or Linear MCP) as the standard.
- A lean, opinionated, MIT-licensed method beats a vendor workflow builder for
  users who want to switch models freely. *Falsified if* Cursor or Anthropic
  ship a first-class markdown-in-git mode.
- Workspace separation as a hard default, once built, is the right call for
  most users, not an opt-in switch. The default itself is not built yet; see
  OPEN.

**OPEN: unsolved:**

- Until people outside the team's instances use it, every statement about a
  target audience is a hypothesis.
- Workspaces as containers are built: `/workspace` binds code repos and
  config overlays into a named workspace (see Shipped). What stays open is
  making separation the default: tasks kept apart per context, the "if you
  can't place it into your known world-models, ask" rule, and stripping
  unrelated tangents. Tangent stripping is hand-tested as a *separate* skill,
  but **none of these three are built into BKS open-bridge yet**, and the
  hard-silo versus soft-folder default is unresolved. The issues that carried
  this ([#43](https://github.com/bks-lab/open-bridge/issues/43),
  [#91](https://github.com/bks-lab/open-bridge/issues/91)) were closed as
  duplicates without the default being built.
- First-session value is thin: a fresh clone gives little reward until
  `work/log.md` is filled. Two worked examples (`examples/agency`,
  `examples/portfolio`) are the current answer; a third shape follows when
  someone asks for it ([#45](https://github.com/bks-lab/open-bridge/issues/45)).
- Rolling an instance out to someone else, with a structured way to learn
  from how it behaves, is set aside for now
  ([#56](https://github.com/bks-lab/open-bridge/issues/56)).

## Next

Nothing is in flight. The next item is whatever the OPEN column above or a
new issue earns first.

## Later

Nothing else is queued. The OPEN column above names what is unsolved; each
item gets an issue here once work on it starts. Open an issue or a
Discussion if something you need is missing.

## Shipped

- **Workspaces**
  ([#88](https://github.com/bks-lab/open-bridge/pull/88),
  [#89](https://github.com/bks-lab/open-bridge/pull/89)): `/workspace` binds
  code repos and config overlays into a named project container, with a
  machine-global identity other tools can read and member clones kept out of
  git.
- **First outside contributions**: a GitLab tracker playbook
  ([#239](https://github.com/bks-lab/open-bridge/issues/239),
  [#244](https://github.com/bks-lab/open-bridge/pull/244)) and a French locale
  theme ([#238](https://github.com/bks-lab/open-bridge/issues/238),
  [#261](https://github.com/bks-lab/open-bridge/pull/261)), plus a Cursor test
  on Windows ([#241](https://github.com/bks-lab/open-bridge/issues/241)).
- **Documentation overhaul**
  ([#234](https://github.com/bks-lab/open-bridge/pull/234),
  [#235](https://github.com/bks-lab/open-bridge/pull/235)): the README as a
  front door, install, update and secrets guides, a docs index that lists
  every page once, a command reference held to the skill tree by CI, and this
  file as the single home of the ledger.
- **A second worked example**
  ([#45](https://github.com/bks-lab/open-bridge/issues/45),
  [#236](https://github.com/bks-lab/open-bridge/pull/236)):
  `examples/portfolio`, one person with several hats and a home server, with
  every example validated against the CORE schemas in CI.
- **Persistent project memory**: context that survives across sessions, in plain
  markdown + YAML in git.
- **Cross-tool skill discovery**: the same `SKILL.md` skills are found through
  three committed symlinks to `skills/`: `.claude/skills` (Claude Code),
  `.github/skills` (GitHub Copilot) and `.agents/skills` (Codex and Mistral
  Vibe, per `docs/tool-mapping.md`; `GEMINI.md` points Gemini CLI there too).
  Tools without a discovery path of their own, such as Cursor, read
  `AGENTS.md` and load a skill from `skills/` by path.
- **Task Management**: a generated board + an append-only work log, with
  a closed status model.
- **Guided onboarding**: a four-lane front door (see it run, describe your
  goal, go private first, or bind a workspace) that takes a fresh clone to a
  running instance; hardened first-run (push-guard, scope consent, goal
  clarity) ([#51](https://github.com/bks-lab/open-bridge/issues/51),
  [#46](https://github.com/bks-lab/open-bridge/issues/46)).
- **Organization overlays**: subscribe to an organization's config by git URL
  and provision it onto a vanilla open-bridge, no fork
  ([#48](https://github.com/bks-lab/open-bridge/issues/48), `docs/org-overlays.md`).
- **Meeting transcription**: a bring-your-own-worker contract for `/debrief`
  plus a full reference pipeline (whisper.cpp + pyannote speaker naming) as a
  CORE skill (`docs/transcription-worker.md`, `skills/meeting-transcription/`).
- **One-command health check**: `/bridge-status` reports whether an instance
  is wired up correctly: configs resolve, the board generates from the task
  dirs, and docs + links are healthy
  ([#44](https://github.com/bks-lab/open-bridge/issues/44)).
- **Mirror-aware install**: a clone commits to your own private repo, never a
  silent push upstream: the armed `pre-push` guard, the private-template setup,
  and the `git fetch upstream && git merge upstream/main` update path keep you
  current without a public fork
  ([#52](https://github.com/bks-lab/open-bridge/issues/52), `rules/push-guard.md`).
- **Representative agent (Bridge-Agent) runtime**: a persistent, addressable
  A2A endpoint that fronts a persona to the world and to peer bridges under
  human gates; generic runtime + template in `agents/`, guide in
  `docs/representative-agent.md`
  ([#49](https://github.com/bks-lab/open-bridge/issues/49),
  [#126](https://github.com/bks-lab/open-bridge/pull/126)).
- **MCP→A2A gateway**: a thin, stateless gateway (`agents/_gateway/`) that
  lets MCP-only frontends (Claude connectors, ChatGPT developer mode, Gemini)
  talk to a bridge's A2A agent; anonymous access is standard, a bearer token
  unlocks more
  ([#125](https://github.com/bks-lab/open-bridge/pull/125), discovery closed
  in [#124](https://github.com/bks-lab/open-bridge/issues/124)).
- **Data-model guardrails: which data lives where**
  ([#53](https://github.com/bks-lab/open-bridge/issues/53)): CORE/org/user
  data boundaries explicit and enforceable, so instances stay clean by
  construction.
- **Staying current, unattended**: a daily job merges CORE updates into your
  branch behind guards that fail closed on local edits or a predicted conflict
  ([#187](https://github.com/bks-lab/open-bridge/pull/187),
  [#213](https://github.com/bks-lab/open-bridge/pull/213)), and a companion job
  keeps every subscribed org overlay current: it applies updates, reports a new
  tool for one explicit yes, and never deletes anything unattended
  ([#214](https://github.com/bks-lab/open-bridge/pull/214)). Finished in
  [#218](https://github.com/bks-lab/open-bridge/issues/218): it holds on a
  conflict, honours the pull interval, and says what it did
  ([#229](https://github.com/bks-lab/open-bridge/pull/229)).
- **Workloads, declared runs on your machines**: one file per scheduled job,
  daemon or watcher; the `workload` skill provisions it and reconciles the
  declaration against the live service manager, never against a status field
  ([#161](https://github.com/bks-lab/open-bridge/pull/161),
  [#178](https://github.com/bks-lab/open-bridge/pull/178),
  [#180](https://github.com/bks-lab/open-bridge/pull/180)).
- **A measured session context**: what every session loads has a declared
  budget that CI enforces, registries are read as a table of contents with one
  entry fetched on demand, and the skill and sub-agent listing is measured too
  ([#165](https://github.com/bks-lab/open-bridge/pull/165),
  [#166](https://github.com/bks-lab/open-bridge/pull/166),
  [#167](https://github.com/bks-lab/open-bridge/pull/167)).
- **Memory in the repo**: Claude Code's auto memory can live under
  `work/memory/`, versioned with the rest of the instance
  ([#208](https://github.com/bks-lab/open-bridge/pull/208)), and archiving a
  period distils its durable facts into it
  ([#158](https://github.com/bks-lab/open-bridge/pull/158)).
- **Memory on any harness**: `scripts/memory-location.py` serves the memory
  index as part of the session-start read, so a harness without Claude Code's
  auto memory reads the same `work/memory/`, and
  `docs/memory.md` states how long a memory's session link resolves
  ([#209](https://github.com/bks-lab/open-bridge/issues/209),
  [#201](https://github.com/bks-lab/open-bridge/issues/201),
  [#230](https://github.com/bks-lab/open-bridge/pull/230)).
- **A secrets skill**: one broker (`/secrets`) that resolves a reference
  against Keychain, KeePass, Azure Key Vault or 1Password without printing
  it, says where a new secret belongs, writes one without it passing through
  argv, and audits for plaintext that never became a reference
  ([#215](https://github.com/bks-lab/open-bridge/issues/215),
  [#222](https://github.com/bks-lab/open-bridge/pull/222),
  [#223](https://github.com/bks-lab/open-bridge/pull/223),
  [#224](https://github.com/bks-lab/open-bridge/pull/224)).
- **One picture of the data model**: `docs/data-model.md`, generated from
  `docs/data-model.yaml` and held to the tree in CI, says which data is core,
  per user and per organisation, where each object lives and what it
  references; the rings on the site come from the same source
  ([#217](https://github.com/bks-lab/open-bridge/issues/217),
  [#221](https://github.com/bks-lab/open-bridge/pull/221)).
- **Storage beyond git**: a decision record (`docs/object-store.md`) for
  content that must not live in a repository, the `infra/object-stores/`
  family, and one resolver (`/object-store`) behind `object://` references
  ([#216](https://github.com/bks-lab/open-bridge/issues/216),
  [#226](https://github.com/bks-lab/open-bridge/issues/226),
  [#225](https://github.com/bks-lab/open-bridge/pull/225),
  [#228](https://github.com/bks-lab/open-bridge/pull/228)).
- **A learning loop that checks itself**: an audit trail written from git,
  proposals that consult earlier rejections, per-skill provenance, and
  optional before and after verification with a recurrence check
  ([#202](https://github.com/bks-lab/open-bridge/issues/202),
  [#203](https://github.com/bks-lab/open-bridge/issues/203),
  [#204](https://github.com/bks-lab/open-bridge/issues/204),
  [#205](https://github.com/bks-lab/open-bridge/issues/205),
  [#231](https://github.com/bks-lab/open-bridge/pull/231)).
- **Lessons inside the skill they are about**: a skill-local lesson journal
  (`docs/skill-learnings.md`) and authoring guidance that marks model-specific
  workarounds
  ([#163](https://github.com/bks-lab/open-bridge/issues/163),
  [#206](https://github.com/bks-lab/open-bridge/issues/206),
  [#232](https://github.com/bks-lab/open-bridge/pull/232)).
- **A question-to-location map**: `docs/where-things-live.md` maps a question,
  in the words somebody asks it, to the file that answers it, and a CI check
  keeps every row a question and every link resolving
  ([#164](https://github.com/bks-lab/open-bridge/issues/164),
  [#233](https://github.com/bks-lab/open-bridge/pull/233)).

## Ecosystem: companion projects

BKS open-bridge is the substrate; these optional, independently usable
projects sit around it. Take only what you need.

- **Bridge Deck**: a pixel-art, real-time dashboard that renders a bridge's
  live state (services, crew, calendar, channels), read-only and
  config-driven. It is a separate companion project and is not public yet.
- **Representative agent**: the CORE `agents/` runtime + template, plus the
  MCP→A2A gateway that fronts it to MCP-only clients; see *Shipped*.

> Honest note: the companion projects run today on the BKS-Lab team's own
> setups. They're built for technical early adopters, not yet for critical
> infrastructure.

## How priorities are set

Today this is shaped by the BKS-Lab team's real use, on its own instances and
on the closed instances it runs for other companies, plus community 👍 on the
linked issues and Discussions. Items move between sections as they're picked
up; the changelog is the [Releases
page](https://github.com/bks-lab/open-bridge/releases).

## Safety & trust

BKS open-bridge drives an AI agent over your repos, infra, and cloud, so the
guardrails matter as much as the features. They live in the agent's
instructions (`AGENTS.md` / `CLAUDE.md`) as plain text, so you can read and
change every one of them:

- **Propose, then confirm.** The agent proposes; you decide. Every persistent change to its own configuration goes through a human gate, and it pauses before writing into your productive folders.
- **Destructive and outward actions are gated per action.** Shutdown, reboot, delete, sending a message, merging a PR, rotating a credential: each needs an explicit `[y]`, never a blanket yes.
- **Secrets never live in the repo.** Only reference URIs (`azure-keyvault://…`, `1password://…`, `keychain://…`); the real values stay in your vault, and CI fails on a committed secret.
- **Nothing phones home.** BKS open-bridge is files your agent reads locally: no telemetry, no analytics, no hosted service. Nothing leaves your machine.
- **It's inspectable.** Clone the repo and `cat` exactly what the agent reads; its "memory" is a diffable git history you own.

These are conventions the agent follows, not an OS-level sandbox. Read them in `AGENTS.md` and adapt them to your own risk tolerance.
