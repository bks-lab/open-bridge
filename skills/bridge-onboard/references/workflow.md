---
description: Full onboarding wizard — six discovery-driven phases Claude executes after the user accepts the new-user greeting. Self-contained.
---

# Onboarding Wizard — Phases

Read this when the user wants the full guided setup. The session-start
gate (`rules/session-start.md`) has already delivered the new-user
greeting and the user said "yes, onboard me". Pick up with a short confirm
("Great, let's get you set up — about 5 minutes.") — no second welcome
wall.

## Principles

1. **Discover, don't interrogate.** Look at what the user already has
   (apps, dirs, git config) and propose matching features. Don't ask
   abstract life-situation questions like "do you file taxes for
   multiple legal entities?" — that scares users away.
2. **Minimum first.** Running in 5 minutes; cluster-wrappers are mostly
   empty on day one and get filled on demand via `--add <feature>` or
   the `feature-discovery` standing-order surfacing them later.
3. **Explain why.** Every suggestion says what becomes possible and
   what stays manual.
4. **GitHub-optional.** Onboarding works end-to-end without a GitHub
   account and without `gh` CLI. Skills that need it warn at use-time,
   not setup-time.
5. **Catch errors gracefully.** Missing tools, permission denials,
   clone failures are non-fatal — record and continue.
6. **Mirror the user's language.** German in → German out (theme +
   bilingual wizard text).

## Prerequisites

- `git` configured (`user.name`, `user.email`) — only hard requirement
- `gh` CLI **optional** — enables GitHub repo detection. Without it,
  ecosystem scan still works (reads local `.git` configs for remote URLs).
- `pipx` + `check-jsonschema` **strongly recommended** — Phase F
  validates generated YAML against shipped schemas. Wizard prompts to
  install if missing.

## Concepts to weave in (don't lecture)

- **CORE/USER split** — the core branch (the repo's default — `main`
  here) carries shared templates + schemas + standing orders + skills;
  `user/{name}` carries personal config, contexts, agent customizations,
  work data. Merges stay conflict-free because the two layers touch
  different paths.
- **Cluster-Wrappers** — config types live in `<wrapper>/<types>/`
  folders. Most start empty; fill on demand.
- **Variables** — `${projects_root}`, `${home}` are defined in
  `bridge-config.yaml` and consumed everywhere; no hardcoded paths.
- **Upstreams** — `bridge-config.yaml.upstreams[]` is a list.
  Most users leave it empty and wire later via `--upstream`.

---

# Phase Map

```
A  Quick Identity              60 sec   purpose + name + projects_root + GitHub-opt + lang + scope-consent gate
B  Discovery Scan             ~60 sec   permission-gated system scan (broader mode only; skipped if confined)
C  Smart Suggestions         ~2-3 min   evidence → feature recommendations (skipped if confined)
D  Quick-Wins                ~2 min    work-system + theme + 3 starter agents + agent soul/identity (deck-picked)
E  Feature Catalog          read-only   "what else Bridge can do, when to add it"
F  Validate + Preview        ~30 sec   schema check, HTML preview, re-entry hints
```

Total: 5-8 minutes for a tailored setup, ~3 minutes for "defaults only".

---

## Phase A — Quick Identity

A tight identity block — five questions (purpose included), one branch creation, and the scope-consent gate (step 7, always last).

1. **Name** — detect from `git config user.name`; offer it back. Becomes
   `identity.name` and the suffix of the user branch. If `git config
   user.name` is **empty**, don't silently proceed — ask the user for a
   name (and offer to set it via `git config --global user.name "<name>"`
   so future commits are attributed).
2. **GitHub org** — *optional*. Three valid answers:
   - Org name (e.g. `acme-corp`) → fills `identity.org`, enables GitHub features
   - "personal" → fills with the user's GitHub login, GitHub features enabled
   - **skip** (empty) → `integrations.github.enabled: false`, no GitHub anywhere
3. **Projects root** — where your repos live. Default suggestion:
   - With org → `~/Developer/{org}`
   - Without GitHub → `~/Developer` or `~/Code` (offer both, pick what exists)
4. **Language** — auto-detected from the user's first message; confirm
   only if ambiguous. Sets `language.conversation` and `language.artifacts`.
5. **Purpose — the instance's north-star.** One line before wiring anything.
   **Discover, don't interrogate:** if `identity.org` was given (step 2),
   pre-fill the lead from it. Render verbatim (EN source; render bilingually at
   runtime — German in → German out):
   ```
   One line before we wire anything — what will you mainly use this Bridge for?

   This becomes its north-star: I lead with the features that serve it and keep the
   rest one keystroke away, so this instance stays focused instead of fanning out
   everything at once. It's a compass, not a fence — every feature stays available and
   you can change this anytime (/bridge-onboard --purpose).

     examples:  "Client delivery for my two freelance engagements"
                "Running ops for the Acme team"
                "Personal life admin — finances, documents, the household"

     [type a line]   [w] mostly work   [p] mostly private   [b] a bit of both   [skip]

     Purpose ▸
   ```
   **Handling** (purpose SUGGESTS/ORDERS/LABELS only — it never gates, hides, or
   removes a feature; every capability stays one `--add`/`enabled:` flip away):
   - **A typed line** → write it verbatim to `purpose.statement`. Then derive
     `purpose.focus` — a subset of the six catalog domains (`identity`,
     `communication`, `infrastructure`, `productivity`, `integrations`,
     `visualization`) — AND `user_profile` (`work | private | both`) from the
     statement. Echo ONE soft confirm:
     > Got it — I'll keep this Bridge pointed at {statement}, leading with {focus
     > domains}; everything else stays one step back. **[ok]** **[adjust domains]**

     `[adjust domains]` is the only correction path (toggle the inferred focus
     domains); it never blocks.
   - **`[w]` / `[p]` / `[b]`** → set `user_profile` to `work` / `private` / `both`
     explicitly; leave `purpose.statement: ""` and `purpose.focus: []`.
   - **`[skip]`** → `purpose.statement: ""`, `purpose.focus: []`,
     `user_profile: both`, with one line:
     > Kept general-purpose — the catalog stays flat; set a focus later with
     > /bridge-onboard --purpose.

   Empty purpose (statement `""` + focus `[]`) reproduces today's exact flat,
   general-purpose behaviour — zero regression.
6. **Check the origin, then create the `user/{name}` branch.** First resolve where
   this clone pushes: `git remote get-url origin` (and `gh repo view --json
   visibility,nameWithOwner` if unsure). **If `origin` is a PUBLIC repo or a known
   upstream (e.g. `bks-lab/open-bridge`) — or `.bridge-origin` says
   `is_public: true` — STOP.** The user's data must not live on a public origin.
   Advise the private-origin setup (GitHub *Use this template → Private*, or re-home
   `origin` to a new private repo with open-bridge as a read-only `upstream`) and
   continue only once `origin` is private — or the user explicitly chooses
   local-only and will never push. Then create the branch from the core/default
   branch — but **arm the push guard FIRST**, before the branch (and any private
   commit) exists, so the deterministic backstop is live from the very first commit:
   ```bash
   git config core.hooksPath scripts/hooks   # arm the pre-push guard (idempotent)
   git checkout -b user/{name}
   ```
   (where `{name}` is the slug from step 1). Arming here — not relying on the user to
   have run `bin/setup` — is what makes the guard actually present on a fresh clone;
   without it the backstop is inert and only the instruction layer protects you. Your
   personal data lives here, CORE stays clean. Confirm the new branch is checked out
   before writing any USER files. **Never push `user/{name}` to a public origin** —
   CORE reaches a public upstream only via `/promote`. See
   [`../../../rules/push-guard.md`](../../../rules/push-guard.md).

**Upstream wiring — defer.** Keep `upstreams: []`. Mention in passing:
"Once `bks-lab/open-bridge` (public) or your own upstream is live, wire
it via `/bridge-onboard --upstream`". No Variant-Wahl prompt while the
upstream repos are not public yet.

7. **Scope consent gate — the last step before any scanning.** Before Phase B
   looks at anything beyond this folder, the user makes one explicit choice.
   This is the consent boundary: with no explicit "yes", the Bridge never
   scans — not now, not later. Render this verbatim:
   ```
   Before I look at anything beyond this folder, one choice — there's no wrong answer:

     [1] Confined (default) — I stay inside this Bridge folder. I won't scan your other
         repos, installed apps, devices, files, or mail. You still get every feature;
         I just won't auto-suggest them — you turn on exactly what you want, when you want.

     [2] Broader — I take a quick look at your machine (with your per-item permission in
         the next step) so I can suggest features that fit what you already use: your
         repos → an ecosystem map, a mesh-VPN → remote-machine control, backup tools →
         a backup topology, and so on. I only ever read names and structure — never file,
         mail, or message content, never secrets. Findings stay local (gitignored).

   You can change your mind anytime: /bridge-onboard --rescan (to broaden) or set
   discovery.mode in bridge-config.yaml.

     [1] Confined   [2] Broader   [?] What exactly would broader look at?
   ```
   - **`[1]` Confined (default)** — write `discovery.mode: confined` and
     `discovery.permissions: []` to `bridge-config.yaml`, then **skip Phase B
     and Phase C entirely → jump to Phase D**. Nothing on the machine is read.
     The user keeps every feature; they enable what they want from the Phase E
     catalog, via `/bridge-onboard --add <feature>`, or by flipping the
     feature's `enabled:` flag in `bridge-config.yaml`.
   - **`[2]` Broader** — write `discovery.mode: broader` and continue into
     Phase B, where the existing per-source permission model applies as today.
   - **`[?]`** — answer from the Phase B permission prompt
     (`system-discovery.md`): which sources, default-on vs opt-in,
     names-and-structure-only, never content/secrets — then re-show the two
     options.

   An absent or unset `discovery.mode` means **confined** — no explicit
   consent, no scan.

**Output of Phase A:**
- `bridge-config.yaml` skeleton (identity block populated, all features off,
  `purpose.statement` + `purpose.focus` set from step 5 — both empty if the user
  skipped, `user_profile` derived from the statement or from `[w]/[p]/[b]`,
  `discovery.mode` set to the user's choice — `confined` if unset)
- `user/{name}` branch created (`git checkout -b user/{name}`) and checked out
- On `[1]` Confined: control jumps to Phase D; on `[2]` Broader: continue to Phase B

---

## Phase B — Discovery Scan

> **Only runs when `discovery.mode: broader`.** If confined, this phase was
> skipped in Phase A (control jumped straight to Phase D).

Permission-gated system scan. Full details in
[`references/system-discovery.md`](system-discovery.md).

0. **Skill-discovery health check (do this first — the adopter's other tools depend on it).**
   The three discovery paths must resolve to the top-level `skills/`, or non-Claude tools
   (Codex / Gemini CLI / Copilot CLI / Cursor) find no skills. Claude Code is already running,
   so `.claude/skills` works — verify the other two and offer to repair, don't just cite a doc:
   ```bash
   for p in .claude/skills .agents/skills .github/skills; do
     { [ -L "$p" ] && readlink "$p" >/dev/null 2>&1; } && echo "OK  $p" || echo "BROKEN  $p"
   done
   ```
   - All three `OK` → say so in one line and continue.
   - Any `BROKEN` (typical on a bare Windows checkout — the symlink degrades to a plain text
     file) → name **which tool would be blind**, then offer:
     `[a]` run `bin/setup` (re-creates all three; Windows: `bin/setup.ps1`, junction fallback) ·
     `[b]` set it by hand (show `ln -s ../skills .agents/skills`, or Windows
     `mklink /J .agents\skills ..\skills`) ·
     `[c]` ignore — "I only use Claude Code" (the degraded non-Claude links then don't matter).
   - After a fix, re-run the loop to confirm `OK` before moving on.

1. **Show the permission prompt** verbatim from `system-discovery.md`
   — what gets scanned, what's default-on, what's opt-in, what's NEVER
   scanned. Trust-building is critical here; the user must feel in control.

2. **Run scans in parallel** with live progress per source:
   ```
   ✓ git_config (alice)
   ✓ developer (12 repos in 3 orgs)
   ✓ os_and_apps (47 apps — mapped to capabilities via the Capability Map)
   ✓ homebrew (rclone, restic, gh, wakeonlan)
   ✓ mesh_vpn (tailscale, 3 devices: alice-macbook, alice-mini, alice-nas)
   ⚠ mail_accounts (permission denied — System Settings → Privacy → Automation)
   ```

3. **Write `work/onboarding-scan.json`** per the schema in
   `system-discovery.md`. Add to `.gitignore` if not already there.

4. **Persist permissions in `bridge-config.yaml`** under `discovery.permissions`
   so `--rescan` and `feature-discovery` standing-order know what's allowed:
   ```yaml
   discovery:
     permissions: [git_config, developer_dir, os_and_apps, homebrew_packages, mesh_vpn_devices]
     last_scan: 2026-05-16T14:30:00+02:00
   ```

5. **If user picked `[s]` Skip** — this is "scan nothing after all": write
   `discovery.mode: confined` and `discovery.permissions: []`, skip Phase C
   entirely, jump to Phase D. Mention: "Scanning skipped — staying confined.
   Enable features yourself from the catalog or `/bridge-onboard --add`, and
   broaden later with `/bridge-onboard --rescan` if you change your mind."

6. **Confirm the Phase-A profile** (silent, only if Phase C will run): the
   `user_profile` was already set in Phase A step 5 — from the purpose statement
   (derived) or from the `[w]/[p]/[b]` answer. **Don't re-ask it here** — that was
   the standalone bias-question's job and it has moved to Phase A (net-zero question
   count, and it fixes that confined-default users were never asked it at all). Just
   note it in one line so the Phase C ordering is transparent:
   ```
   Ordering Phase C for {user_profile} use{, focus: <focus domains> if purpose.focus set}.
   ```
   Purpose (`purpose.focus`) is the primary order, `user_profile` the secondary
   tiebreak; neither gates any feature.

---

## Phase C — Smart Suggestions

Evidence-driven feature activation with full advisory text. Full mapping
table in [`references/smart-suggestions.md`](smart-suggestions.md).

1. **Load `work/onboarding-scan.json`** plus existing
   `work/onboarding-state.yaml` if present (skip suggestions already
   `accepted` or `silenced`).

2. **For each evidence-matching suggestion** (S1–S12 in
   `smart-suggestions.md`), in priority order:
   - Read the advisory text for that block
   - Substitute the variable parts with actual scan data
   - Apply the **known-gotcha overlay** — from the curated CORE table in
     `smart-suggestions.md` only (never scans the operator's memory, never
     names a customer / employer / contact); append as `⚠ Heads-up: ...`
   - Present with `[y]` / `[m]` / `[l]` options
   - Record decision in `work/onboarding-state.yaml`

3. **Apply accepts immediately** — don't batch. Each `[y]` runs the
   scaffolding for that feature (set config, copy template, create
   skeleton file). User sees the file paths created.

4. **Defers** record `remind_after: now + 30 days`. The
   `feature-discovery` standing-order will resurface them.

5. **End Phase C** with a one-line summary:
   ```
   Phase C done — {N} enabled, {M} deferred. Continuing to Phase D.
   ```

**Personas are NEVER suggested in initial Phase C** — see
`smart-suggestions.md § Personas — Explicit Note` for the rationale. They
appear in Phase E catalogue and surface later via `feature-discovery`
if the user develops a pattern that suggests them.

---

## Phase D — Quick-Wins

Three settings that don't benefit from interview. Defaults assumed.

### D1 — Task Management *(STRONGLY recommended — central to The Bridge)*

This is **the single most important step.** Task Management is what
makes The Bridge feel coherent across sessions. Default answer is yes;
only skip if the user is sure they want a dumb chat with no memory.

**What it actually does for you:**

- `work/log.md` is Claude's *working memory* between sessions
- `work/board.md` is your generated task surface
- `work/tasks/<slug>/STATUS.md` turns multi-day finite work into structured
  state that survives compaction and context switches (`work/streams/<slug>/`
  holds long-runners that never close)
- Standing orders (including `feature-discovery`) only fire when this is on

**Skills that depend on it:** `/briefing`, `/debrief`, `/archive`,
`task-close-postmortem`, `bridge-curator`, `bridge-learn`,
`weekly-debrief-reconciler`, everything that reads `work/tasks/`.

**Pitch:**
```
The work system makes me useful tomorrow, not just today. I read
work/log.md at session start to know what we did yesterday, and
work/board.md to know what's in flight. Without it I start every
session cold — like a coworker with amnesia.

  [y] Enable (recommended)  — hybrid logging, 5 max active
  [c] Customize             — pick logging level, limits
  [n] Skip                  — accept cold-start mode
```

On `[y]` or `[c]`:
- Create directories: `work/{active,ongoing,done,archive/days,archive/weeks,imports}`
- Generate `work/log.md` from `work/templates/week-skeleton.md` (fresh week header + today's day-block)
- Generate `work/board.md` — empty board with header
- Set `work.enabled: true` in `bridge-config.yaml`

On `[n]`: leave `work.enabled: false`, explicitly mention that
`/briefing`, `/debrief`, `/archive`, and **`feature-discovery`** are
now inert.

### D2 — Theme

Themes change user-facing vocabulary only — never tools or goals.

```
  [1] professional      Lead, Specialists, Tasks         (en, default)
  [2] professional-de   Leitung, Spezialisten, Aufgaben  (de)
  [3] custom            Skip — copy themes/_template.yaml later
```

Auto-pick from Phase A language: German → `professional-de`,
else → `professional`. One-question confirm.

### D3 — Agents (Sub-agents)

**For Claude Code users:** native Claude Code sub-agents live in
`.claude/agents/*.md` and are auto-discovered by Claude Code at session
start. open-bridge ships one (`archivist`, document intake); everything
else dispatches through the built-in `general-purpose` agent until the
user adds their own files. There is nothing to install or register at
onboarding — explain the drop-in model and move on.

**For other tools (Copilot CLI, Gemini, Codex, Cursor):** sub-agents
aren't available in your API — there is no isolation-worker primitive to
register. Skills dispatch their logic inline instead, with identical
behaviour (no capability loss; only the in-session context isolation
differs). The `.claude/agents/*.md` files still serve as documentation of
each agent's pattern, so a future Claude Code session reads the same
roster.

> **Windows caveat:** on a default Windows git checkout the
> `.agents/skills` + `.github/skills` symlinks degrade to plain text
> files, so non-Claude tools find no skills. See the README (Windows
> section) for the fix (enable symlinks / `git config core.symlinks
> true` + re-checkout).

Where a pain point from Phase B/C suggests it, propose a concrete
sub-agent to create later (e.g. a `log-analyst` for frequent incidents)
— suggest, don't create.

---

### D4 — Agent Identity (SOUL & IDENTITY) *(optional, ~60 sec)*

A fresh clone ships **no live** `identity/agent/SOUL.md` (the
orchestrator's character + cross-cutting voice/posture/defaults) or
`identity/agent/IDENTITY.md` (name, role, backstory) — only the CORE
companions: `_template.*`, the soul deck, and the schemas. This step
seeds both files on the `user/{name}` branch and adds their `@`-imports
to `CLAUDE.md` so they load every session.

**Frame it honestly, don't oversell.** A soul is not authored in one
sitting. The strongest souls *accrete* — the example instance's SOUL.md
was distilled later from real feedback, not written at setup. So this
step **seeds a small starter voice and wires the growth path**; it does
not try to capture who the agent "really is" on day one.

> Your agent carries a character + voice (how it behaves across every
> task) and an identity (its name + role). Sensible defaults exist. Want
> to shape them now, or take the defaults and let them grow?
> **[y] Shape it now (~1 min)** / **[s] Take defaults**

On `[s]`: seed both files from the templates unchanged (neutral
defaults — they are functional as-is) and add the `@`-imports. Mention
the growth path (see "Living soul" below) and move on.

On `[y]`: run the two sub-steps below.

#### D4a — SOUL: pick from the deck (propose, don't interrogate)

Load `identity/agent/_soul-deck.yaml` — a curated library of universal
voice/posture principles. **Pre-check the card set matching the Phase-D3
work-type answer** (`defaults_by_worktype.{dev|devops|consulting|mixed}`)
so the user starts from a tailored proposal, not a blank menu. This is
the same evidence→propose move as Phase C, applied to voice.

Present the deck grouped by section, pre-selected cards marked, each with
its one-line `does:` benefit so the user sees *why* a principle is there:

```
Your agent's starting voice — pre-picked for {work_type} work.
Toggle any line; these are just defaults.

CHARACTER
  [x] The user is a peer, not a customer. When the thinking looks wrong,
      disagree before executing — then commit fully to what's decided.
        → catches bad plans at the cheapest moment
  [ ] Sober by conviction, not caution — impact comes from substance, never volume.
        → grounds the no-hype style in a temperament, not a word ban
VERIFY
  [x] Don't trust declared state. Read the live source before claiming a fact.
        → so it never repeats a stale assumption as checked truth
  [ ] Read external systems' state at write-time, not from memory.
        → catches field names / IDs that quietly changed under you
POSTURE
  [x] Be direct. Push back when you think I'm wrong, before doing the work.
        → a peer that catches mistakes early, not a yes-machine
  ...

  [number] toggle a line   [r N] reword line N in your own words
  [+] add your own principle (free text)   [done] write it
```

**User contribution is first-class, not an afterthought:**
- `[r N]` — reword any card line into the user's own phrasing (keeps the
  section, replaces the line).
- `[+]` — the user types a principle in their own words. Ask which
  section it belongs under (or offer a sensible default), append it
  verbatim. This is the explicit "the soul may receive from me" path —
  invite it, don't bury it.

On `[done]`: render the selected + reworded + custom lines into
`identity/agent/SOUL.md` on the `user/{name}` branch, grouped under their
section headings, keeping the template's frontmatter (`scope: user`,
today's `last_updated`). Drop any section that ended up empty. Add a
one-line dated provenance note: *"Seeded {date} from the onboarding soul
deck — grows via feedback (see README § Living soul)."*

#### D4b — IDENTITY: name, role, optional depth

1. **Name** — the agent's name lives in the active theme's
   `assistant_name` (default **{theme assistant_name}**), NOT as a literal
   in IDENTITY.md. Offer: keep the themed name, or set a new one — if
   changed, write it to `themes/<active-theme>.yaml`
   `vocabulary.assistant_name`, and IDENTITY.md keeps referring to the
   theme. Never hardcode the name in IDENTITY.md.
2. **Role** — confirm or adjust the one-line role from the template.
3. **Depth** — one question:
   > Minimal identity (name + role + self-intro, ~20 lines) or richer
   > (add a backstory / design philosophy / how-I-relate-to-you section)?
   > **[m] minimal** / **[r] richer** / **[+] write your own backstory line**

   `[m]` writes the lean IDENTITY.md from the template. `[r]` keeps the
   template's fuller sections. `[+]` lets the user dictate a backstory or
   stance line in their own words — again, a first-class contribution path.

Write `identity/agent/IDENTITY.md` on `user/{name}` (scope: user).

#### Living soul — wire the growth, don't replace it

Close D4 by pointing at the existing loop (do NOT invent a parallel one):

> This is a starting point, not the finished voice. As we work, when you
> correct me or a pattern repeats, `bridge-curator` synthesises it and
> `/bridge-learn` lets you fold accepted lessons back into SOUL.md. Your
> soul gets sharper by being used.

The mechanics are already shipped: feedback memories →
`bridge-curator` Pass 3 (`work/_learning/user-patterns.md`) →
`/bridge-learn` accept → edit into `identity/agent/SOUL.md`. New CORE
voice defaults land in `_template.SOUL.md` (and the deck), which users
diff-merge. D4 only seeds and points at this — nothing new to build.

**Hard rules:** SOUL.md stays ≤ 80 lines / 4 KB (bridge-audit Check 10
enforces — the deck is sized to stay well under). The name lives in the
active theme's `assistant_name` — never a literal in IDENTITY.md. Full
conventions: `identity/agent/README.md`; deck: `identity/agent/_soul-deck.yaml`.

---

## Phase E — Feature Catalog *(read-only, no questions)*

**Modular by design — there is no "full package".** Every feature is à la
carte: take the individual ones you want, decline the rest, nothing is
bundled or all-or-nothing. Confined users (who skipped Phase B/C) enable any
feature manually — via `/bridge-onboard --add <feature>` or by setting its
`enabled:` flag in `bridge-config.yaml`.

Print the full catalogue from
[`references/feature-catalog.md`](feature-catalog.md), grouped by
life-domain, with state annotations from `work/onboarding-state.yaml`:

- ✓ enabled (feature was accepted in Phase C)
- ⏸ deferred until {date} (will resurface via `feature-discovery`)
- (no signal yet) (Phase B found nothing; surface later if evidence appears)
- (not yet considered) (no evidence, no opt-in)

**Purpose banding (the do-everything fix — applies in confined mode too).** When
`purpose.statement`/`purpose.focus` are set, print `purpose.statement` as the
catalogue header, then split the life-domain groups into two bands per
`feature-catalog.md` § Purpose Banding:

- a lead band **"Most relevant to '{statement}'"** — the `purpose.focus` groups first;
- a collapsed/dimmed secondary band **"Beyond your focus — here whenever you need it"**
  — the full remainder.

Nothing is removed, hidden, or gated — banding ORDERS and LABELS only; every feature
keeps its one-line re-entry command and the trust-closer is unchanged. **Empty
purpose (statement `""` + focus `[]`) → today's flat grouped catalogue, byte-for-byte.**

End the catalogue with the trust-building closer (verbatim from
`feature-catalog.md`):

> You don't need to memorise this. Bridge surfaces relevant features
> proactively...

**Do not ask anything here.** Phase E is purely informational. The
user has already had their decision moment in Phase C; this is the
"here's what else exists" gallery, not a second survey.

---

## Phase F — Validate + Commit + Preview

1. **Scaffold the USER structure** — `bash scripts/scaffold-user.sh`
   (idempotent: creates only what's missing — `work/{active,ongoing,done,
   archive,drafts,imports}`, `rules/user/`, `protocols/standing-orders/` +
   the cluster-wrapper instance dirs; dirs + `.gitkeep` only, never PII).
   Gives a fresh clone the empty USER tree even when it shipped CORE
   templates only. `--dry-run` to preview.

2. **Verify required files exist:**
   - `ecosystem.yaml`, `bridge-config.yaml` (always)
   - `work/{log.md,board.md}` and `work/{tasks,streams}/` etc. if `work.enabled: true`
   - `work/onboarding-state.yaml` if Phase C ran
   - `.gitignore` includes `work/onboarding-scan.json`

3. **Schema validation** — required pass, not optional:
   - Run `python3 scripts/validate-bridge.py`
   - The Bridge ships JSON Schema Draft 2020-12 for personas, themes,
     channels, remotes, mandants, calendars, contexts, projects.
   - If `check-jsonschema` is missing, prompt to install (don't skip silently).

4. **Install pre-commit hook** if `.pre-commit-config.yaml` is present
   (`pre-commit install`). Catches schema drift on every commit.

4. **Commit** all generated files on `user/{name}` branch:
   ```
   chore: bridge onboarding for {name}

   Phase A: identity ({name}, org={org or '-'}, projects_root={path})
   Phase B: discovery scan ({N} sources, {M} findings)
   Phase C: {accepted_count} features enabled, {deferred_count} deferred
   Phase D: work-system={on/off}, theme={theme}, agents={role_list}
   ```

5. **Generate preview** — read
   [`references/preview-generator.md`](preview-generator.md) and write
   `work/bridge-preview.html`. The preview has two sections:
   - **Activated** — config + repos + agents + standing orders
   - **Suggested for later** — deferred features + nothing-found
     features, each with the `/bridge-onboard --add <feature>` re-entry
     command

6. **Open in browser** (`open` on macOS, `xdg-open` on Linux).

7. **Suggest concrete next steps:**
   ```
   You're set up. Try:

     /briefing                  — your first daily briefing
     /bridge-onboard --features — explore what else Bridge offers
     /bridge-onboard --add <X>  — activate any feature on demand
     /knowledge-repo-init       — only if you marked it for follow-up

   I'll proactively suggest features when I see they'd help. Just keep
   working — feature-discovery runs in the background.
   ```

8. **Run `/bridge`** — green = ready, yellow = non-critical warnings,
   red = follow the error message.

---

## Re-Entry Modes

| Mode | Behaviour |
|---|---|
| `/bridge-onboard` | full wizard (Phases A–F) |
| `/bridge-onboard --rescan` | set `discovery.mode: broader`, then re-run Phase B+C with persisted permissions; surface new evidence; skip already-accepted features |
| `/bridge-onboard --reset` | delete scan + state files, restart from Phase A (re-runs the scope-consent gate + purpose before any scan) |
| `/bridge-onboard --purpose` | skip everything except the Phase-A purpose step — set/change `purpose.statement` + `purpose.focus` (re-derive `user_profile`), re-render the Phase F preview ordering |
| `/bridge-onboard --add <feature>` | skip A+B+D+E+F, run only the matching S-block in `smart-suggestions.md` |
| `/bridge-onboard --add agent-soul` | skip everything except D4 — re-pick the soul deck and reshape SOUL.md / IDENTITY.md |
| `/bridge-onboard --features` | read-only Phase E catalogue, interactive |
| `/bridge-onboard --upstream` | skip everything except upstream wiring (see SKILL.md) |

---

## Edge Cases

- **Early exit** — partial setup is fine; `/bridge-onboard` resumes where
  the user left off (reads `bridge-config.yaml` for what's already done,
  `work/onboarding-state.yaml` for what's been decided in Phase C).
- **Already configured** — offer reconfigure (`--reset` for fresh start,
  or `--rescan` for incremental), or exit.
- **No GitHub at all** — fully supported. `integrations.github.enabled:
  false`, `assignee_me: ""`, `upstreams: []`. Skills that need GitHub
  warn at use-time, not setup-time.
- **Repos in multiple locations** — set `projects_root` to a common parent,
  or add stragglers manually to `ecosystem.yaml`.
- **Second instance for a separate org** — fully supported; each instance
  has its own ecosystem, config, and work log. Some users keep the user
  branch local-only for data isolation. See `docs/multi-instance.md`.
- **Reset for fresh onboarding** — `/bridge-onboard --reset` deletes
  `work/onboarding-scan.json` + `work/onboarding-state.yaml` + prompts to
  delete `bridge-config.yaml` (gitignored). Re-run starts clean.
- **Phase B permission denied for an opt-in source** — record as
  `error: permission_denied`, continue. Phase C skips suggestions that
  depend on the missing source; mentions them in Phase E with the
  permission requirement noted.

## Troubleshooting

| Problem | Fix |
|---|---|
| `gh` not installed | Ecosystem scan still works via local `.git/config`. Install `gh` later if you want GitHub features. |
| No GitHub at all | Leave `identity.org` empty + `integrations.github.enabled: false`. Onboarding completes; GitHub-dependent skills warn at use-time. |
| No repos found | Minimal `ecosystem.yaml` written. Add manually or `git clone` first, then `/bridge-onboard --rescan`. |
| `osascript` permission denied (Apple Mail / finance-app scan) | Grant in System Settings → Privacy & Security → Automation, then `/bridge-onboard --rescan`. |
| `/bridge` red | Usually missing `ecosystem.yaml` or `bridge-config.yaml` — error tells you which. |
| Wrong projects root | Edit `bridge-config.yaml` → `identity.projects_root`, then `/bridge-onboard --rescan`. |
| `validate-bridge.py` fails | `pipx install check-jsonschema` (the wrapper depends on it). |
| `validate-bridge.py` passes suspiciously fast | It **silently skips** all schema checks when PyYAML isn't installed — it returns an empty result set, not an error. Install PyYAML (`pip install pyyaml`) and re-run to get real validation. |
| Want to start over | `/bridge-onboard --reset` then `/bridge-onboard`. |
| `feature-discovery` is too noisy | `bridge-config.yaml.feature_discovery.enabled: false` or disable individual heuristics. |
| Phase B scan suggests a feature you don't want | `[l]` defers 30 days; decline 3× total to silence forever. |
