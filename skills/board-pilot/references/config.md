---
scope: core
summary: Per-project board-pilot config: the board and pipeline blocks a project declares, the grammar traps, stage ids and run paths, the stage environment, and what changed for an existing pipeline.
type: reference
last_updated: 2026-10-24
related:
  - ../SKILL.md
---

# board-pilot: per-project config

Moved here from [`../SKILL.md`](../SKILL.md), which keeps the mental model, the
guards and the gates. Read this when writing or changing a project's `board:` +
`pipeline:` blocks, or when a stage's environment is the question.

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

  report:                         # the outward seam — references/transparency.md § 9
    targets:                      # omit the block entirely and NO sink is built or called
      - name: channel             # WEBHOOK TARGETS REHEARSE unless the CLI got
        type: webhook             #   --report-send. See the flag below; a silent
        mode: stream              #   channel is this flag far more often than the address.
        events: [armed, stage_start, stage, reject, park, gate]  # this target's OWN
        url_env: BOARD_PILOT_WEBHOOK                             # filter, not record's
        card:                     # optional SECOND rendering: an adaptive card.
          incident: ""            #   Omit the block and the transport is called with
          incident_env: RUN_ID    #   one argument, exactly as before it existed.
          sender: "board-pilot"   #   incident_env: a VARIABLE NAME holding the run's id
          labels:                 #   the channel's vocabulary — this skill is scope: core
            step: "Step {n} of {m}"   # {m} = len(stages). A literal digit is REFUSED
      - name: summary
        type: webhook
        mode: digest
        flush_on: [gate, park]    # must be a subset of this target's `events`
        url_env: BOARD_PILOT_WEBHOOK
      - name: journal             # a sink this engine did not write. No transport,
        type: python              #   no renderer, no card: your object is all three.
        factory: "mypkg.sinks:Journal"   # "<module or file>:<attribute>", called once
        options: { index: runs }         #   at load; the result needs a callable .emit
        events: [gate, park]      # the ONE thing carried over, so `events:` means the
                                  #   same for every target type

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

Unknown keys under `record:` / `evidence:` / `report:` are **rejected at load**,
naming the offender: a knob that is silently ignored is invisible, and silently
ignoring `require_issue` arms draft cards. `report:` needs that check most of all,
because at runtime every sink is wrapped in `emit_guarded` and a broken target
degrades to a ledger line while the channel stays quiet.

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
fail-closed refusal naming the knob, never a guessed suite. See `../SKILL.md` § Guards.

Other operator knobs, all optional, all read from the unit env:

| Var | Read by | Default | Effect |
|---|---|---|---|
| `BP_PR_AWAIT_CHECKS` | `pr.sh` | off | `1` = wait for the PR's checks and mark it ready on green (§ Behaviour changes) |
| `BP_PR_CHECK_TIMEOUT` / `BP_PR_CHECK_PAUSE` / `BP_PR_CHECK_NONE_GRACE` | `pr.sh` | 600 / 10 / 90 s | only with `BP_PR_AWAIT_CHECKS=1`: total wait, poll interval, how long "no checks yet" is waited out |
| `BP_CLAUDE_TRIES` | `_lib.sh` `bp_claude` | 3 | total model attempts on a transient provider failure; `1` = no retry |
| `BP_CLAUDE_BACKOFF` | `_lib.sh` `bp_claude` | `60 180 300` | pauses in seconds between those attempts |

## Behaviour changes

What changed for an existing pipeline with this version, and how to keep the
old behaviour:

- **Model stages retry transient provider failures.** `bp_claude` (used by
  `spec.sh`, `implement.sh`, `review.sh`) now retries a run that failed with a
  provider-side error (`API Error: 429/5xx`, `Overloaded`, `Connection error`), 3 attempts in total with
  60 s and 180 s pauses by default. Any other failure is not retried. A stage can
  therefore take several minutes longer before it fails. Set
  `BP_CLAUDE_TRIES=1` in the unit env for the old single attempt.
- **The PR stage can wait for CI, opt-in.** Default unchanged: `pr.sh` opens a
  draft PR and exits 0. With `BP_PR_AWAIT_CHECKS=1` it then polls `gh pr checks`
  for up to `BP_PR_CHECK_TIMEOUT` (600 s): all green → `gh pr ready`; any red,
  still running at the limit, or no checks at all → the PR stays a draft and the
  stage FAILS (the item parks or retries per `on_fail`). A retry does not re-run
  the wait: the next tick finds the open PR (`pr_exists`) and hands the item to
  the human gate as is, so the draft stays a draft until a human marks it ready.
  Meant for a pipeline whose human gate is a single tap, where a draft alone is
  too little protection.
- **`report:` is new and absent by default.** No `report:` block means no sink is
  built or called.
- **`record:` gains one default event.** Without `events:`, an enabled record now
  writes `armed, stage_start, stage, reject, park, gate`: `stage_start` is new,
  `note` is in the vocabulary but never a default. List `events:` explicitly
  (e.g. without `stage_start`) to keep the previous rows.
