---
scope: core
description: Theme system — resolution order, built-in themes, custom theme authoring
---
# Theme System

Themes control all user-facing vocabulary — terms, role names, and
recurring phrases. They NEVER control tools, delegation, or goals.
Themes live in `themes/*.yaml`.

## Theme Resolution

1. Read `bridge-config.yaml` field `theme:` (default: `professional`)
2. Load `themes/{theme}.yaml` — if missing, fall back to
   `themes/professional.yaml`
3. If theme has `meta.extends`: deep-merge parent first, then override
4. Fill missing keys from `themes/_schema.yaml` defaults
5. Apply vocabulary to all Claude output for this session

## Built-in Themes

| Theme | Locale | Description |
|-------|--------|-------------|
| `professional` | en | Neutral, business-friendly (default) |
| `professional-de` | de | German translation, extends professional |

```yaml
# bridge-config.yaml
theme: professional        # professional | professional-de | {custom}
```

Full vocabulary: see `themes/professional.yaml`.

## Custom Themes

Copy `themes/_template.yaml` to `themes/{your-name}.yaml`. Override only
the keys you need — everything else inherits from the parent via
`extends`.

Use cases: company vocabulary, industry jargon (SRE, consulting,
agency), locale translations, fun themes. A custom theme needs 10-20
lines of YAML.

### Authoring checklist

1. Choose a parent via `meta.extends` (usually `professional`)
2. Override only keys that differ — leave the rest inherited
3. Validate required fields: `schema_version`, `meta.name`,
   `meta.display_name` (CI checks these)
4. Drop in `themes/{name}.yaml`, set `theme: {name}` in
   `bridge-config.yaml`, restart Claude Code

### Schema reference

- `themes/_schema.yaml` — full key list with defaults
- `themes/_template.yaml` — ready-to-fill starter
