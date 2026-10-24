---
scope: core
summary: Installing the board-pilot poller on a scheduler host (launchd, systemd, cron), chaining stages, board prerequisites, wiring the poller, and the safe live-smoke recipe.
type: reference
last_updated: 2026-10-24
related:
  - ../SKILL.md
---

# board-pilot: install and live smoke

Moved here from [`../SKILL.md`](../SKILL.md). Read this when putting the poller on
an always-on host or proving the loop end to end on a throwaway board.

## Install on a scheduler host (launchd / systemd / cron)

The poller is a cheap cron-style tick — run it on any always-on host. It is a
scheduled `--once` job (~60 s interval), not a long-lived daemon: each tick is
independent and idempotent, so a missed or overlapping run is harmless (the lock
+ durable `Pipeline` field absorb it).

### Chaining stages in one call (`--max-stages N`)

A scheduled tick advances one item by one stage, so a five-stage pipeline costs
four full timer intervals of pure waiting between stages. `--max-stages N` runs
up to N ticks back to back in ONE invocation, walking an item that is **already
armed** through its stages without waiting on the clock:

```bash
python3 -m engine.cli --project <yaml> --state-dir <dir> --max-stages 8 [--tick-pause 2]
```

It is a second mode, not a replacement. Leave the scheduled unit exactly as it
is: it stays the safety net for the times nobody triggers a chain by hand, and
it remains the **only** thing that arms — unless you pass `--arm-first`.

**`--arm-first` (requires `--max-stages`)** lets the OPENING tick of the chain
arm, and no tick after it. It is for the caller that has just performed the human
release ITSELF — a confirmation page that sets the trigger column and then invokes
the chain — and would otherwise need a second, scheduled tick before anything
moves. One release stays one arming sweep. Without `--max-stages` it is refused
rather than silently ignored: on its own it would describe a mode that does not
exist.

**`--report-send`** actually POSTs to the addresses the `report:` webhook targets
name. Without it every webhook target rehearses: it filters, renders the row and
the card, and prints the payload to stderr instead of sending it. File and python
targets are unaffected. This flag is easy to forget and its absence is invisible,
so if a channel is quiet, look here first (§ 9 of `references/transparency.md`
carries the full account of why).

Four properties, each pinned by `tests/test_chain_advance.py`:

- **It never arms.** The chain calls `Engine.tick(arm=False)`, which skips the
  ARM phase outright. Arming stays one human act on one card: a card dragged
  into the trigger column while a chain is running is not swept up by it, and
  the next scheduled tick latches it as always.
- **It always terminates, and the ledger says why.** One JSON line per tick as
  ever, plus `tick` and `stop`; the last line of a chain always carries a
  non-null `stop`: `gate` · `parked` · `rejected` · `idle` · `paused` ·
  `max_stages`. `gate` outranks `max_stages`, so a chain that ends at the human
  gate on its last allowed tick says so rather than inviting a pointless re-run.
- **The cap is mandatory**, an argument and never a default. A loop against a
  board API with no terminator is how a rate-limit bucket gets emptied. It is
  bounded twice on purpose (the loop range and the stop reason), and both halves
  are tested.
- **`touch PAUSED` stops a chain already in flight**, because the engine
  re-reads the kill file at the top of every tick. This matters more here than
  anywhere else: a hand-run chain is the one caller that shares a state dir with
  the scheduled unit, and PAUSED is the only handle that reaches both.

Two traps when running it by hand rather than from the unit:

- **`BP_VERIFY_CMD` lives in the unit env, not in the shim.** A hand-typed
  invocation without it parks at `verify`, fail-closed by design (a stage that
  cannot verify must never report green), but it looks like a pipeline defect.
  Export it alongside the command.
- **The default invocation is byte-frozen.** Without `--max-stages` the summary
  line keeps its exact nine keys, so every existing log reader and plist in the
  fleet still parses it. `--once` and `--max-stages` contradict each other and
  are refused rather than silently resolved.

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
   > (`../SKILL.md` § Guards). Nothing caps spend by tokens today. What actually bounds a smoke
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
