"""Shared interfaces: data records + the two ports the engine depends on.

Decision A (engine-owned program counter): a board item carries a human-owned
`status` (the trigger source — a person drags it to `Todo`) AND an engine-owned
`pipeline` field (the durable program counter). The engine reads `status` only to
ARM an item; from then on it tracks progress via `pipeline`, so a human moving the
card around mid-flight cannot corrupt the state machine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class BoardItem:
    id: str
    title: str
    status: str                       # human-owned column — the trigger source
    pipeline: Optional[str] = None    # engine-owned program counter (None = never armed)
    url: str = ""
    # The STORY: the need, and why it matters. The stage does the analysis itself —
    # an issue that hands the planner a pre-chewed solution is the wrong shape, and
    # the first live run proved it: the hand-written "constraints, VERIFIED" section
    # asserted a fact about the repo that was false, while the planner (which never
    # read it) analysed the repo and got it right.
    # UNTRUSTED: on a public repo this is written by whoever opened the issue, with
    # no authorship assertion of any kind. It is strictly less trusted than
    # `annotation` below, which at least the engine authored. Everything downstream
    # treats it as DATA — see claude_runner._clamp_body / _item_env / _claude_prompt.
    body: str = ""
    bounces: int = 0                  # reject-edge round counter (durable board Number field)
    annotation: str = ""              # latest engine-authored reject note for the current round
    # None = a draft card: no issue behind it, so it can carry no `Closes #N`, no
    # PR link and no issue comment. Such an item must never arm — it would burn
    # every expensive stage and have nowhere to report.
    issue_number: Optional[int] = None


@dataclass
class Stage:
    id: str                           # spec | implement | verify | review | pr | …
    run: str                          # handler ref: skill:|workflow:|agent:|cmd:
    on_success: str                   # pipeline state to set when this stage passes
    gate: Optional[str] = None        # "human" → STOP after this stage (never auto-advance past)
    retry: int = 0
    on_fail: str = "park"             # retry | park | rewind
    rewind_to: Optional[str] = None
    # --- reject edge (on_reject:) ----------------------------------------
    reject_to: Optional[str] = None   # STAGE-ID to return a rejected item to (resolved to a before-key)
    max_rounds: Optional[int] = None  # per-edge override of rework.max_rounds
    on_exhausted: str = "park"        # v1: only "park" (terminal)
    # --- transparency -----------------------------------------------------
    criteria: Optional[str] = None    # criteria filename, relative to board.criteria_dir
    evidence: bool = False            # engine tees this stage's stdout/stderr + exit code


@dataclass
class StageResult:
    ok: bool                          # execution health — did the stage RUN cleanly (no infra crash)
    notes: str = ""
    pr_opened: bool = False
    tokens: int = 0                   # output tokens this stage consumed (for the budget)
    verdict: Optional[str] = None     # None (non-review) | "pass" | "reject" — consulted ONLY when ok
    annotation: str = ""              # full reviewer reason (not truncated like park notes)
    reject_to: Optional[str] = None   # optional result-chosen target; else falls back to Stage.reject_to
    # --- transparency: what the engine OBSERVED, never what a stage claims ---
    duration_s: Optional[float] = None    # wall-clock around the spawn; a retry is invisible without it
    # Where the parent tee'd stdout/stderr + exit code. The evaluated agent never
    # touches that directory — that is the whole reason the evidence is not forgeable
    # by the text of the stage.
    evidence_dir: Optional[str] = None
    # The criteria the stage actually decided on, as name@sha, hashed at dispatch.
    # Reported by the runner rather than re-derived later: the record must cite the
    # standard that was APPLIED, not whatever the file says by the time it is read.
    criteria_ref: Optional[str] = None


# --- reject-comment marker (engine-authored, round-scoped) ----------------
# Anchored at byte 0 (`\A` + .match), because the engine authors MORE than one
# comment stream on the same issue and a run-record entry legitimately QUOTES a
# reject note. An author filter cannot separate those — both streams are the
# engine — and the read-back keeps the LAST match without a break
# (gh_board.py:426-428), so a quoting record would outrank the real note and steer
# the producer. Markdown quotes always carry a `> ` prefix, so anchoring beats the
# quoting case structurally instead of by escaping.
# `\r?\n`: GitHub delivers comment bodies with CRLF; without it the marker stops
# matching over the wire and every rework silently runs blind.
_REJECT_RE = re.compile(r"\A<!-- board-pilot:reject round=(\d+) -->\r?\n")


def reject_comment(round_n: int, note: str) -> str:
    """The engine-authored reject comment body: a machine marker line + the note.

    The marker carries the round so an authenticated read-back can pick the note
    for the CURRENT round only (never just "newest"), and so a re-tick never
    double-counts: the round is the durable board counter, not len(comments).
    """
    return f"<!-- board-pilot:reject round={int(round_n)} -->\n{note or ''}"


def parse_reject(text: str):
    """Parse a reject-comment body → (round:int|None, note:str).

    The note is taken from the match offset, never from a split on the first
    newline: a blind tail-split derives the note by a second, independent rule
    that merely HAPPENS to agree with the marker while the marker sits on line 1.
    It disagrees silently the moment it does not — handing the producer a tail it
    never wrote as its own feedback.
    """
    m = _REJECT_RE.match(text or "")
    if not m:
        return None, ""
    return int(m.group(1)), text[m.end():]


@runtime_checkable
class BoardClient(Protocol):
    """Board I/O port. Real impl talks to GitHub Projects; Fake impl is in-memory."""

    def fetch_items(self) -> "list[BoardItem]": ...
    def set_pipeline(self, item_id: str, value: str) -> None: ...
    def set_status(self, item_id: str, value: str) -> None: ...
    def pr_exists(self, item_id: str) -> bool: ...
    # reject edge -------------------------------------------------------
    def comment(self, item_id: str, text: str) -> None: ...
    def get_number(self, item_id: str, field: str) -> int: ...
    def set_number(self, item_id: str, field: str, value: int) -> None: ...


@runtime_checkable
class StageRunner(Protocol):
    """Stage execution port. Real impl dispatches `claude -p` / shell; Fake is scripted."""

    def run(self, stage: "Stage", item: "BoardItem") -> "StageResult": ...


@runtime_checkable
class Reporter(Protocol):
    """Outward-report port: the shape `Engine._emit` fans one event out to.

    This signature is not new. `Recorder.emit` (record.py) and the SpyRecorder the
    tick tests drive the real engine with have carried it all along; naming it as a
    port is what lets a SECOND sink hang off the same seam without the engine
    learning a single thing about channels, addresses or delivery.

    Two obligations, both structural rather than polite:

    * **construction is cheap and offline.** The engine builds its sinks during
      `Engine.__init__`, which is also where the board preflights run. A sink that
      opened a connection or resolved a secret there would tie the engine's start to
      a network resource, and the Recorder is deliberately built even when the
      record is disabled, so this is a property the seam already has.
    * **`emit` may raise.** It must not swallow: the caller wraps every sink in
      `emit_guarded`, which is what keeps a failing sink from converting a
      successful advance into a skip. A sink that hid its own failure would make
      that guard untestable and the ledger wrong.
    """

    def emit(self, event: str, item: "BoardItem", *, stage=None, result=None, **fields) -> None: ...
