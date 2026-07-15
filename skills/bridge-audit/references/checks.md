# Bridge Audit — Check Implementation

Per-check algorithms (overview table + arguments live in SKILL.md). Severity:
`P0` broken state · `P1` visible drift · `P2` cleanup · `P3` cosmetic.
Scan tracked files only (`git ls-files`); findings are advisory unless `--fix` rules at the end apply.

---

## Check 1 — License consistency

**Sources to read:**
- `README.md`: shields.io License badge (regex `License%3A-([A-Za-z0-9.+-]+)`) + footer line near end (`Apache 2.0 — see LICENSE`, `MIT — see LICENSE`)
- `LICENSE`: first 3 lines (Apache header / MIT header)
- `CLAUDE.md`: any "License: " claim
- `~/.claude/projects/*/memory/MEMORY.md` (if available): any `MIT`/`Apache`/`license` mention

**Algorithm:**
1. Extract license-name from each source
2. Group by source. Disagreement → P0 finding.
3. Fix proposal: pick the source-of-truth (memory / CLAUDE.md if present and recent), align the others.

**Edge cases:**
- LICENSE missing → P0 finding (not a drift, but bad).
- README has no badge but has footer → use footer alone.

---

## Check 2 — Skill-tree truth

**Sources:**
- `skills/*/SKILL.md` — directory listing + `name:` frontmatter, `scope:` frontmatter
- `README.md` — directory tree block (`├── skills/` … `└──` lines) + any skill table in body
- `AGENTS.md` — skill table

**Algorithm:**
1. Build truth set: `actual = set(directory listing of skills/)`
2. Build claim sets: `readme_claimed`, `agents_claimed`
3. Findings:
   - **Dead refs:** in claim, not in actual → P1 ("README mentions `<name>/` — does not exist")
   - **Missing:** in actual, not in any claim (with scope `core` only — org/user can be omitted) → P2
   - **Frontmatter mismatch:** SKILL.md `name:` != directory name → P1

---

## Check 3 — Standing-order count

**Sources:**
- `protocols/standing-orders/*.md` (excluding `_template.md`, `README.md`)
- All Markdown files: any line matching `\b(\d+)\s+(?:standing[- ]orders?)\b`

**Algorithm:**
1. `actual = count(protocols/standing-orders/*.md non-template, non-README)`
2. For each match in step 2, compare. Disagreement → P1.
3. Fix proposal: prefer "Standing orders" without a number — drift-resistant.

---

## Check 4 — Renamed-everywhere

**Sources:**
- `data/renames.yaml` — list of `{ old, new, exceptions: [paths] }`
- `git ls-files` content

**Algorithm:**
1. For each rename: `git grep -n -F "$old" -- $(git ls-files) | grep -v '^binary'`
2. Skip hits in files listed in `exceptions:` for that rename
3. Skip hits inside YAML frontmatter `aliases:` arrays (those are intentional)
4. Each remaining hit → P1 finding with line + suggested replacement

**Why exceptions matter:** intentional old-name mentions (e.g. backwards-compat
alias triggers in a SKILL.md) would otherwise stay flagged forever.

---

## Check 5 — Cross-reference validity

**Sources:**
- All `*.md` files
- All `*.yaml` files with `path:` / `config:` fields

**Algorithm:**
1. Extract patterns:
   - Markdown link: `\[[^\]]+\]\(([^)]+)\)` (skip http/https/mailto)
   - Code-fenced path-like: `` `([a-z][a-z0-9_./-]+\.(md|yaml|yml|py|sh|json))` ``
   - YAML `path:` / `config:` values
2. Resolve relative to file's directory
3. Stat the result. Missing → P2 finding.

**Edge cases:**
- Anchor links (`#section`) — skip the anchor portion, check the file
- Glob patterns (`workflow/projects/<slug>.yaml`) — skip if contains `<` or `*`
- External URLs — skip

---

## Check 6 — Scope coverage (frontmatter + schema-backed instances)

**Sources — two groups, different severity:**

*Group A — markdown frontmatter:*
- `skills/*/SKILL.md` frontmatter — scope under `metadata:` (`metadata.scope`,
  optional, defaults to `core`). It nests there because skill-creator's
  validator forbids non-standard top-level keys.
- `.claude/agents/*.md` frontmatter (top-level `scope:`, optional, defaults to `core`)
- `rules/*.md` frontmatter — scope **REQUIRED**, hard-gated by
  `scripts/validate-bridge.py --surface rules` in pre-commit + CI. Rules are
  **tiered by FOLDER** (`rules/*.md` = core · `rules/org/**` = org ·
  `rules/user/**` = user); the folder is the promote tier, so the frontmatter
  `scope:` MUST match the folder. **Flag a mismatch** → **P1** (mis-routed —
  a wrong top-level core would leak an org rule to the OSS upstream). Also
  flag a skill whose `metadata.scope` is missing/invalid (already hard-gated
  by `scripts/validate-skill-scope.py` in pre-commit + CI).

*Group B — cluster-wrapper YAML instances (scope is a REQUIRED schema field):*
- `identity/{mandants,accounts,personas}/*.yaml` ·
  `workflow/{contexts,projects}/*.yaml` · `infra/{remotes,channels}/*.yaml`
- Skip `_`-prefixed files (`_schema.yaml`, `_template.yaml`) and `*.template`.
- `infra/remotes` + `infra/channels` are single-tier local — always
  `user`/`private` — but the scope field is still schema-required as a
  promote tripwire. `infra/backups/` has no `_schema.yaml` yet; when one
  is authored, add it here.

**Algorithm:**
1. For each Group-A file: check if `scope:` is present in frontmatter
   (for `skills/*/SKILL.md` look under `metadata.scope`; for `.claude/agents/*.md`
   look top-level).
   - Missing on `skills/` / `.claude/agents/` → **P2** ("scope: core implied, but explicit is better")
   - Missing on `rules/*.md` → **P1** (leak risk — already hard-failed by `validate-bridge.py`)
2. For each Group-B instance: check if top-level `scope:` is present.
   - Missing → **P1** ("scope is a required schema field — `check-jsonschema`
     fails AND `/promote` cannot route it; this is the mandant mis-routing
     class"). Fix: add `scope:` with the correct tier.
3. For ALL files: if `scope:` is something other than the generic tiers
   `core | org | user | private` (plus any org-aliases configured in
   `bridge-config.yaml` `promote.scopes.org_aliases`, i.e. the org's short
   tag) → **P1** ("unknown scope value").
4. Group-B sanity tier rules (advisory P2 — flag, don't hard-fail):
   - a mandant / account / persona / context / project tagged `core` or
     `org` is suspect (these carry PII / customer data) → flag for review.

**Why:** explicit `scope:` is what `/promote` and `/bridge-sync` route on —
a missing Group-B scope means the config silently fails to route. Confirm via
`check-jsonschema --schemafile <wrapper>/<type>/_schema.yaml <wrapper>/<type>/*.yaml`.

**Do NOT conflate** with `protocols/standing-orders/*.md`, whose `scope:`
field means standing-order applicability (`always | per-repo |
per-context`), not scope routing — those are out of scope for Check 6.

---

## Check 7 — Routing-SoT conflicts

**Sources:**
- All `*.md` files: tables with header containing "Source of Truth" or "SoT" or "Resolved by"
- `rules/operations.md`, `docs/extension-model.md`, `docs/structure.md` (high-yield files)

**Algorithm:**
1. Parse each routing-table row: `(domain, sot_path, resolver_skill)`
2. Group by `(domain, sot_path)` across files
3. If the same `(domain, sot_path)` appears with different `resolver_skill` or different routing rule → P2 finding
4. If the same `domain` has different `sot_path` claimants → P1 finding

---

## Check 8 — Typo lint

**Sources:**
- `data/typo-patterns.yaml` — list of `{ pattern, suggestion }`
- All tracked `*.md` and `*.yaml` files

**Algorithm:**
1. For each pattern: `git grep -n -E "$pattern"`
2. Each hit → P3 finding with suggestion

The pattern list ships in `data/typo-patterns.yaml` — read it there, don't
duplicate it here.

---

## Check 9 — Cross-repo skill-tree sync coverage

Only runs with `--cross-repo`. Detects file-state drift between the
seed repo and each configured upstream that commit-based syncs miss:

- **Forward-drop:** a `scope: core` (or `scope: org`, for your org overlay)
  skill exists locally but is missing in the target's trunk
- **Reverse-leak:** a directory in the target's `skills/` is currently
  `scope: user`/`private` in the seed repo and shouldn't be there

**Sources:**
- Local: `skills/*/SKILL.md` frontmatter (current scope — under `metadata.scope`)
- Target trunks: `git ls-tree -d <upstream>/<branch> skills/` (after `git fetch`)

**Algorithm:**
1. Build local truth: `{ skill: scope }` for every `skills/*/SKILL.md`
2. For each upstream `<repo>` with allowed-scopes `<allowed>`
   (open-bridge → `{core}`, your org overlay → `{core, org}`):
   - `expected = { s for s,scope in local if scope in allowed }`
   - `actual   = ls-tree of <upstream>/<branch>:skills/`
   - `forward_drops = expected - actual` → P1 finding per skill
   - `reverse_leaks = actual - expected` → P1 finding per skill
3. For each forward-drop, identify the originating commit and whether
   it was MIXED (the common forward-drop cause):
   - `git log --diff-filter=A -- skills/<name>/SKILL.md | tail -1`
   - If the commit also touched `scope: user` paths → annotate
     "MIXED commit; sync skipped — needs per-file cherry-pick"
4. For each reverse-leak, identify when it entered the target:
   - `(cd <target>; git log -- skills/<name>/SKILL.md | tail -1)`
   - Annotate "entered <date>; current source scope: user"

**Severity:** P1 by default. P0 if a forward-drop has been outstanding
for >2 sync windows (defined as 2× the gap between most recent
`bridge-sync-*` tags) — that signals the auto-fix isn't running.

**Fix proposal:**
- Forward-drop → "Run `/bridge-sync` (Step 0 will produce a side-PR)"
- Reverse-leak → "Run `/bridge-sync` (Step 0 will produce a cleanup PR)"
- The audit never auto-applies cross-repo fixes; that stays in
  `/bridge-sync` so PR review happens through one channel.

**Separation from `bridge-leak-check`:** that skill scans file *content*
(strings + classification); Check 9 checks directory-presence + scope-policy.
Run both for independent signals on the same drift.

---

## Check 10 — Agent-identity health

Validates the `identity/agent/` layer (SOUL.md + IDENTITY.md). Always
runs — no `--cross-repo` needed.

The repo ships only the templates (`identity/agent/_template.SOUL.md` +
`_template.IDENTITY.md`); the live `SOUL.md`/`IDENTITY.md` are USER
instances seeded at onboarding (see `identity/agent/README.md`). A fresh
clone has neither file — that is the shipped state, not drift.

**What it checks:**
1. Onboarding gate: if `bridge-config.yaml` is absent (fresh clone, not
   onboarded), **skip** the existence checks — missing instance files are
   expected, no finding.
2. If onboarded (`bridge-config.yaml` exists) and `identity/agent/SOUL.md`
   or `IDENTITY.md` is missing → **P2** advisory: seed them from
   `identity/agent/_template.SOUL.md` / `_template.IDENTITY.md`.
3. (When present) SOUL.md size ≤ 80 lines AND ≤ 4 KB. Over → **P2** (loaded every session; bloat degrades signal). Report actual `wc -l` + `wc -c`.
4. (When present) Both files carry valid frontmatter: `schema_version`, `type` (soul|identity), `scope` (core|user), `last_updated`. Missing/invalid → **P2**.
5. (When present) IDENTITY.md references the active theme's `assistant_name` rather than hardcoding a name that disagrees with it → **P3** advisory on conflict.

**Commands:**
```bash
test -f bridge-config.yaml || echo "fresh clone — skip existence checks"
wc -l identity/agent/SOUL.md          # expect ≤ 80
wc -c identity/agent/SOUL.md          # expect ≤ 4096
test -f identity/agent/IDENTITY.md && echo present || echo missing
```

**Fix mode:** none — advisory only. Voice/identity content is
human-owned and never auto-edited (consistent with the propose-don't-apply
rule in `rules/learning-autonomy.md`).

---

## Check 11 — Gate-shaped memory without a `rules/` home

When a memory file's body reads like a *rule* — an imperative the agent must
always/never follow, or a "when X → do Y" routing instruction — that behavior
is trapped where only this instance can see it. It should be **promoted** to
`rules/<tier>/`, with the memory kept as dated provenance. This is the audit
backstop for `rules/knowledge-growth.md` (where new knowledge belongs).

**Sources:**
- `~/.claude/projects/*/memory/*.md` (the active memory dir for this repo;
  resolve via the harness path, skip `MEMORY.md` itself — it is the index)
- `rules/*.md`, `rules/bks/**/*.md`, `rules/user/**/*.md` — the rule corpus

**Gate-language heuristic (a memory body is "gate-shaped" if):**
1. **Imperative + scope adverb** — a directive verb (the bridge "must / always
   / never" do X) near an always/never token: `always`, `never`, `immer`,
   `nie`, `niemals`, `IMMER`, `NIE`, `stets`, `grundsätzlich`. Caps-lock
   variants count double (users tend to write hard rules in caps).
2. **Routing "when X → do Y"** — a conditional trigger mapped to an action:
   `→`, `->`, "when … then", "bei … →", "falls …", "wenn … dann". This is the
   shape of a standing-order or a skill-routing rule.
3. Plain *observations* (a one-time fact, an API quirk, a snapshot of state,
   a decision-and-why) are NOT gate-shaped — they belong in memory. The
   distinction: a gate tells the agent **what to do every time**; an
   observation records **what is/was true once**.

**Algorithm:**
1. For each memory file (excluding `MEMORY.md`): score the body against the
   gate-language heuristic. Need at least one strong signal (cap-lock
   always/never, or an explicit `→`/"when X do Y" mapping) — a lone lowercase
   "always" in prose is not enough (avoid false positives on observations).
2. If gate-shaped: search the rule corpus for a corresponding rule. Match on
   topic, not exact string — grep the memory's `name:`-slug keywords and the
   distinctive nouns (skill names, paths, vocabulary triggers) against
   `rules/**/*.md`. A rule "covers" the memory if a `rules/` file encodes the
   same imperative or routing.
3. No covering rule found → **P2** finding. The memory is a behavioral rule
   with no enforceable home.
4. Tier hint for the fix: the memory's subject decides the destination —
   generic agent behavior → `rules/<tier>/` core (English); BKS/customer
   routing → `rules/bks/`; personal/freelance → `rules/user/`. Match the
   folder-tier convention in `rules/knowledge-growth.md` § Rules are tiered
   by folder.

**Finding shape:** `P2 — memory/<file> — body is a hard gate but no rules/
file encodes it → Promote to rules/<tier>/<slug>.md (memory kept as provenance).`

**Why a P2 (not higher):** the memory still works in this instance — but the
rule never promotes and never gets enforced by a hook/CI. Drift, not breakage.

**Edge cases / what NOT to flag:**
- Memories already cross-referenced from a `rules/` file (the rule cites the
  memory as provenance) → covered, skip. This is the *intended* end-state.
- The consolidated SOUL.md/IDENTITY.md voice rules under the `MEMORY.md`
  "Consolidated into identity/agent/" banner — those have a home in
  `identity/agent/`, not `rules/`, and the banner says so. Treat
  `identity/agent/SOUL.md` + `IDENTITY.md` as valid rule-homes too.
- A memory that is genuinely an observation with an incidental "never" in
  prose (e.g. "this API never returns null on success") → not gate-shaped.

**Fix mode:** none — advisory only. Promoting a memory to a rule is a
human-authored content move (translation, tier choice, framing); the audit
only surfaces the candidate.

---

## Check 12 — Config-driven CORE skills

A `scope: core` skill ships and merges to the OSS upstream, so it must stay
generic *inside*: it reads instance specifics from config, it does not embed
them. This check flags the inverse — a CORE skill that hardcodes what should
live in `bridge-config.yaml` / `workflow/` / `infra/` / `identity/`. It is the
audit backstop for `CLAUDE.md` § Generic CORE Skills (and `docs/extension-model.md`
§ Generic CORE Skills). Distinct from `bridge-leak-check`: leak-check is
content-safety (PII / customer names → leak); Check 12 is genericity drift —
even a *non-PII* hardcode (your own org's project number baked into a core
skill) breaks upstream-mergeability and is in scope here.

**Sources:**
- `skills/*/SKILL.md` and `skills/*/references/**/*.md` where `metadata.scope`
  is `core` or absent (absent defaults to core).
- Skip non-core skills (`metadata.scope: org | user | private`) — they are
  allowed to be instance-specific.

**Hardcode heuristic — a line is a hit when it presents a CONCRETE operative
value that should be config:**
1. **Org/project/pipeline IDs** — a numeric tracker ID tied to project /
   pipeline / board / org context in operative prose (e.g. `project 18`,
   `pipeline 1234`, an ADO query GUID), as the value to use — not as an example.
2. **Embedded tracker queries** — a literal KQL / WIQL / JQL / SQL string with
   concrete index/table/project names baked in, instead of "read the query from
   `integrations.{name}.*` / `workflow/projects/<slug>.yaml`".
3. **Absolute instance paths / concrete hosts** — `/Users/<realname>/…`, a
   specific machine name, a tenant ID, as the operative path rather than a
   `${variable}` or a config-resolved path.
4. **Persona / customer / stakeholder proper names** as routing values (defer
   the PII angle to `bridge-leak-check`; flag here as a genericity hit too).

**NOT a hit (avoid false positives):**
- Placeholder tokens: `<slug>`, `<id>`, `{name}`, `<your-org>`, `acme`,
  `example.com`, and similar generic stand-ins — that *is* the generic form.
- `docs/examples/**` and any fenced block explicitly labelled as an example.
- A skill *naming the config key it reads* (e.g. "read `integrations.ado.queries`
  from `bridge-config.yaml`") — that is the correct, config-driven pattern.
- The `${variable}` interpolation forms (CLAUDE.md § Variable Interpolation).

**Algorithm:**
1. Enumerate core skills (resolve `metadata.scope`; absent → core).
2. For each `SKILL.md` + `references/**` file, scan for the four hardcode
   patterns above, excluding the NOT-a-hit set.
3. Each concrete hit → **P2** finding. Fix: move the value to
   `bridge-config.yaml` (or the matching `workflow/` / `infra/` / `identity/`
   file, plus a template/example default) and have the skill read it.

**Finding shape:** `P2 — skills/<name>/<file>:<line> — hardcoded <id|query|path|
name> in a scope:core skill → move to bridge-config.yaml (skill reads it). See
CLAUDE.md § Generic CORE Skills.`

**Why a P2 (not higher):** the skill still runs in this instance — but it has
stopped being generic, so it no longer merges cleanly upstream. Drift, not
breakage. (A genuine PII / customer hardcode is escalated separately by
`bridge-leak-check`.)

**The test:** *would this line be wrong in someone else's Bridge?* If yes, it
is instance config, not skill content.

**Fix mode:** none — advisory only. Moving a value into config is a
human-authored content move (choosing the key, adding a template default,
rewiring the read).

---

## Check 13 — User-level skill shadowing

Claude Code loads skills from the **user level** (`~/.claude/skills/`) as well as
the project level, and on a name collision the user level wins ("personal
overrides project" — [skills docs](https://code.claude.com/docs/en/skills.md)).
Every Bridge ships the same CORE skill names, so a user-level pointer at *any*
Bridge repo silently overrides other instances' own copies. There is no setting
to invert precedence and none to relocate the skills path, so the only fix is to
keep colliding names out of the user level.

This is the audit backstop for the rule in `AGENTS.md` § Skills and
[`docs/skill-distribution-architecture.md`](../../../docs/skill-distribution-architecture.md)
§ Why the user level is not a distribution channel:

> `~/.claude/skills` must not point at a Bridge repo.

**Why it needs an automated check:** the failure is silent by construction. A
shadowed instance emits *plausible* output from the wrong instance's skills —
there is no error and no symptom to search for. Nothing else in the framework
notices, and the framework is what leads users into it (`docs/multi-instance.md`
actively encourages the second instance).

**Sources:**
- `~/.claude/skills/` — the directory itself, and each entry inside it.
- `skills/*/` in this repo, with `metadata.scope` per skill.
- A path counts as "a Bridge repo" when its enclosing repo root has an
  `AGENTS.md` **and** a `skills/` directory (`bridge-config.yaml` is a further
  hint but is gitignored, so it must not be required).

**Algorithm:**
1. `~/.claude/skills` does not exist → **pass**, stop. That is the correct state
   for a machine whose skills all live in instances.
2. Resolve it — and each entry inside it — with `realpath`. The pointer may be
   the whole directory *or* per-skill symlinks inside a real directory; handle
   both.
3. Classify each resolved entry:

   **(a) Outbound — resolves into THIS repo.** This instance is the *shadower*:
   its skills are served to every other instance on the machine.
   → **P1**; escalate to **P0** for any entry whose `metadata.scope` is `org` or
   `user` — that content is instance-bound and is now loading elsewhere.

   **(b) Inbound — resolves into a DIFFERENT Bridge repo.** This instance is the
   *victim*. For every name that also exists in this repo's `skills/`:
   → **P0** — this instance's own skill never loads; the other instance's copy
   runs instead. Report `diff -rq` drift per colliding name: a drifted pair means
   this instance's own edits (including CORE fixes authored *here*) have no
   effect *here*. Also report entries with `metadata.scope` of `org` or `user`
   that are not this instance's → **P1**: another organization's context —
   including its customer names in `description:` triggers — is loaded into every
   session of this instance.

   **(c) Neither — a real directory owned by no repo** → **pass**. That is what
   the user level is *for*: skills belonging to the machine. Flag only a name
   collision with this repo's `skills/` → **P2** (it shadows, but no instance is
   leaking into another).

4. **Path consumers** — whenever any finding above fires, also report what
   resolves that path as a *filesystem location*, so the remediation does not
   trade a silent capability bug for a silent automation outage:

   ```bash
   grep -rl '\.claude/skills/' ~/bin ~/Library/LaunchAgents /etc/systemd 2>/dev/null
   ```

   → **P2** per consumer — repoint it at this instance's `skills/` *before* the
   pointer is removed. A launchd/systemd unit that can no longer resolve its
   helper fails with an exit code, not a message anyone reads.

**Finding shapes:**

```
P0 — ~/.claude/skills/<name> → <other-repo>/skills/<name> shadows this instance's
     skills/<name> (content differs) → this instance's own copy never loads.
     Remove the user-level pointer; .claude/skills → ../skills already covers it.
P0 — ~/.claude/skills → this repo's skills/ exposes <n> instance-bound skills
     (scope org or user) machine-wide → they load into every other instance's
     sessions.
P1 — ~/.claude/skills resolves into a Bridge repo (<path>) → violates AGENTS.md
     § Skills. Latent while this is the only instance; it breaks the NEXT one,
     silently. Ship standalone tools as a plugin instead.
P2 — <consumer> resolves ~/.claude/skills/<name>/... as a path → repoint at
     <repo>/skills/<name>/... before removing the pointer.
```

**Fix mode:** none — advisory only, deliberately. The remedy touches `$HOME`
outside the repo and may have live path consumers (step 4), so removing the
pointer is a human decision. State in the finding that the link must be removed
with `mv` or `rm` and **never** with a trash utility that dereferences symlinks:
following the link would move the instance's entire tracked `skills/` tree
instead of the pointer.

**The test:** *if this machine had a second Bridge tomorrow, whose skills would
run inside it?* If the answer is "this one's", the pointer is wrong.

---

## --cross-repo mode

**Prerequisites:** `bridge-config.yaml.upstreams[]` defines targets and `gh` is authenticated.

**Algorithm:**
1. For each upstream: `git clone --depth=1 --branch=$branch` into `/tmp/bridge-audit-<repo>/` (or `git fetch <upstream> <branch>` if already added as a remote)
2. Diff `README.md`, `AGENTS.md`, `CLAUDE.md`, `LICENSE` between local and each upstream
3. Findings:
   - File present in seed repo but not upstream → P2 (missing on that destination)
   - Different License/badge/footer between repos → P0 (cross-repo license drift)
   - Significant content divergence (>30 lines diff in README/AGENTS) → P2 (worth a sync)
4. Run **Check 9** (skill-tree sync coverage) against the same fetched trunks

---

## --fix mode

`--fix` only applies when the fix is **completely unambiguous** and
**single-line**; multi-line replacements always stay advisory. For everything
not marked fixable below: print the suggested fix, leave application to the user.

| Check | Fixable? | Why |
|---|---|---|
| 1 License | Footer line only (`Apache 2.0 — see LICENSE` → `MIT — see LICENSE`) | Single-line, deterministic |
| 2 Skill-tree | No | Multi-line, requires curation |
| 3 Standing-order count | Replace number with word ("8 standing orders" → "Standing orders") | Deterministic |
| 4 Renames | Yes, when not in exceptions | Whole-word grep+replace |
| 5 Xrefs | No | Could rename or remove — needs judgment |
| 6 Scope | Insert `scope: core` after `name:` line | Deterministic IF user opted in |
| 7 Routing-SoT | No | Architectural decision needed |
| 8 Typos | Single-token patterns only (e.g. `gepushtdurch` → `gepusht durch`) | Whitelist |
| 9 Skill-tree sync | No | Cross-repo mutation — defer to `/bridge-sync` Step 0 |
| 11 Memory-gate | No | Promotion needs translation + tier choice — human-authored move |
| 12 Config-driven | No | Move-to-config is a content move — advisory only |
