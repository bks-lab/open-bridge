"""Pipeline config — the per-project `pipeline:` block from
workflow/projects/<slug>.yaml, parsed into an EngineConfig.

The engine is generic; ALL project specifics (which stages, which handlers, the
trigger column) live in config. A heavy project (a compiled product) and a light one (docs) use
the SAME engine with different config.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import re

from .interfaces import Stage
from .record import DEFAULT_EVENTS, EVENTS

# --- transparency: the closed sets -----------------------------------------
# Every value a human can type into the `record:`/`evidence:`/`report:` blocks is
# checked against one of these. The loader below builds EngineConfig from a FIXED
# keyword set and never populates `extra`, so an unrecognised knob is not a no-op
# with a warning: it is invisible. Silently ignoring `require_issue` arms draft
# cards and burns an LLM run on an item that can carry no `Closes #N` and no comment.
#
# The event vocabulary is IMPORTED, never re-typed here. It already existed in
# record.py; a second literal would be a second place for a new event to arrive,
# and the copy that missed it would reject the event as unknown at load while the
# other emitted it happily.
# Vocabulary (what validates) and default (what a silent target gets) are two
# different lists since `note` exists. See record.DEFAULT_EVENTS.
_RECORD_EVENTS = EVENTS
_DEFAULT_EVENTS = DEFAULT_EVENTS
_RECORD_SCAN_MODES = ("redact", "off")
_RECORD_KEYS = ("enabled", "events", "sticky_marker", "templates_dir", "max_body_chars", "scan")
_EVIDENCE_KEYS = ("dir", "require_deterministic")

# --- report: the outward seam ----------------------------------------------
# A target says WHAT kind of wire (`type`), WHEN it speaks (`mode`), and WHICH
# events reach it (`events`), never an address. `url_env` names an environment
# variable; the address itself never enters a tracked file (rules/secret-placement.md),
# which matters twice over here because this skill is `scope: core` and ships into
# the target repo, and a demo repo can be public.
_REPORT_KEYS = ("targets",)
_REPORT_TARGET_KEYS = ("name", "type", "mode", "enabled", "events", "flush_on", "url_env",
                       "path", "card", "factory", "options")
_CARD_KEYS = ("incident", "incident_env", "sender", "labels", "links", "words",
              "stage_names")
_REPORT_TYPES = ("webhook", "file", "python", "module")
_REPORT_MODES = ("stream", "digest")
_ENV_NAME_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")

# The card's label vocabulary is imported, never retyped. A label this file accepts
# and the card never reads is a knob that does nothing; one the card reads and this
# file refuses is a card that cannot be translated. Both are the same drift.
from .card import LABEL_KEYS  # noqa: E402 - placed with the other report vocabulary

# A `step` label MUST interpolate both the position and the total, and must carry no
# digit of its own. The scar: this count once existed as three declarations in two
# files, one of them prose ("Step 3 of 5"), with nothing comparing them — so the
# channel showed six while the declared source said five and nobody noticed.
_STEP_DIGIT_RE = re.compile(r"[0-9]")


@dataclass
class RecordConfig:
    """The record layer's knobs. `enabled: False` = today's engine, which writes
    no run record at all."""

    enabled: bool = False
    events: tuple = _DEFAULT_EVENTS
    sticky_marker: str = "board-pilot:run"
    templates_dir: str | None = None
    max_body_chars: int = 60000       # GitHub's hard ceiling is 65536
    scan: str = "redact"              # redact | off — the PR body is fail-closed regardless


@dataclass
class EvidenceConfig:
    dir: str | None = None
    # Fail-closed default: an agent stage reporting on itself is not evidence, it
    # is a claim. Safe to default ON because no config declares per-stage
    # `evidence:` today, so this refuses nothing that works now.
    require_deterministic: bool = True


@dataclass
class CardConfig:
    """The second rendering of a target's events: an adaptive card.

    Absent = today's engine, a text row and nothing else. Present = the same six
    values ALSO shaped for a screen. `labels` is how the instance gives the card
    its language; this skill ships into whatever repo it drives, so the words
    belong to the project YAML rather than to the engine.
    """

    incident: str = ""              # the constant band on every card of a run
    # The NAME of a variable holding that band, for the common case where the id is
    # minted outside this engine (an alarm invents INC-001 and spawns the run). Same
    # split as `url_env`: config names the variable, the environment holds the value.
    # A literal `incident` wins; an unset variable falls back to the item reference,
    # never to the variable's own name and never to "None".
    incident_env: str = ""
    sender: str = ""                # who the card says it is from, in the card itself
    labels: dict = field(default_factory=dict)
    # Extra buttons after the item's own, as [{label, url}]. The url may carry a
    # {placeholder} filled from the event's own fields; a link whose placeholder has
    # no value for an event is DROPPED rather than rendered empty.
    # Stage ids in the viewer's language, for the journey line ONLY. Separate from
    # `words` because stage ids and pipeline values collide: `words` reaches the
    # outcome, and an entry `pr` there rewrites the real column value `pr-ready`.
    stage_names: dict = field(default_factory=dict)
    links: list = field(default_factory=list)
    # Presentation-only vocabulary for the outcome line: {engine word: your word}.
    # Never a second source — it renames a value the row already carried, whole
    # words only, and anything absent from it passes through untouched.
    words: dict = field(default_factory=dict)


@dataclass
class ReportTarget:
    """One declared outward sink. Defaults are today's engine plus one honest knob:
    a target that is LISTED is on, because a listed target that quietly does nothing
    is the same class of bug as an ignored key."""

    name: str
    type: str
    mode: str = "stream"
    enabled: bool = True
    events: tuple = _DEFAULT_EVENTS
    # Only meaningful for `mode: digest`: the events at which the collected run is
    # sent and the spool cleared. Both engine terminals by default.
    flush_on: tuple = ()
    url_env: str | None = None      # NAME of an env var holding the address, never the address
    path: str | None = None
    card: "CardConfig | None" = None
    # `type: python` only. "<module or file>:<attribute>" — the callable that
    # returns this instance's own sink, plus the keywords it is handed.
    factory: str | None = None
    options: dict = field(default_factory=dict)


@dataclass
class EngineConfig:
    stages: list
    trigger_status: str = "Todo"
    pr_status: str = "In Review"      # status set after the gated PR stage
    done_status: str = "Done"         # the engine MUST NEVER set this (human-only)
    concurrency: int = 1
    token_ceiling: int | None = None
    project: str = "test"
    bounce_field: str = "Bounces"     # board Number field — durable reject counter
    max_rounds: int | None = None     # rework.max_rounds default (per-edge override on the stage)
    extra: dict = field(default_factory=dict)
    # --- transparency ----------------------------------------------------
    # All default to today's behaviour: None means "the engine does not write
    # this column", so landing these knobs changes no pipeline already running.
    working_status: str | None = None   # written at ARM, so a taken card leaves the free column
    park_status: str | None = None      # written at EVERY park, so a parked card stops looking fresh
    require_issue: bool = False         # opt-in: refuse to arm a card with no issue behind it
    record: RecordConfig = field(default_factory=RecordConfig)
    evidence: EvidenceConfig = field(default_factory=EvidenceConfig)
    # Outward sinks. Empty = today's engine exactly: no sink is built, none is
    # called, nothing is logged. Every project that does not declare `report:`
    # gets that for free, without opting out of anything.
    report: tuple = ()


def _on_success(raw) -> str:
    """on_success may be a bare string or a mapping like {set_pipeline: implementing}."""
    if isinstance(raw, dict):
        return raw.get("set_pipeline") or raw.get("set_status") or ""
    return raw or ""


def validate_chain(stages: list, rework_max_rounds=None) -> None:
    """Fail LOUD at load if any transition target is unresolvable.

    Builds the pipeline before-key set (the ``queued`` entry plus each stage's
    ``on_success``) and the stage-id→index map, then checks:

    * every ``on_success`` is non-empty (it defines the chain);
    * every ``rewind_to`` resolves to a real before-key or the terminal value;
    * every ``reject_to`` (the reject edge) names a real stage id that is
      STRICTLY UPSTREAM of the rejecting stage, with a resolvable positive
      ``max_rounds`` (per-edge override, else ``rework.max_rounds``).

    Raises ``ValueError`` naming the offending stage AND target — never a silent
    runtime stall.
    """
    if not stages:
        return
    before_keys = set()
    idx_by_id: dict = {}
    before = "queued"
    for i, s in enumerate(stages):
        before_keys.add(before)
        idx_by_id[s.id] = i
        before = s.on_success
    terminal = stages[-1].on_success
    valid_targets = before_keys | {terminal}

    for i, s in enumerate(stages):
        if not s.on_success:
            raise ValueError(f"stage {s.id!r}: empty on_success — every stage must name its next pipeline state")
        if s.on_fail == "rewind" and s.rewind_to is not None:
            if s.rewind_to not in valid_targets:
                raise ValueError(
                    f"stage {s.id!r}: rewind target {s.rewind_to!r} resolves to no pipeline state; "
                    f"valid before-keys: {sorted(valid_targets)}"
                )
        reject_to = getattr(s, "reject_to", None)
        if reject_to is not None:
            if reject_to not in idx_by_id:
                raise ValueError(
                    f"stage {s.id!r}: on_reject target {reject_to!r} is not a known stage id; "
                    f"have {sorted(idx_by_id)}"
                )
            if idx_by_id[reject_to] >= i:
                raise ValueError(
                    f"stage {s.id!r}: on_reject target {reject_to!r} must be STRICTLY UPSTREAM "
                    f"(target index {idx_by_id[reject_to]} >= rejecting stage index {i}) — "
                    f"a downstream/self target would push a rejected item toward the PR gate"
                )
            eff = getattr(s, "max_rounds", None) or rework_max_rounds
            if not (isinstance(eff, int) and eff > 0):
                raise ValueError(
                    f"stage {s.id!r}: declares on_reject but effective max_rounds is not a positive int "
                    f"(stage.max_rounds={getattr(s, 'max_rounds', None)!r}, rework.max_rounds={rework_max_rounds!r}); "
                    f"set rework.max_rounds (or the per-edge max_rounds) to a positive int"
                )


def _reject_unknown_keys(block: dict, valid: tuple, where: str) -> None:
    unknown = sorted(set(block) - set(valid))
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s) {unknown}; valid keys: {sorted(valid)} — "
            f"an unrecognised knob here is never applied, and this loader has no other "
            f"way to tell you that"
        )


def validate_transparency(stages: list, record: dict, evidence: dict, criteria_dir=None) -> None:
    """Fail LOUD at load on a transparency knob that cannot mean what it says.

    Mirrors ``validate_chain``: names the offending value AND the valid set, never
    a silent fallback to a default. A typo'd ``scan: reduct`` that quietly falls
    back to "redact" reads as "redaction is on" while agent-authored text goes to
    a public repo unscanned.

    Checks:

    * ``record``/``evidence`` carry only known keys, and ``record.scan`` /
      ``record.events`` only known values — checked even when the block is
      disabled, because a typo is still a typo the moment someone flips it on;
    * no stage is an evidence source unless its ``run:`` is ``cmd:`` (an LLM stage
      would be reporting on its own work, and the dossier labels evidence as
      machine-captured) — the ``evidence.require_deterministic`` knob;
    * no stage names ``criteria:`` without a ``board.criteria_dir`` to resolve it
      against.

    Only facts the config can answer about ITSELF live here. Whether a criteria
    file EXISTS is a fact about the filesystem, like whether a board option
    exists — that belongs with the environmental checks at engine preflight
    (``preflight_reject_field``), not in a loader that legitimately runs where the
    target repo does not.
    """
    _reject_unknown_keys(record, _RECORD_KEYS, "record")
    _reject_unknown_keys(evidence, _EVIDENCE_KEYS, "evidence")

    scan = record.get("scan", "redact")
    if scan not in _RECORD_SCAN_MODES:
        raise ValueError(
            f"record.scan: {scan!r} is not a known scan mode; valid: {sorted(_RECORD_SCAN_MODES)}"
        )

    unknown_events = [e for e in (record.get("events") or _DEFAULT_EVENTS) if e not in _RECORD_EVENTS]
    if unknown_events:
        raise ValueError(
            f"record.events: unknown event(s) {sorted(unknown_events)}; valid: {sorted(_RECORD_EVENTS)}"
        )

    require_deterministic = bool(evidence.get("require_deterministic", True))
    for s in stages:
        if s.evidence and require_deterministic and not s.run.startswith("cmd:"):
            raise ValueError(
                f"stage {s.id!r}: evidence: true but run={s.run!r} is not deterministic — "
                f"only a cmd: stage may be an evidence source, because the engine reads that "
                f"stage's output from the pipe; an LLM stage would be reporting on its own work "
                f"while the dossier labels it machine-captured. Set "
                f"evidence.require_deterministic: false to allow it anyway"
            )
        if s.criteria and not criteria_dir:
            raise ValueError(
                f"stage {s.id!r}: criteria {s.criteria!r} is a filename relative to "
                f"board.criteria_dir, but no board.criteria_dir is set — the path resolves to "
                f"nothing and the record would cite a standard the engine never read"
            )


def validate_report(report: dict) -> tuple:
    """Fail LOUD at load on a report target that cannot mean what it says.

    This block needs the check MORE than `record:` does, not less. At runtime every
    sink is wrapped in ``emit_guarded`` (a report must never decide whether work
    advances), so a broken target degrades to a line in the launchd ledger while the
    channel stays quiet. During a live run that is indistinguishable from "the
    automation is still thinking", which is the exact failure the channel exists to
    prevent. Load time is the only place it is visible.

    Returns the parsed targets, so the parse and the check cannot drift apart.
    """
    _reject_unknown_keys(report, _REPORT_KEYS, "report")
    raw = report.get("targets") or []
    if not isinstance(raw, list):
        raise ValueError(f"report.targets: expected a list of targets, got {type(raw).__name__}")

    targets = []
    seen: set = set()
    for i, t in enumerate(raw):
        where = f"report.targets[{i}]"
        if not isinstance(t, dict):
            raise ValueError(f"{where}: expected a mapping, got {type(t).__name__}")
        _reject_unknown_keys(t, _REPORT_TARGET_KEYS, where)

        name = t.get("name")
        if not name or not isinstance(name, str):
            raise ValueError(f"{where}: a target needs a `name`. It labels the ledger line when "
                             f"the sink fails, and it keys the digest spool on disk")
        if name in seen:
            raise ValueError(f"{where}: duplicate target name {name!r}. Two digests sharing a name "
                             f"share one spool file and would report each other's rows")
        seen.add(name)
        where = f"report.targets[{name}]"

        kind = t.get("type")
        if kind not in _REPORT_TYPES:
            raise ValueError(f"{where}.type: {kind!r} is not a known transport; valid: {sorted(_REPORT_TYPES)}")

        mode = t.get("mode", "stream")
        if mode not in _REPORT_MODES:
            raise ValueError(f"{where}.mode: {mode!r} is not a known mode; valid: {sorted(_REPORT_MODES)} "
                             f"(`stream` sends per event, `digest` collects and sends at `flush_on`)")

        events = tuple(t.get("events") or _DEFAULT_EVENTS)
        unknown = sorted(e for e in events if e not in _RECORD_EVENTS)
        if unknown:
            raise ValueError(f"{where}.events: unknown event(s) {unknown}; valid: {sorted(_RECORD_EVENTS)}")

        flush_on = tuple(t.get("flush_on") or ())
        if mode == "digest":
            if not flush_on:
                raise ValueError(f"{where}.flush_on: a digest with no flush event collects forever and "
                                 f"reports nothing. Name the events at which the run is sent")
            unknown = sorted(e for e in flush_on if e not in events)
            if unknown:
                raise ValueError(f"{where}.flush_on: {unknown} is outside this target's own `events` "
                                 f"{sorted(events)}. A flush event the target filters out never arrives, "
                                 f"so the digest would never send")
        elif flush_on:
            raise ValueError(f"{where}.flush_on: only a `mode: digest` target flushes; a stream target "
                             f"sends every event as it happens and would never read this")

        factory = t.get("factory")
        if kind in ("python", "module"):
            # Resolved HERE so a typo is a load error with a name in it, never a
            # channel that quietly stays silent. Only the attribute is resolved;
            # calling it belongs to the build (see build_reporters), because a
            # load-time `.emit` check would run the factory twice.
            built = "sink" if kind == "python" else "transport"
            if not factory:
                raise ValueError(f"{where}.factory: a {kind} target must name the callable that "
                                 f"builds its {built}, as \"<module or file>:<attribute>\"")
            if not t.get("enabled", True):
                # A disabled target must not run instance code at all. Resolving
                # imports a module, and importing is running.
                pass
            else:
                resolve_sink_factory(factory, where)
        elif factory:
            raise ValueError(f"{where}.factory: only a `type: python` or `type: module` target builds "
                             f"from a callable; this target is {kind!r} and would never read it")
        if t.get("options") and kind not in ("python", "module"):
            # `options` are the keywords handed to a factory. A webhook or file
            # target has none, so the knob would be silently ignored.
            raise ValueError(f"{where}.options: only a `type: python` or `type: module` target hands "
                             f"options to its factory; this target is {kind!r} and would never read them")

        url_env, path = t.get("url_env"), t.get("path")
        if kind in ("python", "module"):
            # Both reach their destination through the named callable. An address
            # or a path here is a leftover from an edit that changed `type:` and
            # forgot the rest, and a key nothing reads is the same class of bug as
            # a knob that silently does nothing.
            for key, value in (("url_env", url_env), ("path", path)):
                if value:
                    raise ValueError(f"{where}.{key}: a {kind} target reaches its destination through "
                                     f"its own factory; `{key}` would never be read")
        elif kind == "webhook":
            if not url_env:
                raise ValueError(f"{where}.url_env: a webhook target must name the environment variable "
                                 f"holding its address")
            if path:
                raise ValueError(f"{where}.path: a webhook target writes no file; `path` would never be read")
        else:  # file
            if not path:
                raise ValueError(f"{where}.path: a file target must name the file it appends to")
            if url_env:
                raise ValueError(f"{where}.url_env: a file target opens no socket; `url_env` would never be read")

        if url_env and not _ENV_NAME_RE.match(str(url_env)):
            raise ValueError(
                f"{where}.url_env: {url_env!r} is not the NAME of an environment variable "
                f"(letters, digits, underscore). The address itself never belongs in a tracked "
                f"file: this skill ships into the target repo, and a demo repo can be public."
            )

        card = _validate_card(t.get("card"), where)

        targets.append(
            ReportTarget(
                name=name,
                type=kind,
                mode=mode,
                enabled=bool(t.get("enabled", True)),
                events=events,
                flush_on=flush_on,
                url_env=url_env,
                path=path,
                card=card,
                factory=factory,
                options=dict(t.get("options") or {}),
            )
        )
    return tuple(targets)


def _validate_card(raw, where: str):
    """Parse and check one target's `card:` block. None (absent) stays None.

    Absent is the whole no-config story here too: no card is built, the transport is
    called with one argument, and a wire written before this block existed keeps
    working untouched.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{where}.card: expected a mapping, got {type(raw).__name__}")
    _reject_unknown_keys(raw, _CARD_KEYS, f"{where}.card")

    labels = raw.get("labels") or {}
    if not isinstance(labels, dict):
        raise ValueError(f"{where}.card.labels: expected a mapping, got {type(labels).__name__}")
    unknown = sorted(k for k in labels if k not in LABEL_KEYS)
    if unknown:
        raise ValueError(f"{where}.card.labels: unknown label(s) {unknown}; valid: {sorted(LABEL_KEYS)}. "
                         f"A label the card never reads is a knob that does nothing")
    for key, value in labels.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}.card.labels.{key}: expected a non-empty string")

    step = labels.get("step")
    if step is not None:
        missing = [ph for ph in ("{n}", "{m}") if ph not in step]
        if missing:
            raise ValueError(
                f"{where}.card.labels.step: {step!r} is missing {missing}. The position and the "
                f"total are interpolated from the pipeline's own stage chain, so a label that "
                f"drops one of them prints a count nothing keeps honest"
            )
        if _STEP_DIGIT_RE.search(step):
            raise ValueError(
                f"{where}.card.labels.step: {step!r} carries a literal digit. The count has ONE "
                f"source, the stage chain the engine runs; a number written into prose is a "
                f"second declaration of it, and the second one is the one that goes stale"
            )

    armed = labels.get("armed")
    if armed is not None and _STEP_DIGIT_RE.search(armed):
        # The ARM label may carry {m} and may leave it out — but a DIGIT in it is the
        # same second declaration `step` is refused for, and worse here: the ARM card
        # is the first one on the screen, so a stale total is what the room reads
        # before anything else has happened.
        raise ValueError(
            f"{where}.card.labels.armed: {armed!r} carries a literal digit. Use {{m}}; the "
            f"total comes from the stage chain the engine runs and from nowhere else"
        )

    links = raw.get("links") or []
    if not isinstance(links, list):
        raise ValueError(f"{where}.card.links: expected a list, got {type(links).__name__}")
    for n, link in enumerate(links):
        at = f"{where}.card.links[{n}]"
        if not isinstance(link, dict):
            raise ValueError(f"{at}: expected a mapping, got {type(link).__name__}")
        _reject_unknown_keys(link, ("label", "url"), at)
        for key in ("label", "url"):
            # BOTH are required, and neither can be inferred. A link without a url
            # is a button that opens nothing; a link without a label is a button
            # nobody can read. Refused at load, because at runtime a malformed
            # target is simply a card with one button fewer.
            if not isinstance(link.get(key), str) or not link[key].strip():
                raise ValueError(f"{at}.{key}: expected a non-empty string")

    words = raw.get("words") or {}
    if not isinstance(words, dict):
        raise ValueError(f"{where}.card.words: expected a mapping, got {type(words).__name__}")
    for key, value in words.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}.card.words.{key}: expected a non-empty string")

    stage_names = raw.get("stage_names") or {}
    if not isinstance(stage_names, dict):
        raise ValueError(
            f"{where}.card.stage_names: expected a mapping, got {type(stage_names).__name__}")
    for key, value in stage_names.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{where}.card.stage_names.{key}: expected a non-empty string")

    return CardConfig(
        incident=str(raw.get("incident") or ""),
        incident_env=str(raw.get("incident_env") or ""),
        sender=str(raw.get("sender") or ""),
        labels=dict(labels),
        links=[dict(x) for x in links],
        words=dict(words),
        stage_names=dict(stage_names),
    )


def resolve_sink_factory(spec: str, where: str = "report.target"):
    """"<module or file>:<attribute>" -> the callable. Raises ValueError, named.

    Two spellings, because the two real cases differ: a dotted module for something
    already importable, and a file path for a sink that lives beside the config
    rather than on `sys.path`. A path is anything carrying a separator or ending in
    `.py`; everything else is dotted.

    Bytecode writing is suppressed for the file form. A `.pyc` appearing next to a
    script has broken a guardrail here before, and a sink loaded from a work tree is
    exactly where that would happen again.
    """
    import importlib
    import importlib.util
    import os
    import sys

    if ":" not in spec:
        raise ValueError(f"{where}.factory: {spec!r} has no \":\" — the spelling is "
                         f"\"<module or file>:<attribute>\"")
    where_from, _, attr = spec.rpartition(":")
    if not where_from or not attr:
        raise ValueError(f"{where}.factory: {spec!r} names no module or no attribute")

    is_path = where_from.endswith(".py") or os.sep in where_from
    try:
        if is_path:
            name = "bp_sink_" + os.path.basename(where_from).removesuffix(".py")
            spec_obj = importlib.util.spec_from_file_location(name, where_from)
            if spec_obj is None or spec_obj.loader is None:
                raise ImportError(f"cannot load {where_from!r}")
            module = importlib.util.module_from_spec(spec_obj)
            before = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                spec_obj.loader.exec_module(module)
            finally:
                sys.dont_write_bytecode = before
        else:
            module = importlib.import_module(where_from)
    except Exception as e:                       # noqa: BLE001 - every import failure is one case
        raise ValueError(f"{where}.factory: {spec!r} could not be loaded: "
                         f"{type(e).__name__}: {e}") from None

    target = getattr(module, attr, None)
    if target is None:
        raise ValueError(f"{where}.factory: {spec!r} — {where_from!r} has no attribute {attr!r}")
    if not callable(target):
        raise ValueError(f"{where}.factory: {spec!r} is not callable, so it cannot build a sink")
    return target


def load_pipeline_from_dict(data: dict) -> EngineConfig:
    pl = data.get("pipeline", data) or {}
    board = data.get("board") or {}
    stages = []
    for s in pl.get("stages", []):
        of = s.get("on_fail")
        of_dict = of if isinstance(of, dict) else {}
        oj = s.get("on_reject")
        oj_dict = oj if isinstance(oj, dict) else {}
        mr = oj_dict.get("max_rounds")
        stages.append(
            Stage(
                id=s.get("uses") or s.get("id") or s.get("name") or "",
                run=s.get("run", ""),
                on_success=_on_success(s.get("on_success")),
                gate=s.get("gate"),
                retry=int(of_dict.get("retry", s.get("retry", 0)) or 0),
                on_fail=(of_dict.get("then") or (of if isinstance(of, str) else None) or "park"),
                rewind_to=of_dict.get("rewind_to") or of_dict.get("to"),
                reject_to=(oj_dict.get("to") if oj_dict else None),
                max_rounds=(int(mr) if isinstance(mr, int) else None),
                on_exhausted=(oj_dict.get("on_exhausted") or "park") if oj_dict else "park",
                criteria=s.get("criteria"),
                evidence=bool(s.get("evidence", False)),
            )
        )
    rework = pl.get("rework") or {}
    record = pl.get("record") or {}
    evidence = pl.get("evidence") or {}
    # Third sibling, read exactly like the two above: an absent key is `{}`, which
    # yields no targets, which is byte-for-byte today's engine for every project
    # that never heard of reporting.
    report = pl.get("report") or {}
    validate_chain(stages, rework_max_rounds=rework.get("max_rounds"))
    validate_transparency(stages, record, evidence, criteria_dir=board.get("criteria_dir"))
    report_targets = validate_report(report)
    return EngineConfig(
        stages=stages,
        trigger_status=(pl.get("trigger") or {}).get("on_status", "Todo"),
        pr_status=pl.get("pr_status", "In Review"),
        done_status=pl.get("done_status", "Done"),
        concurrency=int(pl.get("concurrency", 1)),
        token_ceiling=(pl.get("budget") or {}).get("max_tokens"),
        project=pl.get("project", data.get("project", "unknown")),
        bounce_field=rework.get("bounce_field", "Bounces"),
        max_rounds=rework.get("max_rounds"),
        working_status=pl.get("working_status"),
        park_status=pl.get("park_status"),
        require_issue=bool(pl.get("require_issue", False)),
        record=RecordConfig(
            enabled=bool(record.get("enabled", False)),
            events=tuple(record.get("events") or _DEFAULT_EVENTS),
            sticky_marker=record.get("sticky_marker", "board-pilot:run"),
            templates_dir=record.get("templates_dir"),
            max_body_chars=int(record.get("max_body_chars", 60000)),
            scan=record.get("scan", "redact"),
        ),
        evidence=EvidenceConfig(
            dir=evidence.get("dir"),
            require_deterministic=bool(evidence.get("require_deterministic", True)),
        ),
        report=report_targets,
    )


def load_pipeline_from_yaml(path) -> EngineConfig:
    import yaml  # lazy — only the real CLI needs PyYAML; tests build EngineConfig directly

    from pathlib import Path

    return load_pipeline_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
