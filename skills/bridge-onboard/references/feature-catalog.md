---
description: Read-only catalogue of every Bridge feature with "when you need it" + how to activate. Surfaced in Phase E of onboarding (no questions, just info) and as the body of /bridge-onboard --features. Source of truth for what Bridge can do without making the user feel quizzed.
type: reference
last_updated: 2026-05-16
---

# Feature Catalogue — What Bridge Can Do

Read-only. **Never asks** — only shows what's available and when it makes
sense to activate. Used in two contexts:

1. **Phase E of `/bridge-onboard`** — printed at the end of the wizard
   so the user sees the surface they didn't activate, with a clear
   re-entry path
2. **`/bridge-onboard --features`** — interactive walk through the same
   catalogue when the user wants to explore later

## Display Principles

- **No surprise quiz.** Each entry is descriptive, not interrogative.
- **"When you need it" beats "what it is."** Sell the moment, not the
  spec.
- **Show positive evidence only.** If Phase B's scan saw something
  relevant, surface it ("found N accounts in Phase B"); if it saw
  something the user deferred, say so ("you said later — I'll remind in
  30 days"). If nothing matched, **omit the evidence line entirely** —
  never print "not detected" / "no signal".
- **One-line re-entry path.** Every entry ends with the exact command
  to activate.
- **Bridge will surface itself.** End with the trust-builder: "I'll
  notice when one of these becomes relevant and bring it up — you don't
  need to memorise this list."

## Grouping

By life-domain, not by config block. Each group carries the `focus` slug used by
`purpose.focus` (see § Purpose Banding):

| # | Group | `focus` slug |
|---|---|---|
| 1 | Identity & Filing | `identity` |
| 2 | Communication & Calendar | `communication` |
| 3 | Infrastructure | `infrastructure` |
| 4 | Productivity & Knowledge | `productivity` |
| 5 | Integrations | `integrations` |
| 6 | Visualisation & Polish | `visualization` |

Order within each group: highest-evidence-likelihood first, niche last.

## Purpose Banding

This is **the do-everything fix** — and it must work in confined mode too (the
catalogue is the confined user's only feature surface). It reads
`bridge-config.yaml.purpose`:

- **`purpose.statement` + `purpose.focus` set** → print `purpose.statement` as the
  catalogue header line, then split the six groups into two bands:
  - a lead band **"Most relevant to '{statement}'"** — the groups whose `focus`
    slug is in `purpose.focus`, in `focus` order;
  - a collapsed/dimmed secondary band **"Beyond your focus — here whenever you
    need it"** — the full remainder, every other group, in catalogue order.
- **Empty purpose** (`statement: ""` + `focus: []`) → today's flat grouped
  catalogue, byte-for-byte (all six groups in numeric order, no bands, no header).

**Hard rule — banding ORDERS, DIMS, and LABELS; it never removes, hides, or gates.**
Nothing is dropped: every group, every feature, and every one-line re-entry command
appears in both modes — the secondary band is collapsed/dimmed, not omitted. The
trust-closer is printed unchanged in both modes. `purpose.focus` is never an
allowlist; treating it as one is a bug.

---

## 1. Identity & Filing

### Personas
**What:** Multiple identities you hold — freelancer, private, GmbH director, landlord — each with its own tax numbers, signature blocks, and document-filing destinations.

**When you need it:** You write letters or invoices under different legal entities. You file tax bundles to a Steuerberater per persona. You want skills to know which letterhead to use.

**Scan evidence:** Personas are deliberately not detected from initial scan — the signal is too weak and the questions too intimate. Bridge will surface a suggestion later if it sees recurring traffic with a Steuerberater address or distinct mail signatures.

**Activate:** `/bridge-onboard --add personas`

### Document Sensor
**What:** Inbox-scanning that auto-routes PDFs and scans to PARA / Johnny Decimal / custom folders. Audit trail per file. Persona-aware queues for tax bundles.

**When you need it:** You drop scans into an inbox folder and want them in the right place without manual sorting. You file tax-relevant documents per legal entity.

**Scan evidence:** {if doc_sensor surfaced in Phase C → "you decided X"; else → omit this line}

**Activate:** `/bridge-onboard --add doc-system`

### Mail / Calendar Accounts
**What:** `identity/accounts/<id>.yaml` declares which mail and calendar accounts Bridge knows about. Secrets stay in KeyVault / 1Password (referenced by URI, never stored).

**When you need it:** You want skills like `/email-manager`, `/outlook-attachment-processor`, or Graph-based calendar pull to know which account to authenticate against.

**Activate:** `/bridge-onboard --add accounts`

---

## 2. Communication & Calendar

### Mandants
**What:** Recipient groups — team, family, friends, colleagues, individual. Each contains persons with channel preferences (iMessage primary, email fallback, etc.).

**When you need it:** You send the same kind of message to the same people repeatedly (weekly family photo, Monday team report, birthday reminders). Mandants give those addressees structure so calendar entries can target them.

**Activate:** `/bridge-onboard --add mandants`

### Calendar
**What:** `workflow/calendars/entries.yaml` holds every scheduled outbound action — what gets sent, to whom, when, how often. Duration-aware (effective_at = delivery_at − duration_estimate_min). Multi-recipient via mandants.

**When you need it:** You run recurring outbound communication — newsletters, status reports, birthday pings, weekly digests. Anything that wants "send this to that group every Friday."

**Activate:** `/bridge-onboard --add calendar` (typically pairs with mandants)

### Channels
**What:** Outbound transports — iMessage, email, Telegram, voice. Each declared in `infra/channels/<id>.yaml` and usually backed by a launchd/systemd unit on a remote.

**When you need it:** You want Bridge to actually send things (not just draft them) through a specific transport. Most users wire one channel per outbound use-case.

**Activate:** `/bridge-onboard --add channels`

### Voice Messages
**What:** Personal voice-clone for audio messages — Bridge can speak arbitrary text in your voice and deliver via iMessage / email.

**When you need it:** You send voice messages to family or clients and want them to sound like you, not like a generic TTS bot. Requires a separately prepared voice clone (Chatterbox Multilingual or similar).

**Not shipped:** open-bridge does not include a voice skill — treat this
entry as a private/org-overlay skill idea. Voice cloning involves audio
samples and model setup; see `docs/extension-model.md` for adding private
skills.

---

## 3. Infrastructure

### Remotes
**What:** `infra/remotes/<id>.yaml` per physical/virtual machine you administer. SSH config, mesh-VPN (e.g. Tailscale) / LAN topology, Wake-on-LAN settings, service inventory, hardware notes.

**When you need it:** You say "wake alice-mini", "is alice-nas online", "ssh into the workshop PC". You want fleet ops (status across all boxes) and Wake-on-LAN to just work.

**Scan evidence:** {if a mesh-VPN surfaced in Phase C → "you decided X"; else if known_hosts hit → "I saw N hosts in ~/.ssh/known_hosts"; else → omit this line}

**Activate:** `/bridge-onboard --add remotes`

### Backups
**What:** Topology of sources × targets × pipelines in `infra/backups/topology.yaml`. Tools: rclone, restic, rsync, time-machine (documented only). Drift detection: declared schedule vs actual last_run.

**When you need it:** You run multiple backup destinations (NAS + external + cloud) and want a single source-of-truth + drift detection. Especially valuable if you've already lost something once.

**Activate:** `/bridge-onboard --add backups`

### M365 / Exchange Admin (example of an org-overlay skill)
**What:** Shared-mailbox provisioning, delegate permissions, Exchange Online cmdlets via `pwsh`. Specifically for admins of a Microsoft 365 tenant. Not shipped with open-bridge — this is an example of a skill an org overlay can bring along.

**When you need it:** You administer a small-to-medium M365 tenant and provision Shared Mailboxes / Owner mailboxes for cloud services. Not relevant for end-users.

**Activate:** Build it in your org overlay (or seed repo) as `skills/m365-admin/`; it then autoloads on relevant triggers, no config flip needed.

---

## 4. Productivity & Knowledge

### Task Management
**What:** `work/log.md` (Claude's working memory across sessions) + `work/board.md` (generated task surface) + `work/tasks/<slug>/` (finite multi-day work with STATUS.md) + `work/streams/<slug>/` (long-runners). Standing orders fire only when this is on.

**When you need it:** You want Claude to remember what you did yesterday. This is the single biggest difference between a useful assistant and an amnesiac chatbot.

**Default:** Strongly recommended `on` in Phase D. Skip only if you specifically want a stateless chat.

**Activate:** Already covered in Phase D; toggle via `bridge-config.yaml.work.enabled`.

### Knowledge / Wiki Repo
**What:** Separate Git repo for documentation (your wiki / knowledge base), wired to Bridge via `/knowledge-repo-init`. Cross-link from task STATUS.md to wiki pages; `/debrief` Phase 6 routes protocols into the wiki.

**When you need it:** Your documentation is outgrowing the Bridge repo (or you want it shareable separately). You want a stable wiki layout (areas, frontmatter conventions, MOC patterns).

**Activate:** Run `/knowledge-repo-init` directly — it's its own wizard.

### Meeting Transcription & Debrief
**What:** `/debrief` (transcript → 7-category insights + protocol generation + task proposals), shipped with open-bridge. A local transcription pipeline (e.g. a Whisper-based `meeting-transcriber` skill) is an example of an org-overlay or user skill that feeds it — not shipped here.

**When you need it:** You record meetings (own or others) and want them processed into structured notes instead of buried as audio files.

**Activate:** `/debrief` autoloads on triggers. If you want automated transcription, add your own transcriber skill in your overlay/seed repo and point it at your recording inbox.

### Banking / Finance
**What:** Read-only finance integration — account balances, transaction lookups, "is invoice X paid?". Never triggers transfers automatically. MoneyMoney is the reference implementation (read via AppleScript, ships a `/moneymoney` skill); other finance apps map to the same capability.

**When you need it:** You manage bank accounts via a finance app and want invoice-paid checks during freelancer workflows.

**Scan evidence:** {if a finance app detected → "found N accounts in Phase B"; else → omit this line}

**Activate:** Skill autoloads on trigger; no config flip needed.

### Sub-Agents (Claude Code only)
**What:** Named isolation workers declared in `.claude/agents/<name>.md`. Each takes a heavy, parallel, or noisy task and returns only a structured summary, so raw output (log dumps, file trees, API results) never fills your main session. open-bridge ships `archivist` (document intake); everything else routes through the built-in `general-purpose` agent until you add your own.

**Non-Claude note:** sub-agents are a Claude Code primitive — other tools (Copilot CLI, Gemini, Codex, Cursor) have no isolation-worker API, so skills dispatch the same logic inline instead. No capability is lost; only the in-session context isolation differs. The `.claude/agents/*.md` files still document each pattern for any Claude Code session.

**When you need it:** A task keeps flooding your context (incident log triage, multi-file analysis, batch web fetches), or you want several independent jobs to run in parallel without interleaving their output.

**Activate:** Drop a `.claude/agents/<name>.md` with frontmatter (`name`, `description`, `tools`, `model`) — auto-discovered at session start, no registration. Dispatch via the `Task` tool with `subagent_type: <name>`.

---

## 5. Integrations

### GitHub Projects
**What:** Issue boards + custom fields (single-select, text, number, date) read/written through `github-projects-manager` skill. Per-project YAML config in `workflow/projects/<slug>.yaml`.

**When you need it:** You actually use GitHub Projects V2 boards for task tracking (not just issues). Multiple projects with structured field schemas.

**Activate:** `/bridge-onboard --add github-projects`

### Azure DevOps Boards
**What:** Same shape as GitHub Projects but for ADO. Read-only currently; write-paths land per use-case.

**When you need it:** You work in an org that uses ADO Boards.

**Activate:** `integrations.ado.enabled: true` in `bridge-config.yaml`.

### Context Sources (Teams / Outlook)
**What:** Inbound providers that feed `/briefing` and `/debrief` with calendar, chat, and meeting signals. Capability-decoupled: providers declare what they `provide:`, skills discover by capability.

**When you need it:** You want your daily briefing to know about today's meetings, recent Teams chats, or Outlook calendar entries — without manually pasting them.

**Activate:** Edit `integrations.context_sources.*` in `bridge-config.yaml` and wire the matching skill (e.g. `teams-reader`).

### Multi-Upstream Promote
**What:** Multi-repo promotion routing — `scope: core` commits route to OSS upstream, `scope: org` to your org overlay upstream, `scope: user` stays local. `/promote` and `/bridge-sync` are the surfaces.

**When you need it:** You're contributing to an OSS Bridge variant (open-bridge), an internal Bridge variant, or both. Most users start with `upstreams: []` and wire when the destination repos exist.

**Activate:** `/bridge-onboard --upstream`

---

## 6. Visualisation & Polish

### Bridge-Deck (pixel-art visualiser) — not yet public, coming soon
**What:** Optional Apache-2.0 daemon (separate repo `bks-lab/bridge-deck`, still private — do not suggest until it ships) that polls Bridge state read-only and renders agents as walking sprites + calendar timeline + mandant directory.

**When you need it:** You run multiple agents and want a live "office view" — not for the work, for the joy. Or you do demos.

**Activate:** Install on a chosen remote per `docs/bridge-deck.md` — its collectors poll your Bridge files directly, nothing else to wire.

### Bridge Dashboard (ops view)
**What:** Single-file HTML dashboard via `/bridge-dashboard` — fleet status, work board, calendar 24h, channels, git activity, upstream drift. Operational, not pixel-art.

**When you need it:** You want a "everything at a glance" view in a browser tab, not via CLI commands.

**Activate:** Run `/bridge-dashboard`; skill autoloads.

### Themes
**What:** YAML files in `themes/` control user-facing vocabulary only — never tools, delegation, or goals. Switch via `theme:` in `bridge-config.yaml`.

**When you need it:** You want German role names (`professional-de`). Or you build a custom theme.

**Activate:** Already chosen in Phase D; edit `bridge-config.yaml.theme` to change later.

---

## Trust-Building Closer

End the catalogue (both in Phase E and `--features`) with:

```
You don't need to memorise this. Bridge surfaces relevant features
proactively:

  • Every Wednesday in /briefing, I check whether new evidence has
    appeared and propose ONE feature at most. You can defer or decline.
  • Any time you ask me to do something I don't have configured, I'll
    explain how to activate it.
  • /bridge-onboard --features lets you walk this catalogue interactively.
  • /bridge-onboard --add <feature> activates a single feature with
    setup help.

Nothing is locked in. Everything is opt-out via bridge-config.yaml.
```

This is the philosophical closer: Bridge is on your side, not nagging.

## State Coupling

This catalogue reads `work/onboarding-state.yaml` if it exists, and
annotates each entry accordingly:

| State | Display annotation |
|---|---|
| `accepted` | ✓ enabled |
| `deferred (remind_after: <date>)` | ⏸ deferred until {date} |
| `silenced` | hidden (don't surface) |
| `nothing_found` | (no signal yet) |
| (no state) | (not yet considered) |

The `--features` mode lets the user click into any entry and re-decide;
that re-decision updates `onboarding-state.yaml` and (if accepted) runs
the matching S-block from `smart-suggestions.md`.
