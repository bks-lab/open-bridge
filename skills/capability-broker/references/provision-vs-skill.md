# Provision vs Skill — the decision tree

The routing call after the gap is confirmed and (optionally) researched. One
question drives it: **is the missing piece infrastructure or procedure?**

```
Is the capability achievable with tools the machine ALREADY has?
│
├─ NO  → the missing piece is INFRASTRUCTURE → PROVISION A TOOL
│        ├─ a binary / CLI?           → install via package manager
│        ├─ an external API/service?  → wire an MCP, or create an account file
│        └─ also a repeatable procedure around it?
│                 ├─ NO  → document the tool dependency, done
│                 └─ YES → ALSO scaffold a skill (BOTH) — provision the tool first
│
└─ YES → the capability is ORCHESTRATION → worth persisting?
         ├─ recurs / multi-step / needs guardrails or domain knowledge
         │        → SCAFFOLD A SKILL (hand to skill-creator)
         └─ single-use / trivial → ONE-OFF (do it now + ledger note)
```

Rule of thumb: **tool = a thing the machine lacks; skill = a procedure the
machine lacks.** A skill orchestrates tools; it is not a substitute for one.

## Provision sub-routes (each step a per-action `[y]`)

### CLI

- Install via the platform package manager (`brew` / `apt` / `uv` / `npm` / …).
  Confirm the exact command with the user before running it.
- The tool becomes ambient (`command -v <tool>` detectable). Record the
  dependency in the consuming skill's `allowed-tools`.
- Propose a `checkup` registry entry (`workflow/checks/*.yaml`) so the tool's
  presence is health-checked over time (engine + declarative registry, see the
  `checkup` skill). This is how a provisioned CLI stays monitored without a
  bespoke tools registry.

### MCP

- Add the server to `.mcp.json` (create it if absent) — show the diff, confirm.
- Document required secrets/env as a Keychain / Vault / 1Password URI reference,
  **never a raw value** in any tracked file.
- Note that the MCP's tools appear as deferred tools next session.

### Account / service

- A cloud service routes through the existing
  `identity/accounts/<provider>.yaml` flow and its hard credential gates.
- capability-broker **routes here, it does not create credentials.** Account
  creation, token minting, KeyVault writes stay behind the Bridge's existing
  hard gates (per AGENTS.md and docs/cloud-accounts.md). Read the matching account doc first.

## Skill handoff (to skill-creator)

capability-broker does **not** author SKILL.md. It assembles a brief and hands
it to the `skill-creator` skill:

- **name** — a crisp slug (route-neutral, no type-prefix)
- **trigger phrases** — EN (+ the instance's conversation language if non-EN)
- **scope** — `core` if generic, else `user`/`org` (drives `metadata.scope`)
- **the tool it wraps** — the provisioned CLI/MCP/account (if any)
- **the procedure** — the multi-step workflow + any guardrails
- **progressive-disclosure plan** — what goes in SKILL.md vs `references/`

`skill-creator` owns authoring, structure, and the
`scripts/validate-skill-scope.py` check. After it lands, run
`validate-skill-scope.py` once: it validates the new frontmatter and refreshes the
per-instance tier map at `.bridge/skill-scope.md`.

## BOTH (tool + skill)

Common and correct — e.g. a transcription capability needs a binary *and* a
pipeline skill. **Order: provision the tool first**, verify it runs, *then*
scaffold the skill that wraps it, so the skill can call the tool on its first
run. Both artifacts get captured in the learning (see `learning-capture.md`).

## One-off

If orchestration + not worth persisting: do it now with existing primitives,
then write only a ledger row (recurrence counter). If that same gap recurs
≥ `recurrence_escalate_after` times, the ledger escalates it to a "persist now"
proposal — the one-off becomes evidence for a future skill.
