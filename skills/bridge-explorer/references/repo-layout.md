# Repo Layout — CORE / USER Visualization

Renders the CORE/USER branch split as an interactive single-file HTML
dashboard. Two truth sources are merged:

1. **Filesystem** — live counts and sample filenames (the on-disk reality).
2. **`docs/repo-layout/regions.yaml`** — curated descriptions per region:
   `display_name`, `oneliner`, `what`, `examples`, `related`, `put_here`.

This is the canonical content for the rich side panels (v1–v4). The two-
column table in `CLAUDE.md → Git & Branches` is the human reference; the
machine-readable, single-source-of-truth for descriptions is the YAML.

**Trigger phrases:** "repo layout", "core/user split", "where do files
live", "repo structure", "core vs user", "/repo-layout".

## Workflow

### 1. Read truth sources

- `CLAUDE.md → Git & Branches` table — authoritative path list (never invent).
- `docs/repo-layout/regions.yaml` — schema:
  ```yaml
  regions:
    - id: <stable_id>
      path: "<filesystem_path>"   # match key against live walk
      owner: core | user
      display_name: ...
      oneliner: ...
      what: |
        Multi-line prose explaining what lives here.
      examples: ["...", "..."]
      related: ["...", "..."]
      put_here: "Hint: when do you put a new file here?"
  ```

### 1a. Merge rule (live + curated)

For each region in `regions.yaml`, look up its live filesystem stats and
build a record with this merge precedence:

| Field | Source |
|---|---|
| `count`, `samples` | LIVE wins (filesystem truth) |
| `exists`, `missing` | LIVE wins |
| `oneliner`, `what`, `examples_curated`, `related`, `put_here`, `display_name` | CURATED wins |
| layout-specific geometry (`pos`, `x`, `y`, `cx`, `cy`, `anatomy`, etc.) | preserved from existing template (per variant) |

If a curated region's path is missing on disk (e.g. `infra/channels/`),
keep the curated record and set `missing: true`. If a region exists on
disk but has no curated entry, you may include it with empty curated
fields and a TODO note — but prefer adding it to `regions.yaml` first.

### 2. Resolve git state

```bash
git branch --show-current                              # → branch
git rev-list --left-right --count HEAD...development   # → "ahead<TAB>behind"
git log -1 --format=%cI development                    # → last sync ISO ts
```

### 3. Walk paths and gather metadata

For each entry on the CORE side and USER side, in the bridge repo root:

- If it's a file: `count = 1`, `samples = []`, `exists = true`.
- If it's a directory:
  - `count = $(find <path> -type f | wc -l)`
  - `samples = $(find <path> -maxdepth 2 -type f | head -5)` — strip prefix.
  - `exists = true`.
- If missing: `count = 0`, `samples = []`, `exists = false`.

**The CORE list (matching CLAUDE.md table):**

| path | desc |
|---|---|
| `ecosystem.yaml` | Repos, infra, skills, workspaces (single source of truth) |
| `CLAUDE.md` | Operating manual for Claude (this file routes everything) |
| `docs/` | Public docs, onboarding, protocol catalog, multi-instance |
| `skills/` | Skills (CORE; slash-command triggers live in each SKILL.md) |
| `.claude/agents/` | CORE sub-agents (user agents mostly live globally) |
| `identity/personas/_template.yaml` | Persona schema template |
| `docs/examples/personas/` | Example personas (no real tax data) |
| `protocols/standing-orders/` | Standing orders (shipped always-on rules) |
| `docs/examples/projects/` | Example project configs (templates created on demand) |

**The USER list:**

| path | desc |
|---|---|
| `bridge-config.yaml` | Personal config (theme, identity, integrations) |
| `contexts/` | Personal context files |
| `identity/personas/*.yaml` | Real personas with tax IDs / signatures (NEVER core) |
| `work/` | Logs, board, active tasks, briefings — the working memory |
| `infra/remotes/` | Personal machine inventory + setup notes |
| `infra/channels/` | Outbound transports (iMessage, email, Telegram, ...) |
| `mandants/` | Recipient groups (company, household, family, friends) |
| `workflow/calendars/entries.yaml` | Scheduled outbound actions |
| `workflow/projects/*.yaml` | Actual project configs (excluding `_schema`/`_template`/`examples/`) |

For `identity/personas/*.yaml` and `workflow/projects/*.yaml` filter rule: include any
`*.yaml` files at the top of those dirs that are NOT `_schema.yaml`,
`_template.yaml`, and exclude the `examples/` subfolder.

### 4. Hints (worked examples)

Static seed list — adapt as Bridge evolves:

```yaml
- side: user
  label: "New persona for tax data"
  target: "USER/identity/personas/<id>.yaml"
  note: "Schema: identity/personas/_template.yaml"
- side: core
  label: "New standing order"
  target: "CORE/protocols/standing-orders/"
  note: "Promotable via /promote"
- side: user
  label: "New machine inventory"
  target: "USER/infra/remotes/<name>.yaml"
- side: user
  label: "Active task / incident"
  target: "USER/work/tasks/<slug>/"
- side: core
  label: "New CORE skill"
  target: "CORE/skills/<name>/SKILL.md"
- side: user
  label: "Project config (real)"
  target: "USER/workflow/projects/<slug>.yaml"
```

### 5. Fill templates / variants

Each entry in `core[]` and `user[]` (v1, v2, v4) — or `REGIONS[]` (v3) —
must carry curated fields alongside live truth:

```javascript
{
  path: "ecosystem.yaml",
  // live (filesystem)
  count: 1, samples: [], exists: true, missing: false,
  // curated (from regions.yaml)
  display_name: "Ecosystem Registry",
  oneliner: "Single source of truth for all repos, workspaces and skills",
  what: "Central YAML that describes the entire org ecosystem: ...",
  examples_curated: ["base.open-bridge — the hub repo itself", ...],
  related: ["CLAUDE.md", "workflow/projects/*.yaml"],
  put_here: "New repo, new workspace, new customer with code repos.",
  // legacy field — kept for backward compat, set to oneliner
  desc: "Single source of truth for all repos, workspaces and skills",
  // layout-specific geometry preserved per variant
  // v2: region, pos    v3: side, x, y    v4: anatomy, x/y/rx/ry or cx/cy/w/h
}
```

The four variants share one rich side-panel layout:

```
[owner badge] [path]
[oneliner]                    ← italic, muted
─────────────────────────────
WHAT LIVES HERE
[multi-line "what" prose]

EXAMPLES
• examples_curated[0]
• examples_curated[1]
...

RELATED
[chip] [chip] [chip]          ← title="path"

WHERE WOULD I PUT THIS?
[put_here]                    ← amber accent

ON DISK (sample filenames)
[samples joined]              ← monospace
```

A region with `missing: true` shows the curated block normally but
swaps the bottom hint for `⚠ MISSING — region declared in regions.yaml
but not present on disk.`

### 6. Write + open

Output paths (generated on demand — not committed):

- `docs/repo-layout/c-prime.html` (primary structural view)
- `docs/repo-layout/v3.html` (3D particle brain — only variant in active tab UI as 🧪 Brain · exp)

v1/v2/v4 are legacy variant specs kept in this reference doc; render
them on demand if needed.

```bash
# after rendering the variant via /bridge-explorer:
open docs/repo-layout/v3.html     # macOS default
# Fallback: xdg-open / start
```

After regenerating, optionally rsync to a remote for network access
(see `docs/repo-layout.md` § network access for the optional pattern):

```bash
rsync -av docs/repo-layout/*.html homeserver:~/org-repo-layout/
# Then reachable at http://homeserver:8793/v3.html (if you serve that dir over HTTP)
```

### Heatmap data extraction (v3 only)

`v3.html` carries an embedded **Activity Heatmap**: per-region touch
count over the last 30 days, plus a global daily series for the
side-panel sparkline. This data is a **build-time snapshot** — it gets
regenerated each time `v3.html` is produced; the runtime doesn't poll
git.

**Step 1 — per-file touch counts (last 30 days):**

```bash
git log --since="30 days ago" --name-only --pretty=format: \
  | grep -v '^$' | sort | uniq -c | sort -rn
```

Output: `<count> <file_path>` lines.

**Step 2 — map files to regions.** For each file, find the matching
region by **longest-prefix match** against `REGIONS[].id`:

- Region ids ending with `/` (e.g. `docs/`, `work/`) match any path
  starting with that prefix.
- Bare-file region ids (e.g. `CLAUDE.md`, `ecosystem.yaml`) match the
  exact path or anything under `<id>/`.
- Sort regions by `id.length DESC` so deeper paths win.

Sum counts per region. Files with no match are dropped (e.g. files
outside any declared region).

**Step 3 — daily series.** Bucketize repo-wide commit activity per
calendar day for the same window:

```bash
git log --since="30 days ago" --pretty=format:"%ad" --date=short --name-only \
  | awk 'NF==1 && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/ {date=$0; next} NF>0 {print date}' \
  | sort | uniq -c
```

Pad to a 30-element array `[d0…d29]` (oldest first), filling missing
days with `0`.

**Step 4 — inject into v3.html** as a `const HEATMAP = {…};` block,
right after `BRIDGE_STATE`:

```js
const HEATMAP = {
  window_days: 30,
  total_touches: <int>,                 // sum of per_region values
  per_region: { "<region_id>": <int>, … },
  daily: [ <30 ints, oldest first> ],
  daily_start: "<YYYY-MM-DD>",          // ISO date of daily[0]
  generated_at: "<ISO-8601 with offset>"
};
```

The renderer derives `heat_norm = count / max(per_region.values())`
on load and uses it for: cluster halo opacity, top-3 throb selection,
toolbar 🔥-chip tier, side-panel ASCII bar + percentage. The `daily`
array drives the side-panel SVG sparkline (80×16, owner color).

**Step 5 — Heat-Mode pill.** v3's left toolbar contains a `🌡 Heat`
button next to `Both / CORE / USER`. Clicking it toggles a mode where
regions with `heat_norm < 0.1` fade to 0.15 alpha; the rest stay at
full intensity. The pill is independent of CORE/USER filtering — both
can be active.

## Dependency extraction (v3 only)

v3's **🔗 Deps** pill and the side-panel "REFERENCES (machine-extracted)"
section are powered by a generate-time grep across each region's files.
Reveals real machine-observed coupling vs. the curated `related:` list
in `regions.yaml` — divergences flag stale curation or missing entries.

**Step 1 — for each region** with `exists: true`, walk its filesystem
tree (max depth 3, skip dot-dirs except the explicit `.claude/`
sub-paths, cap at 200 files per region). Allowed extensions:
`.md .yaml .yml .json .py .ts .tsx .js .jsx .sh .txt .html .toml`.
Skip files >256 KB or 0 bytes.

**Step 2 — pick a target token per region.** Use the longest unique
substring of the region's path. Examples:

| region id | search token |
|---|---|
| `infra/remotes/` | `infra/remotes/` |
| `CLAUDE.md` | `CLAUDE.md` |
| `identity/personas/_template.yaml` | `identity/personas/_template` |
| `workflow/projects/*.yaml` | `projects/` (broad — exclude self-refs) |
| `identity/personas/user-freelancer.yaml` | `identity/personas/user-freelancer` |

**Step 3 — count substring matches** of each TARGET token in each
SOURCE region's files. Skip self-references and counts of 0. Capture
up to 3 sample `relpath:line` references per (source, target) pair.

**Step 4 — cap at top-8 edges per source** by count, to avoid
spaghetti when a hub region (e.g. `docs/`) references everything.

**Step 5 — inject into v3.html** as `const DEPS = {…};` right after
the `// ============== DEPENDENCY ARCS ==============` block header
(before `CANVAS SETUP`):

```js
const DEPS = {
  generated_at: "<ISO-8601 with offset>",
  edges: [
    { source: "<region_id>", target: "<region_id>",
      count: <int>, samples: ["<relpath:line>", … max 3] },
    …
  ]
};
```

**Step 6 — visual integration.**

- **Hover/lock a region** → up to 8 curved Bezier arcs from that region
  to the targets it references most. Stroke gradient: source-owner
  color → target-owner color (cyan→amber arcs make CORE↔USER coupling
  visually obvious). Stroke width scaled by ref count, capped 0.6–2.5
  px. Control point pulled perpendicular to the screen-space chord +
  slight upward bow for a synaptic-projection feel; cross-hemisphere
  arcs get a stronger bow.
- **Hover the Bridge core** → no arcs. Bridge stays clean.
- **🔗 Deps pill** (next to 🌡 Heat) → independent toggle that draws
  ALL edges simultaneously at low opacity (~0.12) — the full coupling
  network at once.

**Step 7 — side-panel reconciliation.** Between EXAMPLES and RELATED
the panel shows top-5 outgoing observed edges as color-coded chips:

| Chip | Meaning |
|---|---|
| 🟢 (green) | curated in `regions.yaml` AND observed in code |
| 🟡 (amber) | curated only — no code-mention detected (stale curation?) |
| 🔵 (cyan) | observed only — missing from `regions.yaml` (curation gap?) |

The reconciler normalizes curated `related:` strings against
`REGIONS[].id` so paths like `"identity/personas/{id}.yaml"` (curated) align
with the live id `"identity/personas/user-freelancer.yaml"`.

**Heuristic, not perfect.** Substring match catches comments,
docstrings, prose mentions. That's the point — REFERENCES is the
"what's actually mentioned" view; RELATED is the editorial view.
Discrepancies are the interesting signal.

## Schema validation (v3 only)

v3 ships a per-region traffic-light that validates yaml regions
against their template / schema at generate time. The result is
injected as a `const SCHEMA = {...}` block right after `DEPS`.

### Schemas used

| Region | Schema source | Strategy |
|---|---|---|
| `mandants/` | `identity/mandants/_template.yaml` | template-as-schema |
| `identity/personas/_template.yaml`, `identity/personas/user-freelancer.yaml` | `identity/personas/_template.yaml` | template-as-schema |
| `workflow/projects/*.yaml` | (no template today — promote-on-demand) | template-as-schema |
| `infra/remotes/` | `infra/remotes/_template.yaml` | template-as-schema |
| `infra/channels/` | `infra/channels/_template.yaml` | template-as-schema |
| `workflow/calendars/entries.yaml` | `workflow/calendars/_template.yaml` | template-as-schema |
| everything else | — | grey (n/a) |

### Validation algorithm

Pragmatic shallow check, no real YAML library:

1. For each region with a bound schema, glob the matching files
   (excluding the template itself).
2. For each file, extract top-level keys via regex
   `^([A-Za-z_][\w-]*):` — only column-0 lines, ignoring comments,
   list items, and indented children.
3. Diff against the curated `required` set and `allowed_extra` set:
   - missing required → red
   - all required present, unknown top-level keys → amber
   - all required present, no unknown keys → green
4. Aggregate at region level: any red file ⇒ region red; else any
   amber ⇒ amber; else green. No matching files ⇒ grey.

The required / allowed-extra sets are produced at render time by the
skill (no generator script ships with open-bridge) — keep them lean.
"Allowed extras" is intentionally permissive so day-to-day schema
drift surfaces as amber, not red.

### Visual surface

| Surface | Look |
|---|---|
| Per-cluster pip | 3.5 px dot at the cluster centroid (top-right offset). Color: green `#10f5b3`, amber `#f59e0b`, red `#ef4444`. Grey is omitted entirely. |
| Toolbar row | Same colored pip after the count, with a tooltip listing status + checked-file count. |
| Side panel | New `SCHEMA` section between `RELATED` and `WHERE WOULD I PUT THIS?`. Shows the verdict (`conformant` / `issues found` / `broken` / `n/a`), the schema source, the file count, and a bulleted issue list (capped at 8). |

Frame budget: ~20 dot draws / frame, additive composite OFF. No
measurable FPS impact at 60 fps.

## You-are-here anchor (v3 only)

v3 also captures a "you are here" signal at generate time and renders
it as a permanent breathing ring around the matched region.

### Captured at generate time

```js
YOU_ARE_HERE = {
  branch: "<git branch --show-current>",
  cwd: "<git rev-parse --show-prefix>",
  last_edit_path: "<most-recent mtime in repo, excluding .git>",
  last_edit_region: "<longest-prefix match against REGIONS[].id>",
  last_commit_subject: "<git log -1 --format=%s>"
}
```

The most-recent-mtime walk excludes `.git/` and `node_modules/`. The
prefix match falls through to a few hard-coded patterns
(`workflow/projects/*.yaml`, `identity/personas/*.yaml`, `mandants/`, `infra/remotes/`,
`infra/channels/`, `calendar/`) so a freshly touched yaml file always lands
on its region cluster.

### Visual surface

| Surface | Look |
|---|---|
| Region ring | 24-px white stroke at 0.18 alpha + soft white shadow. Breathing cycle 1.5 s, alpha modulates 0.18 ↔ 0.28. Drawn in addition to all other effects. |
| HUD top-left | Extra line `📍 here: <region_display_name>` below the branch indicator. Hover title = last commit subject. |
| Toolbar row | Matching region row gets a leading `📍` glyph with the same hover title. |

Single extra ring per frame, identity composite — negligible cost.

## Notes

- UTF-8 native chars, never HTML entities.
- The template is self-contained: system fonts only, no CDN, no
  external assets. Light/dark theme toggle persisted via localStorage,
  also bound to the `T` key.
- Rendered HTML files in `docs/repo-layout/` are on-demand outputs, not
  committed — they get regenerated on each `/bridge-explorer repo` run.

## v3 extras (intentionally unspecified)

v3 is the experimental variant and carries additional interactive
features beyond the data blocks above — an enriched side panel, a
command palette with view modes, external dependency tendrils, and a
time scrubber. Their detail is intentionally not specified here: when
rendering v3, design them fresh from the data blocks above.
