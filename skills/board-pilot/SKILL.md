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

A project opts in with `board:` + `pipeline:` blocks in its
`workflow/projects/<slug>.yaml` (read `_template.yaml` + `_schema.yaml` there
first). The full shape, the two grammar traps, stage ids, the `run:` path, the
stage environment and the behaviour changes for an existing pipeline:
[`references/config.md`](references/config.md).

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
| **Draft PRs by default** | `pr` stage | The terminal stage opens a **draft** PR and exits. It never opens a ready PR. Only the opt-in `BP_PR_AWAIT_CHECKS=1` ([`references/config.md`](references/config.md) § Behaviour changes) may mark it ready afterwards, and only when every check is green. Merge stays human either way. |
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

A third port, `Reporter`, is where the engine says things OUTWARD. `Engine._emit`
is the one method this module reports through, all eight state-machine call sites
land there, and it fans each event out to the sticky-comment `Recorder` plus every
sink declared in `report:`. Each sink is guarded separately, so a channel that is
down can lose a message but can never stop a run. Every sink renders from the same
`record.row_fields` the board comment does, so the two can never disagree.
References: `references/transparency.md` § 9.

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

**549 tests across 41 files, ~65 s, no network** (measured 2026-10-17 — re-run it
rather than trusting this line; a stale count here is exactly the drift this
section once carried). `test_tick_report.py` + `test_report_config.py` cover the
outward seam: no config means no sink, one message per stage, a throwing sink that
cannot stop the run, one summary at the end, and one source behind both renderings.

## Install and live smoke

The poller is a scheduled `--once` tick (~60 s), not a daemon. Scheduler units,
`--max-stages N`, the board prerequisites the engine refuses to start without,
wiring the poller, and the SAFE live-smoke recipe (throwaway repo and project
only, never a real board): [`references/install.md`](references/install.md).

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
- `references/config.md`: **per-project config**, with the `board:` + `pipeline:`
  shape, grammar traps, stage ids, the stage environment, behaviour changes.
- `references/install.md`: **install and live smoke**, with scheduler units,
  chaining, board prerequisites, wiring the poller, the SAFE smoke recipe.
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
