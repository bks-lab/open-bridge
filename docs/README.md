---
summary: "The capability index of BKS open-bridge: every doc and site page, listed once, grouped by who is reading."
type: readme
last_updated: 2026-11-05
---

# BKS open-bridge documentation

Every page under `docs/` is listed here exactly once, grouped by where you
are: your first day, coming back with a question, or operating and
maintaining the project. The HTML pages are also published at
<https://bks-lab.github.io/open-bridge/>. The operating manual for the agent
itself is [`AGENTS.md`](../AGENTS.md); what is built, what is a bet and what
comes next is in [`ROADMAP.md`](../ROADMAP.md).

## First day

Start here if you have just cloned the repo or are deciding whether to.

- [`index.html`](index.html): the landing page. What a Bridge is, in one scroll.
- [`demo.html`](demo.html): four session flows (briefing, session start, an operator incident, onboarding) replayed as they run.
- [`use-cases.html`](use-cases.html): concrete jobs, each a problem you will recognise and what the Bridge does about it.
- [`concepts.html`](concepts.html): every concept in plain language, in depth.
- [`explore.html`](explore.html): an interactive map of the concepts and of which files ship as CORE and which are yours.
- Onboarding itself is the `bridge-onboard` skill (`skills/bridge-onboard/`): run `/bridge-onboard`.
- [`feature-tour.md`](feature-tour.md): after onboarding, "create your first X" for each of the 19 config families.
- [`commands.md`](commands.md): every CORE slash command and the skill behind it.
- [`install.md`](install.md): setting up your own private instance, by prompt or by hand, and what each step is for.

## Returning user

You have an instance and a question. **Start with
[`where-things-live.md`](where-things-live.md)**: a question in your own words
on the left, the file that answers it on the right.

**Layout and data**

- [`structure.md`](structure.md): the cluster-wrapper layout in prose (Default-to-Folder) and the routing map.
- [`data-model.md`](data-model.md): the data model on one page: islands, object types, stores, references, and what a session reads when.
- [`work-system.md`](work-system.md): Task Management: log, board and task lifecycle (KIND folder versus `status:` field). The operational rules are in [`AGENTS.md` § Task Management](../AGENTS.md).
- [`memory.md`](memory.md): file-based memory: one fact per file, `MEMORY.md` as a lean index, how every harness reads it.
- [`context-index.md`](context-index.md): how a session reads a large registry as a table of contents and fetches one entry on demand.

**Identity, recipients and accounts**

- [`personas.md`](personas.md): identities you hold (tax data, signatures, filing paths).
- [`mandants.md`](mandants.md): recipient groups for outbound messages.
- [`calendar.md`](calendar.md): scheduled outbound actions with recipients.
- [`cloud-accounts.md`](cloud-accounts.md): cloud-account inventory; read it before any cloud operation.
- [`secrets.md`](secrets.md): reference URIs instead of values, which store a new secret belongs in, and the `secrets` skill that resolves them.

**Machines, runs and transports**

- [`remotes.md`](remotes.md): your machine fleet: SSH, wake, services.
- [`channels.md`](channels.md): outbound transports (mail, chat, bots, digests).
- [`workloads.md`](workloads.md): one declared run on one machine, in one file; [`workloads.html`](workloads.html) is the illustrated version.
- [`transcription-worker.md`](transcription-worker.md): the contract between `/debrief` and a transcription pipeline, plus the manual path. Reference implementation: `skills/meeting-transcription/`.
- [`doc-system.md`](doc-system.md): document intake and filing (scan, name, tag, file, audit).
- [`object-store.md`](object-store.md): decision record for content that must not live in a repository, and how an entry points at it with `object://`.

**Several instances, organisations and workspaces**

- [`multi-instance.md`](multi-instance.md): running several Bridges to keep organisations' data apart.
- [`org-overlays.md`](org-overlays.md): subscribing to an organisation's shared config and materialising it as copies (the downstream inverse of `/bridge-promote`).
- [`updating.md`](updating.md): pulling CORE and overlay updates, by hand or unattended, and how a CORE fix flows back.
- [`workspaces.md`](workspaces.md): binding config overlays and member repos into a named workspace; [`workspaces.html`](workspaces.html) is the illustrated version.
- [`capability-registry.md`](capability-registry.md): a machine-global registry through which one instance declares a shared capability (a transcription worker, a backup pipeline) without weakening data isolation.
- [`knowledge-repo-pattern.md`](knowledge-repo-pattern.md): pairing an instance with an optional knowledge or documentation repo.

**Agents facing outward**

- [`representative-agent.md`](representative-agent.md): Bridge-Agents, persistent A2A endpoints that front a persona to the outside world; [`agents.html`](agents.html) is the illustrated version.

**Skills, tools and companions**

- [`tool-mapping.md`](tool-mapping.md): how this repo's tool names map onto Codex, Copilot, Gemini CLI and Cursor.
- [`skill-learnings.md`](skill-learnings.md): where a lesson about one skill lands, inside that skill.
- [`okf-export.md`](okf-export.md): exporting the knowledge surfaces as an Open Knowledge Format bundle for external tooling.
- [`bridge-cockpit.md`](bridge-cockpit.md): the Bridge cockpit, an optional local web page that watches and steers the Bridge; an early version (alpha) that is still being extended. Changing its code: [`bridge-cockpit-dev.md`](bridge-cockpit-dev.md).
- [`ai-services.md`](ai-services.md): which local AI CLI (Claude by default, or Codex) a service such as the cockpit chat uses.
- [`bridge-deck.md`](bridge-deck.md): Bridge Deck, an optional pixel-art visualizer that is not public yet.
- [`changelog.html`](changelog.html): every release, pulled from GitHub Releases.

## Operators and maintainers

You change CORE, run the upstream flow, or maintain the project.

- [`extension-model.md`](extension-model.md): how CORE extends and USER customises, with the schemas.
- [`kernel.md`](kernel.md): the kernel, everything a session reads before its first answer: where each piece lives and at which tier, when it is read, which file links it. Also why `docs/` is tiered by folder.
- [`skill-distribution-architecture.md`](skill-distribution-architecture.md): decision record for where skills live across the tier model.
- [`repo-layout.md`](repo-layout.md): repo-layout visualisations (the primary view is generated on demand).
- [`releasing.md`](releasing.md): how releases work: a conventional-commit PR title becomes a tag and a GitHub release.
- [`workspace-acceptance-test.md`](workspace-acceptance-test.md): a zero-prior-context acceptance-test playbook for the workspace feature.
- Promoting CORE changes from a user branch: [`rules/operations.md`](../rules/operations.md) (path allowlist and routing) and [`rules/promote-safety.md`](../rules/promote-safety.md) (content scan).
