# Distribution Email — Meeting Summary to Participants

Used by **`/debrief`** (Phase 7, the **last** phase before work-log), and
callable from **`/briefing`** when a transcript is processed inline.

## Purpose

After GitHub issue updates and wiki protocol are written, send a compact
summary to meeting participants — with **real issue URLs** from Phase 5,
so recipients can click straight into the updated tickets.

**Critical ordering rule:** this phase runs **after** `task-reconciliation`
and **after** protocol generation. Never before. Otherwise the email links
point to nothing.

## Trigger

Runs automatically when:

```yaml
# classification.md → meeting_types.{type}
distribution:
  email: true
  mandant: <id>
  exclude_absent: true   # default
```

Or on user flag `--email` for any meeting.

## Inputs

| Input | Source |
|---|---|
| `protocol_path` | Phase 6 output |
| `participants` | classification, with name-corrections applied |
| `absent` | classification (people expected but not present) |
| `updated_issues`, `new_issues` | Phase 5 output (URLs!) |
| `distribution_mandant` | `classification.md` meeting_types config |

## Process

### Step 1 — Resolve recipients

1. Load `identity/mandants/{distribution_mandant}.yaml`
2. For each **participant** (not absent!), find matching `persons[]` entry
   by `display_name` or email overlap.
3. Collect `channels.email` for each.
4. **Exclude absent participants.** Example: if charlie is listed in
   `identity/mandants/team.yaml` but was **not** in the meeting, he does not get this
   email. He may get other digests (Hourly Task Digest etc.), but meeting
   summaries go only to attendees.
5. If a CC-list is defined in meeting-type config, verify each addressee
   was either present OR explicitly opted into "keep me in the loop" —
   otherwise skip.

### Step 2 — Build body

Compact (target < 60 lines). Sections in this order:

1. **Opening** — one line, e.g. "kurze Zusammenfassung unseres heutigen Weeklys (18:14, ca. 45 Min)."
2. **To do today / tomorrow** — bullets with owner + deadline
3. **Termine** — dated entries (calendar blocks we've set)
4. **GitHub Updates** — one bullet per issue, with **live URL** from Phase 5
5. **Sonstiges** — info-only items (things that stayed out of issues)
6. **Protokoll** — link to wiki path
7. **Transkript-Hinweis** — if applicable (e.g. Teams without speaker labels)
8. **Signature** — identifies the sender, e.g. `{assistant_name} | {sender_email} | via The Bridge`. Configure under `debrief.distribution.signature` in bridge-config.yaml.

No attachments. No HTML styling (plain text). Markdown-compatible so the
draft file can also be read in the repo.

### Step 3 — Write draft

```
work/drafts/emails/{date}-{meeting-slug}.md    (full markdown incl. frontmatter)
work/drafts/emails/{date}-{meeting-slug}.txt   (plain-text body only, for Mail)
```

Frontmatter in the `.md`:

```yaml
type: email-draft
status: pending-review
created: {ISO}
meeting_ref: {protocol_path}
from: {configured_from}
to: [{email1}, ...]
cc: []
subject: "{meeting title} {date} - Summary"
related_issues: [{numbers}]
```

### Step 4 — Checkpoint 3: send / draft decision

Present preview + options:

```
[s] send via your mail-send skill, if configured (org overlay, e.g. an email-manager — Graph API from your configured sender)
[o] open draft in Apple Mail / Outlook (you review + send)
[k] keep as draft only (I do nothing)
[e] edit first
```

**Default recommendation: `[o]`.** Human-in-the-loop at visible-to-others
actions. Never default to `[s]` unless the user configures `auto_send: true`
for that meeting type.

### Step 5 — Execute

**[s] Send via mail skill:** invoke your bridge's mail-send skill (org
overlay; open-bridge does not ship one) with `action: send` and draft
frontmatter. On success, update draft status → `sent-at: {ISO}`. Without
such a skill, `[s]` is unavailable — use `[o]`.

**[o] Apple Mail draft:** use AppleScript. Body comes from the `.txt` file
(avoid escape hell with multi-line content):

```bash
osascript <<'APPLESCRIPT'
set bodyContent to (do shell script "cat '<path to .txt>'")
tell application "Mail"
    activate
    set newMessage to make new outgoing message with properties ¬
        {visible:true, subject:"<subject>", content:bodyContent}
    tell newMessage
        make new to recipient at end of to recipients with properties {address:"<addr1>"}
        -- one line per recipient
    end tell
end tell
APPLESCRIPT
```

**Outlook variant** (if default mail client is Outlook):
`open -a "Microsoft Outlook" "mailto:..."` — but mailto has length limits,
so prefer AppleScript for Outlook too if body > 2 kB.

**[k] Draft only:** no action; file stays in `work/drafts/emails/`.

### Step 6 — Record

1. `work/log.md` entry:
   ```
   | {ISO} | 📧 | {context} | /debrief email: {subject} → {n} recipients ({s|o|k}) |
   ```
2. Protocol frontmatter: append `email_status: sent-at | draft-opened | draft-kept`.

## Hard rules

1. **No recipient who was absent.** Even if they're listed in the mandant
   and normally get digests. Meetings → attendees only.
2. **Links must be real.** Run after Phase 5 — never with placeholder URLs.
3. **Plain text body.** No HTML styling. Mail clients render poorly otherwise,
   and Org colleagues read on mobile.
4. **Signature identifies the sender as The Bridge.** Recipients should
   know it's an automated summary, not a personal message.

## Integration

Called from:
- `skills/debrief/references/full-workflow.md` Phase 7

Depends on:
- `identity/mandants/{id}.yaml` for recipient resolution
- Phase 5 output (issue URLs)
- a mail-send skill from your org overlay (for the optional `[s]` auto-send path; open-bridge ships none)
- AppleScript / `open` command (for `[o]` draft path)
