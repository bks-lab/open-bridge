# Doc-Status

Shows the current state of all document queues (OneDrive). Pure monitoring view.

## Path resolution

1. Read `bridge-config.yaml` in this Bridge repo
2. Find `doc_sensor.onedrive_root` (name is historical — local
   documents root, OneDrive is optional)
3. Expand `~` to `$HOME`

## Workflow

1. Check whether the documents root exists (`test -d`)
   - No → "Documents root not available." Done.

2. For each entry in `doc_sensor.scan_paths`:
```bash
/usr/bin/find "${ONEDRIVE_ROOT}/${path}" -type f \
  -not -name '.DS_Store' -not -name '_INFO.md' -not -name '.gitkeep' \
  2>/dev/null | wc -l | tr -d ' '
```

3. For each entry in `doc_sensor.queue_paths`:
```bash
/usr/bin/find "${ONEDRIVE_ROOT}/${path}" -type f \
  -not -name '.DS_Store' \
  2>/dev/null | wc -l | tr -d ' '
```

4. Apple Mail — count of flagged mails (unique subjects + PDF subset). **Org overlay (optional).**
   This branch depends on a `process_mail.py --list` helper shipped by an optional
   `mail-attachment-processor` org-overlay skill (not part of open-bridge's shipped skills).
   It deduplicates (Apple Mail mirrors mails into multiple mailboxes → without dedup
   3x counts). Takes ~10s due to AppleScript. When the helper is absent the branch
   silently reports `—`, so it is safe to leave in place.
```bash
# Point SCRIPT at wherever your org-overlay skill installs its mail-listing
# helper — this instance's own skills/, or a plugin's install path. Do NOT
# reach for it via ~/.claude/skills: that path must not point at a Bridge repo
# (docs/skill-distribution-architecture.md § Why the user level is not a
# distribution channel), and it is not a stable API for scripts.
SCRIPT="skills/<your-mail-skill>/scripts/process_mail.py"
if [ -f "$SCRIPT" ]; then
  OUT=$(python3 "$SCRIPT" --list 2>/dev/null)
  APPLE_TOTAL=$(echo "$OUT" | grep -cE "^[0-9]+\.")
  APPLE_PDF=$(echo "$OUT" | grep -c "\[PDF\]")
  APPLE_MAIL_DISPLAY="${APPLE_TOTAL} (${APPLE_PDF} with PDF)"
else
  APPLE_MAIL_DISPLAY="—"
fi
```

5. Outlook (via Graph API) — flagged mails. Silent fail when token missing/expired:
```bash
OUTLOOK_COUNT="— (Auth)"
if [ -f /tmp/graph_token.txt ]; then
  TOKEN=$(cat /tmp/graph_token.txt)
  RESP=$(curl -s -H "Authorization: Bearer $TOKEN" \
    -H "ConsistencyLevel: eventual" \
    "https://graph.microsoft.com/v1.0/me/messages?\$filter=flag/flagStatus%20eq%20'flagged'&\$count=true&\$top=1" 2>/dev/null)
  COUNT=$(echo "$RESP" | jq -r '.["@odata.count"] // empty' 2>/dev/null)
  [ -n "$COUNT" ] && OUTLOOK_COUNT="$COUNT"
fi
```

6. Render output

## Output format

```
╭──────────────────────────────────────────────────────────────────╮
│  Document status    │  {TOTAL} open                              │
╰──────────────────────────────────────────────────────────────────╯

── Inbox ──────────────────────────────────────────────────────────
  ScanSnap:      {N}
  Downloads:     {N}
  Import:        {N}

── Mail (flagged) ─────────────────────────────────────────────────
  Apple Mail:    {N} (M with PDF)
  Outlook:       {N}     [or "— (Auth)" when Graph token is missing]

── Outbox (open) ──────────────────────────────────────────────────
  {area_label_1}:  {N}
  {area_label_2}:  {N}
  {area_label_3}:  {N}
  ... (labels + paths come from context.queue_paths)

── Actions ────────────────────────────────────────────────────────
  /doc-process                 Process next document
  /doc-process --preview 20    Analyze 20 documents
  /doc-process --batch 10      Process 10 automatically
  "process mail attachments"   File Apple Mail receipts
  "outlook attachments"        File Outlook receipts
```

## Rendering rules

- Show all sections (even with 0) — the overview must be complete
- Counts > 20: mark with ⚠ (also applies to mail counts)
- When EVERYTHING is 0: "All queues empty." (compact output)
- TOTAL in the header = filesystem items only (inbox + outbox). Mail counts are shown separately, NOT added to TOTAL — otherwise the number jumps with every flag.
- Mail counts are RAW flag counts (incl. LinkedIn, GitHub notifications, etc.). Actual receipts may be fewer.
