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
A  Quick Identity             ~90 sec   GATHER: purpose (from the door) + name/org/root/lang + origin + scope · then the confirm-back gate ([go] executes)
B  Discovery Scan             ~60 sec   permission-gated system scan (broader mode only; skipped if confined)
C  Smart Suggestions         ~2-3 min   evidence → feature recommendations (skipped if confined)
D  Quick-Wins                ~1-2 min  applies confirm-back defaults: work-system on (never re-asked) + first task from purpose (one quick ask ONLY if no purpose was given) · theme · agent soul/identity (deck-picked)
E  Feature Catalog          read-only   pointer to "what else Bridge can do" (full catalogue in the Phase-F preview / --features)
F  Validate + Preview        ~45 sec   capability check (whose skills run here), advisory schema check, HTML preview, then a LIVE /briefing --quick over the seeded task
```

Total: ~5 minutes for the confined default. On the fast path (a purpose given at the door)
the **only** write-approval is the single confirm-back `[go]` — Phase D then applies the
approved defaults without a second round of questions, landing on a seeded first task + a
live briefing. Give no purpose (demo / "not sure yet") and D1b adds one short first-task
question. 5-8 for a tailored broader setup.

---

## Phase A — Quick Identity

A tight identity block. **Steps 1–7 GATHER only — they decide, they do not write.** The
single commit point is the **confirm-back (step 8)**: on `[go]` it executes, in order, the
private-home re-home (if needed), the guard re-arm, the `user/{name}` branch, and every
config write. So "nothing's written yet" at step 8 is literally true, and `[adjust]` can
reopen any gathered field with nothing to roll back. Steps 9–10 (workspace / resource
advisories) fire only after `[go]`, once the branch exists.

1. **Name** — detect from `git config user.name`; offer it back. Becomes
   `identity.name` and the suffix of the user branch. If `git config
   user.name` is **empty**, don't silently proceed — ask the user for a
   name (and offer to set it via `git config --global user.name "<name>"`
   so future commits are attributed). Also **read `git config user.email`** — if
   it is empty, OFFER to set it (`git config --global user.email "<email>"`, never
   run silently); a fresh machine with no `user.email` otherwise breaks the Phase-F
   onboarding commit and strands every write uncommitted.
2. **GitHub org** — *optional*. Three valid answers:
   - Org name (e.g. `acme-corp`) → fills `identity.org`, enables GitHub features
   - "personal" → fills with the user's GitHub login, GitHub features enabled
   - **skip** (empty) → `integrations.github.enabled: false`, no GitHub anywhere
3. **Projects root** — where your repos live. Default suggestion:
   - With org → `~/Developer/{org}`
   - Without GitHub → `~/Developer` or `~/Code` (offer both, pick what exists)
4. **Language** — auto-detected from the user's first message; confirm
   only if ambiguous. Sets `language.conversation` and `language.artifacts`.
5. **Purpose — already captured at the front door.** In the common path the user
   reached Phase A by describing what they're here to do (front-door lane `[2]`, or a
   free-text answer to the opener). **Do not re-ask.** Write that sentence verbatim to
   `purpose.statement`, then **derive silently** — never as a visible questionnaire —
   both `purpose.focus` (a subset of the six catalog domains: `identity`,
   `communication`, `infrastructure`, `productivity`, `integrations`,
   `visualization`) and `user_profile` (`work | private | both`). The one soft confirm
   happens later, in the confirm-back screen (step 8) — not as a taxonomy menu here.

   Only if the user arrived **without** a purpose (picked `[1]` demo, or said "not
   sure yet") ask ONE light line — never the six-domain menu — and accept `[skip]`:
   > One line, if you have it — what will you mainly use this Bridge for? It just
   > orders what I lead with; everything stays available. `[type a line]` `[skip]`

   Purpose SUGGESTS/ORDERS/LABELS only — it never gates, hides, or removes a feature;
   every capability stays one `--add`/`enabled:` flip away. Empty purpose
   (`statement: ""` + `focus: []`, `user_profile: both`) reproduces today's exact
   flat, general-purpose behaviour — **zero regression**. Change anytime via
   `/bridge-onboard --purpose`.
6. **Resolve the private home (decide now, execute on `[go]`).** Work out where this
   clone pushes: `git remote get-url origin` (and `gh repo view --json
   visibility,nameWithOwner` if unsure). **If `origin` is a PUBLIC repo or a known
   upstream (e.g. `bks-lab/open-bridge`) — or `.bridge-origin` says `is_public: true` —
   the user's data must not live there.** Decide the path with the user, but do **not**
   execute it here — it runs on `[go]` at step 8:
   - **Re-home** to a new private repo (GitHub *Use this template → Private*, or the
     two-step `git remote rename origin upstream` then `gh repo create <you>/my-bridge
     --private --source=. --remote=origin --push`), **or**
   - **local-only** — the user explicitly keeps it local and never pushes.

   On `[go]`, a confirmed re-home also writes a slug-matched
   [`.bridge-origin`](../../../.bridge-origin) (`repo: <new private slug>`,
   `is_public: false`) so the first legitimate `user/*` push classifies PRIVATE even
   offline, instead of the guard fail-closing on an unverifiable remote. **Only ever
   write `is_public: false` for an origin confirmed private — never for a still-public
   origin** (that would make a leak easier, not harder).

   The `user/{name}` branch (`git checkout -b user/{name}` from the core/default branch)
   and a belt-and-suspenders guard re-arm (`git config core.hooksPath scripts/hooks` —
   Step 0 already did it) are part of the `[go]` execution too, **not** run here — so no
   `user/*` branch or private commit exists until the user confirms. **Never push
   `user/{name}` to a public origin** — CORE reaches a public upstream only via
   `/promote`. See [`../../../rules/push-guard.md`](../../../rules/push-guard.md).

**Upstream wiring — defer.** Keep `upstreams: []`. Mention in passing:
"Once `bks-lab/open-bridge` (public) or your own upstream is live, wire
it via `/bridge-onboard --upstream`". No Variant-Wahl prompt while the
upstream repos are not public yet.

7. **Scope consent gate — gather the choice (the write + routing happen on `[go]`).**
   The last thing gathered before the confirm-back: the user makes one explicit scan
   choice. This is the consent boundary: with no explicit "yes", the Bridge never
   scans — not now, not later. Render this verbatim:
   ```
   One choice before I look at anything beyond this folder — no wrong answer:

     Confined (default) — I stay in this Bridge folder: no scanning your other repos,
     apps, devices, files, or mail. You still get every feature; I just won't
     auto-suggest them. Broader lets me take a quick, per-item-permissioned look so I
     can suggest what fits what you already use (names + structure only, never content
     or secrets; findings stay local). Reversible anytime via /bridge-onboard --rescan.

     [1] Confined (default)   [2] Broader   [?] exactly what would broader look at?
   ```
   - **`[1]` Confined (default)** — records the intent to write `discovery.mode:
     confined` + `discovery.permissions: []` (written on `[go]`). Nothing on the machine
     is ever read; **after `[go]`, Phase B and Phase C are skipped → straight to Phase D.**
     The user keeps every feature; they enable what they want from the Phase E catalog,
     via `/bridge-onboard --add <feature>`, or by flipping the feature's `enabled:` flag.
   - **`[2]` Broader** — records the intent to write `discovery.mode: broader`; **after
     `[go]`, continue into Phase B**, where the existing per-source permission model applies.
   - **`[?]`** — answer from the Phase B permission prompt
     (`system-discovery.md`): which sources, default-on vs opt-in,
     names-and-structure-only, never content/secrets — then re-show the two
     options.

   An absent or unset `discovery.mode` means **confined** — no explicit
   consent, no scan.

8. **Confirm-back — reflect the plan before writing anything.** Good consulting ends
   the intake by playing the plan back. On ONE screen, recap what you derived — nothing
   is written until the user says go (this is both the trust/reversibility forcing
   function and a natural read-until-confirmed gate):
   ```
   Here's what I'll set up — nothing's written yet:

     Purpose    {statement}   (I'll lead with {focus domains})
     Your data  {public origin → "give it a private home first (~2 min)" |
                 private origin → "already private (repo), guard armed ✓" |
                 local-only → "staying local, never pushed"}
     Setup      branch user/{name} · work-system on · theme {auto} · first task seeded
     {Workspace  bind {n} repos into one project}   ← only if the multi-repo/org signal fired
     {Machine    {name} can host: fleet · always-on bots · scheduled jobs · a Bridge-Agent}   ← only if a machine/device signal fired

     [go]  [adjust]  [d] show me the demo first
   ```
   **On `[go]`, execute in this order** (nothing above has run — steps 1–7 only gathered):
   1. re-home to the private repo if the user chose it (+ write the slug-matched
      `.bridge-origin`), or confirm local-only — the private-home gate;
   2. re-arm the guard (`git config core.hooksPath scripts/hooks`, belt-and-suspenders to Step 0);
   3. `git checkout -b user/{name}` from the core/default branch;
   4. write the `bridge-config.yaml` skeleton (identity, `purpose.*`, `discovery.mode`);
   5. route: **Broader → Phase B** · **Confined → Phase D** (skip B + C). On the `[go]`
      path Phase D **never re-asks work-system** (approved right here) and **derives the
      first task from `purpose.statement`** without asking — *with one exception:* the
      empty-purpose path (`[1]` demo / "not sure yet"), where D1b still asks the one-line
      first-task question because there is nothing to derive. Apart from that empty-purpose
      ask, Phase D re-prompts only on `[adjust]→customize`;
   6. the step-9 workspace + step-10 resource advisories fire here (the branch now exists).

   `[adjust]` reopens any line — the gathered fields **and** the defaults shown on this
   screen (work-system on, theme) — nothing has executed, so there is nothing to roll
   back. `[d]` drops into `examples/agency` (restart there).

9. **Workspace opt-in — only when the signal fired, and only after the branch exists.**
   The workspace / overlay verbs are `user/*`-branch-gated, so this comes AFTER
   `git checkout -b user/{name}`. Offer it ONLY when the purpose statement or the
   free-text answer named a multi-repo / org signal (≥2 repos/engagements, "across
   projects", "both", "my team's/org's repos", "shared config", or a bare git-URL):
   > You said this Bridge is for {statement} — sounds like more than one repo. Bind
   > them into a named workspace so I treat them as one project? `[y]` set it up ·
   > `[o]` pull my org's shared config (I have a git-URL) · `[l]` later
   `[y]` → `skills/workspace` (`workspace create` + `subscribe … --role code`); `[o]` →
   `skills/bridge-overlay` (`/overlay add <git-url>`); `[l]` → record a deferred
   suggestion in `work/onboarding-state.yaml`; never hold the 5-minute path hostage.
   No signal → this beat never fires.

10. **Resource-offer advisory — connect a named machine to what it can host.** This is the
    OFFER-AWARENESS beat: a good consultant, handed a resource, connects it to what it can
    become. Fire it when the purpose statement or the free-text answer names a compute
    resource — `mac mini`, `spare machine/box`, `a server`, `home server`, `NAS`, or an
    intent like `put it to work` / `dedicate` / `always-on` / `keeps running`. **It is
    CONFINED-SAFE: derived from the user's own words, not a scan, so it fires on the default
    confined path too** — nothing on the machine is read, nothing on disk is touched. Surface
    the CORE machine-capability set with the real `--add` verbs — offer, never force:
    > You mentioned a machine you'd dedicate — nice. On a box like that I can (all CORE, all
    > opt-in):
    >   • **Run your fleet** — health, Wake-on-LAN, SSH, service inventory · `--add remotes`
    >   • **Host always-on bots/channels** — an assistant that keeps running as a launchd/
    >     systemd unit · `--add channels`
    >   • **Run scheduled jobs** — briefings, digests, syncs on a timer · `--add schedule`
    >   • **Host a persistent, addressable Bridge-Agent** — an A2A endpoint that fronts a
    >     persona so people or peer bridges can reach it · see `agents/` + `docs/representative-agent.md`
    >   • **Use it as a backup target** — model it in the backup topology (`infra/backups`;
    >     the executor is a separately-installed skill)
    >
    >   `[pick some]`  `[all]`  `[l] later`
    - **HONESTY BOUND — offer only what THIS repo ships as CORE.** The Bridge-Agent is the
      CORE *single-agent* A2A primitive (`agents/_runtime`, `a2a-sdk`); do **not** advertise a
      multi-agent agent *framework* as CORE. Backup is topology-data-model-only in CORE (the
      `/backup` executor is a separately-installed skill — say so). Do **not** offer
      `bridge-deck` (separate repo, not shipped here).
    - `[l] later` records a deferred suggestion in `work/onboarding-state.yaml`. **No
      machine/device signal → this beat never fires** — it is offer-triggered, never a nag.

**Output of Phase A (all produced on `[go]`, step 8 — steps 1–7 gathered only):**
- `bridge-config.yaml` skeleton — identity populated, all features off,
  `purpose.statement` + silently-derived `purpose.focus`/`user_profile` (empty if the user
  skipped), `discovery.mode` = the user's choice (`confined` if unset)
- `user/{name}` branch created and checked out; private home resolved (re-homed to a private
  repo, or explicit local-only)
- Routing: `[1]` Confined → Phase D (Phase B + C skipped) · `[2]` Broader → Phase B

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

2. **Run scans in parallel** with live progress per source. When invoking
   `scripts/system-discovery.py`, pass `--broader` (its scope-consent backstop
   refuses to scan under a confined/unset `discovery.mode`, exit code 3) along
   with the granted `--permissions` — e.g.
   `scripts/system-discovery.py --broader --permissions git_config,developer_dir,os_and_apps`:
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

2. **For each evidence-matching suggestion** (S1–S14 in
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

**Fast path — no re-ask.** When D1 is reached from the Phase-A confirm-back `[go]`
(the normal onboarding path), the user already approved "work-system on" on that
screen — so **apply the `[y]` default directly** and drop straight to the scaffolding
+ D1b below; do **not** re-render the prompt (that second ask was the redundant beat).
Show the `[y]/[c]/[n]` pitch **only** when D1 is entered *without* that approval —
`/bridge-onboard --add work`, or an `[adjust]→customize` request — or to honour a user
who used `[adjust]` to say they want cold-start mode after all.

**Pitch (shown only on the paths above):**
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
- Create directories: `work/{tasks,streams,done,archive,drafts,imports}` (canonical — matches `scaffold-user.sh` and Phase F's own verify)
- Generate `work/log.md` from `work/templates/week-skeleton.md` (fresh week header + today's day-block)
- Generate `work/board.md` — empty board with header
- Set `work.enabled: true` in `bridge-config.yaml`
- **D1b — seed one real first task** so the very first `/briefing` lands on a populated
  board instead of "Board is empty. Create tasks?" (this is what makes first-session
  value non-thin).
  - **When `purpose.statement` is set** (the normal `[2]`/free-text path) → **don't ask
    again.** The user already told you what they're here to do at the door, so derive the
    first task straight from it — no second question. `slug` from the purpose, `origin` =
    the purpose sentence; then mention it in one line ("Seeded your first task from what
    you told me: …") rather than prompting.
  - **When `purpose.statement` is empty** (arrived via the demo, or said "not sure yet")
    → there is nothing to derive from, so ask ONE line:
    > One thing you're working on right now? I'll seed it as your first task so tomorrow's
    > briefing has something to stand on. `[type it]` `[skip]`
  - **Field fill (both paths)** → copy `work/templates/STATUS.md` to
    `work/tasks/<slug>/STATUS.md` and fill EVERY required field with no leftover
    placeholders: `slug` = the folder name, `type` = a fitting enum (default `admin`),
    `status: doing`, `created`/`last_updated` via `date +%Y-%m-%d`, `sync.bridge_only:
    true`, and a real one-line `origin` (the purpose sentence, or "Onboarding
    first-session intake" on the empty-purpose path).
  - **`[skip]`** (empty-purpose path only) → seed a single tickable "Getting oriented"
    starter task whose Next Steps are the real `/bridge-onboard --features` / `--add`
    / `--rescan` commands.
  - **Always** append one factual onboarding-completion row to today's day-block in
    `work/log.md`, then run `python3 scripts/gen-board.py` so `board.md` Doing shows ≥ 1.
    Consent-free (derived from the user's own words, no scan) and `bridge_only` (no GitHub
    dependency).

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

**Phase E emits a POINTER, not the full wall.** At ~minute 4-5 a ~190-line terminal
catalogue is peak cognitive load at lowest attention — and it is re-rendered, better, as
the Phase F HTML preview (which confined users get too). So here, print only:

- `purpose.statement` as a one-line header (when set), and
- a 3-line pointer:
  ```
  Everything else is one keystroke away:
    /bridge-onboard --features    — browse the full catalogue
    /bridge-onboard --add <name>  — turn one on
  ```
- optionally, just the **names** of the `purpose.focus` lead-band groups (max ~5 lines)
  so a focused user sees their most-relevant area without the firehose.

The full grouped catalogue — with purpose banding per `feature-catalog.md` § Purpose
Banding (lead band **"Most relevant to '{statement}'"**, dimmed remainder **"Beyond your
focus"**) — lives in the Phase F HTML preview and `/bridge-onboard --features`. Nothing is
removed, hidden, or gated; banding ORDERS and LABELS only. **Empty purpose → today's flat
catalogue, byte-for-byte.**

**Honesty closer — gate the proactive-surfacing promise on `discovery.mode`.** The
`feature-discovery` evidence heuristics only run under `broader`. So:

- **broader** → the closer may promise weekly evidence-based suggestions.
- **confined (default)** → do **not** promise "I'll surface features weekly from new
  evidence" — those heuristics never run. Say the truth: *"You drive activation —
  `/bridge-onboard --features` to browse, `--add <name>` to turn one on. (I still
  resurface anything you deferred, and honour `--add`.)"*

**Do not ask anything here.** Phase E is purely informational — the "here's what else
exists" pointer, not a second survey.

---

## Phase F — Validate + Commit + Preview

1. **Scaffold the USER structure** — `bash scripts/scaffold-user.sh`
   (idempotent: creates only what's missing — `work/{tasks,streams,done,
   archive,drafts,imports}`, `rules/user/`, `protocols/standing-orders/` +
   the cluster-wrapper instance dirs; dirs + `.gitkeep` only, never PII).
   Gives a fresh clone the empty USER tree even when it shipped CORE
   templates only. `--dry-run` to preview.

2. **Verify required files exist:**
   - `ecosystem.yaml`, `bridge-config.yaml` (always)
   - `work/{log.md,board.md}` and `work/{tasks,streams}/` etc. if `work.enabled: true`
   - `work/onboarding-state.yaml` if Phase C ran
   - `.gitignore` includes `work/onboarding-scan.json`

3. **Capability check — whose skills will actually run in this instance?**

   One command, and onboarding is the moment it matters: this wizard is where a
   **second** instance is born, and the second instance is where skill shadowing
   starts. Nothing about the first instance hints at it.

   ```bash
   readlink ~/.claude/skills    # empty/absent = correct, this is the good case
   ```

   Resolve it (and any entries inside, if it is a real directory). If it lands
   **inside a Bridge repo** — root carries `AGENTS.md` + `skills/` — report it,
   never fix it silently:

   - **Another Bridge instance** → **P0**. The instance you are setting up right
     now will run *that* instance's skills, not its own — including this wizard.
     Say it plainly: *"`~/.claude/skills` points at `<path>`. The user level
     overrides the project level, so that Bridge's skills — including its
     `scope: org` ones — will run inside this one, and this instance's own copies
     never load. It fails silently: you'd get plausible output from the wrong
     instance's skills."*
   - **This repo** → **P1**. This instance is about to shadow every other Bridge
     on the machine. Latent while it is the only one; it breaks the *next* one.

   **The remedy is the user's call, not yours** — it touches `$HOME`, and scripts
   or launchd/systemd units commonly resolve that same path as a *filesystem
   location* (`~/.claude/skills/<name>/scripts/…`). Removing the pointer would
   break those silently. Offer, in order:

   1. `grep -rl '\.claude/skills/' ~/bin ~/Library/LaunchAgents /etc/systemd 2>/dev/null`
      — find what resolves the path, repoint it at the instance's `skills/` first.
   2. `mv ~/.claude/skills ~/.claude/skills.disabled-<date>` — **`mv` or `rm`,
      never a trash utility that dereferences symlinks**: following the link would
      move the target repo's entire tracked `skills/` tree instead of the pointer.
   3. Nothing else to do — this repo's committed `.claude/skills → ../skills`
      already loads its skills whenever the CWD is inside it. To get a standalone
      tool skill into any directory, ship it as a **plugin**, not a symlink.

   Deeper: `/bridge-audit --check skill-shadowing` (drift list per colliding
   name), [`docs/multi-instance.md` § Capability
   Isolation](../../../docs/multi-instance.md#capability-isolation).

   > **Known limit — do not oversell this check.** If this wizard is *itself*
   > being shadowed, the other instance's older copy is what runs, and it may not
   > carry this step at all. The check that does not depend on which skill version
   > loaded is the session-start tripwire in `rules/session-start.md` — `rules/`
   > is read from the repo and cannot be shadowed. This step catches the case at
   > setup time; that one catches it forever.

4. **Schema validation** — run it, but it is **advisory at onboarding, never a
   red wall at "you're set up":**
   - Run `python3 scripts/validate-bridge.py`
   - The Bridge ships JSON Schema Draft 2020-12 for personas, themes,
     channels, remotes, mandants, calendars, contexts, projects.
   - If `check-jsonschema` is missing (it's only *recommended*), the validator now
     emits a **yellow advisory and exits 0** — offer `pipx install check-jsonschema`
     to enable it, don't block. A genuine schema failure (tool present, YAML
     malformed) still fails — fix those.

   **Hooks need no separate install step:** the `core.hooksPath=scripts/hooks`
   set during setup arms BOTH `pre-push` (leak guard) and `pre-commit` (task-sync
   + logging reminder) for every tool. Do NOT run `pre-commit install` — the
   `pre-commit` framework refuses when `core.hooksPath` is set, and
   `.pre-commit-config.yaml` is for CI / manual `pre-commit run --all-files` only.

5. **Commit** all generated files on `user/{name}` branch:
   ```
   chore: bridge onboarding for {name}

   Phase A: identity ({name}, org={org or '-'}, projects_root={path})
   Phase B: discovery scan ({N} sources, {M} findings)
   Phase C: {accepted_count} features enabled, {deferred_count} deferred
   Phase D: work-system={on/off}, theme={theme}, agents={role_list}
   ```

6. **Generate preview** — read
   [`references/preview-generator.md`](preview-generator.md) and write
   `work/bridge-preview.html`. The preview has two sections:
   - **Activated** — config + repos + agents + standing orders
   - **Suggested for later** — deferred features + nothing-found
     features, each with the `/bridge-onboard --add <feature>` re-entry
     command

7. **Open in browser** (`open` on macOS, `xdg-open` on Linux).

8. **Land the payoff — run the first `/briefing` LIVE, don't just suggest it.** If
   work-system is on and D1b seeded a task, run `/briefing --quick` inline now (local,
   network-free) so the user *sees* their own in-flight work read back — Doing ≥ 1, the
   seeded task surfaced as a goal — instead of being told to try a command that would
   land on an empty board. Then offer the next steps:
   ```
   You're set up — here's your first briefing ↑. From here:

     /briefing                  — your daily briefing (what changed, what's in flight)
     /bridge-onboard --features — explore what else Bridge offers
     /bridge-onboard --add <X>  — activate any feature on demand
     /knowledge-repo-init       — only if you marked it for follow-up
   ```
   **Honesty (gate on `discovery.mode`):** only under `broader` add "I'll proactively
   suggest features when new evidence appears." Under **confined** (default), do NOT —
   the heuristics don't run; instead: "You drive activation with `--features` / `--add`."

9. **Run `/bridge-status`** — green = ready, yellow = non-critical warnings,
   red = follow the error message. (Bare `/bridge` is intentionally not a trigger.)

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
