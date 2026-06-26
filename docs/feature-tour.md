---
summary: "Per-cluster-wrapper guide — fill identity/, infra/, workflow/ folders on demand after onboarding."
type: guide
last_updated: 2026-05-10
related:
  - structure.md
  - extension-model.md
  - ../skills/bridge-onboard/references/workflow.md
---

# Feature Tour — Fill the Cluster-Wrappers

Onboarding (`/bridge-onboard`) gives you a running shell: identity,
ecosystem (opt-in detection), branch, optional work-system, default agents. **Most cluster-
wrapper folders start empty** — `identity/personas/`,
`identity/mandants/`, `infra/channels/`, `workflow/calendars/`, etc.
ship only the templates and schemas. You fill them when a real need
shows up.

This doc is the per-wrapper "create your first X" guide. Each section is
self-contained. Skim the index, jump to what you need, ignore the rest.

## Index

| Wrapper | Folder | When you need it |
|---|---|---|
| identity | [personas](#identitypersonas) | tax data, signatures, persona-aware filing destinations |
| identity | [accounts](#identityaccounts) | mail/calendar accounts your skills authenticate against |
| identity | [mandants](#identitymandants) | recipient groups (team, family, clients) for outbound messages |
| infra | [remotes](#infraremotes) | physical/virtual machines, SSH, Wake-on-LAN, services |
| infra | [channels](#infrachannels) | iMessage, email, Telegram, voice — outbound transports |
| infra | [backups](#infrabackups) | sources × targets × pipelines, scheduled or continuous |
| workflow | [calendars](#workflowcalendars) | scheduled outbound: emails, reports, digests, with recipients |
| workflow | [contexts](#workflowcontexts) | per-domain routing rules (document intake, mail attachments) |
| workflow | [projects](#workflowprojects) | GitHub/ADO project-board configs (fields, governance) |

Validation note: every wrapper that ships a `_schema.yaml` is enforced
by `scripts/validate-bridge.py` (JSON Schema Draft 2020-12 via
`pipx install check-jsonschema`). Run it after edits — it must stay green.

---

## identity/personas/

A persona represents an identity **you hold** — tax data, signature
blocks, document-filing destinations, vehicle classification. Distinct
from mandants (which are recipients you send *to*).

**Create:** `cp identity/personas/_template.yaml identity/personas/<id>.yaml`

**Schema:** `identity/personas/_schema.yaml` (JSON Schema, validates
required fields + types).

**Used by:** routing standing-orders (`protocols/standing-orders/`),
document-intake (`workflow/contexts/doc-system.yaml`), invoice flows.

**Examples:** see `docs/examples/personas/` for anonymised samples.
Full doc: [`docs/personas.md`](personas.md).

## identity/accounts/

A mail or calendar account a skill authenticates against (Microsoft
Graph, Google, IMAP). Stores the auth method and a KeyVault/1Password
URI — never plaintext credentials.

**Create:** `cp identity/accounts/_template.yaml identity/accounts/<id>.yaml`

**Used by:** the `doc-system` skill's mail sources and calendar skills. A
user-supplied or org-overlay skill (e.g. `apple-notes-manager`,
`email-manager`, `outlook-attachment-processor`, `scope: org`) can add more
account-bound consumers — those are not shipped in open-bridge.

**Hard rule:** never commit a real token. Always reference an external
secret store via `keychain://`, `keyvault://`, or `1password://` URIs.

## identity/mandants/

A mandant is a recipient *group* — your team, household, family, a
client. Each mandant carries persons with channel preferences (email,
iMessage, Telegram) and a type tag (`company` 🏢, `household` 👨‍👩‍👧,
`family` 👪, `friends` 🤝, `colleagues` 💼, `individual` 👤).

**Create:** `/mandants add` (interactive) or
`cp identity/mandants/_template.yaml identity/mandants/<id>.yaml`

**Schema:** `identity/mandants/_schema.yaml`.

**Used by:** `workflow/calendars/entries.yaml.recipients[]`, the
`/calendar` and `/mandants` skills.

Full doc: [`docs/mandants.md`](mandants.md).

---

## infra/remotes/

Each physical or virtual machine you administer gets one yaml: hardware,
SSH config, Tailscale + LAN topology, Wake-on-LAN, capabilities, services.

**Create:** `cp infra/remotes/_template.yaml infra/remotes/<name>.yaml`,
plus a `<name>-setup.md` companion for BIOS / first-run / hardware quirks.

**Schema:** `infra/remotes/_schema.yaml`.

**Used by:** `/remote` skill, fleet-ops dispatcher. Vocabulary: "remote"
in Bridge context = a *machine*, not `git remote`. Always check
`infra/remotes/<name>.yaml` first when the user says "my PC", "<your-machine>",
"fleet status", "wake X", "ssh to Y".

**Hard rule:** Tailscale-IP first, LAN as fallback. Never store credentials
in the yaml — KeyVault/1Password URIs only. Honor `wake_on_lan.enabled: false`.

Full doc: [`docs/remotes.md`](remotes.md).

## infra/channels/

A channel is an outbound transport (iMessage, email, Telegram, news digest,
WhatsApp bot). Each channel's runtime usually sits on a remote as a
launchd/systemd unit or watch-path pipeline.

**Create:** `cp infra/channels/_template.yaml infra/channels/<name>.yaml`

**Schema:** `infra/channels/_schema.yaml`.

**Used by:** the `/channel` skill. An org overlay can add
transport-specific skills such as an `email-manager` (`scope: org`). Bots
with their own state live in `infra/channels/bots/<bot-name>/`.

**Hard rule:** declared `status:` is never trusted — the remote's service
manager is the source of truth (see [`rules/deploy-reconciliation.md`](../rules/deploy-reconciliation.md)).

Full doc: [`docs/channels.md`](channels.md).

## infra/backups/

A topology of `sources × targets × pipelines` — what gets backed up where,
with which tool (rclone-sync, rclone-copy, restic-backup, rsync-via-ssh,
time-machine), on which schedule.

**Create:** `cp infra/backups/_template.yaml infra/backups/topology.yaml`
(this folder uses a *singleton* file, not per-instance files).

**State:** `infra/backups/_state.yaml` is written by the `backup` skill —
never hand-edit. `volumes/` and `launchd/` hold supporting files.

**Used by:** a user-supplied or org-overlay `backup` skill (topology-reader + tool-dispatcher) — not shipped in open-bridge; CORE ships the topology data model + schema only.

**Three validation rules** the skill enforces before any run:
1. `sensitivity: encrypted-required` × `tool: rclone-sync` → abort
2. `target.capabilities: [time-machine]` × any other pipeline → abort
3. `mode: scheduled` without `schedule:` → abort

Full doc: [`infra/backups/README.md`](../infra/backups/README.md).

---

## workflow/calendars/

Master list of every scheduled outbound action: emails, iMessages, reports,
digests. Each entry has `recipients: []` (mandant/person pairs),
`delivery_at`, `duration_estimate_min`, optional `repeat`, and an `origin`
block describing how the entry was created.

**Create the master file:**
`cp workflow/calendars/_template.yaml workflow/calendars/entries.yaml`

**Schema:** `workflow/calendars/_schema.yaml`.

**Used by:** `/calendar` skill, the (optional) Python fire-loop, and the
bridge-deck Calendar tab.

**Key rules:**
- Stable slot IDs: `scheduled:calendar:${id}:slot-${N}` — never absolute timestamps
- Duration-aware: `effective_at = delivery_at − duration_estimate_min`
- Multi-mandant: same person can appear in multiple mandants with different roles

Full doc: [`docs/calendar.md`](calendar.md).

## workflow/contexts/

A context is a per-domain routing rule set — most importantly,
`doc-system.yaml` (where PDFs/scans/invoices land) and per-customer
contexts (e.g. routing rules for a specific client engagement).

**Create:** `cp workflow/contexts/_template.yaml workflow/contexts/<id>.yaml`,
add a `<id>.README.md` companion when the rules need explanation beyond
the YAML.

**Used by:** `doc-system`. Org overlays add consumers such as
`mail-attachment-processor` / `outlook-attachment-processor` and
customer-specific coordinators (all `scope: org`).

**Source-of-truth rule:** routing decisions live in exactly one place per
domain — see the routing map in [`docs/structure.md`](structure.md#routing-map-short)
and [`rules/operations.md`](../rules/operations.md). Standing-orders are
NOT routing sources.

## workflow/projects/

A project config tells `github-projects-manager` what fields exist on a
GitHub Project V2 (or ADO board), what their valid values are, and which
governance rules apply (severity levels, required approvals, state mappings).

**Create:** `cp workflow/projects/_template.yaml workflow/projects/<slug>.yaml`

**Used by:** `github-projects-manager` skill (writes), `project-advisor`
skill (governance), `/dashboard` and `/briefing` (reads).

**Workflow rule:** before ANY GitHub/ADO operation, read the matching
`workflow/projects/<slug>.yaml` for valid field values. Don't use raw
`gh issue create` — go through `github-projects-manager` so fields stay
in sync with the project config.

---

## Adjacent surfaces (not cluster-wrappers, but worth knowing)

- **`work/`** — task board, daily log, archives. Activated via
  `work.enabled: true`. See [`AGENTS.md` § Task Management](../AGENTS.md).
- **`protocols/standing-orders/`** — your always-on rules (e.g. "auto-log
  every commit"). USER-layer; CORE ships the templates.
- **`themes/`** — vocabulary themes (`professional`, `professional-de`).
  Set via `bridge-config.yaml` `theme:`. Themes change user-facing wording
  only — never tools, delegation, or protocol logic.
- **`DESIGN.md`** — design-system manifest (palette, typography, spacing).
  Skills generating HTML, PDF, slides, or styled email MUST pull tokens
  from here instead of inventing palettes. Editing rules: `DESIGN.md`
  § Maintaining this file.

## Validation

After any cluster-wrapper edit, run:

```bash
python3 scripts/validate-bridge.py
```

The wrapper depends on `pipx install check-jsonschema`. It walks every
`<wrapper>/<types>/<id>.yaml` (excluding `_`-prefixed files) and
validates against the matching `_schema.yaml`. Must stay green —
pre-commit hook (`.pre-commit-config.yaml`) catches drift early.

## Where to go next

- Add an instance: copy the `_template.yaml`, edit, validate
- Understand the layout: [`docs/structure.md`](structure.md)
- CORE/USER deep dive: [`docs/extension-model.md`](extension-model.md)
- Run multiple Bridges: [`docs/multi-instance.md`](multi-instance.md)
- Upstream promote routing: [`rules/operations.md`](../rules/operations.md) (path allowlist) + [`rules/promote-safety.md`](../rules/promote-safety.md) (content scan).
