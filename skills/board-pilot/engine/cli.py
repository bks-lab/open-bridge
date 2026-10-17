"""board-pilot `tick` CLI — the launchd entrypoint.

DEFAULT: one invocation = exactly ONE engine tick. There is NO internal sleep
loop; the launchd timer (StartInterval, see assets/com.example.board-pilot.plist)
is the clock, so a hung tick can never wedge the loop.

CHAINED: `--max-stages N` runs up to N ticks back to back, so an item already
armed walks its stages in one invocation instead of waiting one timer interval
per stage boundary. It is a second mode, not a replacement: the scheduled unit
keeps ticking on its timer and remains the safety net when nobody triggers a
chain by hand.

Two properties make the chain safe to point at a live board, and both are
tested (tests/test_chain_advance.py):

  * it NEVER arms. `Engine.tick(arm=False)` skips the ARM phase outright, so a
    chain advances what a human already released and sweeps up nothing that
    lands in the trigger column while it runs. Arming stays one human act, one
    card, latched by the next scheduled tick.
  * it always terminates, and says why: the human gate, a park, a reject, a tick
    that moved nothing, PAUSED, or the cap the caller named. The cap is
    mandatory — an argument, never a default — because a loop against a board
    API with no terminator is how a rate-limit bucket gets emptied.

Usage:
    python3 -m engine.cli --project <path-to-project-yaml> --state-dir <dir> [--once] [--dry-run]
    python3 -m engine.cli --project <...> --state-dir <...> --max-stages 6 [--tick-pause 2]

Wiring:
    EngineConfig   ← engine.config.load_pipeline_from_yaml(project_yaml)
    BoardClient    ← engine.gh_board.GhBoardClient   (real GitHub Projects v2 adapter)
    StageRunner    ← engine.claude_runner.ClaudeStageRunner(dry_run=...)
    Engine         ← engine.tick.Engine(config, board, runner, state_dir)

The engine config (stages, trigger, budget) is generic. The board/repo BINDING
(project number, owner, the two single-select field names, the backing repo) is
project-specific and lives in a `board:` block in the SAME project YAML; the CLI
reads it raw to construct the two adapters. See assets/pipeline.example.yaml.

The two real adapters (gh_board, claude_runner) are filled in by the build
workflow. If they are absent the CLI must fail loudly with a clear message
rather than tracebacking — guarded below.

Prints a single one-line JSON summary of the TickResult to stdout (the launchd
StandardOut log is a clean, greppable ledger of every tick).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import NoReturn

# The pause between two chained ticks. Not zero: a chain that fails fast (a held
# lock, a transient board error) would otherwise re-read the board as fast as the
# process can loop, which is the exact shape that emptied the rate-limit bucket.
_DEFAULT_TICK_PAUSE = 2.0


def _die(msg: str, code: int = 2) -> NoReturn:
    """Emit a clear one-line error to stderr and exit non-zero."""
    print(f"board-pilot: {msg}", file=sys.stderr)
    raise SystemExit(code)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="engine.cli",
        description="Run one board-pilot tick (the launchd timer provides the loop).",
    )
    p.add_argument(
        "--project",
        required=True,
        help="Path to the project YAML carrying the `pipeline:` block.",
    )
    p.add_argument(
        "--state-dir",
        required=True,
        help="Durable state directory (prev.json, locks/, budget.json, PAUSED).",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one tick. This is the only mode; flag accepted for clarity.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass dry_run=True to the StageRunner — plan stages, run no real handler.",
    )
    p.add_argument(
        "--max-stages",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Chain up to N ticks in this one invocation, advancing an ALREADY ARMED "
            "item stage by stage. Never arms anything. Stops at the human gate, a "
            "park, a reject, an idle tick, PAUSED, or N — whichever comes first."
        ),
    )
    p.add_argument(
        "--arm-first",
        action="store_true",
        help=(
            "Let the OPENING tick of the chain arm, and no tick after it. For the "
            "caller that has just performed the human release itself (the "
            "confirmation page sets the trigger column, then calls this) and would "
            "otherwise need a second, scheduled tick to latch the card. One "
            "release stays one arming sweep. Requires --max-stages."
        ),
    )
    p.add_argument(
        "--report-send",
        action="store_true",
        help=(
            "Actually POST to the addresses the `report:` webhook targets name. "
            "Without it every webhook target REHEARSES: it filters events, renders "
            "the row and the card, and prints the exact payload to stderr instead "
            "of sending it. File and python targets are unaffected — neither has "
            "an address to hold back."
        ),
    )
    p.add_argument(
        "--tick-pause",
        type=float,
        default=_DEFAULT_TICK_PAUSE,
        metavar="SECONDS",
        help=(
            f"Pause between two chained ticks (default {_DEFAULT_TICK_PAUSE}). "
            "Only meaningful with --max-stages."
        ),
    )
    return p


def stop_reason(result, tick_no: int, max_ticks: int):
    """Why the chain must stop after this tick — or None to keep going.

    Pure: it decides on the TickResult and two integers, so every branch is
    testable without a board. Order is load-bearing, because several of these are
    true at once and the ledger should name the strongest one:

      paused      the PAUSED kill-file appeared mid-chain. Read every tick by the
                  engine itself, so `touch PAUSED` stops a running chain too.
      gate        a human gate was reached — the draft PR is open and a PERSON
                  decides next. Checked before `idle`, because the gated item is
                  in `dispatched` and the tick therefore looks productive; and
                  before the cap, so the last allowed tick still reports the gate.
      parked      the item is out of the chain and needs a human.
      rejected    rework was ordered. Halting hands the round back to a person
                  rather than spending the next stage unattended; the scheduled
                  unit picks the item up on its own timer.
      idle        nothing moved. Not "finished" — a held lock or a transient board
                  error looks identical from here, which is exactly why this is a
                  STOP and not a retry: retrying is what the timer is for.
      max_stages  the caller's cap. Last, so it never masks a real reason.
    """
    if result.paused:
        return "paused"
    if getattr(result, "gated", None):
        return "gate"
    if result.parked:
        return "parked"
    if result.rejected:
        return "rejected"
    if not result.dispatched:
        return "idle"
    if tick_no >= max_ticks:
        return "max_stages"
    return None


def _load_raw(path: str) -> dict:
    """Read the project YAML as a plain dict (for the board: binding block)."""
    try:
        import yaml  # lazy: only the real CLI needs PyYAML
    except ImportError as e:
        _die(f"PyYAML is required to load {path}: {e}")
    from pathlib import Path

    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        _die(f"project YAML not found: {path}")
    except Exception as e:  # malformed YAML
        _die(f"failed to parse project YAML {path}: {e}")


def resolve_binding(raw: dict) -> dict:
    """Resolve the board/repo binding from a project YAML.

    Two sources, in priority order, so a board-pilot config IS a normal
    workflow/projects/<slug>.yaml and need not duplicate the binding:
      1. an explicit ``board:`` block (or ``pipeline.board``) — board-pilot-specific
         keys: owner / project_number / repo / status_field / pipeline_field /
         branch_template / repo_path / criteria_dir;
      2. the standard project-registry ``project:`` block — org / number / issue_repo.
    The three required keys (owner, project_number, repo) fail loudly, naming BOTH
    candidate sources, when absent. Pure/offline — no network — so it is unit-tested.
    """
    board = raw.get("board") or (raw.get("pipeline") or {}).get("board") or {}
    proj = raw.get("project") or {}
    owner = board.get("owner") or proj.get("org")
    number = board.get("project_number") or proj.get("number")
    repo = board.get("repo") or proj.get("issue_repo")
    missing = [
        name
        for name, val in (
            ("owner (or project.org)", owner),
            ("project_number (or project.number)", number),
            ("repo (or project.issue_repo)", repo),
        )
        if val in (None, "")
    ]
    if missing:
        _die(
            "board binding incomplete — missing " + ", ".join(missing)
            + ". Set a `board:` block or the standard `project:` registry block "
            "(see skills/board-pilot/assets/pipeline.example.yaml)."
        )
    return {
        "owner": owner,
        "project_number": number,
        "repo": repo,
        "status_field": board.get("status_field", "Status"),
        "pipeline_field": board.get("pipeline_field", "Pipeline"),
        "branch_template": board.get("branch_template", "bridge/{project}/{item_id}"),
        "repo_path": board.get("repo_path", repo),
        # No default, unlike the fields above: absent means "no stage may declare
        # criteria:", which config.validate_transparency already enforces at load.
        # A guessed default would anchor (claude_runner._anchor) into repo_path —
        # the repo the autonomous agent is editing — so a stage could rewrite the
        # standard it is judged against, and the record would cite the SHA of that
        # rewrite as if it were the operator's.
        "criteria_dir": board.get("criteria_dir"),
    }


def _summary(project: str, result, dry_run: bool) -> dict:
    """The one-line ledger entry for one tick. The KEY SET IS FROZEN.

    Every launchd log reader, every `jq` one-liner and every plist in the fleet
    parses this shape. `TickResult.gated` is deliberately NOT in it: it is a
    control signal for the chain, and adding it here would change the default
    invocation's output for a mode that invocation does not run.
    """
    return {
        "project": project,
        "paused": result.paused,
        "armed": result.armed,
        "dispatched": result.dispatched,
        "skipped": result.skipped,
        "parked": result.parked,
        "rejected": result.rejected,
        "dry_run": dry_run,
        "notes": result.notes,
    }


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.arm_first and args.max_stages is None:
        # `--tick-pause` may sit unused in a plist harmlessly: it changes nothing.
        # This one is a claim about ARMING, and a plain tick arms regardless — so
        # accepting it here would make the flag look load-bearing while the
        # behaviour came from somewhere else entirely.
        _die("--arm-first is only meaningful with --max-stages — pass both or neither")

    if args.max_stages is not None:
        # The cap IS the terminator. A 0 or a negative is a typo, and quietly
        # correcting it to 1 (or to "unbounded") would leave the operator believing
        # in a bound that is not there.
        if args.max_stages < 1:
            _die(f"--max-stages must be at least 1 (got {args.max_stages})")
        if args.once:
            # Opposite claims about how many ticks run. Refusing beats letting one
            # win silently: a plist that grew --max-stages without losing --once
            # would otherwise run a mode nobody chose.
            _die("--once and --max-stages contradict each other — pass exactly one")
        if args.tick_pause < 0:
            _die(f"--tick-pause must not be negative (got {args.tick_pause})")

    # Engine core (no third-party deps) — import errors here are bugs, let them surface.
    from .config import load_pipeline_from_yaml
    from .tick import Engine

    # Real adapters — built by the build workflow; guard so a missing/broken
    # adapter fails with a clear message instead of a raw ImportError traceback.
    try:
        from .gh_board import GhBoardClient, GhCliError
    except ImportError as e:  # pragma: no cover - depends on build-stage module
        _die(f"GhBoardClient unavailable (engine.gh_board): {e}. "
             "The real GitHub Projects adapter is not built yet.")
    try:
        from .claude_runner import ClaudeStageRunner
    except ImportError as e:  # pragma: no cover - depends on build-stage module
        _die(f"ClaudeStageRunner unavailable (engine.claude_runner): {e}. "
             "The real stage runner is not built yet.")

    try:
        config = load_pipeline_from_yaml(args.project)
    except FileNotFoundError:
        _die(f"project YAML not found: {args.project}")
    except Exception as e:  # malformed YAML, missing PyYAML, etc.
        _die(f"failed to load pipeline config from {args.project}: {e}")

    # Board/repo binding: from the `board:` block OR the standard `project:` registry block.
    raw = _load_raw(args.project)
    b = resolve_binding(raw)
    branch_template = b["branch_template"]

    has_reject_edge = any(getattr(s, "reject_to", None) for s in getattr(config, "stages", []))
    board = GhBoardClient(
        project_number=b["project_number"],
        owner=b["owner"],
        status_field=b["status_field"],
        pipeline_field=b["pipeline_field"],
        repo=b["repo"],
        # board + runner MUST share the branch template/slug, else pr_exists checks
        # the wrong head and a re-tick opens a duplicate PR.
        branch_template=branch_template,
        project=getattr(config, "project", ""),
        # activate the reject-edge read-back (bounce Number field + annotation) only
        # when the pipeline actually declares a reject edge.
        bounce_field=getattr(config, "bounce_field", "Bounces"),
        reject_edge=has_reject_edge,
    )
    # The evidence sink is a per-ITEM template and the substitution is SPLIT: only
    # this process knows --state-dir, only the runner knows the item, so each side
    # renders its own placeholder and leaves the other literal.
    # `str.replace`, not `str.format`: format would demand `item_id` here and raise
    # KeyError — and satisfying it would collapse every item on the board onto one
    # evidence dir, each overwriting its neighbour's receipt.
    evidence_dir = getattr(getattr(config, "evidence", None), "dir", None)
    if evidence_dir:
        evidence_dir = evidence_dir.replace("{state_dir}", args.state_dir)
    runner = ClaudeStageRunner(
        repo=b["repo_path"],
        branch_template=branch_template,
        dry_run=args.dry_run,
        project=getattr(config, "project", ""),
        # Both default to None on the runner, so omitting either here is not a
        # degraded mode but a SILENT one: no tee (the dossier's only machine-captured
        # section never exists) and every `criteria:` stage failing closed. The suite
        # cannot see it — every other test constructs the runner itself.
        evidence_dir=evidence_dir,
        criteria_dir=b["criteria_dir"],
    )
    # Engine construction runs the board preflights (bounce field, writable
    # options) — the first live `gh` calls of the process. Failures split on
    # WHOSE fault they are:
    #   * TRANSIENT (rate limit, HTTP 5xx): the API's — the same board preflights
    #     clean on a later tick. An uncaught raise here tracebacks into err.log
    #     and launchd relaunches the unit straight back into the same rate limit
    #     (736 crashes in one night). Skip THIS tick with a quiet ledger note and
    #     exit 0 — the launchd timer IS the retry loop.
    #   * PERMANENT (missing field/option → RuntimeError from the preflight; bad
    #     auth/scope → a non-transient GhCliError): the operator's — every future
    #     tick fails identically, and a quiet skip would hide a board that can
    #     never work behind a healthy-looking ledger. Raise loudly, unchanged.
    # fetch_items failures inside tick() already get the quiet-note treatment;
    # this gives the preflights the same one WITHOUT widening what fails open.
    try:
        engine = Engine(config, board, runner, args.state_dir, report_send=args.report_send)
    except GhCliError as e:
        if not e.is_transient():
            raise
        detail = (e.stderr or "").strip().replace("\n", " ")[:200]
        summary = {
            "project": getattr(config, "project", "unknown"),
            "paused": False,
            "armed": [],
            "dispatched": [],
            "skipped": [],
            "parked": [],
            "rejected": [],
            "dry_run": args.dry_run,
            "notes": f"preflight skipped (transient gh error): {detail}",
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0

    project = getattr(config, "project", "unknown")

    if args.max_stages is None:
        result = engine.tick()
        print(json.dumps(_summary(project, result, args.dry_run), ensure_ascii=False, sort_keys=True))
        return 0

    # --- chained mode ----------------------------------------------------
    # One ledger line per tick, same as ever, plus `tick` and `stop`. The last
    # line of a chain always carries a non-null `stop`, so the log says why the
    # call ended instead of leaving the reader to infer it from a missing line.
    for n in range(1, args.max_stages + 1):
        # Never arms, unless the caller performed the release itself and said so
        # — and then only on the opening tick. See Engine.tick and --arm-first.
        result = engine.tick(arm=args.arm_first and n == 1)
        stop = stop_reason(result, n, args.max_stages)
        line = _summary(project, result, args.dry_run)
        line["tick"] = n
        line["stop"] = stop
        print(json.dumps(line, ensure_ascii=False, sort_keys=True), flush=True)
        if stop is not None:
            break
        if args.tick_pause > 0:
            time.sleep(args.tick_pause)
    return 0


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
