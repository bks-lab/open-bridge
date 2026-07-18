# Bridge Leak Check — Classification Rules

Implementation reference for the four-bucket categorization.

## Per-Repo Tolerance Model (the load-bearing rule)

Different repos in the tier model tolerate different things by
design. The model lives in [`data/per-repo-tolerance.yaml`](../data/per-repo-tolerance.yaml)
— that file is the source of truth, this section explains it.

| Repo | Role | Tolerates | Blocks |
|---|---|---|---|
| `<your-username>/your-bridge` | saat-private | personal-pii, customer-names, org-branding, internal-vocabulary | (nothing — by design) |
| `<your-org>/<your-bridge>` (org overlay) | org-internal | customer-names, org-branding, internal-vocabulary | personal-pii |
| `bks-lab/open-bridge` | oss-public | oss-self-reference, oss-sister-repo, schema-id-urls | personal-pii, customer-names, org-branding, internal-vocabulary |
| (unknown origin) | unknown | (strictest = open-bridge) | (everything) |

**Why this matters:** running `bridge-leak-check` on `<your-username>/your-bridge` should
return ZERO findings — the seed repo is allowed to track persona files, <bks-lab>
configs, and customer engagement skills because that IS its job. Running the
same command on `open-bridge` returns findings for any of those things because
it's a public OSS repo. The auto-detection by `.git/config remote.origin.url`
picks the right tolerance row.

A finding only fires when the matched pattern's category is in the target
repo's `blocks:` list. Same content, different repo, different verdict — that's
intentional.

## Auto-detect target repo

```bash
ORIGIN=$(git config --get remote.origin.url 2>/dev/null)
# Match against per-repo-tolerance.yaml repos[].match
# Fallback to "unknown" (= strictest) if no match.
```

Override with `--repo <name>`.

## Standard scan

```bash
# Strings + patterns from bridge-config.yaml.promote.content_blocklist.<REPO>
STRINGS=$(yq -r ".promote.content_blocklist.\"$REPO\".strings[]?" bridge-config.yaml | paste -sd'|' -)
PATTERNS=$(yq -r ".promote.content_blocklist.\"$REPO\".patterns[]?" bridge-config.yaml | paste -sd'|' -)
[ -z "$STRINGS" ] && STRINGS=$(yq -r '.promote.fallback_blocklist[]?' bridge-config.yaml | paste -sd'|' -)

# Find all hits
git ls-files | xargs -I{} grep -nHwE "$STRINGS" {} 2>/dev/null > /tmp/hits.tsv
git ls-files | xargs -I{} grep -nHE "$PATTERNS" {} 2>/dev/null >> /tmp/hits.tsv
```

Each hit is then run through the categorizer.

## Categorizer rules (in order — first match wins)

### 1. Legitimate — self-reference

A hit is self-reference when:

- The matched string is the **canonical name of THIS repo** (auto-detected from origin)
  - In `open-bridge`: `bks-lab/open-bridge`, `bks-lab.github.io/open-bridge`
  - In your org overlay (`org-overlay`): `<your-org>/<your-bridge>`
  - In `your-bridge`: `<your-username>/your-bridge`
- The match is a **schema `$id` URL** pointing at this repo's published schema location
  - Pattern: `\$id:\s*"https://[^"]*<repo-domain>[^"]*"`
- The match is in a **frontmatter `name:` field** (skill name = directory name = legitimate)

```yaml
exceptions_self_reference:
  open-bridge:
    strings:
      - "bks-lab/open-bridge"
      - "bks-lab.github.io/open-bridge"
  org-overlay:
    strings:
      - "<your-org>/<your-bridge>"   # ← replace with your overlay repo slug
      - "bks-lab/open-bridge"   # your org overlay legitimately references its OSS upstream
  your-bridge:
    strings:
      - "<your-username>/your-bridge"
      - "bks-lab/open-bridge"
      - "<your-org>/<your-bridge>"   # ← replace with your overlay repo slug
```

### 2. Legitimate — sister-repo

A hit is sister-repo when:

- The matched string is a **bks-lab/* repo OTHER than the current one**, AND it appears in a context that's clearly a cross-link (markdown link, ecosystem.yaml entry, doc cross-reference)
- The match appears in `ecosystem.yaml` (which is the org's own registry — by definition references all sister repos)

```yaml
exceptions_sister_repo:
  - "{org}/bridge-deck"
  - "{org}/sister-repo-a"
  - "{org}/sister-repo-b"
  # Add others as the OSS-family grows
```

These are scoped per-repo: a `<your-org>/<your-bridge>` mention in `open-bridge` is **NOT** sister-repo (open-bridge shouldn't promote your org overlay as a sibling — it's the internal overlay, a leak). See category 4.

### 3. Leak — personal PII (always)

Personal PII is always a leak, regardless of which repo it appears in (only the seed repo `your-bridge` legitimately tracks PII per the per-repo `.gitignore` policy, but even there it shouldn't appear in CORE files).

Detected via the `always_leak` block in `bridge-config.yaml`:

```yaml
always_leak:
  strings: [<your-username>, <your-username>, <customer-slug-1>, <customer-slug-2>, <customer-slug-3>, <your-homeserver>, <your-desktop>]
  patterns:
    - "/Users/[a-z]+/"
    - "100\\.118\\.[0-9]+\\.[0-9]+"
    - "@bks-lab\\.com"
```

**Suggested fixes:**
- `<your-username>` → `<your-username>`
- `~/` → `~/`
- `<your-homeserver>` → `<your-machine>` or remove example
- Tailscale IPs → omit

### 4. Leak — internal vocabulary (OSS-strict only)

Only flagged when `--strict-oss` is set, AND the target repo is the OSS variant.

Reads `skills/bridge-audit/data/renames.yaml` § `vocabulary_renames` for the list of internal terms that should be replaced with org-neutral placeholders in OSS-shipped content.

Each finding suggests the canonical replacement from the rename entry.

**Why this is a separate category:** these are legitimate inside org-internal repos (your org overlay, your-bridge) but should not appear in OSS skill docs. A blocklist alone can't tell the difference — it needs the context of "this skill is shipped to OSS users".

## Standard exceptions per file type

Some files inherently contain references that look like leaks but aren't:

| File pattern | Allowed | Why |
|---|---|---|
| `LICENSE`, `NOTICE` | Org name in copyright | Legitimate copyright holder |
| `ecosystem.yaml` | All `bks-lab/*` repos | The org's own repo registry |
| `bridge-config.yaml` | All blocklist strings | The blocklist literally lists them |
| `rules/promote-safety.md` | All blocklist strings | Documents the blocklist by example |
| `skills/<X>/SKILL.md` (description / triggers) | Aliases for renamed concepts | Backwards-compat triggers |
| `MEMORY.md` (auto-memory) | All personal references | This is private memory, not committed in OSS |

## --target-dir mode (post-merge verify)

```bash
# After /bridge-sync merges to upstream, verify the destination is still clean:
git clone --depth=1 git@github.com:bks-lab/open-bridge.git /tmp/post-merge-verify
bridge-leak-check --repo open-bridge --strict-oss --target-dir /tmp/post-merge-verify
```

This is the missing step that this session needed. With it, the
"synchron, aber sauber?" question gets answered automatically.
