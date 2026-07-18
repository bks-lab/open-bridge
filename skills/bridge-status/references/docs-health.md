# Documentation Health — Link Checking & Quality Analysis

Validates documentation quality across Bridge-managed repositories.
Run during `/briefing` (best-effort), on demand, or as pre-release gate.

## When to Use

- `/briefing` Stream C health checks (summary only: "3 critical docs issues")
- `/channel --docs-health` or `/health --docs` (full analysis)
- Pre-release quality gate (block on critical issues)
- After bulk documentation changes

## Link Detection Patterns

5 regex patterns to find all link types in markdown files:

| Type | Regex | Example |
|------|-------|---------|
| Markdown | `\[([^\]]*)\]\(([^)]+)\)` | `[text](link.md)` |
| Image | `!\[([^\]]*)\]\(([^)]+)\)` | `![alt](image.png)` |
| Wiki-style | `\[\[([^\]]+)\]\]` | `[[page-name]]` |
| Reference | `^\[([^\]]+)\]:\s*(.+)$` | `[ref]: link.md` |
| Anchor | `#section-name` in any link | `[text](file.md#section)` |

### Smart Link Resolution

Before marking a link as broken, apply these fixes:

1. **Missing `.md` extension**: `[link](page)` → check if `page.md` exists
2. **Case-insensitive match**: `[link](Page.md)` → check lowercase variant (macOS compatibility)
3. **Directory linking**: `[link](dir/)` → check for `dir/index.md` or `dir/README.md`
4. **Relative path resolution**: resolve `../` paths relative to the source file, not CWD
5. **Strip anchors**: `file.md#section` → validate `file.md` exists (anchor validation is separate)

## Multi-Agent Quality Analysis

Run 5 concurrent checks in parallel:

### MetadataAgent
Validates YAML frontmatter:
- Required fields: `title`, `date` (or `last_updated`)
- Optional but recommended: `summary`, `type`, `related`
- Invalid YAML → Critical
- Missing required fields on index files → Critical
- Missing optional fields → Medium

### LinkAgent
Validates internal and external links:
- Internal links: file must exist at resolved path
- External links: HEAD request with 5s timeout (skip if no network)
- HTTP instead of HTTPS → Medium (suggest upgrade)
- Localhost URLs in published docs → High
- Broken internal links → High
- Broken external links → Medium (may be transient)

### StructureAgent
Validates directory organization:
- Directories with high navigation traffic should have `README.md` (industry standard).
- File naming: lowercase, kebab-case (no spaces, no CamelCase)
- Empty directories → Medium
- Missing README in heterogeneous directories → Low (advisory, not enforced)

### ContentAgent
Validates content quality:
- TODO/PLACEHOLDER/TBD markers → High (in published docs)
- Empty files (< 10 chars) → High
- Broken markdown references (`[ref]` without definition) → Medium
- Very long lines (> 200 chars) → Low

### FormattingAgent
Validates markdown structure:
- Heading hierarchy (no jump from `#` to `###`)
- Blank line before/after headings
- Consistent list markers (all `-` or all `*`, not mixed)
- Trailing whitespace → Low

## Severity Classification

| Severity | Meaning | Examples |
|----------|---------|---------|
| **Critical** | Blocks publishing, data corruption | Invalid YAML, broken nav links, missing index on root |
| **High** | Significant quality issue | Broken internal links, placeholders in active docs, empty files |
| **Medium** | Should fix soon | Missing metadata, TODO without issue ref, naming inconsistency |
| **Low** | Polish/optimization | Style improvements, long lines, trailing whitespace |

## Pre-Release Quality Gate

Configurable thresholds (fail the gate if any exceeded):

```yaml
# Default thresholds
quality_gate:
  max_critical: 0           # Zero tolerance for critical
  max_high: 5               # Up to 5 high-priority issues
  max_broken_link_pct: 10   # Less than 10% broken links
  min_frontmatter_pct: 90   # At least 90% files have frontmatter
  no_placeholders: true     # No TODO/TBD in published docs
```

## Output Format

### Summary (for /briefing)
```
Docs health: 2 critical, 5 high, 12 medium (wiki: 142 files checked)
```

### Full Report (for /health --docs)
```
Documentation Health Report — wiki/

  Critical (2):
    wiki/customers/acme/index.md — invalid YAML frontmatter
    wiki/my-org/protocols/ — missing index.md (12 files, no entry point)

  High (5):
    wiki/customers/acme/setup.md:23 — broken link: ../api/endpoints.md
    wiki/my-org/processes/onboarding.md:45 — [TODO] placeholder
    ...

  Quality Gate: FAIL (2 critical issues, max 0 allowed)
```

### Auto-Fix Suggestions

For fixable issues, suggest concrete edits:

```
Suggested fixes (3 auto-fixable):
  1. wiki/guide.md:15 — [link](setup) → [link](setup.md)  (missing extension)
  2. wiki/api.md:8 — http://docs.example.com → https://docs.example.com  (HTTPS upgrade)
  3. wiki/old-page.md:1 — Add missing frontmatter (title from H1, date from git log)

  [a] Apply all  [r] Review one by one  [s] Skip
```

## Integration with Bridge

- **remote** (infra/remotes/) and **channel** (infra/channels/) own their respective config docs; docs-health checks quality across all of them
- **briefing** Stream C calls docs-health in summary mode (1-line output)
- **archive** weekly checkpoint can include quality trend
- Works on any repo with markdown files, not just the wiki
