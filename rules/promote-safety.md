---
scope: core
description: Content-safety scan that runs before any cherry-pick, merge, or commit onto CORE — blocklist patterns, scrub rules, and the decision matrix for what leaks
---

# Promote Safety — content leakage prevention

**This rule runs before any cherry-pick, merge, or commit that targets
`main` or any upstream branch.** It prevents user-personal
or organization-specific content from slipping into CORE branches that
other Bridge users pull.

## Why this rule exists

The CORE/USER split in this repo is path-based: files under `work/`,
`contexts/`, `infra/remotes/`, `infra/channels/`, etc. never
reach CORE. But the allowlist paths (`CLAUDE.md`, `docs/`, `trackers/`,
`skills/`, `rules/`, …) can still carry
**content** that leaks user identity, customer names, product codenames,
or private infrastructure — especially inside "Example" blocks, render
samples, and adoption notes.

A real incident during the first tracker-abstraction promote: an
"Example run" block in a CORE playbook carried customer-specific
org names, user handles, product codenames, and a real issue title.
The first content-safety scan **saw** these strings and rationalized
them as "acceptable for docs". That rationalization is the failure
mode this rule exists to block.

## When to run

Run this rule **before** any of these actions, whether invoked via
`/promote`, `/contribute` (both backed by `skills/bridge-promote/SKILL.md`),
or a raw `git cherry-pick` / `git merge`:

| Action | Gate |
|---|---|
| Cherry-pick onto `main` | Scan all touched files in the picked commit |
| Merge user branch into `main` | Scan the merge diff |
| Direct commit on `main` | Scan the staged diff |
| PR to an upstream fork | Scan the branch-vs-base diff |

Do **not** run this on commits staying on a user branch — those are
allowed to carry user content by design.

## What to scan

0. **Scope check (skills + sub-agents)** — two locations, same rule:
   - If the diff touches `skills/<name>/`, read
     `skills/<name>/SKILL.md` frontmatter — for skills the field lives
     under `metadata:` (`metadata.scope`), not top-level. If `scope:` is
     `user` or `private`, **block the entire skill directory** from the promote.
     Only `scope: core` (or no `scope:` field) may land on
     `main`.
   - If the diff touches `.claude/agents/<name>.md`, read that file's
     frontmatter. Same rule — `scope: org` or `scope: private` means
     **block the file** from the promote. Only `scope: core` (or
     absent) is allowed for `main`. The sub-agent frontmatter shape differs from
     skills (`name`/`description`/`tools`/`model`) but the `scope:`
     field is the shared convention.
   - If the diff touches `rules/`, the **folder is the tier** (no per-file
     frontmatter needed): top-level `rules/*.md` is core and **may land**;
     `rules/org/**` and `rules/user/**` are non-core — **block them** from
     open-bridge / `main` (`rules/org/` routes to your org overlay
     only, `rules/user/` never promotes). Structure is the primary guard
     here; this content scan is the **backstop** that catches a real name
     accidentally left in a core-tier file.
1. **Files in the diff** — every added / modified file, full new content
2. **The commit message body** — leakage in commit messages is still leakage
3. **Skip git metadata** — the `Author:` line (`name <email>`) is
   allowed; Claude does not rewrite commit authorship.

### Tooling — never use `git grep` for leak/content scans

Run every leak/content scan with plain `grep -rnIE` over the working tree,
**never `git grep`**. `git grep` has already produced a false **CLEAN** on
a leak audit that shipped real colleague names, customer reverse-IDs, and a
foreign client instance live in the public repo — two failure modes hit
silently at once:

- **`git grep -r …`** — `-r` is not a git-grep flag (git grep is recursive
  by default). Passing it makes git grep error to stderr and print
  **nothing on stdout** → reads as zero hits → false-negative.
- **`git grep -E "…ü…"`** — a non-ASCII char in the `-E` alternation
  silently drops matches (locale/encoding). Plain grep handles `ü`/`ß`/`→`
  fine; git grep does not.

`git grep` also only sees **tracked, committed** content — it misses
untracked, gitignored, and partially-staged files, exactly the places
PII tends to sit at the promote gate. Use plain grep with quoted globs:

```bash
grep -rnIE "pat1|pat2" --include='*.md' --include='*.yaml' .
```

Quote the globs (`--include='*.md'`) — the Bash tool runs **zsh**, which
expands a bare `*.md` and fails with "no matches found" (see
`rules/discovery.md` for the zsh-glob caveat). Cross-check any "repo is
clean" claim with a second tool before asserting it — verify-before-claim
applies to the verification command itself.

## Patterns to block

Patterns come from two sources, combined at scan time:

### Hardcoded universal patterns (always active)

These catch classes of leakage that are never CORE-appropriate:

| Category | Regex (case-insensitive) |
|---|---|
| Absolute user paths | `/Users/[a-z0-9._-]+/`, `/home/[a-z0-9._-]+/`, `C:\\Users\\` |
| Private SSH / keys | `BEGIN [A-Z ]+PRIVATE KEY`, `ssh-rsa AAAA`, `ssh-ed25519 AAAA` |
| Common API-token prefixes | `sk-[-A-Za-z0-9_]{20,}`, `ghp_[A-Za-z0-9]{20,}`, `xox[bp]-[-A-Za-z0-9]{10,}`, `AKIA[0-9A-Z]{16}`, `Bearer [-A-Za-z0-9._~+/=]{20,}` |
| OneDrive / Dropbox personal | `OneDrive-[A-Za-z]+`, `Dropbox/.*/Apps/` |
| Phone numbers (E.164) | `\+?[1-9][0-9]{7,14}` — flag for review, false positives possible |
| Email addresses | `[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}` — flag unless it is the git author |

### User-configured blocklist (from `bridge-config.yaml`)

Each Bridge user maintains their own list under
`promote.content_blocklist:` in `bridge-config.yaml`. **Schema**: per-repo
blocklists keyed by upstream-name, plus a `fallback_blocklist` for
operations without an explicit upstream target.

Per-repo lists let `/promote` pick the right strictness:
- `open-bridge` (public OSS) gets the **strictest** list (org + customers
  + personal — anything that isn't generic platform code is blocked)
- your org overlay (org-internal) is **relaxed** — customer names, teammate
  emails are OK, but personal PII (`<your-username>-*`, personal hostnames)
  is still blocked

```yaml
# bridge-config.yaml  (USER layer, gitignored — your real values live here)
promote:
  content_blocklist:
    open-bridge:                         # destination: bks-lab/open-bridge (public OSS)
      strings:
        - my-company
        - my-company-internal
        - customer-a
        - customer-b
        - codename-x
        - vendor-sdk-name
        - first-name
        - last-name
        - github-username
        - kv-customer-a-prod
        - fn-customer-a-ingest
      patterns:
        - "@my-company\\.com"
        - "/Users/<your-username>"
    my-company-bridge:                   # destination: your org overlay (internal)
      strings:
        - github-username                # personal handle
        - first-name
      patterns:
        - "/Users/<your-username>"
        - "personas/<your-username>-"
  fallback_blocklist:                    # used when no explicit upstream target
    - my-company
    - first-name
    - github-username
```

**Selecting which list applies:**
1. `/promote` knows the destination repo (it's routing the commit)
2. Look up `promote.content_blocklist.<repo-name>` → use its `strings`+`patterns`
3. If no per-repo entry exists, fall back to `promote.fallback_blocklist`

A clean Bridge install has no patterns → scan still runs the hardcoded
universal patterns, just without the user-specific layer.

**Context-sensitivity**: a pattern is only a hit if it appears as a
word-level match, not inside a longer token. A pattern like `acme`
should match `acme` and `acme-tools` but **not** match `academy` or
`replacement`. Use `grep -wi` or an equivalent word-boundary regex.

### Three remediation paths

A blocklist hit has three possible remediation paths, picked by what
the user configured for that destination:

1. **`scrub_rules.<dest>` matches the hit** → auto-rewrite during
   cherry-pick. The substitution turns the personal/internal token into
   a placeholder that's safe in the destination. Used for usernames,
   org names, hostnames where there's a stable mapping.
2. **No scrub-rule match, hit is `adaptable`** → semantic content that
   needs human-judged rewording (a routing-table example with concrete
   wiki paths, an ADR mentioning specific upstream repos). Defer the
   commit, surface for `/contribute --adapt`.
3. **No scrub-rule match, hit is personal-PII** → can't fix in place
   (real names in long-form examples). Refuse the commit; user reworks
   source.

### User-configured scrub rules (`promote.scrub_rules`)

Each destination can declare a list of `{ pattern, replacement }` pairs
that get applied **before** the safety scan during a sync. Format:

```yaml
# bridge-config.yaml (USER layer)
promote:
  scrub_rules:
    open-bridge:                          # strictest — strip user + org + customers
      - { pattern: '\bmy-github-handle\b',          replacement: '<your-username>' }
      - { pattern: '\bmy-github-handle/the-bridge\b', replacement: '<your-username>/the-bridge' }
      - { pattern: '\bmy-org-slug\b',               replacement: '<your-org>' }
      - { pattern: '\bmy-hostname\b',               replacement: '<host>' }
    my-org-overlay:                       # your org overlay repo — relaxed, only personal-PII scrubs
      - { pattern: '\bmy-github-handle\b',          replacement: '<your-username>' }
      - { pattern: '\bmy-hostname\b',               replacement: '<host>' }
```

Each rule is a perl `s|pattern|replacement|g` substitution applied
in order over the files touched by the cherry-pick. Use word
boundaries (`\b`) so `my-handle` matches but `my-handle-something`
doesn't (unless you want it to — declare a separate rule).

Rules are USER-scope by definition — they reference your real
identifiers. The `bridge-config.yaml.template` ships an empty
structure; you populate it during `/bridge-onboard` or by hand.

## Scan procedure

There are **two scan moments**, both required:

### A. Pre-commit scan (before running `git commit`)

Run this on **any commit** that touches allowlist paths, regardless of
branch. Even on a user branch, such commits are candidates for later
cherry-pick to CORE — the commit **message** becomes part of CORE
history permanently when that cherry-pick happens.

```bash
# Scan the staged file content AND the drafted commit message body.
# Per-repo blocklist: pass --repo <name> to pick the right strictness.
# Without --repo, falls back to promote.fallback_blocklist.

REPO="${PROMOTE_REPO:-fallback_blocklist}"   # or open-bridge / your org-overlay upstream name

# Pull strings + patterns from per-repo blocklist (with fallback)
STRINGS=$(yq -r ".promote.content_blocklist.\"${REPO}\".strings[]?" bridge-config.yaml 2>/dev/null | paste -sd'|' -)
PATTERNS=$(yq -r ".promote.content_blocklist.\"${REPO}\".patterns[]?" bridge-config.yaml 2>/dev/null | paste -sd'|' -)
[ -z "$STRINGS" ] && STRINGS=$(yq -r '.promote.fallback_blocklist[]?' bridge-config.yaml 2>/dev/null | paste -sd'|' -)

UNIVERSAL='BEGIN [A-Z ]+PRIVATE KEY|sk-[-A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|/Users/[a-z0-9._-]+/'

DRAFT_MSG_FILE=$(mktemp) && : > "$DRAFT_MSG_FILE"
# ... write the drafted commit message into $DRAFT_MSG_FILE ...

# Staged file content
[ -n "$STRINGS" ]  && git diff --cached | grep -niEw "^\+.*($STRINGS)"  && echo "  → blocklist hit in staged diff (repo=$REPO)"
[ -n "$PATTERNS" ] && git diff --cached | grep -niE  "^\+.*($PATTERNS)" && echo "  → pattern hit in staged diff (repo=$REPO)"
git diff --cached | grep -niE "^\+.*($UNIVERSAL)" && echo "  → universal pattern in staged diff"

# Drafted commit message body — the one that will end up in git log
[ -n "$STRINGS" ]  && grep -niEw "$STRINGS"  "$DRAFT_MSG_FILE" && echo "  → in commit message"
[ -n "$PATTERNS" ] && grep -niE  "$PATTERNS" "$DRAFT_MSG_FILE" && echo "  → in commit message"
grep -niE "$UNIVERSAL" "$DRAFT_MSG_FILE" && echo "  → universal in commit message"
```

**Hard rule for Claude writing commit messages on this repo**: before
invoking `git commit -m "$MSG"`, pipe `$MSG` through a blocklist grep.
Do not commit any message that names the leakage it is removing — write
about the **pattern** ("example values in a doc block", "customer-
specific identifiers") instead of the **literal terms** (listing each
removed string verbatim). A "fix: remove XYZ from file" message where
XYZ is the blocklist term re-introduces the term at the git-log layer.
The concept is enough; the words are not.

### B. Pre-promote scan (before cherry-pick / merge onto CORE)

Run this when a commit is about to land on `main` or
any upstream branch.

```bash
# Before cherry-pick / merge / commit onto CORE — per-repo strictness.
# REPO="open-bridge" for OSS pushes, your org-overlay upstream name for org-internal pushes.
REPO="${PROMOTE_REPO:-fallback_blocklist}"

FILES=$(git diff-tree --no-commit-id --name-only -r <commit>)
MSG=$(git log -1 --format=%B <commit>)

STRINGS=$(yq -r ".promote.content_blocklist.\"${REPO}\".strings[]?" bridge-config.yaml 2>/dev/null | paste -sd'|' -)
PATTERNS=$(yq -r ".promote.content_blocklist.\"${REPO}\".patterns[]?" bridge-config.yaml 2>/dev/null | paste -sd'|' -)
[ -z "$STRINGS" ] && STRINGS=$(yq -r '.promote.fallback_blocklist[]?' bridge-config.yaml 2>/dev/null | paste -sd'|' -)

UNIVERSAL='BEGIN [A-Z ]+PRIVATE KEY|sk-[-A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|/Users/[a-z0-9._-]+/'

for f in $FILES; do
    [ -n "$STRINGS" ]  && git show <commit>:"$f" 2>/dev/null | grep -niEw "$STRINGS"  && echo "  → blocklist hit in $f (repo=$REPO)"
    [ -n "$PATTERNS" ] && git show <commit>:"$f" 2>/dev/null | grep -niE  "$PATTERNS" && echo "  → pattern hit in $f (repo=$REPO)"
    git show <commit>:"$f" 2>/dev/null | grep -niE "$UNIVERSAL" && echo "  → universal hit in $f"
done

[ -n "$STRINGS" ] && printf '%s\n' "$MSG" | grep -niEw "$STRINGS" && echo "  → in commit message"
```

If scan A (pre-commit) ran correctly, scan B should find zero hits for
any commit originating in this repo. Scan B is defense in depth plus
protection against commits that pre-date this rule.

## Decision matrix

| Result | Action |
|---|---|
| **Zero hits** in files and commit message | Proceed with the promote action |
| **1+ hits** in the commit message only | Rewrite the message, re-attempt |
| **1+ hits** in files, all inside "Example" / sample blocks | Offer to neutralize (replace with `my-org`, `alice`, `#42`, "Example title"). After fix, re-scan. Do **not** promote with the original content. |
| **1+ hits** in files, inside semantic content (rules, agent templates, config defaults) | Skip the commit. This is not fixable in isolation — the semantic intent is user-specific. |
| **Phone / email** hits | Flag to the user, ask per occurrence — these may be intentional (e.g. a README example of how to write a mail address). Git author email is allowed. |

## The anti-rationalization rule

These thoughts are **not permitted** as reasons to promote a hit:

| Thought | Reality |
|---|---|
| "It's just in the Example section" | Example sections are the #1 leak vector; they look harmless and copy across forks |
| "It's how other READMEs do it" | Other READMEs leak too. We are not them. |
| "It's a private repo anyway" | Git history is forever. Private repos get unforked, transferred, open-sourced. |
| "The user knows what it means" | Other Bridge users don't. CORE is for them, not for us. |
| "It's just a customer name" | Customer names in CORE = breach of engagement confidentiality |
| "It's only one occurrence" | One is enough to leak. Neutralize it. |
| "Neutralizing would take too long" | Neutralizing takes one `Edit` tool call. Leakage takes one upstream contributor finding it and asking "who is this customer". |

If you find yourself forming any of these thoughts, stop and neutralize.

## What is NOT a leak

- **Git author metadata** (`Your Name <you@example.com>` in commit
  headers). Git authorship is infrastructure, not content.
- **Bridge's own product names**: "The Bridge", "CORE", "USER",
  "/briefing", sub-agent names like "archivist" — these are the product, not
  leakage.
- **Generic technical terms**: even if a user-configured blocklist has
  a short pattern like `acme`, it should not match `academy` or
  `placement`. Use word-boundary matching.
- **Commits staying on user branches**: no scan, no restriction.
  User branches are allowed to carry everything.

## Neutralization cheat sheet

When fixing an Example block, use these neutral placeholders:

| Category | Replace with |
|---|---|
| Company / org name | `my-org` |
| Customer / client name | `customer-a`, `Example Customer` |
| User handles / names | `alice` (first user), `bob` (second user) |
| Project / board numbers | `7`, `42` |
| Issue ids | `#42` (GitHub style), `PROJ-42` (Jira style) |
| Real issue titles | `"Example issue title"` |
| Repo URLs | `github.com/my-org/some-repo` |
| Tax IDs, KBO, VAT numbers | omit or use `0000000000` |
| Engagement-specific labels | `bug`, `feature`, `enhancement` |
| Infrastructure names (KeyVaults, Function Apps, RG) | omit entirely |
| Absolute user paths | `~/Developer/<repo>/...` or `${projects_root}/...` |
| Phone numbers | `+1-555-0100` (documentation reserved range) |
| Email addresses | `alice@example.com`, `bob@example.org` |

## See also

- `rules/operations.md` — CORE/USER path allowlist (separate
  layer; works together with this rule, not instead of it)
- `skills/bridge-promote/SKILL.md` — backs the `/promote` and
  `/contribute` commands that trigger this rule (and the same rule
  applies to upstream PRs)
