---
summary: Architecture and current-state review of open-bridge — components, strengths, gaps, and improvement suggestions, grounded in the repository as it stands.
type: analysis
last_updated: 2026-06-27
related:
  - AGENTS.md
  - README.md
  - docs/structure.md
  - docs/extension-model.md
  - rules/session-start.md
  - rules/push-guard.md
---

# open-bridge — Architecture & Current-State Review

This is a sober review of the repository as it actually exists on this branch.
It cites real file paths and asserts only what the files support. Where a claim
rests on a generated summary rather than a line I read directly, or where I am
unsure, it is marked as such. It is intentionally not promotional.

## 1. What the system is and what it is for

open-bridge is a **plain-text substrate** that an AI coding agent reads at the
start of every session: markdown and YAML in a git repo, no database, no daemon,
no hosted service. The README (`README.md:34-42`) and `AGENTS.md` frame it as a
"central command hub" giving the agent persistent, structured knowledge of the
user's world (identity, repos/clients, conventions, prior work) so context does
not get rebuilt every session.

The README is unusually candid about maturity: it states the project is built and
self-used at BKS-Lab on **one instance with no external users** (N=1), separates
**PROVEN / BET / OPEN** claims (`README.md:132-155`), and labels several headline
ideas — workspace separation as a hard default, off-topic stripping — as *not yet
built into open-bridge*. `CHANGELOG.md` confirms it is in the `0.x` series
(current line is v0.3.x, 2026-06). Treat this as an early-stage, actively
iterated convention/method repo, not a finished product.

The substrate is also tool-agnostic by design: `AGENTS.md` is the canonical
manual (Linux-Foundation `AGENTS.md` convention); `CLAUDE.md` and `GEMINI.md` are
thin wrappers. Claude Code is the only tool described as fully exercised
(`README.md:277`); Codex/Copilot CLI are claimed to work via `AGENTS.md` + the
`skills/` symlink; Gemini/Cursor/Windsurf are explicitly **untested**.

## 2. Main components and how they fit

### 2.1 CORE/USER branch split + scope routing
The load-bearing architectural decision. CORE (the default branch, `main` here)
ships generic templates, skills, docs, schemas; USER data lives on a `user/{name}`
branch. They touch **disjoint paths**, so CORE updates merge conflict-free
(`README.md:166-174`, `docs/structure.md`). Every file's tier is decided
**structurally** — by folder, by `_`-prefix on instance files, or (skills only)
by `metadata.scope` frontmatter (`AGENTS.md` § Scope). `/promote` and
`/bridge-sync` route changes upstream by that scope. This is the mechanism that
keeps PII out of the public OSS upstream, with a content leak-scan as a backstop
rather than the primary guard.

I verified the CORE-clean claim mechanically: a glob of
`{identity,infra,workflow}/**/*.yaml` returns **only** `_schema.yaml` /
`_template.yaml` files — no instance YAML is committed on this branch. Real
instance files appear only under `examples/agency/`.

### 2.2 Session-start gate (Phase 0)
`rules/session-start.md` defines a mandatory pre-response detection step: resolve
the default branch **live** (`gh` → `git symbolic-ref` → `init.defaultBranch` →
`main`), then route on (current branch, `user/*` existence, `bridge-config.yaml`
presence) into NEW USER / WRONG BRANCH / ORPHAN / BROKEN CONFIG / NORMAL / CORE
DEV MODE. The rule records a concrete past failure (a hardcoded branch causing a
PR to land on `bks-codex`, 2026-05-01) as the reason detection is dynamic. A
`.claude/hooks/session-start-phase0.sh` hook exists alongside the behavioural
rule. The matrix is duplicated across `CLAUDE.md`, `AGENTS.md`, and
`rules/session-start.md` — belt-and-suspenders, but three copies to keep in sync.

### 2.3 The three cluster-wrappers
Config is organised into `identity/` (WHO / to WHOM), `infra/` (WHERE / HOW), and
`workflow/` (WHAT happens when), each holding typed subfolders with
`_template.yaml` + `_schema.yaml` and (on a user branch) instance files. Observed
types: `identity/{accounts,agent,contracts,mandants,personas}`,
`infra/{backups,channels,instances,remotes}`,
`workflow/{calendars,contexts,projects}`. Discovery is a plain glob
(`rules/discovery.md`). This is a clean, uniform "default-to-folder" model — going
from one instance to five is zero structural work.

### 2.4 Skills layer
29 skills live flat under `skills/`, each a `SKILL.md` with a decision tree and
optional `references/` files (per the sub-agent inventory; all 29 carry
`metadata.scope: core`). They are surfaced to multiple tools via committed
symlinks (`.claude/skills`, `.agents/skills`, `.github/skills` → `skills/`).
`scripts/validate-skill-scope.py` enforces scope frontmatter and regenerates the
SKILL-SCOPE table in `AGENTS.md` (CI + pre-commit), which keeps the documented
list from drifting.

### 2.5 Standing orders and sub-agents
`protocols/standing-orders/*.md` are always-on rules injected into every dispatch
(`document-work.md` and `task-sync.md` are `enforcement: blocking`; the rest
advisory). Sub-agents are Claude-Code-specific (`.claude/agents/*.md`); the repo
ships exactly **one** reference agent, `archivist.md` — the README is honest that
you add the rest yourself. On non-Claude tools the same logic runs inline.

### 2.6 Task management (`work/`)
The "Chaos Tamer": finite tasks in `work/tasks/<slug>/`, long-runners in
`work/streams/`, closed work in `work/done/YYYY-MM/`, a generated `work/board.md`,
and an append-only `work/log.md`. KIND is the folder; `status` is a CI-validated
enum (`backlog/doing/review/done`). `scripts/gen-board.py` regenerates the board
from the directory tree (never hand-edited).

### 2.7 Trackers and automation
`trackers/*.md` are pluggable provider playbooks (`github.md` working via `gh`;
`ado.md` reference via `az`) normalising into a shared item schema; new providers
are drop-in markdown, no code change. Automation is substantial: ~13 Python +
several shell scripts under `scripts/`, a deterministic `scripts/hooks/pre-push`
guard, fixture-based tests under `scripts/tests/`, five `.github/workflows/`
(validate, release, dco, claude, claude-pr-review), and a `.pre-commit-config.yaml`
mirroring the CI checks locally.

## 3. Notable strengths

- **Substrate choice is coherent and inspectable.** Plain text + git means the
  agent's "memory" is diffable and owned by the user. The CORE/USER disjoint-path
  design makes the central claim (conflict-free upstream merges) structurally
  true, not aspirational — verified by the glob showing zero instance files on
  CORE.
- **Structure-over-declaration for tiering.** Scope is mostly decided by *where a
  file lives*, not a tag a human can forget. The one place it must be declarative
  (skills) is gated by a validator. This is a genuinely robust way to keep PII out
  of an OSS upstream.
- **The push guard is real and well-thought-through.** `scripts/hooks/pre-push`
  is offline-first, fails *closed* on unknown remotes, keys the decision on the
  push *destination ref* (not the local ref) to defend against
  `HEAD`/detached/sha push forms, and inspects pushed *commits* rather than the
  working tree. The header comments document the specific leak vectors each
  measure closes. `scripts/tests/test-push-guard.sh` exercises these paths.
- **CI enforces what it can statically.** yamllint, JSON-Schema validation of all
  config types, ecosystem cross-ref checks, content-leak scan, skill-scope, DCO
  sign-off, and an onboarding-safety job all run on PRs, mirrored in pre-commit.
- **Honest self-assessment.** The README's PROVEN/BET/OPEN framing and explicit
  N=1 / untested-tool disclaimers are rare and reduce the risk of a reviewer being
  misled about adoption or completeness.
- **Cross-tool agnosticism is structural, not a slogan** — `AGENTS.md` as the
  canonical manual plus the committed discovery symlinks is a concrete mechanism.

## 4. Gaps, risks, and inconsistencies actually found

- **`identity/contracts/` has no leak protection on either layer.** It ships a
  `_template.yaml` + `_schema.yaml` and is described as holding recurring
  financial obligations (USER PII), yet: (a) `.gitignore` does **not** ignore
  `identity/contracts/*.yaml` — unlike `personas`, `mandants`, and `accounts`,
  which are all ignored; and (b) it is **absent from the push-guard `USER_PATHS`
  regex** (`scripts/hooks/pre-push:123`), which lists
  `identity/(personas|mandants|accounts)` but not `contracts`. Net effect: a
  user-created contract file is git-tracked by default and is not flagged as
  sensitive content on a non-`user/*` destination. The primary `user/*`
  destination rule still blocks it on a user branch, so the practical exposure is
  narrow — but this is a real, citable inconsistency in a PII-bearing type. (The
  type is also only lightly wired into the rest of the system — no standing order
  or briefing references it, per the structure scan.)
- **The promote router's scope mapping is unverified by tests.**
  `scripts/categorize-commits.py` mirrors the path→scope table from
  `rules/operations.md` by hand (it carries a "keep in sync" comment, per the
  automation scan), but `scripts/tests/` contains tests only for the push guard,
  system-discovery, tracker-sync, and ecosystem validation — **none for
  categorize-commits.py**. Since this script is what decides whether a commit goes
  to a public upstream, a silent drift between it and `operations.md` is a leak
  risk with no automated tripwire.
- **Phase-0 logic is triplicated.** The session-start matrix and rationale are
  copied into `CLAUDE.md`, `AGENTS.md`, and `rules/session-start.md`. The
  duplication is deliberate (survives a dropped import) but is a standing drift
  surface; there is no check that the three copies agree.
- **First-run value is thin and the README says so.** A fresh clone is mostly
  empty until `work/log.md` accrues real history (`README.md:152`). This is an
  honest limitation rather than a defect, but it is the main adoption risk.
- **Several headline behaviours are roadmap, not shipped.** Workspace separation
  as a hard default, the "if you can't place it, ask" rule, and off-topic
  stripping are agreed in principle but **not built** (`README.md:146-151`). A
  reader skimming the "Chaos Tamer" section could mistake these for present
  features; the README mitigates this with an explicit warning, but the gap is
  worth keeping front-of-mind in any evaluation.
- **Operator/generator scripts are untested and ungated.** `gen-board.py`,
  `extract-bridge-state.py`, `bridge-dashboard.py`, and the constellation builder
  have no tests and are not exercised in CI (per the automation scan). A
  regression in `gen-board.py` would silently corrupt the board with no signal.
- **Minor naming/asymmetry items.** `workflow/contexts/` carries both
  `_template.yaml` and a second `_doc-system.template.yaml` (non-obvious naming);
  one skill (`github-projects-manager`) declares a `tools:` frontmatter list while
  the other 28 do not (cosmetic, not a bug). Per the skills scan, five skills ship
  with no `references/` dir — by design for simple coordinators, but asymmetric.
- **Tool-coverage claims outrun testing.** Gemini/Cursor/Windsurf are listed as
  following the same standard but untested, and Windows symlink degradation is a
  documented sharp edge (`README.md:277`, `AGENTS.md` Windows note). Anyone relying
  on a non-Claude tool should expect rough edges.

## 5. Improvement suggestions (specific, actionable)

1. **Close the `identity/contracts/` gap on both layers.** Add
   `identity/contracts/*.yaml` (with `!_template`/`!_schema` negations) to
   `.gitignore`, and add `contracts` to the `USER_PATHS` regex in
   `scripts/hooks/pre-push:123`. Then either wire contracts into a standing order /
   briefing block, or move it to a documented "planned" state so the type isn't
   half-present. Add a fixture to `test-push-guard.sh` asserting a contracts
   instance file is treated as sensitive.
2. **Add a regression test for `categorize-commits.py`.** A small fixture suite
   under `scripts/tests/` that feeds representative paths and asserts the
   core/org/user verdict, plus a check that every path prefix in
   `rules/operations.md` is represented. This converts the "keep in sync" comment
   into an enforced invariant on the most leak-sensitive script.
3. **De-duplicate the Phase-0 matrix or add a drift check.** Make
   `rules/session-start.md` the single source and have `CLAUDE.md` / `AGENTS.md`
   carry a short pointer plus a CI check (or a `bridge-audit` rule) that fails if
   the inlined copies diverge from the canonical table.
4. **Bring generator scripts under test/CI.** At minimum a smoke test for
   `gen-board.py` and `extract-bridge-state.py` against a fixture `work/` tree
   (round-trip: directories in → expected board sections/counts out). These are
   cheap and catch the silent-corruption class.
5. **Reduce first-run emptiness.** Ship a *read-only* sample `work/log.md` /
   board snapshot (similar to `examples/agency/`) that the NEW USER greeting can
   point at, so a fresh clone demonstrates the compounding value before the user
   has logged anything. Keep it clearly labelled as example data.
6. **State the roadmap-vs-shipped boundary inside the feature docs, not only the
   README.** The "Chaos Tamer" / workspace-separation language recurs in
   `docs/` and skill copy; a one-line "(roadmap — not yet built)" marker at each
   occurrence prevents the shipped/aspirational confusion from leaking past the
   README's disclaimer.
7. **Add at least one smoke test for a non-Claude tool path.** Even a CI job that
   verifies the `.agents/skills` / `.github/skills` symlinks resolve and that a
   representative `SKILL.md` is discoverable would turn "untested" into
   "minimally verified" for the cross-tool claim that is central to the pitch.
8. **Document the `infra/instances/` and `workflow/projects/` leak posture.**
   Both are absent from the push-guard `USER_PATHS` net; confirm and record
   whether that is intentional (they are org/config, not PII) so the omission is a
   decision rather than an oversight — the same reasoning that should govern
   `contracts`.

---

### Method note
This review is based on direct reads of `README.md`, `AGENTS.md`/`CLAUDE.md`,
`rules/session-start.md`, `scripts/hooks/pre-push`, `.gitignore`, `CHANGELOG.md`,
and globs of `skills/`, `scripts/`, and the cluster-wrappers, supplemented by
structured sub-agent scans of the skills layer, the automation/CI surface, and the
config/structure layer. Claims drawn from those sub-agent scans rather than a line
I read myself (e.g. the exact contents of `categorize-commits.py`, the full skill
reference-file counts, the CI job breakdown) are attributed as such above and
should be spot-checked before being treated as load-bearing.
