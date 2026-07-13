# Bridge Preview — Generation Guide

After onboarding completion (Phase F), generate a personalised HTML
preview that shows the user **both** what was activated and what was
left for later — in one visual overview.

## When to generate

- End of onboarding (Phase F, after all phases complete, before final commit)
- On `/bridge --html` command
- On `/bridge-onboard --features` (read-only catalogue view)

## How to generate

1. Read `docs/templates/bridge-preview.html`
2. Replace placeholders with actual data from the user's configuration
3. Write the filled HTML to `work/bridge-preview.html`
4. Open in browser:
   - macOS: `open work/bridge-preview.html`
   - Linux: `xdg-open work/bridge-preview.html`

## Placeholder reference

| Placeholder | Source |
|-------------|--------|
| `{{USER_NAME}}` | `bridge-config.yaml` → `identity.name` |
| `{{ORG}}` | `bridge-config.yaml` → `identity.org` (empty if not set) |
| `{{PURPOSE}}` | `bridge-config.yaml` → `purpose.statement` (empty string ⇒ omit the header line entirely) |
| `{{THEME_NAME}}` | `bridge-config.yaml` → `theme` (capitalized display name) |
| `{{ECOSYSTEM_CARDS}}` | Generated from `ecosystem.yaml` repos — see format below |
| `{{CREW_CARDS}}` | Generated from `.claude/agents/*.md` sub-agent frontmatter |
| `{{STANDING_ORDER_LIST}}` | Generated from `protocols/standing-orders/*.md` frontmatter |
| `{{CONFIG_SUMMARY}}` | Generated from `bridge-config.yaml` core toggles |
| `{{ACTIVATED_FEATURES}}` | Features marked `accepted` in `work/onboarding-state.yaml` |
| `{{SUGGESTED_LATER}}` | Features marked `deferred` or `nothing_found` — with re-entry command |
| `{{DISCOVERY_SUMMARY}}` | One-line summary of last scan ("3 sources, 5 findings, 2 features enabled") |
| `{{DATE}}` | Current date in `YYYY-MM-DD` format |

## Placeholder formats

### {{PURPOSE}}

A header line, rendered **above** "Activated Features", that states what this
instance is for. Source: `bridge-config.yaml` → `purpose.statement`. If the
statement is empty (general-purpose instance), **omit this block entirely** — the
preview then looks exactly as it did before purpose existed.

```html
<div class="purpose-banner">
  This Bridge is for <strong>{{PURPOSE}}</strong>.
</div>
```

### {{ECOSYSTEM_CARDS}}

One card per repo. Use description from ecosystem.yaml if available.

```html
<div class="eco-card">
  <div class="eco-card-header">
    <span class="eco-card-name"><a href="https://github.com/{org}/{repo}">repo-name</a></span>
  </div>
  <div class="eco-card-desc">Short description from ecosystem.yaml</div>
  <div class="eco-card-badges">
    <span class="badge badge-type">function-app</span>
    <span class="badge badge-lang">python</span>
  </div>
</div>
```

Type badges: `function-app`, `web`, `docs`, `tool`, `package`, `infra`, `reference`.
Language badges: `python`, `typescript`, `rust`, `go`, `javascript`, or omit if not set.

### {{CREW_CARDS}}

One card per sub-agent. Read frontmatter (`name`, `description`) from each
`.claude/agents/*.md` file. If `~/.claude/agents/` also has globally-installed
sub-agents, include them too.

Icon: pick something fitting from the agent's description (e.g.
🗄️ for `archivist`); default 🤖 when nothing obvious fits.

```html
<div class="crew-card">
  <div class="crew-icon">{icon}</div>
  <div class="crew-info">
    <div class="crew-name">agent-name</div>
    <div class="crew-spec">Elasticsearch log analysis, pattern detection</div>
  </div>
</div>
```

If no agents are configured yet, show a single placeholder card:

```html
<div class="crew-card">
  <div class="crew-icon">👤</div>
  <div class="crew-info">
    <div class="crew-name">No agents assembled yet</div>
    <div class="crew-spec">Drop a sub-agent file into .claude/agents/ — Claude Code auto-discovers it</div>
  </div>
</div>
```

### {{STANDING_ORDER_LIST}}

One row per standing order. Read frontmatter from
`protocols/standing-orders/*.md` files (skip `_template.md` and
`README.md`).

```html
<div class="order-item">
  <span class="order-dot"></span>
  <span class="order-name">task-sync</span>
  <span class="order-scope">always</span>
</div>
```

Scope comes from the `scope` frontmatter field.

### {{CONFIG_SUMMARY}}

Build from `bridge-config.yaml`. Show these items:

```html
<div class="config-item">
  <div class="config-label">Theme</div>
  <div class="config-value">Professional</div>
</div>
<div class="config-item">
  <div class="config-label">Language</div>
  <div class="config-value">en</div>
</div>
<div class="config-item">
  <div class="config-label">Work Tracking</div>
  <div class="config-value enabled">Enabled</div>
</div>
<div class="config-item">
  <div class="config-label">GitHub Projects</div>
  <div class="config-value">org/project #1</div>
</div>
```

Use class `enabled` for active features, `disabled` for inactive ones.
If GitHub Projects are not configured, show "Not configured" with the `disabled` class.

### {{ACTIVATED_FEATURES}}

Read `work/onboarding-state.yaml` and list every entry with
`status: accepted`. Each row shows feature name, when activated, and the
file(s) that were scaffolded.

```html
<div class="feature-row activated">
  <div class="feature-icon">✓</div>
  <div class="feature-name">doc-system</div>
  <div class="feature-meta">Enabled — workflow/contexts/doc-system.yaml created</div>
</div>
```

If no features were accepted in Phase C, show:

```html
<div class="feature-empty">
  No features activated in Phase C — Bridge runs lean for now.
  Use <code>/bridge-onboard --add &lt;feature&gt;</code> to enable on demand.
</div>
```

### {{SUGGESTED_LATER}}

Two sub-sections.

**Sub-section 1 — Deferred.** Read `work/onboarding-state.yaml` for
`status: deferred`. Show each with remind-date and re-entry command:

```html
<div class="feature-row deferred">
  <div class="feature-icon">⏸</div>
  <div class="feature-name">backups</div>
  <div class="feature-meta">Deferred until 2026-06-15</div>
  <div class="feature-action">
    <code>/bridge-onboard --add backups</code>
  </div>
</div>
```

**Sub-section 2 — No signal yet.** Read `feature-catalog.md` for the
full feature list and skip those already in `accepted`, `deferred`, or
`silenced`. Show the rest grouped by life-domain (Identity & Filing,
Communication, Infrastructure, etc.) with one-line description and
re-entry command. **Order focus-first when `purpose.focus` is set:** the groups
whose `focus` slug is in `purpose.focus` come first, the remainder after — same
ORDER-only banding as the Phase E catalogue, nothing hidden. Empty `purpose.focus`
→ today's catalogue order.

```html
<div class="feature-group">
  <h4>Identity & Filing</h4>
  <div class="feature-row available">
    <div class="feature-name">Personas</div>
    <div class="feature-meta">Multiple identities with tax data, signature blocks, filing destinations.</div>
    <div class="feature-action"><code>/bridge-onboard --add personas</code></div>
  </div>
</div>
```

End the {{SUGGESTED_LATER}} section with the trust-building closer. It branches on TWO
axes — whether `purpose.statement` is set, and `discovery.mode`. **Only under `broader`
does `feature-discovery` run its evidence heuristics**, so the confined variants must NOT
promise weekly evidence-based surfacing — under confined the heuristics never run, so
that would be a false promise. Confined still resurfaces *deferred* features and honours
`--add`; say that instead.

```html
<!-- purpose set · broader: -->
<div class="trust-closer">
  These stay one step back so this Bridge stays pointed at
  <strong>{{PURPOSE}}</strong> — none of them is hidden or gated. Bridge surfaces
  the relevant ones proactively: <strong>feature-discovery</strong> checks weekly
  for new evidence and proposes ONE at most per briefing, prioritising your focus
  but never suppressing a strong-evidence match outside it. Disable any time via
  <code>bridge-config.yaml.feature_discovery.enabled</code>.
</div>

<!-- purpose set · confined (default): -->
<div class="trust-closer">
  These stay one step back so this Bridge stays pointed at
  <strong>{{PURPOSE}}</strong> — none is hidden or gated. In confined mode I don't
  scan for new evidence, so you drive activation: <code>/bridge-onboard --features</code>
  to browse, <code>--add &lt;name&gt;</code> to turn one on. (I still resurface anything
  you deferred, and honour <code>--add</code>.) Broaden any time with
  <code>/bridge-onboard --rescan</code>.
</div>

<!-- purpose empty · broader: -->
<div class="trust-closer">
  Bridge surfaces features proactively. <strong>feature-discovery</strong>
  checks weekly for new evidence and proposes ONE at most per briefing.
  Disable any time via <code>bridge-config.yaml.feature_discovery.enabled</code>.
</div>

<!-- purpose empty · confined (default): -->
<div class="trust-closer">
  In confined mode I don't scan for new evidence — you drive activation:
  <code>/bridge-onboard --features</code> to browse, <code>--add &lt;name&gt;</code> to
  turn one on. (I still resurface anything you deferred.) Broaden any time with
  <code>/bridge-onboard --rescan</code>.
</div>
```

### {{DISCOVERY_SUMMARY}}

One-line summary of the last discovery scan, read from
`work/onboarding-scan.json` and `work/onboarding-state.yaml`:

```html
<div class="discovery-summary">
  Last scan: 2026-05-16 14:30 — 5 sources, 12 findings,
  3 features enabled, 2 deferred, 1 declined.
</div>
```

If no scan was run (user skipped Phase B):

```html
<div class="discovery-summary">
  Discovery skipped — running with defaults.
  <a href="#"><code>/bridge-onboard --rescan</code></a> to opt in later.
</div>
```

## Required CSS additions

The existing template's CSS supports `eco-card`, `crew-card`,
`order-item`, `config-item`. The new sections need:

```css
.feature-row {
  display: grid;
  grid-template-columns: 24px 200px 1fr auto;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-soft);
  align-items: center;
}
.feature-row.activated .feature-icon { color: #10b981; }
.feature-row.deferred .feature-icon { color: #f59e0b; }
.feature-row.available .feature-icon::before { content: '○'; color: #6b7280; }
.feature-name { font-weight: 600; }
.feature-meta { color: var(--text-secondary); font-size: 0.875rem; }
.feature-action code {
  background: var(--code-bg);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.8rem;
}
.feature-group h4 {
  margin: 16px 0 8px;
  color: var(--text-secondary);
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.feature-empty {
  padding: 24px;
  background: var(--card-bg);
  border-radius: 8px;
  color: var(--text-secondary);
  text-align: center;
}
.trust-closer {
  margin-top: 24px;
  padding: 16px;
  background: var(--accent-soft);
  border-left: 3px solid var(--accent);
  border-radius: 4px;
  font-size: 0.9rem;
}
.discovery-summary {
  padding: 12px 16px;
  background: var(--code-bg);
  border-radius: 4px;
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin-bottom: 24px;
}
```

If the template doesn't yet have a "Features" section, add it after the
Crew/Protocols block:

```html
<section class="features-section">
  {{PURPOSE}}
  <h2>Activated Features</h2>
  {{DISCOVERY_SUMMARY}}
  <div class="features-list">{{ACTIVATED_FEATURES}}</div>

  <h2>Suggested for Later</h2>
  <div class="features-list">{{SUGGESTED_LATER}}</div>
</section>
```

## Notes

- The HTML template is self-contained — no external CSS, JS, or font dependencies
- System fonts only (Helvetica Neue, -apple-system, sans-serif)
- Accent colors are used subtly (Indigo #6366f1, Violet #8b5cf6)
- The template uses CSS variables for easy theming adjustments
- The generated file goes into `work/` (USER layer) and is gitignored
- The "Suggested for Later" section is the **most important new piece** —
  it's the moment the user sees the full Bridge surface without being
  asked to commit to anything
