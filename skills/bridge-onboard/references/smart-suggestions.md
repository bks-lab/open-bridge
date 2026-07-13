---
description: Phase C of onboarding — map Phase-B evidence to concrete feature suggestions with full advisory text. Evidence-driven, never asks abstract life-situation questions. Also used by /bridge-onboard --add to scaffold a specific feature on demand.
type: reference
last_updated: 2026-05-16
---

# Smart Suggestions — Evidence to Recommendation

Phase C of the onboarding wizard. The scan from Phase B
(`work/onboarding-scan.json`) is loaded; this file maps each evidence
pattern to a concrete suggestion with the advisory text the wizard
shows the user.

## Ordering Signals — Purpose + Profile (both set in Phase A)

Phase C **asks no bias question here.** Both ordering signals were captured in
Phase A (step 5); the standalone bias-question that used to live in this file (and
in broader-only Phase B) has moved there — so confined-default users get asked it
too. *(Phase C is skipped entirely in confined mode — that's fine; these signals
then only matter on `--add` and in the Phase E catalogue.)*

- **`purpose.focus`** — the **primary order**. A subset of the six catalog
  life-domains (`identity`, `communication`, `infrastructure`, `productivity`,
  `integrations`, `visualization`) derived from the user's one-line purpose statement.
- **`user_profile`** (`work | private | both`) — the **secondary tiebreak**, and it
  still colours suggestion *language* ("for your team" vs "for your family").

**Precedence for every suggestion (the whole filtering contract):**
evidence-strength → `purpose.focus` membership → `user_profile`.

1. **evidence-strength** gates whether a suggestion appears at all — **UNCHANGED**
   ("no suggestion without evidence", below).
2. **`purpose.focus` membership** is the primary sort: a suggestion whose tagged
   life-domain is in focus sorts first. A strong-evidence suggestion **outside**
   focus still appears — never hidden — after the focus ones, prefixed
   `Outside your stated focus, but strong evidence:`.
3. **`user_profile`** breaks ties under focus: **work** → GitHub-projects, channels
   (team), remotes, m365-admin tiebreak up, finance/voice down; **private** →
   finance, voice, household mandant up, m365-admin and team channels down;
   **both** → balanced.

> **Guardrail — purpose SUGGESTS/ORDERS/LABELS only.** Neither `purpose.focus` nor
> `user_profile` gates, hides, removes, or blocks a feature. Treating `focus` as an
> allowlist is a bug. Every capability stays one `/bridge-onboard --add`/`enabled:`
> flip away. **Empty purpose (focus `[]`) → ordering falls back to the
> `user_profile` tiebreak only, i.e. today's exact behaviour.**

Where it reads naturally, substitute `purpose.statement` into the advisory copy
("This fits what you said this Bridge is for — {statement}.") — copy only, never a
gate.

### Catalog-domain tag per S-block

Used for the `purpose.focus`-first sort above:

| S-block | Feature | Catalog domain |
|---|---|---|
| S1 | Repos & GitHub | `integrations` |
| S2 | Remotes | `infrastructure` |
| S3 | Backups | `infrastructure` |
| S4 | Document Sensor | `identity` |
| S5 | Finance | `productivity` |
| S6 | Mail Accounts | `identity` |
| S7 | Calendar integration | `integrations` |
| S8 | Bridge-Deck | `visualization` |
| S10 | Voice messages | `communication` |
| S11 | Knowledge / Wiki repo | `productivity` |
| S12 | Upstream wiring | `integrations` |

## Principles for Suggestions

1. **No suggestion without evidence.** If Phase B found nothing matching
   a feature, it goes to Phase E (catalogue), not to Phase C. That feature
   is NOT mentioned in Phase C at all — no "not detected" line, no "you
   don't have X". It lives only in the Phase E catalogue.
2. **Concrete advice, not toggles.** Each suggestion explains *what
   gets created*, *what becomes possible*, and *what stays manual*.
3. **Three answers per suggestion:**
   - `[y]` Do it — feature enabled, scaffolds created, state recorded
   - `[m]` More info — show longer description + link to docs, then re-ask
   - `[l]` Later — recorded as deferred, surfaces again via
     `feature-discovery` standing-order in ~30 days
   - (No `[n]/skip` button — that path is friendlier as `[l]` and gives
     the user a clean way back. If they want hard-no: `decline 3 times`
     → silenced forever, or `--reset` to start over.)
4. **Memory-check first.** Each suggestion section starts by reading
   `work/onboarding-state.yaml` — skip if `accepted` or `silenced`,
   honour `remind_after` if `deferred`.
5. **Curated gotcha warnings only.** Where a suggestion has a known
   product-level gotcha (e.g. OneDrive FileProvider Orphan-Stub Bug),
   surface it from the curated CORE table — see "Known-Gotcha Overlay"
   below. Never free-scan the operator's memory base, and never name a
   customer, employer, persona, or contact.

## Evidence → Suggestion Mapping

Listed in **typical surface order** for `user_profile: both`. Each block
is a self-contained advisory script — paste the relevant text near-
verbatim into the wizard output, substituting the variable parts.

---

### S1 — Repos & GitHub (almost always surfaces)

**Trigger:** `evidence.developer.repo_count >= 1`

**Advisory:**

```
Found {N} repos in {projects_root}:
  • {count_per_org_summary}

I'll write these into ecosystem.yaml grouped by org. Repos without a
git remote land as `local-only: true`.

{if !evidence.homebrew.formula.includes("gh"):}
  Optional: install `gh` (GitHub CLI) for issue / PR / project features.
  → brew install gh && gh auth login
{endif}

  [y] Write ecosystem.yaml from scan
  [m] Show the table first
  [l] Later — I'll add repos manually
```

> Note: don't manually copy `ecosystem.example.yaml` — onboarding
> generates the live `ecosystem.yaml` from the scan; the example is the
> reference shape only.

**On accept:** generate ecosystem.yaml using the algorithm in
`discovery.md` (which is now scoped to repo-detection only); record
`suggestions.ecosystem: accepted`.

---

### S2 — Remotes (when a mesh-VPN or known_hosts present)

**Trigger:** `evidence.mesh_vpn.devices.length >= 2`
**OR:** `evidence.ssh_known_hosts.length >= 3`

**Advisory (mesh-VPN variant):**

```
Your mesh-VPN ({evidence.mesh_vpn.impl}) reports {N} devices:
  {device_list}

Bridge can manage these as a "fleet" — SSH config + Wake-on-LAN +
service inventory per box. Useful when you say "wake alice-mini" or
"is alice-nas online?".

What this enables:
  • /remote status — health-check across all devices
  • /remote wake <name> — Wake-on-LAN via LAN-relay
  • SSH config templates with mesh-VPN-first, LAN-fallback

What stays manual:
  • Credentials never live in YAML — KeyVault / 1Password URIs only
  • You opt in per machine before any destructive action runs

  [y] Scaffold {N} remote files (one per device, you fill capabilities later)
  [m] Show the template first
  [l] Later — wire up when I need fleet ops
```

**On accept:**
- Copy `infra/remotes/_template.yaml` → `infra/remotes/<hostname>.yaml`
  for each detected device, pre-filling: `hostname`, the mesh-VPN IP
  (e.g. `network.tailscale_ip`), `os` (best-guess from device-name patterns or known)
- Set `remotes.enabled: true` in `bridge-config.yaml`
- Mention follow-up: "Edit each file to add `capabilities`, `services`,
  `wake_on_lan` settings as you need them — see `docs/feature-tour.md
  #infra-remotes`"

---

### S3 — Backups (when rclone/restic/Backblaze/Time Machine detected)

**Trigger:** Any of:
- `evidence.homebrew.formula` includes `rclone` or `restic` or `borgbackup`
- `evidence.apps` includes `Backblaze.app`, `Arq.app`, `Carbon Copy Cloner.app`
- `tmutil destinationinfo` returns at least one destination (run only if user opted into a backups-probe)

**Advisory:**

```
Detected backup tooling:
  {tool_list}

Bridge (CORE) can model your backup topology declaratively — sources × targets ×
pipelines — a version-controlled description of what should be backed up.

What CORE ships here:
  • The topology data-model + template (infra/backups/) — declarative, version-controlled
  • Per-pipeline validation rules (e.g. encrypted-required sources can't use rclone-sync)

What needs a separate install:
  • The /backup EXECUTOR (drift detection, running rclone/restic/rsync) is a
    separately-installed skill — CORE ships the data model, not an executor. Without it,
    the topology is documentation you can act on manually.
  • You wire actual sources/targets — the wizard scaffolds the topology shell only.

  [y] Scaffold topology.yaml with current sources pre-filled (data-model only)
  [m] Read infra/backups/README.md first
  [l] Later
```

**On accept:**
- Copy `infra/backups/_template.yaml` → `infra/backups/topology.yaml`
- Pre-fill `sources:` with detected backup-relevant paths (~/Developer, ~/Documents, ~/Library)
- Leave `targets:` and `pipelines:` empty with `# fill me` comments

---

### S4 — Document Sensor (when PARA/JD structure or Inbox PDFs)

**Trigger:** Any of:
- `evidence.documents_structure` matches PARA pattern (`0_Import`, `1_PROJECTS`, `2_AREAS`, `3_RESOURCES`, `4_ARCHIVE`)
- `evidence.documents_structure` matches Johnny Decimal pattern (`00-09_`, `10-19_`, ...)
- A scanned inbox-like folder (`Downloads`, `0_Import`, `Inbox`, `Scans`) contains ≥5 PDFs/scans

**Advisory (PARA detected):**

```
Found a PARA-style structure at {docs_root}:
  {folder_list, max 6}

{if inbox has PDFs:}
  I see {N} PDFs waiting in {inbox_path} — doc-system can route these
  automatically as they arrive.
{endif}

What this enables:
  • Auto-classify PDFs/scans dropped into your inbox
  • Route to context-aware destinations (rules in workflow/contexts/doc-system.yaml)
  • Audit trail in work/doc-system/log.md

What I'll scaffold now:
  • bridge-config.yaml: doc_sensor.enabled: true, scan_paths preset to PARA defaults
  • workflow/contexts/doc-system.yaml from template — empty routing rules

What stays for later:
  • Routing rules — you define these when you actually have files to sort
  • Persona-specific queues (e.g. tax-folder destinations) — wire when needed

{if docs_root contains "OneDrive":}
  ⚠ Heads-up (from the curated gotcha table): macOS Tahoe + OneDrive can hit
    a FileProvider Orphan-Stub bug. Consider migrating PARA to a local tree
    (e.g. ~/PARA-Documents) before enabling.
{endif}

  [y] Enable with PARA defaults
  [c] Choose a different docs_root
  [l] Later
```

**On accept:**
- Write `bridge-config.yaml`:
  ```yaml
  doc_sensor:
    enabled: true
    onedrive_root: "{detected_docs_root}"  # variable name historical; any folder
    context: "workflow/contexts/doc-system.yaml"
    scan_paths:
      - { label: "Import",    path: "0_Import" }
      - { label: "Areas-Import", path: "2_AREAS/Import" }
    queue_paths: []   # user fills as personas / contexts arrive
  ```
- Copy `workflow/contexts/_doc-system.template.yaml` → `workflow/contexts/doc-system.yaml`
- Mention: "Personas (e.g. freelancer vs private filing) are a follow-up —
  `/bridge-onboard --add personas` when you have a tax bundle to file."

---

### S5 — Finance (when a finance app is installed)

**Trigger:** the Capability Map matched a finance app (e.g. MoneyMoney). If
none is installed, this block never appears.

**Advisory:**

```
Finance app detected: {app_name}{, with {N} accounts: {account_names} if scanned}.

If it's MoneyMoney, Bridge can read it via AppleScript — read-only, no
transfers ever triggered automatically. Any finance app maps to the same
read-only finance capability.

What this enables:
  • "Is invoice X paid?" → a private finance skill looks up the transaction
  • Account balance summaries in /briefing
  • Invoice-status checks for freelancer workflows

What stays manual:
  • Any actual transfer needs your TAN in the finance app itself
  • Bridge writes nothing — read-only by design

  [y] Note as a private skill to build (open-bridge ships no finance
      skill — see docs/extension-model.md for private/org skills)
  [l] Later
```

**On accept:** record `suggestions.finance: accepted` so we don't
re-suggest; building the skill is up to the user (`scope: private`).

---

### S6 — Mail Accounts → identity/accounts/

**Trigger:** `evidence.mail_accounts.length >= 1`

**Advisory:**

```
Mail accounts found: {account_list}

Bridge tracks mail/calendar accounts in identity/accounts/<id>.yaml —
references to credentials live as KeyVault / 1Password URIs, never raw.

What this enables:
  • Skills that send mail know which account to use (per persona later)
  • /briefing can pull calendar/mail signals if you enable
    integrations.context_sources.outlook
  • Audit of which accounts Bridge touches

What stays manual:
  • Secrets — Bridge never sees passwords, only references to them

  [y] Scaffold {N} account files (display-name only, you wire secrets later)
  [m] Show the schema
  [l] Later
```

**On accept:**
- Copy `identity/accounts/_template.yaml` → `identity/accounts/<slug>.yaml`
  per account (slug = account-name normalized)

---

### S7 — Calendar integration

**Trigger:** `evidence.calendar_list.length >= 1` AND mail accounts include something Graph-compatible (Outlook/Microsoft 365)

**Advisory:**

```
You have {N} calendars connected{, including Outlook/M365 — Microsoft Graph
is available for read-only pulls if you wire it}.

What this enables (only if you flip context_sources.outlook to true):
  • /briefing reads your next 24h of calendar entries
  • /debrief can cross-reference meeting transcripts with calendar events

What stays manual:
  • Graph auth — needs an account.yaml with credentials referenced
  • Default OFF — flip when you actually want it

  [y] Set integrations.context_sources.outlook.enabled: true (you wire auth later)
  [l] Later
```

---

### S8 — Bridge-Deck visualisation

> **Not yet public — coming soon.** The bridge-deck repo is still
> private. SKIP this suggestion until it ships; everything below is
> staged for that moment.

**Trigger:**
- `evidence.os.platform == "darwin"` AND
- agent count after Phase E ≥ 3 AND
- another machine on the network is also user-controlled (from the mesh-VPN or known_hosts)

**Advisory:**

```
Bridge-Deck is an optional pixel-art visualizer (separate Apache-2.0 repo,
bks-lab/bridge-deck). It runs on a remote machine, polls Bridge state,
and renders agents as walking sprites.

What this enables:
  • Always-on visualisation of who's working on what
  • Calendar timeline, mandant directory
  • Reads only — never writes to Bridge

What stays manual:
  • Installation on the chosen remote (one-liner provided)
  • Choosing which machine hosts it

  [y] Show the one-liner installer to run on a remote
  [l] Later — I'll set this up when I have multi-agent workflows
```

(Don't auto-install — `docs/bridge-deck.md` is explicit about that.)

---

### S10 — Voice messages

**Trigger:** Almost never surfaces in initial scan. Promote to Phase E
unless the user has explicit voice-clone artefacts.

**Surface in Phase E catalogue instead:**
- "A voice-message skill is not shipped with open-bridge — note it as a
  private-skill idea (needs a separately-prepared voice clone, Chatterbox
  Multilingual or similar)."

---

### S11 — Knowledge / Wiki repo

**Trigger:**
- `evidence.developer.repos` includes a repo named `*-wiki`, `wiki`, `docs`, `knowledge*`
- OR user has explicit wiki-style folder under projects_root

**Advisory:**

```
Found what looks like a documentation/wiki repo: {repo_path}

Bridge can wire a separate knowledge repo via /knowledge-repo-init —
keeps docs out of the main Bridge clone, ships its own conventions.

What this enables:
  • Documentation lives in a parallel repo with shared MOC patterns
  • Cross-link from work/tasks/<slug>/STATUS.md to wiki pages
  • /debrief Phase 6 can route protocols into wiki/<area>/

What stays manual:
  • The init wizard runs separately — /knowledge-repo-init when you're ready

  [y] Schedule /knowledge-repo-init as a follow-up
  [l] Later
```

(Just records the intent; doesn't try to run init inline.)

---

### S12 — Upstream wiring

**Trigger:** `evidence.developer.repos` contains a repo named
`open-bridge`, `*-bridge`, or matches a known upstream pattern

**Advisory:** Defer to the existing `--upstream` flow in SKILL.md.
Mention it in Phase E if not surfaced here.

---

### S13 — Channels (host an always-on bot / transport on a machine)

Catalog-domain tag: `infrastructure`. **Dual-triggered — offer OR scan:**

**Trigger (offer):** the resource-offer advisory (Phase A step 10) fired — the user named
a machine to dedicate — **or** the free-text names an always-on/messaging intent
(`always-on`, `keep running`, `a bot`, `an assistant I can message`). Offer-derived, so it
is **confined-safe** (no scan).
**Trigger (scan, broader only):** `evidence.launchd_units` or `evidence.systemd_units`
include a messaging/bot-shaped unit, **OR** `evidence.apps` includes a bot runtime.

**Advisory:**

```
A dedicated machine is a home for always-on messaging — a bot or digest that keeps
running as a launchd (macOS) / systemd (Linux) unit, outliving your terminal.

What this enables (CORE — skills/channel):
  • /channel status | health — see what's deployed and running
  • Declare a transport in infra/channels/<name>.yaml (iMessage, email, Telegram, …)
  • /channel deploy — generate + install the service unit on a chosen remote
  • Pairs with /schedule for timed sends (see S14)

What stays manual:
  • Credentials never live in YAML — KeyVault / 1Password / Keychain URIs only
  • You pick which remote hosts it (needs an infra/remotes/<host>.yaml — see S2)

  [y] Scaffold an infra/channels/<name>.yaml shell (you fill the transport)
  [m] Read docs/channels.md first
  [l] Later
```

**On accept:**
- Copy `infra/channels/_template.yaml` → `infra/channels/<name>.yaml`, pre-fill `type` and
  the target `host` if a remote was offered/scaffolded (S2).
- Set `channels.enabled: true` in `bridge-config.yaml`.
- Mention deploy-reconciliation: declared `status:` is never trusted — the box's service
  manager is (`rules/deploy-reconciliation.md`).

---

### S14 — Scheduled jobs (cron / launchd / systemd on a machine)

Catalog-domain tag: `infrastructure`. **Dual-triggered — offer OR scan:**

**Trigger (offer):** the resource-offer advisory (Phase A step 10) fired, **or** the
free-text names a recurring-automation intent (`on a timer`, `every morning`, `nightly`,
`scheduled`, `recurring`). Offer-derived → **confined-safe**.
**Trigger (scan, broader only):** `evidence.crontab` non-empty, **OR** user launchd/systemd
timer units detected.

**Advisory:**

```
A dedicated machine can run things on a timer — a morning briefing, a nightly sync, a
weekly digest — as a native launchd / systemd / cron unit, without you being there.

What this enables (CORE — skills/schedule):
  • /schedule list | create — define a job (command + cadence + output)
  • Generates the platform-native unit (launchd plist / systemd timer / crontab line)
  • /schedule deploy — install it on a chosen remote (needs an infra/remotes/<host>.yaml)

What stays manual:
  • You choose the command + cadence; the wizard scaffolds the definition
  • Secrets stay in the vault, never in the job definition

  [y] Scaffold a scheduled-job definition (you fill command + cadence)
  [m] Show the schedule template first
  [l] Later
```

**On accept:**
- Add a job entry to the schedule registry `infra/channels/_scheduled.yaml` (created on
  first use by `skills/schedule`), leaving `command` / `cadence` for the user with `# fill
  me` comments.
- Mention `/schedule deploy` targets a remote — pair with S2 (remotes) if none exists yet.

---

## Known-Gotcha Overlay (curated, generic only)

These heads-ups come from the curated CORE table below — a fixed,
CORE-shipped list of generic, product-level gotchas. The wizard does
**not** read or scan the operator's memory base, and **never** names a
customer, employer, persona, or contact. Where a suggestion's condition
matches a row, append the row's `⚠ Heads-up:` line.

| Suggestion / condition | Heads-up to surface |
|---|---|
| S4 doc-system + docs_root contains "OneDrive" | "macOS Tahoe OneDrive FileProvider Orphan-Stub bug — consider a local PARA tree" |
| S2 remotes + ssh involved | "macOS remote SSH lacks Homebrew PATH unless you source ~/.zprofile" |
| S5 finance (e.g. MoneyMoney) | "Read-only via AppleScript; the DB is encrypted, no direct access" |

Add a row only when the gotcha is generic and product-level. Anything
instance-, customer-, or person-specific does not belong here.

## After Walking Suggestions

End Phase C with a one-line summary:

```
Phase C done — {accepted} enabled, {deferred} on the later-list, {nothing_found_count} skipped (no evidence).

Continuing to Phase D (work-system, theme, agents).
```

Write each decision to `work/onboarding-state.yaml` per the schema in
`system-discovery.md`.

## Adding a Feature Later — `/bridge-onboard --add <feature>`

The same advisory blocks (S1–S12) are reused when the user invokes
`--add <feature>` (e.g. `--add personas`, `--add doc-system`). The
mode is: skip Phases A, B, D, E, F; run only the single S-block
matching the feature; record the result in `onboarding-state.yaml`.

If a feature has prerequisite evidence missing (e.g. `--add doc-system`
but no docs_root detected), prompt for the path inline rather than
re-running the full scan.

## Personas — Explicit Note

We intentionally do **not** surface personas as a Phase-C suggestion
from initial scan evidence (no robust signal exists; "do you have a
GmbH" is exactly the kind of question we said we wouldn't ask).

Personas come in three other paths:
1. Phase E catalogue — read-only mention with "when you need it"
2. `/bridge-onboard --add personas` — user-initiated when they have a
   tax bundle / business identity to file
3. `feature-discovery` standing-order — surfaces a soft suggestion if
   it detects evidence later (e.g. repeated mail traffic with a
   Steuerberater address, multiple distinct mail signatures in
   draft folder, etc.)

This keeps the initial onboarding warm and non-intrusive.
