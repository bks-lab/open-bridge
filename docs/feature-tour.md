---
summary: "Per-family guide: fill the identity/, infra/ and workflow/ folders on demand after onboarding."
type: guide
last_updated: 2026-09-24
related:
  - structure.md
  - extension-model.md
  - data-model.md
  - ../skills/bridge-onboard/references/workflow.md
---

# Feature Tour: Fill the Cluster-Wrappers

Onboarding (`/bridge-onboard`) gives you a running shell: identity,
ecosystem (opt-in detection), branch, optional Task Management, default
agents. **Most cluster-wrapper folders start empty**: `identity/personas/`,
`identity/mandants/`, `infra/channels/`, `workflow/calendars/` and the rest
ship only their templates and schemas. The goal is **not** to fill every
folder. Fill what serves *this* instance's purpose; the rest stays dormant
until a real need earns it a place.

Onboarding captures that purpose as a one-line north-star (`bridge-config.yaml`
`purpose.statement`/`focus`; change it anytime with `/bridge-onboard --purpose`).
It only ORDERS what surfaces first. It never gates or hides a family, so every
section below is available whenever you reach for it.

This doc is the per-family "create your first X" guide, covering all 19
families in [`AGENTS.md` § Layout](../AGENTS.md). Each section is
self-contained. Skim the index, jump to what you need, ignore the rest.

## Index

| Wrapper | Folder | When you need it |
|---|---|---|
| identity | [personas](#identitypersonas) | an identity you hold: tax data, signatures, filing destinations |
| identity | [mandants](#identitymandants) | recipient groups (team, family, clients) for outbound messages |
| identity | [accounts](#identityaccounts) | a cloud tenant, subscription or vault reference |
| identity | [contracts](#identitycontracts) | a recurring obligation: utility, telco, insurance, SaaS |
| identity | [vehicles](#identityvehicles) | a vehicle you own or lease: plate, VIN, the persona that bears it |
| identity | [agent](#identityagent) | this orchestrator's own name, role and voice |
| infra | [remotes](#infraremotes) | physical or virtual machines, SSH, Wake-on-LAN, services |
| infra | [channels](#infrachannels) | iMessage, email, Telegram, voice: outbound transports |
| infra | [backups](#infrabackups) | sources × targets × pipelines, scheduled or continuous |
| infra | [instances](#infrainstances) | another Bridge this one should know about |
| infra | [transcriptions](#infratranscriptions) | where the meeting-transcription pipeline runs |
| infra | [secret-stores](#infrasecret-stores) | where a secret lives, who reaches it, which kind belongs in it |
| infra | [object-stores](#infraobject-stores) | where content that is not configuration lives: recordings, documents, exports |
| infra | [utilities](#infrautilities) | a supply contract at a location: power, gas, water, heat |
| workflow | [calendars](#workflowcalendars) | scheduled outbound: emails, reports, digests, with recipients |
| workflow | [contexts](#workflowcontexts) | per-domain routing rules (document intake, mail attachments) |
| workflow | [projects](#workflowprojects) | GitHub/ADO project-board configs (fields, governance) |
| workflow | [workloads](#workflowworkloads) | one declared run on one machine: report, poller, daemon, watcher, agent |
| workflow | [workspaces](#workflowworkspaces) | a named binding of repos and config overlays |

Validation note: `scripts/validate-bridge.py` validates instances against
their `_schema.yaml` for personas, mandants, remotes, channels, secret-stores,
object-stores and calendars (JSON Schema Draft 2020-12 via
`pipx install check-jsonschema`). The other families ship a schema for your
editor and for review, but the validator does not check them yet. Run it after
edits; it must stay green.

---

## identity/personas/

A persona represents an identity **you hold**: tax data, signature blocks,
document-filing destinations. Distinct from mandants (which are recipients
you send *to*).

**Create:** `cp identity/personas/_template.yaml identity/personas/<id>.yaml`

**Schema:** `identity/personas/_schema.yaml` (JSON Schema, validates
required fields + types).

**Used by:** routing standing-orders (`protocols/standing-orders/`),
document intake (`workflow/contexts/doc-system.yaml`), invoice flows.

**Examples:** see `docs/examples/personas/` for anonymised samples.
Full doc: [`docs/personas.md`](personas.md).

## identity/mandants/

A mandant is a recipient *group*: your team, household, family, a client.
Each mandant carries persons with channel preferences (email, iMessage,
Telegram) and a type tag (`company` 🏢, `household` 👨‍👩‍👧, `family` 👪,
`friends` 🤝, `colleagues` 💼, `individual` 👤).

**Create:** `/mandants add` (interactive) or
`cp identity/mandants/_template.yaml identity/mandants/<id>.yaml`

**Schema:** `identity/mandants/_schema.yaml`.

**Used by:** `workflow/calendars/entries.yaml.recipients[]`, the
`/calendar` and `/mandants` skills.

Full doc: [`docs/mandants.md`](mandants.md).

## identity/accounts/

A cloud account as inventory, one file per account, conventionally
`<provider>-<tenant>.yaml`: tenant or account ID, subscription or project,
vault and keystore names, resource-group map, and a ready-to-copy
`bootstrap:` block for the login sequence. The template also carries
optional `mail:` and `calendar:` blocks for an account a skill reads mail or
calendar data through.

**Create:** `cp identity/accounts/_template.yaml identity/accounts/<provider>-<tenant>.yaml`,
plus a `<id>.README.md` companion for setup and rotation recipes.

**Used by:** every cloud operation. Before any `az`, `wrangler`, `gcloud`,
`gh api` or provider REST call, the agent reads the matching account file
instead of reconstructing IDs from memory.

**Hard rule:** never commit a real token. Reference the secret by URI only,
`azure-keyvault://<vault>/<secret>`, `keychain://<service>/<account>` or
`1password://<vault>/<item>/<field>`, per
[`rules/secret-placement.md`](../rules/secret-placement.md).

Full doc: [`docs/cloud-accounts.md`](cloud-accounts.md).

## identity/contracts/

A recurring financial obligation you hold: electricity, gas, internet,
mobile, insurance, a SaaS subscription, a retainer. One file per contract,
named `<provider>-<product>.yaml`, so personas can reference a contract
that several of them share instead of duplicating it.

**Create:** `cp identity/contracts/_template.yaml identity/contracts/<provider>-<product>.yaml`,
plus an optional `<id>.README.md` for tariff decisions and price history.

**Schema:** `identity/contracts/_schema.yaml` (required: `schema_version`,
`id`, `provider`, `product`, `status`).

**Used by:** no CORE skill reads it yet; it is reference data for you and the
agent. Put a reminder for the next deadline into `workflow/calendars/` as its
own entry. The meter and site details of a utility contract live in
[`infra/utilities/`](#infrautilities).

## identity/vehicles/

A vehicle you own or lease, the tax classification that decides which persona
bears it, and pointers to everything the vehicle generates (contracts,
remotes such as a wallbox, tasks, archived documents). It is an entry point,
not a warehouse: name where things live in `refs:` and `archive:` instead of
copying them.

**Create:** `cp identity/vehicles/_template.yaml identity/vehicles/<plate-slug>.yaml`

**Schema:** `identity/vehicles/_schema.yaml` (required: `schema_version`,
`id`, `plate`, `persona`, `classification`). Plate, VIN and tax data are
personal data, so an instance is never `scope: core`.

Full doc: [`identity/vehicles/README.md`](../identity/vehicles/README.md).

## identity/agent/

The orchestrator's own identity, distinct from the identities you hold
(`personas/`) and the recipients you send to (`mandants/`): `IDENTITY.md`
(who am I) and `SOUL.md` (how I behave, loaded every session).

**Create:** onboarding seeds both from `_template.IDENTITY.md` and
`_template.SOUL.md` and adds the `@`-import. CORE ships only the templates;
the live files stay on your `user/*` branch and never promote.

**Hard rule:** `SOUL.md` is capped at 80 lines / 4 KB, enforced by
`/bridge-audit`.

Full doc: [`identity/agent/README.md`](../identity/agent/README.md).

---

## infra/remotes/

Each physical or virtual machine you administer gets one yaml: hardware,
SSH config, Tailscale + LAN topology, Wake-on-LAN, capabilities, services.

**Create:** `cp infra/remotes/_template.yaml infra/remotes/<name>.yaml`,
plus a `<name>-setup.md` companion for BIOS, first-run and hardware quirks.

**Schema:** `infra/remotes/_schema.yaml`.

**Used by:** the `/remote` skill. Vocabulary: "remote" in Bridge context
means a *machine*, not `git remote`. Always check
`infra/remotes/<name>.yaml` first when the user says "my PC", "<your-machine>",
"fleet status", "wake X", "ssh to Y".

**Hard rule:** Tailscale IP first, LAN as fallback. Never store credentials
in the yaml, only secret references. Honor `wake_on_lan.enabled: false`.

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

**Hard rule:** a declared `status:` is never trusted; the remote's service
manager is the source of truth (see [`rules/deploy-reconciliation.md`](../rules/deploy-reconciliation.md)).

Full doc: [`docs/channels.md`](channels.md).

## infra/backups/

A topology of `sources × targets × pipelines`: what gets backed up where,
with which tool (rclone-sync, rclone-copy, restic-backup, rsync-via-ssh,
time-machine), on which schedule.

**Create:** `cp infra/backups/_template.yaml infra/backups/topology.yaml`
(this folder uses a *singleton* file, not per-instance files).

**State:** `infra/backups/_state.yaml` is written by the backup skill, never
by hand. `volumes/` and `launchd/` hold supporting files.

**Used by:** a user-supplied or org-overlay `backup` skill (topology reader +
tool dispatcher). It is not shipped in open-bridge; CORE ships the topology
data model and schema only.

**Three validation rules** the skill enforces before any run:
1. `sensitivity: encrypted-required` × `tool: rclone-sync` → abort
2. `target.capabilities: [time-machine]` × any other pipeline → abort
3. `mode: scheduled` without `schedule:` → abort

Full doc: [`infra/backups/README.md`](../infra/backups/README.md).

## infra/instances/

Another Bridge this one should know about: its path, purpose, relationship
(`self`, `sibling`, `upstream`, `downstream`), branch, data and push policy,
and which org overlays it subscribes to. Awareness and navigation only:
registering an instance never authorises reaching into it. You operate it in
its own session.

**Create:** `cp infra/instances/_template.yaml infra/instances/<slug>.yaml`

**Schema:** `infra/instances/_schema.yaml`.

**Used by:** the `/bridge-overlay` engine, which reads
`subscribes_overlays:` to decide whether an instance takes org overlays at
all. See [`docs/multi-instance.md`](multi-instance.md) and
[`docs/org-overlays.md`](org-overlays.md).

## infra/transcriptions/

Where the meeting-transcription pipeline runs: one `topology.yaml` with
`mode: local` (this machine is the worker) or `mode: remote` (a worker host
reached over SSH + rsync). This file is placement only; the content of a
context (language, voice library, output routing) stays in
`workflow/contexts/<ctx>.yaml`.

**Create:** `cp infra/transcriptions/_template.yaml infra/transcriptions/topology.yaml`

**Schema:** `infra/transcriptions/_schema.yaml`.

**Used by:** the `meeting-transcription` skill and `/debrief`.

Full docs: [`infra/transcriptions/README.md`](../infra/transcriptions/README.md),
[`docs/transcription-worker.md`](transcription-worker.md).

## infra/secret-stores/

Where secrets actually live: a keychain on one machine, a KeePass database on
a share, a Key Vault in one subscription, a 1Password vault. One file per
store says where it is, which references it answers (`addresses:`), who
reaches it from where, and which kind of secret belongs in it (`holds:`), so
"where does this new token go" is decided once and not per session.

**Create:** `cp infra/secret-stores/_template.yaml infra/secret-stores/<slug>.yaml`

**Schema:** `infra/secret-stores/_schema.yaml`.

**Used by:** the `/secrets` skill (`stores`, `where`, `store`, `check`,
`audit`). **Hard rule:** never a secret value in this file, only locators,
paths and policy ([`rules/secret-placement.md`](../rules/secret-placement.md)).

## infra/object-stores/

Where content that is not configuration lives: recordings, filed documents,
exports, deliverables that carry personal data. A store is a local directory
or an S3-compatible bucket; an entry elsewhere in the tree points at one
object with `object://<store>/<key>`.

**Create:** `cp infra/object-stores/_template.yaml infra/object-stores/<slug>.yaml`,
then mark a local store once with `object-store.sh init <store>` while it is
really there.

**Schema:** `infra/object-stores/_schema.yaml`.

**Used by:** the `/object-store` skill (`stores`, `stat`, `path`, `fetch`,
`put`, `init`, `forget`). Credentials are references into a secret store,
never values.

Full doc: [`docs/object-store.md`](object-store.md).

## infra/utilities/

One supply contract at one location: electricity, gas, water, district
heating, internet, waste. It holds the master data you need exactly when you
do not have it to hand: meter number, customer numbers with the supplier and
the metering operator, the reading portal.

**Create:** `cp infra/utilities/_template.yaml infra/utilities/<slug>.yaml`,
plus an optional `<slug>-setup.md` for operating notes. There is no schema
yet.

**Used by:** no CORE skill reads it yet. The recurring meter-reading date
belongs in `workflow/calendars/` and points back here via `utility_ref`; the
contract itself can live in [`identity/contracts/`](#identitycontracts).

---

## workflow/calendars/

Master list of every scheduled outbound action: emails, iMessages, reports,
digests. Each entry has `recipients: []` (mandant/person pairs),
`delivery_at`, `duration_estimate_min`, optional `repeat`, and an `origin`
block describing how the entry was created.

**Create the master file:**
`cp workflow/calendars/_template.yaml workflow/calendars/entries.yaml`

**Schema:** `workflow/calendars/_schema.yaml`.

**Used by:** the `/calendar` skill and the (optional) Python fire-loop. Bridge
Deck, a companion dashboard that is not public yet, can show the entries in a
Calendar tab.

**Key rules:**
- Stable slot IDs: `scheduled:calendar:${id}:slot-${N}`, never absolute timestamps
- Duration-aware: `effective_at = delivery_at − duration_estimate_min`
- Multi-mandant: the same person can appear in several mandants with different roles

Full doc: [`docs/calendar.md`](calendar.md).

## workflow/contexts/

A context is a per-domain routing rule set, most importantly
`doc-system.yaml` (where PDFs, scans and invoices land) and per-customer
contexts (routing rules for a specific client engagement).

**Create:** `cp workflow/contexts/_template.yaml workflow/contexts/<id>.yaml`,
add a `<id>.README.md` companion when the rules need explanation beyond
the YAML.

**Used by:** `doc-system`. Org overlays add consumers such as
`mail-attachment-processor` / `outlook-attachment-processor` and
customer-specific coordinators (all `scope: org`).

**Source-of-truth rule:** routing decisions live in exactly one place per
domain; see the routing map in [`docs/structure.md`](structure.md#routing-map-short)
and [`rules/operations.md`](../rules/operations.md). Standing orders are
NOT routing sources.

## workflow/projects/

A project config tells `github-projects-manager` what fields exist on a
GitHub Project V2 (or ADO board), what their valid values are, and which
governance rules apply (severity levels, required approvals, state mappings).

**Create:** `cp workflow/projects/_template.yaml workflow/projects/<slug>.yaml`

**Used by:** `github-projects-manager` skill (writes and governance),
`/dashboard` and `/briefing` (reads).

**Workflow rule:** before ANY GitHub/ADO operation, read the matching
`workflow/projects/<slug>.yaml` for valid field values. Don't use raw
`gh issue create`; go through `github-projects-manager` so fields stay
in sync with the project config.

## workflow/workloads/

One declared run on one machine, in one file: a scheduled report, an interval
poller, a daemon, a path watcher, an inbound agent, a one-shot. The declaration
is the truth; the unit the service manager holds is an artifact rendered from
it and may be rebuilt at any time.

**Create:** `workload declare <id> --kind K --runtime R --host H`, or
`cp workflow/workloads/_template.yaml workflow/workloads/<id>.yaml`

**Used by:** the `workload` skill (`provision`, `reconcile`, `view`, `retire`),
which reads hosts from `infra/remotes/` and paths from the `workloads:` block
of `bridge-config.yaml`.

**Workflow rule:** there is no `status:` field, deliberately. A declared status
is never the truth; the service manager is. State comes from `reconcile` asking
the live source ([`rules/deploy-reconciliation.md`](../rules/deploy-reconciliation.md)).
Full model: [`docs/workloads.md`](workloads.md).

## workflow/workspaces/

A named binding of member repos and config-overlay subscriptions: the working
set a session operates on. The file is your intent; `role: code` members are
cloned into the gitignored `.bridge/workspaces/<id>/<member>/`, and
`role: config` members are delegated to the overlay engine.

**Create:** `python3 scripts/workspace.py create <id>` (or `/workspace create <id>`),
then `subscribe <id> <git-url>` per member repo.

**Schema:** `docs/schemas/workspace.schema.yaml`.

**Used by:** the `/workspace` skill and `scripts/workspace.py`.

Full doc: [`docs/workspaces.md`](workspaces.md).

---

## Adjacent surfaces (not cluster-wrappers, but worth knowing)

- **`work/`**: task board, daily log, archives. Activated via
  `work.enabled: true`. See [`AGENTS.md` § Task Management](../AGENTS.md).
- **`protocols/standing-orders/`**: always-on rules (e.g. "auto-log every
  commit"). CORE ships the defaults; your own orders live in
  `protocols/standing-orders/user/`.
- **`themes/`**: vocabulary themes (`professional`, `professional-de`, `professional-fr`).
  Set via `bridge-config.yaml` `theme:`. Themes change user-facing wording
  only, never tools, delegation, or protocol logic.
- **`DESIGN.md`**: design-system manifest (palette, typography, spacing).
  Skills generating HTML, PDF, slides, or styled email MUST pull tokens
  from here instead of inventing palettes. Editing rules: `DESIGN.md`
  § Maintaining this file.

## Validation

After any cluster-wrapper edit, run:

```bash
python3 scripts/validate-bridge.py
```

The wrapper depends on `pipx install check-jsonschema`. It walks the
`<wrapper>/<types>/<id>.yaml` instances of the schema-checked families
(excluding `_`-prefixed files) and validates each against the matching
`_schema.yaml`. It must stay green; the pre-commit hook
(`.pre-commit-config.yaml`) catches drift early.

## Where to go next

- Add an instance: copy the `_template.yaml`, edit, validate
- Understand the layout: [`docs/structure.md`](structure.md)
- The whole data model on one page: [`docs/data-model.md`](data-model.md)
- CORE/USER deep dive: [`docs/extension-model.md`](extension-model.md)
- Run multiple Bridges: [`docs/multi-instance.md`](multi-instance.md)
- Upstream promote routing: [`rules/operations.md`](../rules/operations.md) (path allowlist) + [`rules/promote-safety.md`](../rules/promote-safety.md) (content scan).
