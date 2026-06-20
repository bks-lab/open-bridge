# yaml-language-server: $schema=./_schema.status.yaml
---
# Copy this file to work/tasks/<slug>/STATUS.md when starting a new task
# (or work/streams/<slug>/STATUS.md for a long-runner — KIND = the folder).
# Validate with:
#   check-jsonschema --schemafile work/templates/_schema.status.yaml \
#                    work/tasks/<slug>/STATUS.md
#
# Three-axis routing (see CLAUDE.md § Task Sync Routing):
#   context: → workflow/contexts/<slug>.yaml   (WHERE we document)
#   mandant: → identity/mandants/<slug>.yaml   (WHO we address)
#   sync.github.project → workflow/projects/<slug>.yaml (WHICH board)

slug: <slug-matches-folder-name>
type: refactor              # refactor | incident | customer-comm | research |
                            # bug | feature | admin | talk | ops | infra | meeting
status: doing               # backlog | doing | review | done
priority: P2                # P0 | P1 | P2 | P3
created: YYYY-MM-DD
last_updated: YYYY-MM-DD

# Optional — blocked is a FLAG, not a status: a blocked task stays doing/review
# and carries the reason here (presence = blocked).
# blocked_by: "<reason — presence means blocked; status stays doing/review>"

# Optional — set ONLY together with status: done. 'declined' = closed without
# completion (replaces a 'cancelled' status).
# outcome: declined

# Optional — link to routing defaults (resolves through workflow/contexts/)
# context: my-context

# Optional — link to recipients (resolves through identity/mandants/)
# mandant: my-mandant

# ---------------------------------------------------------------------------
# Sync block — explicit external bindings, overrides context defaults.
#
# Decision tree for every new task:
#   1. Is this purely local work?           → sync: { bridge_only: true }
#   2. Customer/team work tracked in GitHub? → fill sync.github (+ wiki)
#   3. Work tracked in Azure DevOps?        → fill sync.ado
#
# `bridge_only: true` is a legitimate answer, not a placeholder. State it
# explicitly so future-you knows this task was DELIBERATELY local.
# ---------------------------------------------------------------------------
sync:
  bridge_only: true         # set to false when one of the blocks below is filled

  # github:
  #   repo: my-org/my-repo
  #   issues: [42]                              # tracking issues, multiple allowed
  #   project: { org: my-org, number: 1 }       # GitHub Project V2 board

  # wiki:
  #   path: wiki/customers/example/projects/this-task/
  #   moc_update: wiki/customers/example/_MOC.md

  # ado:
  #   project: null
  #   work_items: []

# Optional — free-form references (kept for human readers)
# related:
#   - ../../log.md
#   - ../../board.md
---

# <Task Title>

## Situation

(What is this task about? What problem are we solving?)

## Status

(Current state, what's been done, what's blocked.)

## Next Steps

- [ ] First action
- [ ] Second action

## Stakeholder / Stakeholders

(Optional — who's involved beyond `mandant:` recipients.)

## Postmortem

(Set at task close. Optional — the task-close-postmortem skill prompts six
questions, all skip-able. Fill what's useful, ignore what's not. Frontmatter
fields `time_invested`, `estimate_vs_actual`, `lessons`, `bridge_gaps` are
the machine-readable counterparts; the prose below is for the human reader.)

### What went well

(1-N bullets, or skip)

### What went wrong / time burned

(1-N bullets, or skip)

### Where did the Bridge help / fall short

(skill / standing-order / rule / doc — or "nothing noteworthy")

### Concrete Bridge improvements proposed

(Each bullet here becomes a candidate Proposal under work/_learning/proposals/.
Filled by the postmortem skill — User just says yes/no per candidate.)
