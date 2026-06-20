# /contribute — Upstream Contribution Assistant

Scans your user branch for files worth contributing to one of the upstream
repos, classifies them by `scope:` (which destination), runs adaptation
where needed, and submits PRs.

Three destinations:
- `bks-lab/open-bridge:main` — generic CORE (scope: core, MIT, public OSS)
- `<your-org>/<your-bridge>:development` — your org overlay (scope: org)
- stays local — personal (scope: user / private)

Architecture: see CLAUDE.md § Tier Model.

## Usage

```
/contribute              — scan and categorize all contributable files
/contribute {path}       — analyze a specific file or directory
/contribute --adapt      — generalize org-specific content before contributing
/contribute --repo open-bridge   — only consider open-bridge candidates
/contribute --repo <your-bridge> — only consider org-overlay candidates
```

## Trigger

`/contribute`, `/contribute {path}`, `/contribute --adapt`, `/contribute --repo <name>`

## Prerequisites

- Current branch must be `user/*`. Refuses on `development` or `main`.
- `bridge-config.yaml.upstreams[]` defines the available targets. The
  template ships `bks-lab/open-bridge` as the shared OSS upstream with
  `contribute: true` — every clone can contribute there out of the box.
- For PR submission: `gh` CLI authenticated. **No push access to the
  upstream is needed or assumed** — external contributors cannot push
  branches to `bks-lab/open-bridge`. The skill works fork-based:
  `gh repo fork` creates (or reuses) your personal fork of the upstream,
  the contribution branch is pushed there, and the PR is opened
  cross-fork via `gh pr create --repo bks-lab/open-bridge`. Your org
  overlay (if configured) is typically reachable directly as the
  `upstream` remote.
- **Content-safety roster**: before your first contribution, put your
  own sensitive identifiers (customer names, client codenames,
  third-party person names) into `scripts/leak-patterns-internal.txt`
  (one `<class-id> <regex>` per line; the file is local-only and never
  shipped). The shipped scanner only knows universal classes (absolute
  user paths, key/token shapes) — it cannot know YOUR customers. An
  empty roster means the gate is blind to them.

## Workflow

### Step 1: Scan paths on user branch

Find files that exist on user/ but not on development, AND CORE files that were modified:

```bash
# Detect this repo's core/default branch live — never hardcode `development`
# (open-bridge's core is `main`; see skills/bridge-promote/references/workflow.md
# § Default-branch asymmetry).
CORE_BRANCH=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name 2>/dev/null \
  || git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||' \
  || echo main)
# New files on user/, plus modified files in CORE-allowlist + Org-overlay paths
git diff --name-only "${CORE_BRANCH}..HEAD" -- \
  protocols/ rules/ themes/ docs/ examples/ \
  .claude/agents/ \
  skills/ identity/personas/_template.yaml identity/personas/_schema.yaml \
  identity/mandants/_template.yaml identity/mandants/_schema.yaml \
  infra/{remotes,channels,backups}/_template.yaml \
  workflow/{calendars,contexts}/_template.yaml \
  workflow/context.{customer-a,doc-system}.yaml ecosystem.yaml \
  CLAUDE.md README.md AGENTS.md CONTRIBUTING.md
```

If `{path}` argument is provided, restrict the scan to that path only.

### Step 2: Categorize each file by scope

For each file found, determine destination:

1. **Read frontmatter** if it's a `.md` file under `skills/` or `.claude/agents/`:
   - `scope: core` (or unset) → candidate for **open-bridge**
   - `scope: org`            → candidate for **your org overlay**
   - `scope: user`/`private` → not contributable

2. **Path inference** for raw config files (rules/operations.md § CORE/USER):
   - `rules/`, `themes/`, `docs/` (except tier-model/public-release-cleanup) → **open-bridge**
   - `ecosystem.yaml`, `workflow/context.{customer-a,doc-system}.yaml`, Org-overlay → **your org overlay**
   - `bridge-config.yaml`, persona/mandant/calendar instances → **not contributable**

### Step 3: Per-destination content-safety classification (MANDATORY)

This step is a **hard gate** — no PR is created until it passes for the
exact set of files being sent.

**3a. Leak scanner over the outgoing files** — always, before anything
else:

```bash
# Scan exactly the files that would land in the PR.
# Loads universal classes (abs paths, key/token shapes) PLUS your own
# roster from scripts/leak-patterns-internal.txt if present.
python3 scripts/no-scrub-leak.py {files-to-contribute}
```

Exit code 1 = hits. Make sure your roster file
(`scripts/leak-patterns-internal.txt`) carries your customer/person
patterns — see Prerequisites. If it is missing or empty, warn the user
once: "leak roster is empty — scanner only checks universal patterns;
add your customer/PII regexes before contributing."

**3b. Blocklist scan** from `rules/promote-safety.md`, **per destination**:

```bash
PROMOTE_REPO=open-bridge bash -c '<scan>'   # for open-bridge candidates
PROMOTE_REPO=<your-bridge> bash -c '<scan>' # for org-overlay candidates
```

**REFUSE path:** if 3a or 3b reports a hit classified as personal-PII or
customer/roster content, the skill **refuses to create the PR** for the
affected files — no override flag, no "it's just an example"
rationalization (`rules/promote-safety.md § anti-rationalization`).
Options offered instead:

```
🔴 Content-safety gate FAILED for 2 file(s):
   [customer-name] rules/my-new-rule.md:14
   [abs-user-path] skills/foo/SKILL.md:88

   These files will NOT be contributed.
   [d] Adapt now (/contribute --adapt — neutralize, then re-scan)
   [x] Drop them from this contribution (continue with clean files)
   [n] Abort entirely
```

After adaptation, **re-run 3a + 3b** — only a clean re-scan unblocks the
file. Clean files in the same batch still ship.

For each file, mark:

**Ready** ✓ — no blocklist hits, no absolute paths, no theme-specific terms, frontmatter complete

**Needs adaptation** ⚠ — has org-specific refs that could be generalized:
- `BigCorp` → `{client}` (open-bridge), or kept as-is (org overlay if known customer)
- Absolute paths → `${variables}`
- Theme-specific terms → neutral wording (no "Captain"/"Lead" vocabulary in CORE files)
- Tool-specific refs (e.g. "PagerDuty") → generic ("alerting platform") for open-bridge

**Not contributable** ✗ — personal data, credentials, USER-only paths, blocklist hits even after adaptation

### Step 4: Present routing matrix

```
Contribution Analysis

  open-bridge candidates (scope:core, public OSS):
   ✓ protocols/standing-orders/health-check.md  NEW standing order (health-check rule)
   ✓ themes/consulting.yaml             NEW theme (management consulting)
   ⚠ .claude/agents/sre-on-call.md       References "PagerDuty" → adapt
   ⚠ rules/your-new-rule.md              Contains "BigCorp" → adapt to "{client}"

  org-overlay candidates (scope:org, org-internal):
   ✓ skills/{customer}-coordinator/SKILL.md  Updated dispatch logic
   ✓ workflow/contexts/doc-system.yaml         Adjusted destinations

  Not contributable (stays local):
     bridge-config.yaml                  USER config
     identity/personas/{user}-org.yaml   USER persona

  Routing:
    → bks-lab/open-bridge   (4 candidates: 2 ready, 2 need adapt)
    → <your-org>/<your-bridge>   (2 candidates: 2 ready)

  [a]  Contribute all ready items (per repo)
  [s]  Select items individually
  [d]  Adapt items first (generalize org refs)
  [r]  Force one repo only (--repo override)
  [n]  Not now
```

### Step 5: Contribute

For selected items, per destination:

1. Cherry-pick (or path-selectively re-apply) the relevant commits onto a
   fresh branch based on the **upstream's** default branch
2. Push the branch to a repo you can write to — for open-bridge that is
   **your personal fork of `bks-lab/open-bridge`** (never `origin`, which
   is your Bridge instance, not a fork of the upstream)
3. Create the cross-fork PR with `gh pr create --repo`

**PR to open-bridge — fork flow** (external contributors have no push
access to `bks-lab/open-bridge`; DCO sign-off required):

```bash
# 0. One-time: create (or reuse) your fork of the OSS upstream.
#    --clone=false: we only need the remote, not a second working copy.
gh repo fork bks-lab/open-bridge --clone=false
git remote add ob-fork git@github.com:{your-username}/open-bridge.git 2>/dev/null || true

# 1. Branch from the UPSTREAM's default branch (main — never your
#    instance's development; histories may be disjoint).
git fetch git@github.com:bks-lab/open-bridge.git main:refs/remotes/open-bridge/main
git checkout -b contrib-open-bridge-$(date +%Y%m%d) open-bridge/main
git cherry-pick {hashes-with-scope-core}      # or path-selective re-apply, see skills/bridge-promote/references/workflow.md § Step 5 Mode B

# 2. DCO: every commit must be signed off (-s). Amend any that aren't:
git commit --amend -s --no-edit               # repeat / rebase --signoff for multiple commits

# 3. Final gate: re-run the leak scanner on the branch's outgoing files
python3 scripts/no-scrub-leak.py $(git diff --name-only open-bridge/main..HEAD)

# 4. Push to YOUR FORK, then open the cross-fork PR
git push ob-fork contrib-open-bridge-$(date +%Y%m%d)

gh pr create --repo bks-lab/open-bridge \
  --base main \
  --head {your-username}:contrib-open-bridge-$(date +%Y%m%d) \
  --title "{summary}" \
  --body "$(cat <<'EOF'
## Contribution

{list of contributed files with one-line descriptions}

## Why

{one sentence per file explaining usefulness}

## Checklist

- [x] No absolute paths (uses ${variables})
- [x] No secrets or credentials
- [x] No org-specific terms (generalized via /contribute --adapt)
- [x] Leak scanner clean (`scripts/no-scrub-leak.py` incl. own roster)
- [x] Theme-compatible (uses role IDs, not themed vocabulary)
- [x] YAML frontmatter has required fields
- [x] DCO sign-off on all commits (`git commit -s`)
EOF
)"
```

**PR to your org overlay** (no DCO required, customer refs OK):

```bash
git checkout -b contrib-org-$(date +%Y%m%d) upstream/development
git cherry-pick {hashes-with-scope-org}
git push origin contrib-org-$(date +%Y%m%d)

gh pr create --repo <your-org>/<your-bridge> \
  --base development \
  --head {your-username}:contrib-org-$(date +%Y%m%d) \
  --title "{summary}" \
  --body "Updates to Org-internal overlay. Commits: {list}"
```

Show PR URLs on success.

### Step 6: Adapt mode (--adapt)

When a file needs adaptation (or user runs `/contribute --adapt`):

1. Read the file
2. Identify the destination's blocklist (`promote.content_blocklist.<repo>` from `bridge-config.yaml`)
3. Identify org-specific terms (names, tools, URLs, paths)
4. Replace with generic placeholders **per destination**:
   - For open-bridge: aggressive — all customer/personal/Org refs → `{placeholder}`
   - For your org overlay: light — only personal PII → `{placeholder}`, customer refs stay
5. Show diff of proposed changes
6. User confirms before applying

After adaptation, re-run categorization — adapted files should now appear as Ready.

## Relationship to /promote

| | /promote | /contribute |
|---|---|---|
| **Purpose** | cherry-pick commits to local development + push | scan files, classify by readiness, adapt, submit PR |
| **Scope** | commit-level (whole commits move) | file-level (cherry-picks subsets per file) |
| **Adaptation** | none (commits go as-is) | yes (`--adapt`) |
| **PR creation** | optional (Step 7) | always (Step 5) |
| **Scope routing** | per commit `scope:` | per file `scope:` |

`/promote` is the lightweight workflow when you have clean per-commit
scope-discipline. `/contribute` is the heavyweight workflow when you
have a mixed user branch with content that needs adaptation before
upstream submission.
