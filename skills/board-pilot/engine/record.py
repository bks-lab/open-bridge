"""The record layer — what the engine DID, and what it decided on.

One sticky comment per run, edited in place. Edits never re-notify; a new comment
mails every subscriber. That asymmetry — not volume — is the entire cost model, so
the table may grow as long as it likes and a second comment is a real expense.
The only discrete comment the engine authors is the round-scoped reject note, and
that one is NOT written here (see "Two streams" below).

WHAT THIS REFUSES TO SAY
------------------------
The record reports what the engine OBSERVED. Three things it cannot observe are
therefore absent rather than guessed:

  * the model — nothing pins `--model` and claude_runner spawns exactly
    ["claude", "-p", prompt]; the child resolves the CLI default and the parent
    never learns it;
  * the token count — hardcoded to 0 on both real paths, so `tokens: 0` would read
    as "this run was free";
  * TDD order — green at the end is not red-before-green, and it is not
    reconstructible afterwards.

`StageResult.tokens` sits in the scope of every hook here, one attribute access
away. Printing it is the easy, wrong thing, which is why a test pins its absence.
The `handler` column is cut for the same family of reason: it is config echo,
constant per stage — and it would put an absolute local path in a public comment.

TWO STREAMS, ONE ENGINE, AND WHY THE MARKER IS LOAD-BEARING
-----------------------------------------------------------
The engine authors two comment streams on the same issue:

  * the reject note  — `<!-- board-pilot:reject round=N -->`, discrete, one per
    round, read BACK and fed to an autonomous code writer as its own feedback;
  * the run record   — `<!-- board-pilot:run item=<id> -->`, sticky, edited, never
    read back for any decision.

An author filter cannot separate them: both ARE the engine. A record legitimately
QUOTES a round's reject note, and the read-back keeps the LAST match without a
break (gh_board.py:426-428) while gh returns comments chronologically — so a record
that parsed as a reject note would outrank the real note and steer the producer,
silently and order-dependently. parse_reject is anchored at byte 0, which beats the
quoting case structurally; this module's job is to never hand it a byte-0 match.
The marker is validated by running the real parser over the real rendered line
(`_validate_marker`) rather than by a lookalike check that could drift from it.
A probe proved the hazard is reachable from config alone: a `sticky_marker` that
closes its own comment and opens a decoy renders a valid round-1 reject note.

THE FORMAT IS A TEMPLATE, NOT A FORMAT STRING IN CODE
-----------------------------------------------------
`record.templates_dir` points at a directory of `*.md.tmpl` files. The defaults
shipped under `templates/` ARE the documented format — the same text this module
falls back to when the knob is unset, pinned byte-for-byte by
`test_default_templates_match_builtin_output`. Adjusting the format means editing a
tracked markdown file, not this module.

A template is a `str.format_map` format string. No Jinja, no eval, no loops: it
describes a shape, it is not a program. `{rows}` arrives pre-joined precisely
because "no loops" means the ENGINE iterates, never the template.

Two failure classes, deliberately split:

  * an UNKNOWN placeholder renders LITERALLY and can never raise — `SafeDict`
    returns a `_Literal` that survives every operation format_map can perform on a
    looked-up value (`{x!r}`, `{x:>10}`, `{x:d}`, `{x.y}`, `{x[0]}`). A typo must
    cost the run nothing;
  * a template that cannot render AT ALL — an unclosed brace, a positional field
    (`{}` / `{0}`, and there are no positional args), or a format spec no string can
    satisfy (`{took:.2f}`) — fails LOUD from `Recorder.__init__`, the same
    wiring-time posture as `_validate_marker`.

The load-time probe renders with STRING samples, and that is what makes the first
bullet a guarantee instead of a hope: every field this module substitutes is a `str`
on every path, so a template that renders with string samples at load cannot raise
on real values at render.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .interfaces import parse_reject
from .scan import scrub

# THE event vocabulary. Public because it is imported, not re-typed: config.py
# validates against this very object, and a second literal is a place for a new
# event to arrive in one copy and never in the other.
# `stage_start` sits between `armed` and `stage` because that is where it lands.
# Every other event here reports a COMPLETION. Measured on the first full run,
# 2026-09-02: between `armed` (16:49:51) and the end of the first stage (16:55:42,
# 5m47s) NOTHING wrote a line, anywhere. In that window a running chain and a
# wedged one are indistinguishable, which for an operator is the difference
# between "it is working" and "it is broken".
# The full vocabulary, which is what an `events:` list is VALIDATED against.
EVENTS = ("armed", "stage_start", "stage", "reject", "park", "gate", "note")
# What a target gets when it declares no list of its own. `note` is deliberately
# NOT in it: a note is an observation, not a state change, and a ledger that grows
# a row every time a stage mutters is no longer a ledger. An instance that wants
# notes in a channel says so.
DEFAULT_EVENTS = ("armed", "stage_start", "stage", "reject", "park", "gate")
_EVENTS = EVENTS          # historical name, kept for readers of this module

# A marker is a fixed MACHINE token: letters, digits and `.:_-`, nothing else. No
# `>` (ends the tag early), no whitespace, no `=`. Everything variable rides in the
# visible body, where it is prose instead of grammar. The failure this prevents is
# silent both ways: a broken marker renders as visible junk AND misses the byte-0
# find on the next tick, so every event posts a new comment and mails every
# subscriber.
# The `--` clause is separate because the charset alone cannot express it: `-` is
# legal (board-pilot), `--` is not (it cannot appear inside an HTML comment at all).
_MARKER_TOKEN_RE = re.compile(r"\A[A-Za-z0-9._:-]+\Z")
_PROBE_ITEM_ID = "PVTI_probe"

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_FILES = {"row": "row.md.tmpl", "record": "record.md.tmpl"}

_ROW_FIELDS = ("when", "stage", "kind", "criteria", "took", "outcome")
_RECORD_FIELDS = ("marker", "issue", "rows", "summary", "narration")

# The append contract: `_existing_rows` finds the prior rows by this line. It is a
# REGEX rather than the shipped literal because the columns are a KNOB — a template
# that renames or drops one renders a different separator, and an exact-string match
# would then refuse to edit its own record on every tick after the first. Matching the
# shape is what lets the knob turn. No data row can collide: `when` always carries a
# timestamp, and digits are not in the class.
_TABLE_SEP_RE = re.compile(r"\A\|[\s:|-]*-[\s:|-]*\|\s*\Z")

# The built-in fallback. `templates/*.md.tmpl` is generated from this and pinned equal
# to it by a test, so the shipped file IS the default rather than a copy that drifts.
# The `when` header carries no zone name on purpose: the engine cannot verify the box's
# IANA zone, and every cell already carries its offset — the honest form of the same
# statement.
_DEFAULT_TEMPLATES = {
    "row": "| {when} | {stage} | {kind} | {criteria} | {took} | {outcome} |",
    "record": (
        "{marker}\n"
        "## board-pilot run record{issue}\n"
        "\n"
        "Edited in place: one notification, at the first post. Machine-written.\n"
        "`machine` = an exit code this engine read from the pipe.\n"
        "`agent`   = a model's words — evidence of what it SAID, not that it is right.\n"
        "\n"
        "| when | stage | kind | criteria | took | outcome |\n"
        "|---|---|---|---|---:|---|\n"
        "{rows}\n"
        "\n"
        "{summary}\n"
        "\n"
        "{narration}"
        "### Not recorded here, and why\n"
        "- **Cost:** unmeasured. The engine observes no token count, so this reports none "
        "rather than a made-up one.\n"
        "- **Model:** not reported. Nothing pins one and nothing captures one from the child, "
        "so the engine observes none.\n"
        "- **TDD order:** not proven. Green at the end is not red-before-green, and it is not "
        "reconstructible afterwards. See the PR dossier."
    ),
}

_CELL_MAX = 200        # free text (a park reason, a quoted note)
_OUTCOME_MAX = 400     # composed from already-clean fragments
_REDACTION_RE = re.compile(r"\[redacted:([a-z-]+)\]")
_WHEN_RE = re.compile(r"\A\| (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}) \|")

# -- narration -----------------------------------------------------------------
# Per-stage agent words, surfaced in the SAME sticky as a collapsible <details>
# per stage — so the record SHOWS what each step produced (the plan, the test
# output, the review reasoning) instead of only a pass/reject outcome, and it does
# so WITHOUT a second comment: volume inside the sticky is free, a new comment is
# not (see the module header's cost model). Each source is a durable evidence file
# the engine RE-READS on every render — never parsed back out of the prior body,
# so it stays correct across ticks and re-armed runs. Order = pipeline order; the
# label carries the same machine/agent honesty the table does. `_render` renders
# nothing when no file is present, so an early tick reads exactly as it does today.
_NARR_BLOCK_MAX = 4000   # per-stage cap; the rest lives in the PR dossier / evidence
_NARR_MARGIN = 500       # keep the whole body clear of max_body_chars, header included
# Only files the ENGINE writes — never a stage teeing its own stdout, which the
# `test_no_script_swallows_exit_code_via_tee` invariant forbids (the engine owns the
# tee, §5). spec.sh WRITES plan.md from the model's captured stdout; verify's stdout is
# engine-tee'd (evidence: true); review.sh writes verdict.json. The implement stage's
# own account is deliberately NOT here: capturing it needs an engine-owned narration
# sink (a stage `| tee` is banned, and result.notes carries argv+stderr on failures) —
# a separate change. implement's WHAT already shows as the diff numstat in the dossier.
_NARRATION_SOURCES = (
    ("spec/plan.md",        "spec · the plan — [agent] the model's plan, not a measurement",        "text"),
    ("verify/stdout",       "verify · test output — [machine-executed, agent-authored]",             "text"),
    ("review/verdict.json", "review · verdict + reasoning — [agent] an opinion, not a verification", "verdict"),
)


class _Literal(str):
    """The rendered form of an unknown placeholder: `{typo}` stays `{typo}`.

    It yields itself under every operation `str.format_map` can perform on a value it
    looked up, so no field expression can turn a typo into an exception. A plain `str`
    from `__missing__` covers only the bare `{typo}` case and still raises on
    `{typo.attr}` (AttributeError) and `{typo:d}` (ValueError) — both of which a human
    editing a markdown file writes by accident, and neither of which is worth a lost
    record.
    """

    def __getattr__(self, name):        # {typo.attr}
        return self

    def __getitem__(self, key):         # {typo[0]}
        return self

    def __format__(self, spec):         # {typo:d} — a spec for a type this is not
        try:
            return str.__format__(self, spec)
        except (ValueError, TypeError):
            return str(self)


class SafeDict(dict):
    """`format_map` mapping whose misses render literally instead of raising.

    Fail-SOFT on purpose, and the one place in this layer that is: config validation
    fails loud because a wrong knob means the engine does the wrong thing, while a
    typo'd placeholder means one cell reads oddly. Trading the run's record for a
    stray brace is the worse bargain.
    """

    def __missing__(self, key):
        return _Literal("{" + key + "}")


def _probe(fields) -> SafeDict:
    """String samples, because every value this module substitutes is a `str`. That is
    what lets a load-time render prove the render-time one cannot raise."""
    return SafeDict({f: f"\x00{f}\x00" for f in fields})


def _validate_template(name: str, text: str, fields: tuple) -> str:
    """Fail LOUD at wiring time on a template that can never render. Returns the probe."""
    try:
        return text.format_map(_probe(fields))
    except Exception as e:
        raise ValueError(
            f"record template {_TEMPLATE_FILES[name]} cannot render: {e}. A template is a "
            f"str.format_map format string — no Jinja, no loops, no eval. An unknown "
            f"placeholder is fine (it stays literal); this is an unclosed brace, a positional "
            f"field (`{{}}` or `{{0}}` — there are no positional args), or a format spec no "
            f"string can satisfy. Fields for this template: "
            f"{', '.join('{' + f + '}' for f in fields)}."
        )


def _load_templates(templates_dir) -> dict:
    """Resolve both templates: a file under `templates_dir`, else the built-in.

    The DIRECTORY is config and fails loud when wrong — a typo'd path that silently
    served the defaults would leave the knob looking broken with nothing to read. An
    individual FILE is optional: overriding the row format must not force you to copy a
    document skeleton you did not want to touch.

    A relative path resolves against the skill root, never the CWD: the poller runs
    under launchd, whose working directory is nobody's idea of a base path.
    """
    root = None
    if templates_dir:
        root = Path(templates_dir)
        if not root.is_absolute():
            root = _SKILL_ROOT / root
        if not root.is_dir():
            raise ValueError(
                f"record.templates_dir {str(templates_dir)!r} is not a directory (resolved to "
                f"{root}). A relative path resolves against the skill root."
            )

    out = {}
    for name, fname in _TEMPLATE_FILES.items():
        text = _DEFAULT_TEMPLATES[name]
        if root is not None and (root / fname).is_file():
            text = (root / fname).read_text(encoding="utf-8").rstrip("\n")
        out[name] = text

    # Structural checks — each one guards the sticky APPEND, which is the property a
    # bad template destroys silently rather than loudly.
    row = _validate_template("row", out["row"], _ROW_FIELDS)
    if "\n" in row or not row.startswith("|"):
        raise ValueError(
            f"record template {_TEMPLATE_FILES['row']} must render ONE line starting with `|`. "
            f"`_existing_rows` reads the table by exactly that shape, so a row breaking it drops "
            f"the run's history on the next append. Rendered: {row!r}"
        )

    record = _validate_template("record", out["record"], _RECORD_FIELDS)
    if "\x00rows\x00" not in record:
        raise ValueError(
            f"record template {_TEMPLATE_FILES['record']} must contain `{{rows}}` — without it the "
            f"record renders no history and every later append refuses to edit it."
        )
    if not any(_TABLE_SEP_RE.match(ln) for ln in record.splitlines()):
        raise ValueError(
            f"record template {_TEMPLATE_FILES['record']} must contain a markdown table separator "
            f"line (e.g. `|---|---|`) — it is the anchor `_existing_rows` finds the prior rows by."
        )
    return out


def _marker_line(marker: str, item_id: str) -> str:
    return f"<!-- {marker} item={item_id} -->"


def _validate_marker(marker: str) -> None:
    """Fail LOUD at wiring time on a marker that cannot mean what it says.

    Two checks, in this order, because the first one is the security boundary and
    should own the error message:

    1. the REAL parse_reject over the REAL rendered line — a marker whose render
       parses as a reject note turns every record into forged feedback for the
       autonomous producer;
    2. the token charset — refuses values that are inert today but are one
       renderer change away from (1), and nothing would announce that change.
    """
    line = _marker_line(marker or "", _PROBE_ITEM_ID)
    round_n, _ = parse_reject(line + "\n")
    if round_n is not None:
        raise ValueError(
            f"record.sticky_marker {marker!r} renders a line that parse_reject reads as a "
            f"reject note for round {round_n} — every run record would be forged feedback "
            f"handed to the autonomous producer. The record marker and the reject marker "
            f"must never share a grammar."
        )
    if not _MARKER_TOKEN_RE.match(marker or "") or "--" in marker:
        raise ValueError(
            f"record.sticky_marker {marker!r} is not a bare machine token (allowed: letters, "
            f"digits and `.:_-`, and never `--`). A `>` ends the HTML comment early and `--` "
            f"cannot sit inside one; either way the marker becomes visible prose AND the byte-0 "
            f"find misses on the next tick — so every event posts a new comment and notifies "
            f"every subscriber."
        )


# === the single source: one event → its six values ==========================
#
# Everything that renders an engine event derives its text HERE: the sticky
# comment on the board, and every outward reporter hanging off `Engine._emit`. Two
# renderers with two derivations disagree the first time one of them is edited,
# and the disagreement is invisible: both look right on their own.
#
# What is deliberately NOT reachable from these values:
#   * `result.notes`, argv + stderr of a crashed subprocess, so it can reprint a
#     secret; it goes to the launchd ledger and nowhere else;
#   * `item.body`, written by whoever opened the issue, on a public repo;
#   * `result.tokens`, hardcoded 0 on both real paths, so printing it would report
#     a cost that was never measured.
# All three sit one attribute access away from every function below. That is why
# their absence is pinned by tests rather than left to reading discipline.


def iso_now(now=None) -> str:
    """ISO-8601 WITH offset, always.

    There is a real TZ trap on this fleet (DE +02 vs Dubai +04). A naked wall clock
    inherits it: the same run reads as two different afternoons depending on which
    box rendered it, and nothing in the text says which.

    `astimezone()` ONLY when the clock handed us a naive datetime — that is the
    guarantee. Calling it unconditionally re-zones an AWARE clock to whatever the
    worker box is set to, which is the same trap coming back in through the door
    marked "safety net".
    """
    stamp = (now or (lambda: datetime.now().astimezone()))()
    if stamp.tzinfo is None:
        stamp = stamp.astimezone()
    return stamp.isoformat(timespec="seconds")


def clean_cell(text, limit: int = _CELL_MAX, scan: str = "redact") -> str:
    """Scrub → flatten → escape → truncate. Every rendered value goes through here.

    Order matters: scrub FIRST, while the spans still map onto the text the rules
    matched. Redaction is per-span (scan.py), so a false positive costs one
    placeholder, not the whole value.
    """
    out = str(text if text is not None else "")
    if scan == "redact":
        out, _ = scrub(out)
    out = out.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    # `|` would silently re-column a table row; agent-authored text may contain any
    # byte, so this is not a formatting nicety.
    out = out.replace("|", r"\|")
    out = " ".join(out.split())
    if len(out) > limit:
        out = out[: limit - 1].rstrip() + "…"
    return out or "—"


def kind_of(stage) -> str:
    """`machine` = the engine read an exit code from the pipe. `agent` = a model
    spoke. Collapsing the two is how a claim gets read as a measurement."""
    if stage is None or not getattr(stage, "run", ""):
        return "—"
    return "machine" if stage.run.startswith("cmd:") else "agent"


def outcome_text(event, item, stage, fields, status_field="Status", pipeline_field="Pipeline") -> str:
    """The prose for one event: what the engine DID, in the engine's own words.

    `fields` are the per-event extras documented on `Recorder.emit`:
      armed:  to, status_to · stage: to, outcome, attempt, of ·
      reject: to, round, max_rounds, note · park: reason · gate: to, status_to, pr, skipped
    """
    to = fields.get("to")
    if event == "armed":
        parts = [f"armed · {pipeline_field} ∅→{to}"]
        status_to = fields.get("status_to")
        if status_to:
            parts.append(f'{status_field} "{item.status}"→"{status_to}"')
        return " · ".join(parts)

    if event == "note":
        # The stage's own words, verbatim. Cleaning and clamping happen in
        # `row_fields` like for every other cell — this is untrusted text.
        return str(fields.get("note") or "")

    if event == "stage_start":
        # No outcome, no duration, no result: at this moment there is none. The
        # row says exactly what is true — the stage was dispatched and the engine
        # is now waiting on it.
        return "**running** · dispatched, no result yet"

    if event == "stage":
        kind = fields.get("outcome", "pass")
        if kind == "retry":
            sid = getattr(stage, "id", "stage")
            return f"retry {fields.get('attempt', '?')}/{fields.get('of', '?')} · {sid} re-runs"
        if kind == "rewind":
            return f"rewind → {to}"
        return f"pass → {to}"

    if event == "reject":
        parts = [f"**reject** → {to} · round {fields.get('round', '?')}/{fields.get('max_rounds', '?')}"]
        if fields.get("note"):
            parts.append(f"note: {fields['note']}")
        return " · ".join(parts)

    if event == "park":
        return f"**parked** · {fields.get('reason') or 'no reason given'}"

    # gate — the engine's last act on this item, at both call sites
    parts = ["PR already open" if fields.get("skipped") else f"pass → {to}"]
    if fields.get("pr"):
        parts.append(str(fields["pr"]))
    if fields.get("status_to"):
        parts.append(f'{status_field} → "{fields["status_to"]}"')
    parts.append("**STOP**")
    return " · ".join(parts)


def row_fields(
    event,
    item,
    stage=None,
    result=None,
    fields=None,
    *,
    when=None,
    status_field="Status",
    pipeline_field="Pipeline",
    scan="redact",
) -> dict:
    """One event → the six values of `_ROW_FIELDS`, cleaned and ready to render.

    Returned as a dict keyed by field name rather than a positional tuple, so a
    renderer that wants four of the six cannot silently pick the wrong four.
    """
    fields = fields or {}
    if event == "armed":
        # No handler, no kind, no criteria: at ARM the stage is not resolved yet
        # (the dispatch loop has not run). Borrowing the first stage's would be
        # invention.
        cells = ["—", "—", "—", "—"]
    elif event == "note":
        # `agent`, not `machine`: a note is words, and `kind` is exactly the column
        # that separates a measured exit code from a model's opinion. No duration,
        # because a note does not take time — an empty one reads as instant.
        cells = [clean_cell(getattr(stage, "id", "") or "—", 40, scan), "agent", "—", "—"]
    else:
        cells = [
            clean_cell(getattr(stage, "id", "") or "—", 40, scan),
            kind_of(stage),
            clean_cell(getattr(result, "criteria_ref", None) or "—", 80, scan),
            _took(getattr(result, "duration_s", None)),
        ]
    outcome = clean_cell(
        outcome_text(event, item, stage, fields, status_field, pipeline_field),
        _OUTCOME_MAX,
        scan,
    )
    return dict(zip(_ROW_FIELDS, [when if when is not None else iso_now(), *cells, outcome]))


def _took(seconds) -> str:
    if seconds is None:
        return "—"
    total = int(round(float(seconds)))
    if total < 60:
        return f"{total}s"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{sec:02d}s"


def _span(rows: "list[str]") -> str:
    """First → last recorded entry. Derived from the rows themselves, so it cannot
    disagree with what is printed above it."""
    stamps = [m.group(1) for m in (_WHEN_RE.match(r) for r in rows) if m]
    if len(stamps) < 2:
        return ""
    try:
        start, end = datetime.fromisoformat(stamps[0]), datetime.fromisoformat(stamps[-1])
    except ValueError:
        return ""
    minutes = int((end - start).total_seconds() // 60)
    delta = f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"
    return f"{start.strftime('%H:%M')}→{end.strftime('%H:%M')} ({delta})"


class Recorder:
    """Renders and upserts the sticky run record.

    Parameters
    ----------
    sink :
        The comment port. Needs `comment(item_id, text)` (exists on both board
        clients today), plus `list_comments(item_id) -> [{id, body, viewerDidAuthor}]`
        and `edit_comment(comment_id, body)` — the two the adapters must still grow.
    config : RecordConfig
    status_field, pipeline_field :
        Board display names, for the transition prose only. They live on the board
        client, not in EngineConfig, so cli.py should pass them; the defaults are
        generic rather than wrong.
    now :
        Injectable clock. Returns an AWARE datetime — see `_when`.
    """

    def __init__(
        self,
        sink,
        config,
        *,
        status_field="Status",
        pipeline_field="Pipeline",
        evidence_dir=None,
        project="",
        now=None,
    ):
        _validate_marker(getattr(config, "sticky_marker", "") or "")
        self.tmpl = _load_templates(getattr(config, "templates_dir", None))
        self.sink = sink
        self.cfg = config
        self.status_field = status_field
        self.pipeline_field = pipeline_field
        # The per-ITEM evidence dir template ({item_id} still pending), for narration.
        # None = today's engine: no evidence to read, so the record renders no <details>.
        self.evidence_dir = evidence_dir
        self._project = project
        self._max_body = getattr(config, "max_body_chars", 60000)
        self._now = now or (lambda: datetime.now().astimezone())

    # -- rendering ---------------------------------------------------------
    # Thin wrappers over the module-level source above. They stay as methods
    # because they close over this Recorder's clock, scan mode and field names,
    # not because the derivation lives here. It does not, and must not: an
    # outward reporter renders the SAME event and would otherwise grow a second
    # derivation that agrees today and diverges on the first edit.
    def _when(self) -> str:
        return iso_now(self._now)

    def _clean(self, text, limit: int = _CELL_MAX) -> str:
        return clean_cell(text, limit, getattr(self.cfg, "scan", "redact"))

    @staticmethod
    def _kind(stage) -> str:
        return kind_of(stage)

    def _outcome(self, event, item, stage, fields) -> str:
        return outcome_text(event, item, stage, fields, self.status_field, self.pipeline_field)

    def _row(self, event, item, stage, result, fields) -> str:
        return self.tmpl["row"].format_map(
            SafeDict(
                row_fields(
                    event,
                    item,
                    stage,
                    result,
                    fields,
                    when=self._when(),
                    status_field=self.status_field,
                    pipeline_field=self.pipeline_field,
                    scan=getattr(self.cfg, "scan", "redact"),
                )
            )
        )

    def _render(self, item, rows: "list[str]") -> str:
        body = "\n".join(rows)
        hits = _REDACTION_RE.findall(body)
        summary = [f"{len(rows)} {'entry' if len(rows) == 1 else 'entries'}"]
        rework = sum(1 for r in rows if "**reject**" in r)
        if rework:
            summary.append(f"{rework} rework {'round' if rework == 1 else 'rounds'}")
        if hits:
            rules = ", ".join(f"`{r}`" for r in sorted(set(hits)))
            summary.append(f"{len(hits)} {'redaction' if len(hits) == 1 else 'redactions'} ({rules})")
        span = _span(rows)
        if span:
            summary.append(span)
        issue = f" — #{item.issue_number}" if getattr(item, "issue_number", None) else ""
        fields = dict(
            marker=_marker_line(self.cfg.sticky_marker, item.id),
            issue=issue,
            rows=body,
            summary=" · ".join(summary),
            narration="",
        )
        # Two passes so the narration NEVER pushes the body past max_body_chars: render
        # the skeleton empty to measure it, give what is left (minus a margin) to the
        # narration, then render for real. A GitHub comment that exceeds 65536 chars is
        # rejected outright — and emit_guarded would swallow that into the ledger, so the
        # whole record would silently vanish. The cap is not optional.
        base = self.tmpl["record"].format_map(SafeDict(**fields))
        fields["narration"] = self._narration(item, self._max_body - len(base) - _NARR_MARGIN)
        return self.tmpl["record"].format_map(SafeDict(**fields)) + "\n"

    # -- narration: the agent words each stage left as evidence, per stage --
    def _item_evidence_dir(self, item) -> "str | None":
        """This item's evidence dir, or None. Same template the runner resolves, so it
        points at the very files the stages tee'd — resolved defensively, since an
        unresolved placeholder must degrade to "no narration", never raise."""
        if not self.evidence_dir:
            return None
        try:
            return self.evidence_dir.format_map(
                SafeDict(item_id=item.id, project=self._project, item=item)
            )
        except Exception:
            return None

    @staticmethod
    def _verdict_text(raw: str) -> str:
        """A review verdict.json → readable `verdict + annotation`. Unparseable JSON
        falls back to the raw bytes (still scrubbed downstream) rather than hiding it."""
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            return raw
        if not isinstance(d, dict):
            return raw
        return f"verdict: {d.get('verdict') or 'unknown'}\n\n{d.get('annotation') or '(no annotation)'}"

    def _details_block(self, summary_label: str, content: str, limit: int) -> str:
        """One collapsible <details> block, agent words inside a code fence.

        The fence is what makes this safe to embed raw: newlines survive (a code block,
        not a table cell, so no flatten), a stray `|` cannot re-column anything, markdown
        and HTML inside are inert, and the fence length always exceeds the longest run of
        backticks in the body so the content can never break out of it. Scrub still runs
        first (redact-never-block), so a secret in the agent's own words is redacted here
        exactly as in a cell — just without destroying the newlines.
        """
        scrubbed = content
        if getattr(self.cfg, "scan", "redact") == "redact":
            scrubbed, _ = scrub(scrubbed)
        scrubbed = scrubbed.rstrip("\n")
        if len(scrubbed) > limit:
            scrubbed = scrubbed[:limit].rstrip() + "\n… (truncated — full text in the PR dossier / evidence)"
        longest = max((len(m) for m in re.findall(r"`+", scrubbed)), default=0)
        fence = "`" * max(3, longest + 1)
        return (
            f"<details>\n<summary>{summary_label}</summary>\n\n"
            f"{fence}\n{scrubbed}\n{fence}\n\n</details>"
        )

    def _narration(self, item, budget: int) -> str:
        """The per-stage <details> section, or "" — read fresh from evidence each render.

        `budget` is the chars left under max_body_chars; blocks are emitted in pipeline
        order until it runs out, each one also capped to `_NARR_BLOCK_MAX`. Reading from
        the evidence files (never from the prior comment body) is what keeps it correct
        across ticks: `_existing_rows` recovers only the table, so anything else in the
        body is rebuilt from source every time.
        """
        if not self.evidence_dir or budget <= 0:
            return ""
        item_dir = self._item_evidence_dir(item)
        if not item_dir:
            return ""
        base = Path(item_dir)
        blocks: "list[str]" = []
        used = 0
        for rel, label, kind in _NARRATION_SOURCES:
            try:
                raw = (base / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue                       # stage not run yet, or no such artefact
            if not raw.strip():
                continue
            room = min(_NARR_BLOCK_MAX, budget - used)
            if room <= 0:
                break
            content = self._verdict_text(raw) if kind == "verdict" else raw
            block = self._details_block(label, content, room)
            blocks.append(block)
            used += len(block) + 2             # +2 for the "\n\n" join
        if not blocks:
            return ""
        return "### What each step produced\n\n" + "\n\n".join(blocks) + "\n\n"

    # -- upsert ------------------------------------------------------------
    def _find_sticky(self, item):
        """The LAST engine-authored comment carrying this item's marker at byte 0.

        `viewerDidAuthor is not True` — GitHub's server-side assertion, the same
        fail-closed predicate the reject read-back uses. A comment whose authorship
        was not positively asserted is never this engine's sticky, so the record is
        never appended to a body someone else controls.
        """
        marker = _marker_line(self.cfg.sticky_marker, item.id)
        found = None
        for c in self.sink.list_comments(item.id) or ():
            if c.get("viewerDidAuthor") is not True:
                continue
            if (c.get("body") or "").startswith(marker):
                found = c
        return found

    def _existing_rows(self, body: str) -> "list[str]":
        lines = (body or "").splitlines()
        start = next((i + 1 for i, ln in enumerate(lines) if _TABLE_SEP_RE.match(ln)), None)
        if start is None:
            # Refuse rather than rebuild: the prior rows exist ONLY in this body, so
            # an edit that cannot find them would drop the run's history and still
            # read as a complete record. Raising lands it in the ledger instead.
            raise ValueError(
                "run record: table separator not found — refusing to edit, the prior rows "
                "would be dropped and the record would read as complete"
            )
        rows = []
        for line in lines[start:]:
            if not line.startswith("|"):
                break
            rows.append(line)
        return rows

    def emit(self, event: str, item, *, stage=None, result=None, **fields) -> None:
        """Append one row for `event`.

        RAISES on any sink failure — deliberately. If this swallowed, the caller's
        own guard would be untestable: `test_record_failure_never_converts_advance_to_skip`
        would pass whether or not the try/except in tick.py exists. The guard belongs
        at the call site and is `emit_guarded` below.

        Fields per event (all keyword):
          armed  — to, status_to
          stage  — to, outcome ∈ {pass, retry, rewind}, attempt, of
          reject — to, round, max_rounds, note
          park   — reason  (engine-authored; NEVER res.notes)
          gate   — to, status_to, pr, skipped
        """
        if event not in _EVENTS:
            raise ValueError(f"unknown record event {event!r}; valid: {sorted(_EVENTS)}")
        if not self.cfg.enabled or event not in (self.cfg.events or ()):
            return

        row = self._row(event, item, stage, result, fields)
        # `armed` always OPENS a run: a re-armed item is a NEW run (a human cleared
        # the pipeline and dragged the card back, and its bounce count was reset).
        # Appending to the previous run's table would report one run where two
        # happened.
        found = None if event == "armed" else self._find_sticky(item)
        if found is None:
            self.sink.comment(item.id, self._render(item, [row]))
            return
        self.sink.edit_comment(found["id"], self._render(item, self._existing_rows(found["body"]) + [row]))


def emit_guarded(recorder, res, event: str, item, **kwargs) -> None:
    """Call `recorder.emit` so that it can NEVER become a termination path.

    This is the hardest invariant in the transparency layer. An unguarded hook that
    raises lands in the dispatch loop's outer guard (tick.py:279-281) → res.skipped
    → the item re-dispatches next poll — WITHOUT rolling back the set_pipeline that
    already landed. A permanently failing sink (a 403, a deleted issue) therefore
    re-runs the most expensive stage on every poll forever, while reporting a
    successful advance as a skip.

    `res` is an explicit PARAMETER, never reached out for: an earlier design
    referenced it out of scope, which raises NameError INSIDE the hook — i.e. it
    produced exactly the damage the hook exists to avoid.

    The failure goes to `res.notes` — the launchd ledger — and never to the board.
    That is the same channel that carries `{e!r}` of a GhCliError (argv + stderr,
    gh_board.py:34-38), which is precisely why nothing posts it.
    """
    if recorder is None:
        return
    try:
        recorder.emit(event, item, **kwargs)
    except Exception as e:  # a report must never decide whether work advances
        # The receiver names itself when it can. With more than one sink on the
        # seam, "the report failed" without saying WHICH one is a ledger line that
        # cannot be acted on. The sticky, which has no name, stays `record`.
        who = getattr(recorder, "name", None) or "record"
        res.notes = (res.notes + f"; {who} {event} {item.id}: {e!r}").lstrip("; ")
