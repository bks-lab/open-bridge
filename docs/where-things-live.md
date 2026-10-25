---
summary: "A question-to-location map: the question in the words somebody asks it on the left, the file that answers it on the right. CORE ships the CORE rows; an instance appends its own in work/where-things-live.md"
type: reference
last_updated: 2026-09-24
related:
  - ../rules/knowledge-growth.md
  - structure.md
  - ../scripts/check-where-things-live.py
---

# Where things live

You have a question right now and do not know which file answers it. Find the
question below; the right column is the file, with a section where the file is
long. Two other documents sound similar and answer something else:
[`rules/knowledge-growth.md`](../rules/knowledge-growth.md) says where **new**
knowledge should go, and [`docs/structure.md`](structure.md) says how the tree is
**laid out**. Neither helps when you already have the question.

The answer usually exists already, often in a reference file of a skill nobody
thought to open. Searching finds it only when you already know the words it was
written in, which is why this map is written in the words of the question instead.

**Your question is not here?** Answer it, then propose the row: the question the
way you would have asked it, the file that answered it. A CORE answer goes into
this file, an answer that lives in this instance goes into the instance file
(§ Adding rows). Answering and leaving the map as it was means the next person
searches again.

## Configuration

| Question | Where |
|---|---|
| Which fields does a new config file of a given type take? | [`rules/file-creation.md`](../rules/file-creation.md#where-templates-live-lookup-table), then that type's `_template.yaml` and `_schema.yaml` |
| Which folder does a new kind of config go in? | [`docs/structure.md`](structure.md#cluster-wrappers--default-to-folder) |
| Which AI CLI handles each service, and how can a worker choose one? | [`docs/ai-services.md`](ai-services.md), `workflow/ai-services/` |
| Does this file ship to open-bridge, or stay in my instance? | [`docs/structure.md`](structure.md#core--user-split), [`docs/extension-model.md`](extension-model.md) |
| How does a skill find every file of one config type? | [`rules/discovery.md`](../rules/discovery.md#contract) |
| Which field values and states may I set on a tracker board? | [`workflow/projects/_template.yaml`](../workflow/projects/_template.yaml), then the instance's `workflow/projects/<slug>.yaml` |
| Where does a secret go, and how does a config file refer to it? | [`rules/secret-placement.md`](../rules/secret-placement.md), [`infra/secret-stores/_template.yaml`](../infra/secret-stores/_template.yaml) |
| Which cloud tenant and subscription does a command need? | [`docs/cloud-accounts.md`](cloud-accounts.md) |
| Which machine is "my PC", and how do I reach it? | [`skills/remote/references/fleet.md`](../skills/remote/references/fleet.md#stage-1--identify-target), then the instance's `infra/remotes/` |

## Gates: how an operation is guarded

| Question | Where |
|---|---|
| What does a session check before it answers the first message? | [`rules/session-start.md`](../rules/session-start.md) |
| Do I have to ask before I start changing things? | [`AGENTS.md`](../AGENTS.md#consult-before-write), [`rules/task-management-workflow.md`](../rules/task-management-workflow.md#intent-classification) |
| What must I read before I create a new file? | [`rules/file-creation.md`](../rules/file-creation.md#pre-write-checklist) |
| May I push this branch to that remote? | [`rules/push-guard.md`](../rules/push-guard.md#the-invariant) |
| What is scanned before a file moves to open-bridge? | [`rules/promote-safety.md`](../rules/promote-safety.md#what-to-scan) |
| What do I owe after a push before I call it done? | [`rules/ci-discipline.md`](../rules/ci-discipline.md) |
| When does work need an independent review before "done"? | [`rules/operations.md`](../rules/operations.md#pre-done-independent-review) |
| May I trust a `status:` field that says a service is running? | [`rules/deploy-reconciliation.md`](../rules/deploy-reconciliation.md#the-rule) |
| How much may a session load before it starts working? | [`context-budget.yaml`](../context-budget.yaml) |
| How does a CORE change get from my instance to open-bridge? | [`rules/operations.md`](../rules/operations.md#coreuser-separation), [`rules/core-fix-workflow.md`](../rules/core-fix-workflow.md) |
| What happens before an overlay writes into my tree? | [`rules/org-overlays.md`](../rules/org-overlays.md) |

## Skills: what they do and what they may write

| Question | Where |
|---|---|
| What may a skill change about itself, or about the Bridge, without asking? | [`rules/learning-autonomy.md`](../rules/learning-autonomy.md#the-four-layers) |
| May a CORE skill hard-code an ID, a name or a query? | [`docs/extension-model.md`](extension-model.md#generic-core-skills--the-one-never-hardcode-principle) |
| Which tier does a skill ship to, and who decides? | [`AGENTS.md`](../AGENTS.md#skills-universal) |
| Which skill must a given keyword trigger? | [`rules/skill-routing.md`](../rules/skill-routing.md) |
| Should this skill step be written as a procedure or marked as a workaround? | [`rules/file-creation.md`](../rules/file-creation.md#writing-skill-steps-procedure-or-workaround) |
| Where does a lesson about one skill go? | [`docs/skill-learnings.md`](skill-learnings.md) |
| Where does a file a task produces go? | [`rules/task-management-workflow.md`](../rules/task-management-workflow.md#deliverables-location--never-tmp) |

## External tools and their conventions

| Question | Where |
|---|---|
| How are GitHub issues read and normalised for the briefing? | [`trackers/github.md`](../trackers/github.md) |
| How are Azure DevOps work items read and normalised for the briefing? | [`trackers/ado.md`](../trackers/ado.md) |
| How are GitLab issues read and normalised for the briefing? | [`trackers/gitlab.md`](../trackers/gitlab.md) |
| Which GraphQL call does a GitHub Projects operation need? | [`skills/github-projects-manager/references/graphql-patterns.md`](../skills/github-projects-manager/references/graphql-patterns.md) |
| What is a tool called in the agent client I am running in? | [`docs/tool-mapping.md`](tool-mapping.md) |
| Which colour, font or spacing does a page or slide use? | [`DESIGN.md`](../DESIGN.md) |
| Which slash commands exist? | [`docs/commands.md`](commands.md) |

## Decisions: where they were recorded, and why

| Question | Where |
|---|---|
| Why was a learning proposal accepted, rejected or deferred? | [`work/_learning/audit-trail.md`](../work/_learning/audit-trail.md), empty in CORE and filled by the instance's own reviews |
| Why was a context-budget cap raised? | [`context-budget.yaml`](../context-budget.yaml), the `note:` of that item |
| Why does the push guard block a user branch? | [`rules/push-guard.md`](../rules/push-guard.md#why-this-rule-exists) |
| Where was yesterday's work and its reasoning written down? | [`docs/work-system.md`](work-system.md#log-format--one-file-per-period-daily-blocks), the instance's `work/log.md` |
| What changed in a release? | [`docs/changelog.html`](changelog.html) |

## Knowledge and work

| Question | Where |
|---|---|
| Where does a new piece of knowledge belong? | [`rules/knowledge-growth.md`](../rules/knowledge-growth.md) |
| What goes into the memory base, and where is it on disk? | [`docs/memory.md`](memory.md) |
| Where does a task live, and what does its status mean? | [`docs/work-system.md`](work-system.md#status-semantics) |
| What still needs me, and how does an open item get closed? | [`docs/inbox.md`](inbox.md) |
| What does my briefing show, from which trackers, and how do I change it? | [`docs/briefings.md`](briefings.md) |
| How do I choose the cockpit's tabs, columns, marks and language? | [`docs/bridge-cockpit.md`](bridge-cockpit.md) § 8 |
| How do I see and steer the whole Bridge in a browser (inbox, tasks, agent tabs, machines)? | [`docs/bridge-cockpit.md`](bridge-cockpit.md) (early version) |
| What is in `mods/`, and how do I install or test a mod? | [`mods/README.md`](../mods/README.md) |
| How do the day's agent tabs get planned and steered, with or without a terminal tool? | [`docs/workplace.md`](workplace.md) |
| How does a machine that is always on become the arm of my Bridge? | [`docs/always-on-machine.md`](always-on-machine.md) |
| How do I close a task? | [`docs/work-system.md`](work-system.md#3-step-close) |
| Which task, open or closed, mentioned a word, and in which file? | [`docs/work-system.md`](work-system.md#finding-work) (`scripts/work-find.py`), in the cockpit the search of [the files view](bridge-cockpit.md#the-files-view) |
| Which view does the cockpit's work tab open on, and how do I switch it? | [`docs/bridge-cockpit.md`](bridge-cockpit.md#the-files-view) (`cockpit.work_view`, `cockpit.focus_to_files`) |
| What does a row of the work log look like? | [`AGENTS.md`](../AGENTS.md#logging), [`docs/work-system.md`](work-system.md#log-format--one-file-per-period-daily-blocks) |
| Which always-on orders apply to every session? | [`protocols/standing-orders/README.md`](../protocols/standing-orders/README.md) |
| Which language must a file be written in? | [`rules/language-policy.md`](../rules/language-policy.md) |
| How do I read one project's entry without loading the whole registry? | [`docs/context-index.md`](context-index.md#using-it) |

## Adding rows

**CORE rows** live in this file and ship with open-bridge. **Instance rows** live
in `work/where-things-live.md`, a file CORE never ships: the answers to an
instance's own questions sit in its own skills, config and external stores, and
none of that may travel upstream. `work/` is instance content as a whole folder,
so every router already keeps the file home (promote, sync, contribute, the
push guard), and because upstream never writes it, an upstream merge never
touches an instance's rows. Create it the first time you need it, with the same
two-column table; links are relative to `work/`:

```markdown
# Where things live: this instance

| Question | Where |
|---|---|
| Which wiki holds the customer runbooks? | [runbooks](https://wiki.example.org/runbooks) |
| Which field values does our main board take? | [`workflow/projects/main.yaml`](../workflow/projects/main.yaml) |
```

Three rules for every row, in either file:

1. **The left column is a question**, opening the way a question does (how, what,
   where, which, may, does, ...) and ending in `?`, in the words somebody who is
   stuck would use. "How do I write a comment that renders on the tracker?", not
   "Tracker conventions". A reader should recognise their own question, not deduce
   it. This is the property that decays first.
2. **The right column is a link** that resolves, with a `#section` where the file
   is long. An external store is a link too.
3. **An instance row adds a question**; it does not repeat a CORE one. When the
   instance answers a CORE question differently, that is a fork of the answer and
   belongs in the file the CORE row points at.

`python3 scripts/check-where-things-live.py` holds both files to these rules: a
row that is not a question, a link that does not resolve (or resolves only on a
case-insensitive disk, or outside the repository), an anchor the target does not
have, and a question asked twice. CI and `bridge-audit` Check 15 both run it, on
the CORE file and, where it exists, the instance file. The question test is
mechanical: it catches "Tracker conventions" and "Tracker conventions?", not a
question nobody would actually ask, so a reviewer still reads the left column.

Rows are written by people who got stuck, not generated from the tree. A
generated table of contents is the thing this map deliberately is not.
