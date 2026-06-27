---
summary: Architecture and current-state review of open-bridge — components, strengths, gaps, and actionable improvements.
type: analysis
last_updated: 2026-06-27
related:
  - AGENTS.md
  - README.md
  - docs/structure.md
  - docs/extension-model.md
---

# open-bridge — Architecture & Current-State Review

Scope of this review: the actual files in this repository as of 2026-06-27, on
branch `bridge/open-bridge-analyze/PVTI_lADOB6Rsr84BbzHOzgxAYjI`. Claims below are
tied to real paths. Where something is uncertain or unverified, it is marked as
such. No adoption or performance claims are made — the project itself states it has
zero external users (`README.md:7`, `README.md:134`).

---

## 1. What it is and what it is for

open-bridge is a **git repository of markdown and YAML that an AI coding agent reads
at the start of every session** to gain persistent, structured context about a user's
world — who they are, their repos and clients, their conventions, and what they worked
on previously. The substrate "runs nothing": there is no database, daemon, or hosted
service; the artifacts are plain text the agent reads and writes (`README.md:34-42`).

The operating manual for the agent is **`AGENTS.md`** (~650 lines, the canonical
tool-agnostic instruction file), with `CLAUDE.md` and `GEMINI.md` as thin wrappers that
`@`-import it. The repo positions itself as the public, MIT-licensed **CORE** layer of a
larger tiered system, where private forks add org/user overlays (`AGENTS.md` § Tier Model;
`docs/extension-model.md`).

Two framing claims drive the design (`README.md:46-63`):

- **"Context Booster"** — an always-read context layer independent of model/frontend.
- **"Chaos Tamer"** — a shipped task/log/board structure so users don't reinvent it.

The README is unusually candid about maturity: it separates **PROVEN** (built and
self-used, N=1), **BET** (falsifiable wagers), and **OPEN** (unsolved) items
(`README.md:132-155`). That honesty is itself a notable property of the project and is
respected throughout this review.

---

## 2. Main components and how they fit

### 2.1 Session-start gate (the control-flow spine)

Every session begins with a **Phase 0** detection gate defined in
`rules/session-start.md`. It detects the repo's default branch **live** (a `gh` →
`git symbolic-ref` → `init.defaultBranch` → `main` fallback cascade,
`rules/session-start.md:31-43`), then routes on `{current branch × user/* branch ×
bridge-config.yaml presence}` into states: NEW USER, WRONG BRANCH, ORPHAN, BROKEN
CONFIG, NORMAL, CORE DEV MODE (`rules/session-start.md:56-65`). The rule documents a
real past misfire (a stale `refs/remotes/origin/HEAD` landed a PR on the wrong branch,
`2026-05-01`) as justification for live detection. A deterministic backstop hook exists
at `.claude/hooks/session-start-phase0.sh`.

This gate is the load-bearing mechanism — much of the system's behavior depends on it
running first and correctly.

### 2.2 CORE/USER split (the data model)

Two branches with **disjoint paths**: CORE templates/skills/docs on the default branch
(`main`), user instance data on `user/{name}`. Because paths don't overlap, upstream
merges are conflict-free by construction (`README.md:166-174`, `docs/structure.md`).
Tier (`core`/`org`/`user`) is **structural, not declarative** — decided by location
(`AGENTS.md` § Scope): whole-folder rules, `_`-prefix for templates/schemas inside the
three cluster-wrappers, and frontmatter `metadata.scope` for the (un-folderable) skills.

### 2.3 Three cluster-wrappers (the config layout)

Config lives under `identity/` (WHO/to-WHOM), `infra/` (WHERE/HOW), and `workflow/`
(WHAT-when), each type in a plural folder with `_template.yaml` + optional `_schema.yaml`
+ instances (`AGENTS.md` § Layout). The repo ships the schemas/templates only; the
verified template set includes personas, mandants, accounts, contracts, agent identity,
channels, remotes, backups, instances, calendars, contexts, and projects (all present
under `identity/`, `infra/`, `workflow/`).

### 2.4 Skills (the verbs) — 29 skills

Skills live flat under `skills/<name>/SKILL.md` (+ `references/`), discovered via
committed symlinks (`.claude/skills`, `.agents/skills`, `.github/skills` → `skills/`).
All 29 SKILL.md files declare `metadata.scope: core` (per the AGENTS.md scope table),
consistent with this
being the OSS CORE layer. SKILL.md is a thin router; depth lives in `references/`. The
heaviest are `bridge-onboard` (SKILL.md ~180 lines + ~2.3k lines of references) and
`debrief` (~75 + ~1.4k). None are empty stubs; `onboard-sim` and `knowledge-repo-init`
deliberately have no `references/` dir (they dispatch to `assets/` scripts and
`docs/examples/` respectively).

### 2.5 Standing orders, sub-agents, themes

- **Standing orders** (`protocols/standing-orders/*.md`) are always-on rules injected
  into dispatches — 8 shipped order files (task-sync, board-task-criteria,
  drift-advisory, document-work, code-standards, security-baseline, feature-discovery,
  work-board-reconciliation), alongside `_template.md` and `README.md`.
- **Sub-agents** are Claude-Code-specific (`.claude/agents/*.md`); CORE ships exactly one
  reference agent (`archivist.md`). On other tools the logic runs inline.
- **Themes** (`themes/`) control vocabulary only — `professional` (en) and
  `professional-de` (de); resolution rules in `rules/theme.md`.

### 2.6 Task-Management system (`work/`)

KIND is the folder (`work/tasks/` finite, `work/streams/` long-runners,
`work/done/YYYY-MM/` closed); status is a CI-validated enum
(`backlog|doing|review|done`); `board.md` is **generated** from the task dirs by
`scripts/gen-board.py`, never hand-curated (`AGENTS.md` § Task Management). Activation is
config-gated by `work.enabled` in `bridge-config.yaml`.

### 2.7 Scripts (the tooling, `scripts/`)

Two tiers, with materially different maturity:

- **Validators / guards** (focused, mostly CI-wired): `validate-bridge.py` (296 ln),
  `validate-ecosystem.py` (254 ln), `validate-skill-scope.py` (145 ln),
  `no-scrub-leak.py` (232 ln, PII/leak gate), `categorize-commits.py` (228 ln, promote
  routing), `gen-board.py` (147 ln), `scaffold-user.sh` (156 ln), and the
  security-critical `hooks/pre-push` (206 ln).
- **Generators / visualizers** (large, untested, partly orphaned):
  `generate-bridge.py` (~1744 ln), `bridge-dashboard.py` (~1136 ln),
  `extract-bridge-state.py` (302 ln), `verify-constellation-links.py` (279 ln),
  `system-discovery.py` (686 ln), `tracker-sync.py` (749 ln).

### 2.8 Safety surface (CI + hooks)

`.github/workflows/validate.yml` runs yamllint, schema validation, the content-leak
scan, skill-scope/AGENTS.md sync, frontmatter checks, a "no PII personas / no active
agent instances on core" guard, a public-repo leak-roster guard, and an
**onboarding-safety job** (`test-push-guard.sh` + `test-system-discovery.sh` + a
model-free `onboard-sim` leak simulation). Pre-commit (`.pre-commit-config.yaml`)
mirrors the four core validators plus yamllint.

The **`pre-push` guard** (`scripts/hooks/pre-push`) is the standout safety component: it
classifies a push target as private/public/unknown (offline-first, from a built-in list +
`bridge-config.yaml` `push_guard.*` + a `.bridge-origin` marker, escalating to
`gh repo view` only when still unknown), and **fails closed** — blocking `user/*`
destinations and USER-content commits to public *or* unverifiable remotes, while allowing
CORE-clean pushes everywhere. It keys on the fully-qualified `remote_ref` (not the local
ref) and inspects pushed commits rather than the working tree — both noted in-file as
fixes for real prior leak vectors.

---

## 3. Strengths (assertable from the files)

1. **Structure is enforced, not just documented.** Tier-by-location plus CI/pre-commit
   validators (`validate-skill-scope.py` regenerates the SKILL-SCOPE table in `AGENTS.md`;
   `validate-bridge.py` schema-checks every config surface) make several invariants
   load-bearing instead of aspirational.

2. **The privacy/leak surface is genuinely defended in depth.** Behavioral rules
   (`rules/push-guard.md`), a deterministic `pre-push` hook, a content-leak scanner
   (`no-scrub-leak.py`), CI personas/agent-instance guards, and a model-free
   `onboard-sim` end-to-end leak test. `test-push-guard.sh` (179 ln) is the most thorough
   test in the repo and encodes specific regressions (HEAD/sha/detached pushes, fail-closed
   on unknown remotes).

3. **Tool-agnostic by construction.** A single `skills/` tree reached via committed
   symlinks, an `AGENTS.md` convention readable by multiple runtimes, and an explicit
   Tool Mapping table. The cross-tool claim is structural, though only Claude Code is
   described as fully tested (`README.md:277`).

4. **Honest self-assessment.** The PROVEN/BET/OPEN split (`README.md:132-155`) and
   N=1 framing are rare and reduce the risk of over-promising.

5. **Conflict-free upgrade path.** The disjoint-path CORE/USER model is a clean answer
   to "how do shared templates update without clobbering private data."

6. **A complete worked example ships in-repo.** `examples/agency/` is a full two-client
   configuration (identity, infra, workflow, standing orders, populated `work/`), which
   materially lowers the "empty fresh clone" cold-start problem for readers.

---

## 4. Gaps, risks, and inconsistencies (actually found)

### 4.1 Documentation/registry drift

- **`onboard-sim` is missing from the human-readable skill index in `AGENTS.md`**
  (the grouped "Skills (Universal)" table lists 28 skills) while it *is* present in the
  auto-generated SKILL-SCOPE table (all 29) and in the runtime skill list. The curated
  index and the generated table disagree by exactly one skill. The generated table is
  kept honest by a validator; the hand-curated group table is not.

- **Broken cross-reference:** `bridge-config.yaml.template:276` points to
  `docs/agent-spawning.md`, which does not exist in `docs/`. (`docs/work-system.md`,
  referenced elsewhere as "if present", *does* exist.) The repo ships a `bridge-audit`
  skill specifically to catch broken cross-refs; this one is currently live.

### 4.2 Stale assumptions in the generator/visualizer scripts

Two scripts contradict the project's own "default branch is detected LIVE, never
hardcoded" doctrine:

- `scripts/extract-bridge-state.py` hardcodes `development` as the core branch and
  `user/user` as the user branch (`extract-bridge-state.py:36,39,272`).
- `scripts/verify-constellation-links.py` hardcodes `USER_BRANCH = "user/your-name"`.

Both also appear to be **orphaned**: a repo-wide search finds no skill, doc, or CI step
that invokes either. `extract-bridge-state.py` is described in-file as feeding a "v3
live-reload" visualization that is not wired up, and `verify-constellation-links.py`
regex-scrapes JS node objects out of an HTML file that is "rendered on demand, not
committed" (it no-ops when absent). These read as unmaintained surface area.

### 4.3 Test coverage is concentrated, not broad

Of ~15 scripts, **4 have dedicated test harnesses** (`test-push-guard.sh`,
`test-system-discovery.sh`, `test-validate-ecosystem.sh`, `test-tracker-sync.sh`).
Untested includes two **correctness/security-load-bearing** scripts:

- `no-scrub-leak.py` — the PII/leak gate (CI runs it, but it has no fixture test
  asserting it *catches* known-bad inputs and *passes* known-good ones).
- `categorize-commits.py` — the promote-routing classifier, which self-admits drift risk
  ("Keep in sync with operations.md — manual, no automated drift check yet"). A
  miscategorization here is a leak vector, and it has no test.

Additionally, `tracker-sync.py` *has* a test harness (`test-tracker-sync.sh`) that CI
does **not** invoke — tests that nothing runs automatically.

### 4.4 Duplicated, fragile parsing

- **Frontmatter/YAML parsing is reimplemented ~5 times** at differing rigor: a canonical
  PyYAML extractor (`extract-frontmatter.py`) exists, but `gen-board.py` (hand-rolled
  regex, "no PyYAML dep"), `extract-bridge-state.py` (naive `split(":",1)`),
  `generate-bridge.py`/`tracker-sync.py` (regex/`split("---")`), and the `pre-push` hook
  (awk/sed) each roll their own. Most scripts do not reuse the canonical one.
- The `pre-push` hook's hand-rolled YAML parsing is inherently fragile, but it is at least
  well-covered by `test-push-guard.sh` — an acceptable trade given the offline-first,
  dependency-free constraint.
- **Inconsistent PyYAML posture:** some scripts hard-`import yaml` (crash if absent),
  some degrade gracefully with an install hint, some deliberately avoid it. No single
  convention.

### 4.5 Two large, untested, overlapping generators

`generate-bridge.py` (~1744 ln) and `bridge-dashboard.py` (~1136 ln) each embed a full
HTML/CSS/JS app as a Python triple-quoted string, share intent (read every repo source →
emit a single-file dashboard), and duplicate collection/parsing helpers between each
other and `extract-bridge-state.py`. Neither has tests or CI. This is the highest
drift-risk concentration in the codebase.

### 4.6 Inherent (acknowledged) product risks

These are stated in `README.md` and are not defects so much as open questions:

- **Thin first-session value** until `work/log.md` accumulates real history
  (`README.md:152`). The value proposition is compounding, so a fresh clone under-rewards.
- **Workspace separation — the headline "Chaos Tamer" isolation default — is not built**
  yet; the README explicitly flags it as roadmap, not shipped (`README.md:64`,
  `README.md:146-151`).
- **Cross-tool support is largely unverified** beyond Claude Code (`README.md:277`).
- **Behavioral, not sandboxed, guardrails.** Most safety properties ("propose then
  confirm", per-action gates) are conventions the agent is instructed to follow, not
  OS-level enforcement (`README.md:237`). The `pre-push` hook is the main exception.

---

## 5. Actionable improvements

1. **Add `onboard-sim` to the `AGENTS.md` grouped skill index** and, more
   durably, extend `validate-skill-scope.py` (or `bridge-audit`) to assert that *every*
   skill in the generated SKILL-SCOPE table also appears in the human group table. This
   turns the one drift you have now into a class of drift CI catches.

2. **Fix or remove the `docs/agent-spawning.md` reference.** Either author the doc (the
   config block at `bridge-config.yaml.template:274-289` already describes the model and
   would seed it) or repoint the comment to an existing doc. Then add a link-checker step
   so dangling `docs/*.md` references fail CI — the `bridge-audit` skill already conceives
   of this check; promote it into automation.

3. **Add fixture tests for the two load-bearing-but-untested scripts.**
   `no-scrub-leak.py` should have a known-bad/known-good corpus proving it catches PII and
   passes governance allowlists; `categorize-commits.py` should have a table-driven test
   pinning core/org/user/mixed classification against `rules/operations.md`. These are
   leak-adjacent and currently rest on manual discipline.

4. **Decide the fate of the orphaned scripts.** Either wire `extract-bridge-state.py` and
   `verify-constellation-links.py` into a skill/CI and fix their hardcoded
   `development` / `user/user` / `user/your-name` branch assumptions to use the live
   detection the project mandates, or delete them. Dead code that contradicts the
   documented branch model is a maintenance trap and a misleading example.

5. **Extract one shared frontmatter/YAML helper and adopt it.** `extract-frontmatter.py`
   already is the canonical parser; have `gen-board.py`, `extract-bridge-state.py`, and
   the generators import it (where the stdlib-only constraint permits). Document the
   PyYAML-vs-stdlib policy explicitly so each script's choice is intentional.

6. **Consolidate the two HTML generators or add a smoke test.** `generate-bridge.py` and
   `bridge-dashboard.py` should at minimum share their collection helpers; better, a CI
   smoke test that runs each against `examples/agency/` and asserts non-empty,
   well-formed HTML output would catch the silent breakage their size + zero-coverage
   invites.

7. **Wire the existing-but-unrun tests into CI.** `test-tracker-sync.sh` exists and
   passes locally but is not in `validate.yml`. Adding it (and any future
   `scripts/tests/*.sh`) closes the gap between "test written" and "test enforced" — a
   glob-driven CI step over `scripts/tests/` would make this self-maintaining.

8. **Close the thin-first-session gap with a guided seed.** Since the README itself names
   cold-start as a top OPEN risk, consider an onboarding option that imports
   `examples/agency/` as a populated demo workspace (clearly marked, reversible) so a new
   user sees the compounding-value shape before they've logged anything — turning the
   already-shipped example into first-run value rather than just documentation.

---

## 6. Summary

open-bridge is a coherent, deliberately plain-text agent-context substrate whose strongest
engineering is in its **invariant enforcement** (tier-by-location + validators) and its
**leak-prevention surface** (the fail-closed `pre-push` guard, content scanner, and
model-free onboarding leak sim). Its honest PROVEN/BET/OPEN framing accurately reflects an
N=1, newly-public project.

The weak points are concentrated and addressable: a small amount of doc/registry drift
(`onboard-sim` index gap, a dangling `docs/` link), a generator/visualizer script tier
that is large, untested, partly orphaned, and carries stale branch assumptions that
contradict the project's own live-detection doctrine, and gaps in test coverage on two
leak-adjacent scripts. None of these undermine the core design; all are tractable with the
validation machinery the project already favors.
