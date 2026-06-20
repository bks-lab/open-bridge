# Terminal Rendering Rules

## Layout

- **Target width**: 76 characters
- **Focus box inner width**: 72 characters (76 - 2 border - 2 padding)
- **No ANSI colors**: Plain text only, rely on structure for clarity

## Box Drawing Characters

| Element | Characters |
|---------|-----------|
| Rounded box | `╭ ╮ ╰ ╯` (corners) |
| Horizontal line | `─` |
| Vertical line | `│` |
| Section divider | `── Title ─────...` (pad `─` to 76 chars) |

### Focus Box Template

```
╭──────────────────────────────────────────────────────────────────────────╮
│  {line1, max 72 chars}                                                   │
│  {line2, max 72 chars}                                                   │
╰──────────────────────────────────────────────────────────────────────────╯
```

- Top/bottom borders: `╭` + 74x `─` + `╮` / `╰` + 74x `─` + `╯`
- Content lines: `│  ` + content padded to 72 chars + `  │`

### Section Divider Template

```
── {Title} ({count}) ──────────────────────────────────────────────────────
```

- Start: `── ` + Title + ` ` + pad `─` to fill 76 chars

## Sparklines

Use Unicode block characters for 7-day commit frequency:

```
▁▂▃▄▅▆▇█
```

- 8 levels, index 0-7
- Scale: `level = round(count / max_count * 7)`
- 0 commits on a day = `▁` (not blank)
- 7 characters total = 7 days

## Task Rows

```
  #{id}   {title}                            {status}   {assignee}
```

| Field | Width | Alignment | Truncation |
|-------|-------|-----------|------------|
| `#` prefix + id | 6 chars | right-aligned | never |
| gap | 3 spaces | - | - |
| title | 40 chars max | left-aligned | truncate with `..` |
| status | 12 chars | left-aligned | never |
| assignee | remaining | left-aligned | first name only |

### Overflow

- Single project: max 5 tasks, then `       + {n} in backlog`
- Global view: max 3 tasks per project, then `       + {n} more`
- Sorting: In Progress first, then Todo, then rest

## Git Rows

```
  {repo_short}   {branch}   {sparkline}   {n} commits (7d)
```

| Field | Notes |
|-------|-------|
| repo_short | Last path segment, max 25 chars |
| branch | Current branch name, max 20 chars |
| sparkline | 7 block chars |
| commits | Integer + "(7d)" |

## Deployment Rows

```
  {app_name}   {status}   build {date}
```

| Status | Display |
|--------|---------|
| HTTP 200 | `healthy` |
| HTTP != 200 | `unhealthy ({code})` |
| Timeout | `timeout` |
| No URL | Omit entire section |

## Relative Time Format

| Duration | Display |
|----------|---------|
| < 1 hour | `{n}min ago` |
| 1-23 hours | `{n}h ago` |
| Yesterday | `yesterday` |
| 2-6 days | `{n}d ago` |
| 7+ days | `{n}d ago` |

## Typography Rules

- No emoji within table columns or data rows
- Emoji allowed only at line start for section headers (but prefer plain `──` dividers)
- Labels: "open", "in backlog", "more", "Last commit", "Projects active"
- English for status values: "In Progress", "Todo", "Backlog", "Done"
