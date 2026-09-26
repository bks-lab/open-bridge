---
name: board-pilot
description: >-
  Board-driven implementation pipeline: polls a GitHub Project, arms an item when
  dragged into the trigger column, advances it stage by stage to a human-gated
  draft PR. Stages configured per project in workflow/projects/<slug>.yaml.
  Trigger: "/board-pilot", "board pilot", "auto-implement from board", "pipeline
  runner".
allowed-tools:
  - Bash
  - Read
  - Glob
  - Grep
metadata:
  scope: core
---

# board-pilot

A **generic, board-driven implementation pipeline**. It watches a GitHub Project,
and when a human drags an item into the trigger column it drives that item
autonomously — stage by stage, each stage a Bridge primitive — to a **human-gated
draft pull request**, then stops. No project specifics live in the engine; a
project declares its own pipeline in config. The same engine runs a heavy project
(full implement→verify→review) and a light one (a two-stage doc edit) unchanged.

> **What it is NOT.** Not a merge bot, not a board-sync tool (that is
> `tracker-sync`), not a write executor for board fields (that is
> `github-projects-manager`). board-pilot only *advances* an item to a draft PR
> and hands the merge decision back to a human.

## Mental model

- **Poller-fast / worker-slow split.** A cheap cron tick (`Engine.tick()`) runs
  often (~1 min). It contains **no LLM** — it only reads the board, arms new
  items, and advances each in-flight item by exactly **one** stage under a
  per-item lock. The slow work (a `claude -p` implement run, a workflow harness)
  happens *inside* a dispatched stage; the next tick re-reads the board to
  confirm before advancing again (confirmed-advance). A 1-minute poll therefore
  never double-dispatches a 20-minute job.

- **Decision A — engine-owned `Pipeline` vs human-owned `Status`.** Each board
  item carries two fields:
  - **`Status`** — the human lifecycle column (e.g. `Backlog → Ready → Ready for
    Development → In Progress → Blocked → In Review → Done`). A person owns it;
    dragging an item into the **configured trigger column**
    (`trigger.on_status`) is the only arm signal the engine reads. Which field
    this is (`board.status_field`) and which value arms are **both config** —
    the engine hardcodes neither. It *writes* `working_status` / `park_status` /
    `pr_status` here, but arming never depends on them.
  - **`Pipeline`** — the engine's program counter (`queued → implementing →
    verifying → … → pr-open`). The engine owns it. Once an item is armed, the
    engine tracks progress through `Pipeline` and **ignores** further `Status`
    moves, so a human shuffling cards mid-flight cannot corrupt the state
    machine. `Pipeline` is also the **durable arm marker**: arming is gated on
    `pipeline is None`, so a wiped snapshot can never re-arm an in-flight item.

- **STOP at the PR gate.** The last stage carries `gate: human`. When it
  succeeds, the engine opens **one draft PR** (idempotent), sets `Status` to the
  configured `pr_status` (`In Review`), and stops. The engine **never** sets
  `done_status` — merge and Done are a human's, always.

- **Fresh session per stage (fresh eyes).** Every model stage — `spec`,
  `implement`, `review` — is a separate `claude -p` with **no session carried in**
  (no `--resume` / `--continue` / `--session-id`). The reviewer therefore judges the
  **artefacts** — the diff, the plan file, the requirement — and cannot see the
  implementer's reasoning; state crosses stages **only through files** (`plan.md`, the
  diff, the reject note, `verdict.json`). `verify` and `pr` run **no model** at all.
  The one shared context is the target repo's own `CLAUDE.md`/settings via
  `--setting-sources project` — static, identical for every stage, never a stage's
  transient reasoning: this is *fresh eyes*, not *zero shared context*. The property is
  enforced purely by the **absence** of a resume flag (`stages/_lib.sh` `bp_claude`) and
  pinned by `test_the_fence_starts_a_fresh_session_every_stage`. Per-stage detail —
  role, tools, prompt, requirement, guards — is in `references/agents.md`.

## Per-project config

A project opts in by adding `board:` + `pipeline:` blocks to its
`workflow/projects/<slug>.yaml` (read `_template.yaml` + `_schema.yaml` there
first — house rule). Shape the engine parses (`engine/config.py`):

```yaml
board:
  status_field: Workflow        # the LIFECYCLE field. MANDATORY unless yours is
                                # literally named "Status" — see the trap below.
  pipeline_field: Pipeline
  repo: <owner>/<repo>
  repo_path: "~/path/to/the/clone"             # the clone stages run in
  criteria_dir: "skills/board-pilot/criteria"  # relative → anchored on repo_path
  branch_template: "bridge/{project}/{item_id}"

pipeline:
  project: <slug>
  trigger:
    on_status: "Ready for Development"   # the ONLY human column that arms an item
  working_status: "In Progress"   # written at ARM — a taken card leaves the free column
  park_status: "Blocked"          # written at EVERY park — a parked card stops looking fresh
  pr_status: "In Review"          # written at the gated PR stage
  done_status: "Done"             # the engine MUST NEVER set it — and HALTS if a human does
  concurrency: 1                  # max items advanced per tick
  require_issue: true             # refuse to arm a card with no issue behind it

  rework:
    max_rounds: 3                 # the ONLY real per-item terminator (see budget below)
    bounce_field: Bounces         # board Number field — the durable reject counter

  budget:
    max_tokens: null              # INERT — see § Guards. `null` is the honest value.

  record:                         # the transparency layer — references/transparency.md
    enabled: true
    events: [armed, stage, reject, park, gate]
    sticky_marker: "board-pilot:run"
    templates_dir: "templates"    # relative → anchored on the SKILL ROOT (not repo_path!)
    max_body_chars: 60000
    scan: redact                  # redact | off — the PR body is always fail-closed
  evidence:
    dir: "{state_dir}/evidence/{item_id}"
    require_deterministic: true   # an agent:/skill:/workflow: stage may NEVER be an evidence source

  stages:
    - name: spec                  # the stage ID — the attribution key in the record
      run: "cmd:bash skills/board-pilot/stages/spec.sh"
      criteria: "spec.md"         # → $CRITERIA_FILE; path + SHA cited in the record
      on_success: implementing    # the Pipeline value to set on pass
      on_fail: { then: park }

    - name: implement
      run: "cmd:bash skills/board-pilot/stages/implement.sh"
      criteria: "implement.md"
      on_success: verifying
      on_fail: { retry: 1, then: park }

    - name: verify
      run: "cmd:bash skills/board-pilot/stages/verify.sh"
      evidence: true              # the ENGINE tees stdout/stderr/exit code itself
      on_success: reviewing
      on_reject: { to: implement }       # red tests = REWORK, durably counted — NOT rewind
      on_fail: { retry: 1, then: park }  # verifier itself crashed = infra, capped

    - name: review
      run: "cmd:bash skills/board-pilot/stages/review.sh"
      criteria: "review.md"       # ← the knob for "the reviewer rejected for the wrong reason"
      on_success: pr-ready
      on_reject: { to: implement, on_exhausted: park }

    - name: pr
      run: "cmd:bash skills/board-pilot/stages/pr.sh"
      on_success: pr-open
      gate: human                 # STOP after this stage
```

Handler refs are dispatched by the real `ClaudeStageRunner`: `skill:` /
`workflow:` / `agent:` map to a detached `claude -p` / harness call, `cmd:` to an
argv subprocess. **Board-sourced values are always passed as argv, never
interpolated into a shell string.**

Unknown keys under `record:` / `evidence:` are **rejected at load**, naming the
offender: a knob that is silently ignored is invisible, and silently ignoring
`require_issue` arms draft cards.

### Two traps in the grammar

**1. `on_reject.to:` is a STAGE ID — `on_fail`'s `rewind_to:` is a BEFORE-KEY.**
They look alike and are validated by different code paths (`config.py`). This
asymmetry has already caused one critical off-by-one; it is documented here so
the next one is caught at load instead of in production.

| Edge | `to:` names | Validated against | On a bad value |
|---|---|---|---|
| `on_reject: { to: implement }` | a **stage id** (`name:`/`id:`/`uses:`) | the stage-id map, must be **strictly upstream** | `ValueError` naming the stage + target |
| `on_fail: { then: rewind, to: implementing }` | a **before-key** (a `Pipeline` value, i.e. some stage's `on_success`) | the before-key set + terminal | `ValueError` listing valid before-keys |

Both raise at load, never stall at runtime. Note the pairing in the chain above:
`on_reject: { to: implement }` targets the *stage* `implement`, whose before-key
is `implementing` — **the same edge would be spelled `implementing` under
`on_fail`**. Prefer `on_reject` for "the work was wrong" (it has a durable
counter, a cap and a test); keep `on_fail` for "the tool crashed".

**2. Relative paths in the same block anchor on two different bases.**

| Key | Relative base | Why |
|---|---|---|
| `board.criteria_dir` | **`repo_path`** (the target clone) | criteria are read in the repo the stages edit |
| `record.templates_dir` | **the skill root** | the record format ships with the skill, not the target |

Absolute paths sidestep both. A relative `templates_dir` of
`skills/board-pilot/templates` is a common mistake — it resolves under the *skill
root* and raises at startup.

### Stage IDs and the `run:` path

`config.py` accepts `uses:` **or** `id:` **or** `name:` for the stage ID. **Pick
one idiom and keep it** — the stage ID is the attribution key in the record.
These docs use `name:`.

`cmd:` stages run with **`cwd = repo_path`**, so a bare `run: "cmd:bash spec.sh"`
resolves inside the *target clone* and fails `rc=127`. Write the path the stage
actually lives at. Because this skill is `scope: core` it ships **into** the
target repo, so `skills/board-pilot/stages/spec.sh` resolves there.

> **`board.stages_dir` is INERT.** It appears in some drafts and **no engine code
> reads it** (`grep -rn stages_dir engine/` → nothing). Setting it changes
> nothing; it will not prefix your `run:` paths. Put the path in `run:`.

### The stage environment

The engine exports these to every stage:

| Var | Meaning |
|---|---|
| `$CRITERIA_FILE` | the resolved `criteria:` file — the standard this stage judges against |
| `$EVIDENCE_DIR` | this item's evidence dir; the engine tees `<stage_id>/` beneath it |
| `$BOUNCES` | the durable rework round, so a stage can name its own round |
| `$VERDICT_FILE` | the reject sidecar — **only** for a stage that has a reject edge |

Some stages also read **operator-configured** vars the engine never sets — e.g.
`verify.sh` requires `BP_VERIFY_CMD` (the suite command for the target repo) to
already be exported by the unit (the scheduler's `EnvironmentVariables`/env block,
not this table, and not the per-project YAML — there is no `stages[].env:` key
today). There is **no heuristic fallback**: an unset or empty `BP_VERIFY_CMD` is a
fail-closed refusal naming the knob, never a guessed suite. See § Guards.

## Guards

Split honestly. The first table is **engine-enforced and fail-closed** — the
engine itself refuses. The second is **partial / by-convention**: real, useful,
and *not* a guarantee. Nothing below is dressed up as more than it is.

### Engine-enforced

| Guard | Where | What it prevents |
|---|---|---|
| **PAUSED kill-file** | `guards.is_paused` | A single `PAUSED` file in the state dir halts the whole engine on the next tick — instant, no redeploy. |
| **Atomic snapshot** | `snapshot.save_atomic` | The board snapshot is written temp-then-`os.replace` + `fsync`. A half-written snapshot is impossible → no mass re-arm. |
| **Lock liveness via `kill -0`** | `lock.Lock` | A per-item lock carries pid + heartbeat. Reclaimed **only** when the holder is BOTH heartbeat-stale AND pid-dead — so a swap-starved worker is not falsely reclaimed. |
| **argv-safe handlers** | `ClaudeStageRunner` | Board ids/titles never reach a shell as a string; strict allowlist (`valid_item_id`) parks anything that doesn't match `^[A-Za-z0-9_-]+$`. |
| **Draft PRs only** | `pr` stage | The terminal stage opens a **draft** PR — never a ready-for-merge one. |
| **Byte-0 reject marker** | `parse_reject` | The **read-back hijack**: a record that quotes a reject note being fed to the code writer as its own feedback. Anchored at byte 0, so a markdown quote (`> ` prefix) can never match. Probe + table: [`references/transparency.md`](references/transparency.md). |
| **Options preflight** | `preflight_options` | Endless re-dispatch of the most expensive stage. Every writable `Pipeline` value **and** `working`/`park`/`pr_status` is checked against the live board at startup; a value the board lacks raises **before** any spend, instead of `KeyError`-ing inside the dispatch loop forever. |
| **Preflight transient-vs-permanent split** | `cli.run` + `GhCliError.is_transient` | A rate-limited or 5xx `gh` call during Engine construction (the first live board reads of a tick) is the API's fault and clears on its own: caught, folded into one quiet ledger note, tick exits 0 — the scheduler's own timer IS the retry. Measured before the fix: **736 crashes in one night**, each relaunching straight back into the same rate limit. A permanent preflight failure (missing field/option, bad auth scope) stays loud and raises unchanged — a quiet skip there would hide a board that can never work behind a healthy-looking ledger. |
| **Bounded board reads** | `gh_board.py` | `item-list` requests a capped page (100, not 1000 — GraphQL point cost is charged for the *requested* page size, not the returned rows) and raises rather than silently processing a possibly-truncated board. The reject-note read-back (`gh issue view`, one call per item) runs **only** when `bounces > 0` — an item that never bounced has no note to read. `field-list` is fetched **once per tick process** and cached, not once per field name. Together these are what let a 6-item board's 60 s poll live inside a shared rate-limit budget instead of paying it out 10x on every tick. |
| **Rewind cap over a durable counter** | `tick.py` + `bounce_field` | The **unbounded LLM loop**. The backward edge bumps the durable board counter and parks at `max_rounds` instead of resetting in-memory attempts. Measured before the fix: **40 paid runs in 40 ticks**, counter at 0, never parking. |
| **Blind-rework park** | `tick.py` | Burning the whole rework budget on **nothing**. `bounces > 0` and no reject note reached the item (lost comment / denied read-back) → park, loud, zero spend. Makes a silent failure audible. |
| **Verify fail-closed, no suite fallback** | `verify.sh` | An unset or empty `BP_VERIFY_CMD` refuses immediately, naming the knob and its home (the unit env) — **no heuristic guess** of a suite from the repo's shape. A guessed `python3 -m pytest -q` once ran on a box whose `python3` had no pytest; the rc=1 was misread as a red suite and burned a paid rework round on a failure no repo change could fix. `rc` 126/127 (cannot execute) also refuse — `on_fail`, never the reject edge; only `rc` 1–125 (the suite ran and found something) writes the reject verdict. |
| **Two-armed empty-diff guard** | `implement.sh` | An empty staged diff on a branch still at base dies (nothing was implemented; passing it forward would green a suite that tested nothing and open an empty PR). The same empty diff on a branch already ahead of base — a rework round whose rejection cause lives outside the repo — is convergence, not failure: it succeeds without a new commit but still pushes idempotently, healing a prior round whose push failed after its commit. Origin is therefore current on every exit-0 path of the only stage that pushes — verify judges the same tree the PR will carry. |
| **Foreign-commit sweep** | `implement.sh` | Before the model runs, every commit in `origin/<base>..HEAD` must carry the pipeline's own `board-pilot <item-id>` marker; one unmarked commit dies the stage. A poisoned item branch (junk pushed by anyone with repo access, DWIM-adopted by `git switch` on a fresh clone) can neither ride a do-nothing round to the PR gate nor cost a paid model run. The marker is a tripwire, not authentication — push access can forge it; the boundary that actually holds is who has push access. |
| **Engine-written evidence** | `claude_runner._spawn` | **Fabricated verification.** The parent tees stdout/stderr/exit code; the evaluated agent never touches the file. `require_deterministic` refuses to let a non-`cmd:` stage be an evidence source. Without this, `require_evidence` is an existence check sold as a verification gate. |
| **Draft cards never arm** | ARM gate + `require_issue` | A full LLM run on a card that can hold no `Closes #N`, no PR link and no comment. Refused (not parked, so it self-heals the moment the card grows an issue) with **zero** stage calls. |
| **Human `Done` halts** | dispatch gate | The engine overwriting a human's terminal signal. `done_status` was always "never SET"; it is now also "STOP if set". |
| **Record never breaks the run** | `emit_guarded` | A failing record sink turning a **successful advance** into a misleading skip — and re-running the most expensive stage every poll. Every hook is individually guarded and fires **after** its latch. |

### Partial / by-convention — do not rely on these as guarantees

| Not-a-guard | Reality |
|---|---|
| **`budget.max_tokens`** | **INERT.** `claude_runner` hardcodes `tokens=0` on both real paths, so cumulative spend is always 0 and the ceiling never bites. `guards.TokenBudget` persists the counter durably and correctly — it is a structure **awaiting token metering**, not a cap. Set it to `null`; a number implies a ceiling that does not exist. **The only real per-item terminator is `rework.max_rounds`.** |
| **Redaction** | A **regex denylist, not gitleaks**. It catches token shapes it already knows plus an absolute-home-path rule. Better than the nothing that scans prose today; not a secret scanner. |
| **PR-body scan** | Fail-closed (hit → exit 1 → no PR → park) — but the **scanner is engine-owned while the invocation lives in the shipped `pr` stage**. Point the `pr` stage's `run:` elsewhere and nothing scans the body. |
| **`cmd:` = determinism** | `cmd:` proves the **engine** owned the pipe, not that no model ran. A `cmd:` script may invoke one internally; `require_deterministic` cannot see that. |
| **Config ↔ board-option sync** | The preflight checks the values the engine may **write**. Everything else — renamed columns, options a human adds later, the registry's own field lists — can still drift silently. |
| **Protected branches** | There is **no built-in denylist in the engine**. The shipped stage scripts refuse protected branches before any spend, and `branch_template` keeps work on the item's own branch — both are stage/config responsibility, not an engine invariant. |

## Human gates (never crossed autonomously)

- **Never auto-merge.** The engine stops at the draft PR; merge + Done belong to
  a human, always.
- **Never push `main` / `development` / `dev`.** Stages push only to the item's own
  feature branch (`branch_template`, e.g. `bridge/<project>/<item_id>`). Enforced by
  the project's stage commands + the template — there is **no built-in protected-branch
  denylist in the engine yet**, so a misconfigured `branch_template` is the config
  author's responsibility.
- **Board writes via the `gh` CLI.** `GhBoardClient` sets `Status` / `Pipeline` with
  `gh project item-edit`, resolving option ids **live** from `gh project field-list`
  (never hardcoded, never a hand-rolled GraphQL mutation). It needs the `project` write
  scope (`gh auth refresh -s project`). *(It does not currently route through the
  `github-projects-manager` skill — it talks to `gh` directly.)*
- **`done_status` is read-only to the engine.** It exists in config purely so the
  engine knows which column it must *never* set.

## Architecture (ports + adapters)

The engine depends on two ports (`engine/interfaces.py`), each with a Fake (for
tests) and a real adapter (for production):

- **`BoardClient`** — `FakeBoardClient` (in-memory) · `GhBoardClient` (GitHub
  Projects v2 straight through the `gh` CLI — **not** via the
  `github-projects-manager` skill; see § Human gates).
- **`StageRunner`** — `FakeStageRunner` (scripted, records every call) ·
  `ClaudeStageRunner` (detached `claude -p` / harness / argv).

`engine/tick.py` is the whole state machine; everything else is config, guards,
or I/O. Tests inject the Fakes, so the entire process (trigger column → stages →
draft PR → STOP) runs deterministically with zero side effects.

## Run the tests

```bash
cd skills/board-pilot && python3 -m pytest tests/ -q
```

`tests/test_acceptance.py` is the headline contract (trigger column → exactly one
draft PR → `pr_status` → engine never sets Done → subsequent ticks are no-ops).
The rest cover arming, concurrency, retry/rewind/park, the durable rework cap,
PAUSED, lock reclaim, the byte-0 reject parser, the options preflight, the
evidence tee, redaction, the record layer, the `verify.sh` exit-code contract
(`test_verify_contract.py`), the two-armed empty-diff guard
(`test_implement_emptydiff.py`), and the rate-limit hardening — bounded page
size, bounces-gated comment read-back, per-process field-list caching, the
transient-vs-permanent preflight split (`test_rate_limit.py`).

**339 tests across 31 files, ~27 s, no network** (measured 2026-07-16 — re-run it
rather than trusting this line; a stale count here is exactly the drift this
section once carried).

## Install on a scheduler host (launchd / systemd / cron)

The poller is a cheap cron-style tick — run it on any always-on host. It is a
scheduled `--once` job (~60 s interval), not a long-lived daemon: each tick is
independent and idempotent, so a missed or overlapping run is harmless (the lock
+ durable `Pipeline` field absorb it).

### Board prerequisites (do these FIRST — the engine refuses to start without them)

The engine reads and writes a real board. Every value it may write must already
exist as a live option, or the options preflight raises at startup (by design —
that is the good failure). In order:

1. **Name the lifecycle field.** Set `board.status_field` to whatever your
   lifecycle field is actually called.

   > **The `status_field` trap.** `cli.py` defaults `status_field` to **`"Status"`**.
   > On a board whose lifecycle field is named something else (e.g. `Workflow`)
   > while a *built-in* `Status` field also exists, the engine reads the wrong
   > field, sees the trigger value nowhere, and **silently never arms**. No error,
   > no log line, no work. If items never arm, check this first.

2. **Add the trigger + engine-written options to the lifecycle field.** The
   engine writes `working_status`, `park_status` and `pr_status`; it only *reads*
   the trigger and never writes `done_status`. With the config above that means
   these must exist as options, spelled **exactly** as configured:

   | Option | Written by | Why it must exist |
   |---|---|---|
   | `Ready for Development` | **human only** | `trigger.on_status` — the arm command |
   | `In Progress` | engine | `working_status`, written at ARM |
   | `Blocked` | engine | `park_status`, written at every park |
   | `In Review` | engine | `pr_status`, written at the human gate |
   | `Done` | **human only** | the engine never sets it — and halts if it is set |

   Deliberately **not** the trigger: a grooming column such as `Ready`. Cards
   already sitting there must not start running the moment you arm the poller.

3. **Create the `Pipeline` field** — single-select, engine-owned, one option per
   pipeline value the chain can write. For the chain above:
   `queued`, `implementing`, `verifying`, `reviewing`, `pr-ready`, `pr-open`,
   `parked`.

4. **Create the bounce field** — a **Number** field named to match
   `rework.bounce_field` (e.g. `Bounces`). **Mandatory, not optional:** it is the
   durable rework counter and the only real per-item terminator. Missing → loud
   startup crash.

5. **Two manual clicks the API cannot do for you.** Field visibility, column
   grouping and swimlanes are **per-view UI settings, not settable via YAML or
   API**. If your project has only a table view, "the phase is visible on the
   board" is not true until a human creates a **board-layout view** and makes
   `Pipeline` visible. The data is there either way; the two clicks are a build
   step, not a footnote.

6. **Grant the board write scope:** `gh auth refresh -s project`.

### Wire the poller

1. Add the `board:` + `pipeline:` blocks to the target `workflow/projects/<slug>.yaml`,
   and keep that file's own `fields:` / `state_map:` in step with the options you
   just created — `github-projects-manager` and `tracker-sync` read exactly
   that block, and it drifts silently.
2. Schedule one `python3 -m engine.cli --project <yaml> --state-dir <dir> --once`
   per project (launchd `StartInterval` / systemd timer / cron). On macOS, load it
   into the per-user GUI domain so the stage runner can reach the login keychain —
   see `assets/com.example.board-pilot.plist`. Declared status is never trusted,
   the service manager is (the `deploy-reconciliation` rule).
3. **Baseline-gate every (re)deploy.** Before bootstrapping/reloading the unit,
   prove `BP_VERIFY_CMD` runs **GREEN on the deploying box**, against the target
   repo's base branch (a detached temp worktree keeps a live pipeline's checked-out
   branch untouched), and **abort the deploy** — before the reload, so a failed
   gate leaves the running unit as-is — if it is red. `verify.sh` has no baseline
   of its own; it attributes every red to the agent. Without this gate, a
   box-level red (a missing interpreter module, a broken tool) becomes a rework
   verdict, burns a paid LLM round chasing a failure no repo change can fix, and
   parks the item after an empty diff. A comment claiming "measured green" proves
   nothing the moment it was measured on a different machine than the one that
   actually runs the unit — only a gate that runs on the real deploying box, at
   deploy time, does. Build this into your deploy script; there is no shipped
   generic one (the engine only ships the unit template, not its installer).
4. Drop a `PAUSED` file in the project's state dir to halt instantly; remove it
   to resume.
5. Verify live: `launchctl print gui/$(id -u)/<label>` (or `systemctl --user
   status <unit>`) and tail the state dir (`prev.json`, `budget.json`, `locks/`).

> The `ClaudeStageRunner` / `GhBoardClient` adapters + the CLI entrypoint are the
> production wiring the build workflow fills in; the deterministic test suite
> exercises only the Fakes.

## SAFE live-smoke recipe

Prove the full loop end-to-end against a **throwaway / personal** repo and
project — **never** against a real customer or partner board:

1. Create a scratch repo you own (e.g. `<you>/board-pilot-smoke`) and a scratch
   GitHub Project with a lifecycle single-select + a `Pipeline` single-select.
   Register it as a temporary `workflow/projects/board-pilot-smoke.yaml` with a
   tiny two-stage `pipeline:` (`noop` → `pr`, the PR stage `--draft`). Set
   `board.status_field` to the lifecycle field's real name, and add every option
   the chain writes (`queued`, `pr-open`, plus your `working`/`park`/`pr_status`)
   — the preflight raises at startup otherwise. A chain with no reject/rewind
   edge needs no bounce field.
2. Set `concurrency: 1`.

   > **Do NOT rely on `budget.max_tokens` to bound this run — it is INERT**
   > (§ Guards). Nothing caps spend by tokens today. What actually bounds a smoke
   > run is a trivial two-stage chain with **no** model stage (`noop` → `pr`),
   > `concurrency: 1`, running ticks **by hand**, and the `PAUSED` file. If you
   > put a real `claude -p` stage in this chain, the only terminator is
   > `rework.max_rounds`.

3. Add one trivial item and drag it into your configured trigger column.
4. Run a single tick by hand and watch it arm (`Pipeline → queued`); run more
   ticks and watch it advance to a **draft** PR and land in `In Review`.
5. Confirm the engine **stopped**: it did not merge, did not set `Done`, and a
   further tick is a no-op. Drop a `PAUSED` file and confirm the next tick bails.
6. Tear down: close the draft PR, delete the scratch repo/project, remove the
   temporary `workflow/projects/board-pilot-smoke.yaml`.

This exercises the real `GhBoardClient` + `ClaudeStageRunner` against disposable
state — so a bug surfaces on your own throwaway PR, never on someone else's board.

## Related

- `references/agents.md` — **the five agents at a glance**: role, fresh-session,
  tools, prompt assembly, requirement, I/O and guards per stage, each pointing at the
  exact `stages/*.sh` lines and the `criteria/*.md` standard. Read this to see what
  every step is told and held to.
- `references/transparency.md` — **the transparency layer**: the two comment
  streams and why they must never merge, the byte-0 anchor (with the hijack probe
  — read it before you touch `parse_reject`), the engine-writes-evidence
  contract, the per-stage narration (`<details>` in the sticky), the placeholder
  rule, and the REAL-vs-CLAIM table the PR dossier is bound by.
- `references/operations.md` — **operations & troubleshooting** for a live
  deployment: the `status_field` silent-never-arms trap, recovering a parked item,
  the `gh project … unknown owner type` GraphQL rate-limit disguise (and how to
  monitor the loop without draining the shared budget) + the lock-liveness
  `kickstart -k` restart caveat. Read this when the loop stalls.
- `templates/` — the record format (`row.md.tmpl`, `record.md.tmpl`). Editing
  these is how you change the record's shape; `record.templates_dir` points at a
  copy of them.
- `stages/` + `criteria/` — what a stage **does** and what it **judges against**.
  `criteria/*.md` is the main tuning knob: tracked, versioned, and cited by SHA
  in every record row.
- `engine/` — the state machine (`tick.py`), config parser, guards, lock,
  snapshot, ports + Fake/real adapters
- `tests/` — `test_acceptance.py` (the goal) + engine/lock unit tests
- `skills/github-projects-manager/` — the gated board-write executor
- `skills/tracker-sync/` — board ↔ Bridge state reconcile (a different concern)
- `workflow/projects/<slug>.yaml` — per-project `pipeline:` config + field IDs
- `rules/deploy-reconciliation.md` — launchd/service truth model for install
