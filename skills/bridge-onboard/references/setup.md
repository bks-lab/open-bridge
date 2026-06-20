# Bridge Setup — Onboarding & Configuration

## Activation

### Step 1: Detect State

- `bridge-config.yaml` exists? → config present
- `ecosystem.yaml` exists? → ecosystem present
- `work/log.md` exists? → work system active
- Branch is `user/*`? → already set up

States:
- **Fresh:** Nothing → full setup (read `workflow.md`)
- **Config exists, work not enabled:** → offer work system activation
- **Fully active:** → inform, offer reconfigure

### Step 2: Propose Configuration

Present ONE smart proposal:

```
Bridge Setup:
  Theme:    professional
  Work:     enabled (hybrid logging, 5 max active tasks)
  GitHub:   [auto-detected from ecosystem.yaml]
  Agents:   archivist ships built-in; add your own in .claude/agents/

  [y] Accept  [c] Customize  [n] Cancel
```

### Step 3: Generate Task Management

Create directories:
```bash
mkdir -p work/{tasks,streams,done,archive/days,archive/weeks,imports}
```

The standalone `work/.config.yaml` is obsolete — work configuration lives
in `bridge-config.yaml` under the `work:` block (since 2026-04). Edit
`bridge-config.yaml`:
- `work.enabled: true`
- `work.logging_level:` — `hybrid` (default), `auto`, or `manual`
- `work.activity_types:` — emoji + label list driving log column 2
- `integrations.github.projects:` — read from `ecosystem.yaml` or list explicitly

Generate `work/log.md` from `work/templates/week-skeleton.md` — replace the
week header (CW + date range), today's day-block header (`date '+%a %d.%m'`),
and the Active Focus / Focus lines. The day-block body is byte-identical to
`work/templates/day.md`, so every parser reads it uniformly.

Generate `work/board.md`:
```markdown
# Task Board

*Updated: {today_date}*

---

## Active (0)

| Task | Description | Type | Context | Since | Status |
|------|-------------|------|---------|-------|--------|

---

## Queue (0)

| Prio | Task | Description | Type | Context |
|------|------|-------------|------|---------|

---

## Done ({month} {year})

| Task | Description | Context | Completed |
|------|-------------|---------|-----------|

---

## Stats

- **Active:** 0 / 5
- **Queue:** 0
- **Log:** [log.md](log.md)
```

### Step 4: Confirmation

Show `/bridge` status to confirm everything is green.

## Deactivation

1. Confirm with user
2. Set `work.enabled: false` in bridge-config.yaml
3. Data preserved in `work/`
