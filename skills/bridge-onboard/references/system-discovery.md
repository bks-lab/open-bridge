---
description: Permission-gated system scan that collects evidence about what the user already has installed and structured, so the wizard can suggest features instead of asking abstract questions. Used by Phase B of workflow.md and by /bridge-onboard --rescan.
type: reference
last_updated: 2026-05-16
---

# System Discovery — Permission-Gated Scan

Phase B of the onboarding wizard. The user has already passed Phase A
(name, projects_root, optional GitHub org). Now we collect **evidence
about what is already on the system** so Phase C can propose specific
features, not abstract questions.

## Principle: Discover, don't Interrogate

Asking a new user "do you file taxes for multiple legal entities?" is
hostile — they came here to set up an AI assistant, not to inventory
their life. Instead we look at what they already use (apps, directories,
git config, installed CLIs) and propose features that match.

Everything is **opt-in per scan source**, transparently listed before
the scan runs, and **never persisted beyond `work/onboarding-scan.json`**
(gitignored, auto-deleted after 30 days or on `--reset`).

## The Permission Prompt

> **This whole phase only runs in `broader` mode.** The `confined` vs.
> `broader` choice (`discovery.mode` in `bridge-config.yaml`) was already
> made at the **end of Phase A**, via the gate prompt in `workflow.md`. If
> the user chose `confined` (the template/absent default — no explicit
> consent ⇒ never scan), **no scan happens at all** and Phase B is skipped
> entirely: the Bridge stays inside this repo folder and the user enables
> features explicitly (onboarding feature catalog, `/bridge-onboard --add
> <feature>`, or the feature's `enabled:` flag). The choice is reversible
> — `/bridge-onboard --rescan` broadens, or edit `discovery.mode`. The
> per-source permission model below is the **per-item permission within
> `broader` mode**, not a second confined/broader decision.

Run once, at the start of Phase B (broader mode only). Theme it bilingually
(German speakers get the German labels; default English):

```
Bridge can take a quick look at what you already use, so I can suggest
features instead of asking abstract questions. What may I look at?

DEFAULT-ON (non-invasive, safe to leave checked):
  [x] git config            name + email
  [x] ~/Developer           directory listing (folder names, no file contents)
  [x] OS + installed apps   uname + the full list of installed app names, read
                            generically and mapped to capabilities. No app is
                            assumed, nothing is searched for by name.
  [x] Homebrew packages     brew list

DEFAULT-OFF (opt in explicitly — surface only):
  [ ] ~/Documents structure top-level folder names only
  [ ] Mail account list     account names from Apple Mail / Outlook (NO mail content)
  [ ] Calendar list         which calendars are connected (NO events)
  [ ] SSH known_hosts       hostnames you've connected to before

DEEPER PROBES (offered only if the app scan already found a matching app —
you're asked per match, never up front, never for an app you don't have):
  [ ] Mesh-VPN device list  if a mesh-VPN is installed (e.g. Tailscale): device names only, no peers from other tailnets
  [ ] Finance-app accounts  if a finance app is installed (e.g. MoneyMoney): account display names only, NO transactions

NEVER SCANNED:
  · Mail / message / document CONTENT
  · Passwords, OAuth tokens, keychain entries
  · Browser history
  · iMessage / WhatsApp / Signal conversations
  · Your memory / notes base — onboarding never reads cross-context memory and never names a real customer, employer, or contact in its output

  [y] Defaults + opt-ins all on (recommended)
  [d] Defaults only (cautious)
  [c] Choose individually
  [s] Scan nothing — switch to confined (no scan now or later)
```

If the user picks `[s]`, they are choosing confined after all: set
`discovery.mode: confined` and `discovery.permissions: []`, then jump
straight to Phase D (Quick-Wins). No scan runs now or later — the
`feature-discovery` standing-order honours confined mode. Surface the full
feature catalog in Phase E and let the user enable features explicitly
(catalog, `/bridge-onboard --add <feature>`, or the `enabled:` flag).

## Scan Sources — What Each Looks At

For each source: what it runs, what it captures, why it matters.

### Default-on

#### `git_config`
- **Runs:** `git config --global user.name && git config --global user.email`
- **Captures:** name, email
- **Why:** confirms identity, can suggest `identity.name` for Phase A if not yet set
- **Sensitivity:** low — already public in commits

#### `developer_dir`
- **Runs:** `find ${projects_root} -maxdepth 2 -name .git -type d | head -50` plus `ls ${projects_root}`
- **Captures:** repo paths, top-level folder names, count
- **Why:** drives ecosystem.yaml — same logic as old `discovery.md` (which becomes a special case of this scan)
- **Sensitivity:** low — local filesystem listing

#### `os_and_apps`
- **Runs:** `uname -srm`, `ls -1 /Applications 2>/dev/null` (macOS), `dpkg -l` or equivalent (Linux)
- **Captures:** OS + the FULL list of installed app names, generically — nothing is searched for by name (e.g. "MoneyMoney.app", "Tailscale.app", "Backblaze.app", "Things.app", "Obsidian.app" are just illustrative of what the list might contain)
- **Why:** apps are the strongest evidence for features — but they map to capabilities through the **Capability Map** below, never hard-coded to a single product. An app matching no capability is ignored, not surfaced. (e.g. a finance app maps to "Banking / finance" and surfaces S5; a backup app maps to "Backup" and surfaces S3)
- **Sensitivity:** low

#### `homebrew_packages`
- **Runs:** `brew list --formula 2>/dev/null` and `brew list --cask 2>/dev/null`
- **Captures:** CLI tool + cask names (`rclone`, `restic`, `gh`, `tailscale`, `wakeonlan`, `pandoc`, …)
- **Why:** detects backup tools (rclone, restic), CLI integrations (gh, az), and tooling that drives suggestions
- **Sensitivity:** low

### Opt-in (surface only)

#### `mesh_vpn_devices` *(deep probe — only offered if a mesh-VPN app was found)*
- **Runs:** the installed mesh-VPN's device-list command (e.g. `tailscale status --json 2>/dev/null`; equivalent for Netbird/Headscale/Nebula). Never offered when no mesh-VPN is installed.
- **Captures:** hostnames + OS per device — **not** peers from other tailnets, **not** ACL info
- **Why:** drives `infra/remotes/*.yaml` skeleton suggestions; same network = fleet
- **Note:** Tailscale is the reference implementation, not a requirement — any mesh-VPN maps to the same capability.
- **Sensitivity:** medium — reveals device names

#### `documents_structure`
- **Runs:** `ls -d ${docs_root}/*/  2>/dev/null` where `docs_root` is detected from `~/Documents`, `~/OneDrive`, `~/PARA*`, `~/iCloud*`
- **Captures:** top-level folder names only (e.g. "0_Import", "1_PROJECTS", "Steuern", "Rechnungen")
- **Why:** detects PARA / Johnny Decimal / custom — drives doc-system suggestion
- **Sensitivity:** medium — folder names can hint at projects

#### `mail_accounts`
- **Runs (macOS Apple Mail):** `osascript -e 'tell application "Mail" to get name of every account'`
- **Runs (Outlook):** parse `~/Library/Group Containers/UBF8T346G9.Office/Outlook/Outlook 15 Profiles/Main Profile/Accounts.plist` for account display-names only
- **Captures:** account display names — **no** email addresses, **no** messages
- **Why:** drives `identity/accounts/*.yaml` skeleton + `integrations.context_sources.outlook` toggle
- **Sensitivity:** medium

#### `finance_accounts` *(deep probe — only offered if a finance app was found)*
- **Runs:** the detected finance app's account-list command — for MoneyMoney that is `osascript -e 'tell application "MoneyMoney" to get name of every account'`
- **Captures:** account display names only (e.g. "Checking", "Business") — **NO** transactions, **NO** balances
- **Why:** confirms finance-app usage, can scaffold a persona-banking link
- **Note:** MoneyMoney is the reference implementation (ships a `/moneymoney` skill); any finance app maps to the same capability.
- **Sensitivity:** medium

#### `calendar_list`
- **Runs:** `osascript -e 'tell application "Calendar" to get name of every calendar'`
- **Captures:** calendar names
- **Why:** drives `context_sources.outlook.provides: [calendar]` and calendar-skill suggestions
- **Sensitivity:** medium

#### `ssh_known_hosts`
- **Runs:** `cut -d ' ' -f 1 ~/.ssh/known_hosts | sort -u | head -30`
- **Captures:** hostnames the user has SSHed to
- **Why:** secondary evidence for remotes (especially when no mesh-VPN is installed)
- **Sensitivity:** medium — reveals infrastructure

## Capability Map — Detected App/Tool → Capability → Suggestion

The scan captures **everything** installed; this map turns raw app/tool names
into capabilities. It is **extensible and example-driven** — add a row when a
new product maps to an existing capability; never special-case a single product
in the scan logic. An app matching **no** row is ignored — not surfaced as
"unknown", not mentioned at all.

| Capability | Example apps / tools (non-exhaustive) | Suggestion block |
|---|---|---|
| Fleet / mesh-VPN | Tailscale, Netbird, Headscale, Nebula; or ≥3 `ssh_known_hosts` | S2 — Remotes |
| Backup | rclone, restic, borg, kopia; Backblaze, Arq, Carbon Copy Cloner | S3 — Backups |
| Banking / finance | MoneyMoney, Banktivity, … (read-only via AppleScript/API) | S5 — Finance |
| Document filing | a PARA / Johnny-Decimal folder tree under a docs root | S4 — Document Sensor |
| Mail / calendar | Apple Mail, Outlook, any configured account | S6 / S7 |
| Notes / knowledge | Obsidian, a `*-wiki` / `docs` repo | S11 — Knowledge repo |

**Rule of thumb:** match by capability, not by brand. A finance app you've
never heard of still maps to "Banking / finance" and surfaces S5. If the user
has none in a category, that category's block **never appears** — no "not
detected" line, no mention of the absent product.

## What's NEVER Scanned

Be explicit in the prompt so trust is established:

- Message/mail/document **content** (only names + structure)
- Keychain, password managers, OAuth tokens
- Browser history, search history
- iMessage / WhatsApp / Signal / Telegram conversation content
- Photos, screenshots, voice memos

If a scan would require reading content (e.g. parsing mail bodies to
guess Mandant candidates), it is OUT OF SCOPE for onboarding. Such
discovery only happens later, voluntarily, after the user explicitly
asks (e.g. `/mandants suggest`).

## Output: `work/onboarding-scan.json`

Write findings to a structured file the wizard, Phase C, and the
`feature-discovery` standing-order can all read:

```json
{
  "scan_timestamp": "2026-05-16T14:30:00+02:00",
  "permissions_granted": ["git_config", "developer_dir", "os_and_apps", "homebrew_packages", "mesh_vpn_devices"],
  "evidence": {
    "git": { "name": "alice", "email": "alice@example.com" },
    "developer": {
      "root": "/Users/alice/Developer",
      "repo_count": 12,
      "orgs": ["acme-corp", "personal"],
      "repos": [
        { "path": "acme-corp/api", "origin": "github.com/acme-corp/api" }
      ]
    },
    "os": { "platform": "darwin", "arch": "arm64", "release": "25.5.0" },
    "apps": [
      "MoneyMoney.app", "Tailscale.app", "Backblaze.app",
      "Visual Studio Code.app", "Obsidian.app", "1Password 7 - Password Manager.app"
    ],
    "homebrew": {
      "formula": ["rclone", "restic", "gh", "wakeonlan", "pandoc"],
      "cask": ["docker", "iterm2"]
    },
    "mesh_vpn": {
      "impl": "tailscale",
      "self": "alice-macbook",
      "devices": ["alice-macbook", "alice-mini", "alice-nas"]
    }
  }
}
```

Schema notes:

- `permissions_granted` records what the user said yes to — re-runs
  (`--rescan`) honour the same list; user can change via `--reset`.
- `evidence` only contains keys for granted permissions — denied
  sources simply don't appear (no empty stubs).
- File location: `work/onboarding-scan.json`. **Gitignored** (add to
  `.gitignore` if not already there).
- Retention: deleted automatically after 30 days, or on `/bridge-onboard
  --reset`. Stale scans are harmless but `feature-discovery` skips them.

## Discovery State — `work/onboarding-state.yaml`

Separate from the raw scan: records what the user did with each
suggestion. Phase C and the standing-order both read+write this.

```yaml
suggestions:
  finance:
    status: accepted
    decided_at: 2026-05-16T14:32:00+02:00
  doc_system:
    status: deferred
    decided_at: 2026-05-16T14:33:00+02:00
    remind_after: 2026-06-15
  personas:
    status: declined
    decided_at: 2026-05-16T14:34:00+02:00
    decline_count: 1   # 3 declines → silenced forever
  remotes:
    status: nothing_found   # scan ran but no mesh-VPN + 0 ssh hosts
```

Status values:

| Status | Meaning | Re-surface? |
|---|---|---|
| `accepted` | feature enabled + scaffolded | no |
| `deferred` | "later" — recheck after `remind_after` | yes, after date |
| `declined` | user said no | yes, on `--rescan` unless `decline_count ≥ 3` |
| `silenced` | declined 3×, never surface again | no |
| `nothing_found` | scan ran but produced no evidence | only if new evidence appears |

This file lives in `work/` (USER layer), is **not** gitignored — it's
useful in commits as a record of setup decisions.

## Re-Run Modes

| Mode | Behaviour |
|---|---|
| `/bridge-onboard` | full wizard, including discovery |
| `/bridge-onboard --rescan` | broaden discovery (set `discovery.mode: broader`), then re-run the scan, recompute suggestions, ignore `accepted`/`silenced`, surface new evidence |
| `/bridge-onboard --reset` | delete `onboarding-scan.json` + `onboarding-state.yaml`, restart Phase B from scratch |
| `/bridge-onboard --add <feature>` | skip A+B+E, run Phase C scaffold for one specific feature (e.g. `--add personas`, `--add doc-system`) |
| `/bridge-onboard --features` | read-only Phase E catalogue, interactive |

`--add` is the friendly path when a user reads `feature-catalog.md` and
decides "actually, I do need that now" — no full re-run.

## Implementation Notes

- Scan runs **in parallel** where possible (each source is independent).
  Show a progress line per source: `✓ git_config (alice)`, `✓ apps (47 found)`,
  `✓ mesh_vpn (tailscale, 3 devices)`. Trust-building.
- Errors are **non-fatal** — if `osascript` permission is denied (e.g.
  user hasn't given Bridge automation rights yet), record the source as
  `error: permission_denied` and continue with the rest.
- The wizard must surface the error gracefully: "I couldn't read Apple
  Mail accounts — you may need to grant automation permission in
  System Settings → Privacy & Security → Automation. Continuing without it."
- **Never** ask for system-level permissions outside of the explicit scan
  prompt. If a scan source needs TCC permission, mention it once in the
  permission prompt's hover-help, not as a follow-up modal.
