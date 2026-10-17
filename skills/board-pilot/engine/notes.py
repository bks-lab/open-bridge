"""Relay what a running stage says, while it is still running, and BUNDLED.

WHY THIS EXISTS
---------------
`claude_runner._spawn` reads the child's pipe exactly once, when the child exits.
That is right for evidence — the parent, and only the parent, can write an output
the stage cannot forge — but it means a stage that takes seven minutes is mute for
seven minutes. On a screen, mute and stalled look the same.

A note is the other channel: the stage APPENDS a line to a file whose path the
engine handed it, and this follower relays each new line as it appears. Nothing
about the subprocess is touched, so this cannot delay, kill or mis-report a stage.

WHY IT BUNDLES
--------------
The third live run put 26 cards in the channel, several of them inside the same
second: `criteria read` and `planner started` are written microseconds apart, and
the three notes of the `pr` stage inside fifteen seconds. Being told is the point;
being told four times in one second is not.

So the follower holds a burst until nothing new has arrived for `hold_s`, and
relays it as ONE message. It relays regardless after `max_hold_s`, and that cap is
the load-bearing half: a stage writing a line every four seconds would never fall
quiet, a pure quiet-window would hold everything until the stage ends, and the
channel would go silent exactly when there is most to say.

FOUR PROPERTIES, EACH ONE A WAY THIS GOES WRONG
-----------------------------------------------
1. A FAILING RECEIVER IS SWALLOWED. A note is an observation, never a decision. A
   channel that is down must not take the run with it, and must not silence the
   notes that come after the one that failed.
2. THE TAIL IS RELAYED AFTER THE STOP FLAG, window or no window. A follower that
   sees `should_stop()` and returns has dropped whatever the child wrote in its
   last second, which is the line that says how it ended.
3. LENGTH AND BLANKS ARE THE FOLLOWER'S PROBLEM. A blank line is a card with
   nothing on it; a 3000-character line is a channel post that fails to render.
4. THE CLOCK IS A PARAMETER. Every window here is a duration, and a duration
   measured against a clock a test cannot move is a test that sleeps or a test
   that lies.

The line count, not a byte offset, is what marks the position: notes are appended,
the files are tiny, and a count survives a rewrite that a stale offset would read
as garbage.
"""
from __future__ import annotations

import time
from pathlib import Path

# Long enough for a sentence, short enough for a card and a comment cell.
MAX_LEN = 240

# Quiet before a burst is relayed, and the hard cap that defeats a steady trickle.
HOLD_S = 5.0
MAX_HOLD_S = 20.0


def _read(path, seen: int):
    """Every line after `seen`, cleaned. Returns (lines, new count). Raises nothing."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        # No file yet is the NORMAL case: a stage with nothing to say writes none.
        return [], seen
    fresh = [raw.strip()[:MAX_LEN] for raw in lines[seen:]]
    return [t for t in fresh if t], len(lines)


def _relay(on_lines, batch) -> None:
    if not batch:
        return
    try:
        on_lines(list(batch))
    except Exception:  # noqa: BLE001 - see property 1 in the module docstring
        pass


def follow(path, on_lines, should_stop, *, sleep=None, poll_s=2.0,
           hold_s=HOLD_S, max_hold_s=MAX_HOLD_S, clock=None) -> None:
    """Relay bundled bursts until `should_stop()`, then relay the tail and return.

    `on_lines` receives a LIST of lines, never a single one: what arrived together
    belongs together, and deciding that here is what keeps every caller from
    inventing its own idea of "together".
    """
    rest = sleep or time.sleep
    now = clock or time.monotonic
    seen = 0
    batch: "list[str]" = []
    first_at = last_at = 0.0

    while True:
        fresh, seen = _read(path, seen)
        if fresh:
            if not batch:
                first_at = now()
            batch.extend(fresh)
            last_at = now()

        if batch and (now() - last_at >= hold_s or now() - first_at >= max_hold_s):
            _relay(on_lines, batch)
            batch = []

        try:
            rest(poll_s)
        except Exception:  # noqa: BLE001 - a clock is not worth a run
            pass

        if should_stop():
            fresh, seen = _read(path, seen)
            batch.extend(fresh)
            # Window or no window: the last thing a stage said is the thing that
            # says how it ended.
            _relay(on_lines, batch)
            return
