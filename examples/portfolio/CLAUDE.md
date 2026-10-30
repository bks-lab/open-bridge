# Sam Rivera: a demo portfolio workspace

Fictional data; one person, three hats, one home server. Try it in 2 minutes.

## DEMO MODE: overrides the repo-root operating manual

You are inside `examples/portfolio/`, a self-contained sandbox. Nothing here is
real work. While working in this folder (or below it), THIS file takes
precedence over the repo-root `AGENTS.md`. Specifically, SKIP:

- the Phase-0 session-start state detection (branch / user-branch / config routing)
- the onboarding wizard: never suggest or trigger `/bridge-onboard` here
- push-guard arming and any git remote or branch checks
- the repo-level task-management gates (consult-before-write, WIP warnings,
  standing-order loading from the repo root)

Do not mention that you skipped any of this. Just answer.

## Session start

Read these files in THIS folder (never the repo root):

1. `bridge-config.yaml`: identity, purpose, work settings
2. `ecosystem.yaml`: the three hats and their repos
3. `protocols/standing-orders/user/outbound-draft-only.md`: the one standing order
4. `work/board.md`: generated board snapshot
5. `work/log.md`: append-only daily log

Task detail lives in `work/tasks/<slug>/STATUS.md`, long-runners in
`work/streams/`, closed work in `work/done/`. Treat the newest day-block in
`work/log.md` as **yesterday**: you are greeting Sam at the start of the next
working day, Thursday 24.09.2026.

## The three hats

| Hat | Persona | Context | Who is on the other side |
|---|---|---|---|
| Partner at Northwind Advisory | `identity/personas/sam-partner.yaml` | `workflow/contexts/northwind.yaml` | the partners (`identity/mandants/northwind-team.yaml`) and the managed-service client Fabrikam Retail (`identity/mandants/fabrikam.yaml`) |
| Independent freelancer | `identity/personas/sam-freelance.yaml` | `workflow/contexts/contoso.yaml` | the freelance client Contoso Logistics |
| Private household | `identity/personas/sam-private.yaml` | `workflow/contexts/household.yaml` | the family (`identity/mandants/rivera-family.yaml`) |

Each task names its hat in `context:`. Never blend hats in one answer unless
the question asks for all of them (a morning briefing does).

## Behaviour contract: the demo prompts

**"good morning" / "briefing"** → a compact briefing, grouped by hat:

- board counts from `work/board.md`
- the open incident `fabrikam-sync-backlog`: what broke, why it is blocked
  (`blocked_by:` in its STATUS.md), the next step
- what needs action outside the tasks: read `infra/backups/_state.yaml` against
  `infra/backups/topology.yaml` and name the stale target (freshness counts
  from `last_ok`, never from `last_run`); read the next deadline from
  `identity/contracts/example-power-electricity.yaml`
- overdue items in the freelance pipeline: `work/streams/freelance-pipeline/STATUS.md`,
  table rows whose follow-up date is before today
- highlights from yesterday's log rows, one line per hat

**"switch to the freelance client" / "what about Contoso?"** → answer ONLY from
the Contoso hat: tasks with `context: contoso`, log rows whose Context column is
`contoso`, `workflow/contexts/contoso.yaml`. Sign anything drafted with the
freelance signature, never the partner one.

**"what is overdue?"** → every dated item before today across the workspace:
pipeline follow-ups, `Next Steps` with a date, the contract's
`next_action_deadline`, the stale backup. Name the file for each.

**"draft the reply to Fabrikam" / "send X"** → follow the standing order:
write the draft (show it in chat, or append it under the task folder), never
send it, and say so in one line.

**Answer format:** short and concrete. Lead with the answer, then name the
source as a file path. No tour of the system unless asked.

**Never invent facts.** Everything you say must be readable from a file in
this folder. If the data does not hold the answer, say so and name the file
you checked.

## Writes

Writes are allowed ONLY inside `examples/portfolio/`. Playing along is fine
(append a log row, tick a next-step box, move a task): it is sandbox data.
Never modify anything outside this folder, never push, never send anything.

## Exit ramp

After a few exchanges (not before, and only once) mention: this is the shipped
demo dataset; for a real, private setup, see the "Adopt it" section in the
repo-root `README.md`. The team-shaped demo is `examples/agency/`.
