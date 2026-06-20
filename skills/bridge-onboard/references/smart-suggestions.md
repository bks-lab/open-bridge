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

## The Single Bias-Setting Question (asked once, optional)

Before walking suggestions, ask **one** question — purely to prioritise
which suggestions surface first:

```
Will you mostly use Bridge for:

  [w] work    (clients, team, deadlines, infrastructure)
  [p] private (personal organisation, household, finances)
  [b] both    (recommended for most users)
  [s] skip    (treat everything as equally relevant)
```

This is **not** a feature-toggle — it's a sort-order hint. It biases:

- **work** → suggestions for GitHub-projects, channels (team), remotes,
  m365-admin surface first; MoneyMoney / voice surface last
- **private** → MoneyMoney, voice, household mandant
  surface first; m365-admin and team channels surface last
- **both** → balanced order, drives nothing else
- **skip** → strict evidence-strength order only

Persist as `bridge-config.yaml.user_profile: work | private | both`.
Doesn't gate any feature; only affects ordering and the language of
suggestions ("for your team" vs "for your family").

## Principles for Suggestions

1. **No suggestion without evidence.** If Phase B found nothing matching
   a feature, it goes to Phase E (catalogue), not to Phase C.
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
5. **Bridge-specific MEMORY warnings.** Where the user's own MEMORY file
   contains a known gotcha (e.g. OneDrive FileProvider Orphan-Stub Bug),
   surface it as part of the advisory. See "Known-gotcha overlay" below.

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

### S2 — Remotes (when tailscale or known_hosts present)

**Trigger:** `evidence.tailscale.devices.length >= 2`
**OR:** `evidence.ssh_known_hosts.length >= 3`

**Advisory (tailscale variant):**

```
Tailscale found {N} devices in your tailnet:
  {device_list}

Bridge can manage these as a "fleet" — SSH config + Wake-on-LAN +
service inventory per box. Useful when you say "wake alice-mini" or
"is alice-nas online?".

What this enables:
  • /remote status — health-check across all devices
  • /remote wake <name> — Wake-on-LAN via LAN-relay
  • SSH config templates with Tailscale-first, LAN-fallback

What stays manual:
  • Credentials never live in YAML — KeyVault / 1Password URIs only
  • You opt in per machine before any destructive action runs

  [y] Scaffold {N} remote files (one per device, you fill capabilities later)
  [m] Show the template first
  [l] Later — wire up when I need fleet ops
```

**On accept:**
- Copy `infra/remotes/_template.yaml` → `infra/remotes/<hostname>.yaml`
  for each detected device, pre-filling: `hostname`, `network.tailscale_ip`,
  `os` (best-guess from device-name patterns or known)
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

Bridge can model your backup topology declaratively — sources × targets ×
pipelines — and reconcile what should be backed up against what actually is.

What this enables:
  • /backup status — drift detection (last_run, missing mounts, stale snapshots)
  • Topology lives in infra/backups/topology.yaml — declarative, version-controlled
  • Per-pipeline validation rules (e.g. encrypted-required sources can't use rclone-sync)

What stays manual:
  • Backup execution itself — Bridge orchestrates known tools (rclone/restic/rsync),
    Time Machine is documented but not triggered
  • You wire actual sources/targets — the wizard scaffolds the topology shell

  [y] Scaffold topology.yaml with current sources pre-filled
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

{if MEMORY contains FileProvider/OneDrive warning AND docs_root contains "OneDrive":}
  ⚠ Heads-up: your MEMORY notes a FileProvider Orphan-Stub bug under
    macOS Tahoe with OneDrive. Consider migrating PARA to ~/PARA-Documents
    before enabling. Check feedback_fileprovider_orphan_stubs.md.
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

### S5 — MoneyMoney (when MoneyMoney.app installed)

**Trigger:** `evidence.apps` includes `MoneyMoney.app`

**Advisory:**

```
MoneyMoney.app detected{, with {N} accounts: {account_names} if scanned}.

Bridge can read MoneyMoney via AppleScript — read-only, no transfers
ever triggered automatically.

What this enables:
  • "Is invoice X paid?" → a private finance skill looks up the transaction
  • Account balance summaries in /briefing
  • Invoice-status checks for freelancer workflows

What stays manual:
  • Any actual transfer needs your TAN in MoneyMoney itself
  • Bridge writes nothing — read-only by design

  [y] Note as a private skill to build (open-bridge ships no finance
      skill — see docs/extension-model.md for private/org skills)
  [l] Later
```

**On accept:** record `suggestions.moneymoney: accepted` so we don't
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
- another machine on the network is also user-controlled (from tailscale or known_hosts)

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

## Known-Gotcha Overlay (MEMORY-aware)

Before showing any suggestion, check the user's MEMORY index
(`~/.claude/projects/<project-hash>/memory/MEMORY.md`) for relevant
warnings. If a memory tag matches the suggestion topic, append a
`⚠ Heads-up:` line citing the memory file.

Examples baked into the wizard:

| Suggestion | Memory tag to check | Warning to surface |
|---|---|---|
| S4 doc-system + docs_root contains "OneDrive" | `feedback_fileprovider_orphan_stubs` | "macOS Tahoe OneDrive FileProvider Orphan-Stub bug — consider local PARA tree" |
| S2 remotes + ssh involved | `reference_remote_ssh_path` | "macOS remote SSH lacks Homebrew PATH unless you source ~/.zprofile" |
| S5 MoneyMoney | `reference_moneymoney_accounts` | "Read-only via AppleScript; DB is encrypted, no direct access" |

This makes the wizard feel like it knows the user, not generic.

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
