"""The card layer: what the outward seam PUTS ON A SCREEN, and what it refuses to.

`test_tick_report.py` already measures the seam itself (N1-N5): one `Engine._emit`,
one source for the six values, a guard so a broken sink never decides whether work
advances. This file measures the SECOND rendering that hangs off the same seam — an
adaptive card, the shape a channel actually displays — and the two properties that
only exist once a card is in play:

  T1  no `card:` block  → no card is built and none is handed to a transport, and a
                          transport that never heard of cards still works;
  T2  one card per stage, carrying THAT stage's values;
  T3  a throwing card sink neither stops the run nor re-runs a stage;
  T4  the digest spool is empty at RUN START, not merely after a successful flush —
                          an aborted earlier run must not bleed its rows into the next;
  T5  every card of one run carries the same incident, an ascending step number, and
                          a denominator that comes from the pipeline rather than prose;
  T6  no secret reaches a card, a ledger line, or a dry-run dump.

Plus the two properties the arming gate rests on: nothing leaves the process without
an explicit flag, and the card is derived from `record.row_fields` rather than from a
private copy that merely agrees today.

Nothing here opens a socket. Every transport is a double.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from engine import record as record_mod
from engine.board import FakeBoardClient
from engine.card import DEFAULT_LABELS, build_card
from engine.config import CardConfig, EngineConfig, RecordConfig, load_pipeline_from_dict
from engine.interfaces import BoardItem, Stage, StageResult
from engine.report import DigestReporter, StreamReporter, WebhookTransport, build_reporters
from engine.runner import FakeStageRunner
from engine.tick import Engine

_FROZEN = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))

_CHAIN = ("spec", "implement", "verify", "review", "pr")

_LABELS = {
    "incident": "Case",
    "step": "Phase {n} out of {m}",
    "armed": "armed · zero out of {m}",
    "item": "Ticket",
    "stage": "Phase",
    "kind": "Type",
    "criteria": "Yardstick",
    "duration": "Took",
    "outcome": "Result",
    "button": "Open ticket",
    "journey_prev": "previously {prev}",
    "journey_now": "currently {now}",
    "journey_next": "up next {next}",
}


class CardTransport:
    """A wire that accepts a card beside the text row. `boom` makes it loudly broken."""

    def __init__(self, boom=False):
        self.sent = []          # list of (text, card|None)
        self.boom = boom

    def send(self, text, card=None):
        self.sent.append((text, card))
        if self.boom:
            raise RuntimeError("webhook failed (502): bad gateway")

    @property
    def cards(self):
        return [c for _, c in self.sent if c is not None]


class TextOnlyTransport:
    """A wire written before cards existed. It must keep working untouched."""

    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


class _MeasuredRunner:
    """Reports what a parent process can observe: duration and the criteria applied."""

    def __init__(self):
        self.ran_stage_ids = []

    def run(self, stage, item):
        self.ran_stage_ids.append(stage.id)
        return StageResult(ok=True, duration_s=42.0, criteria_ref=f"{stage.id}.md@abc1234")


def _before(chain, i):
    """The pipeline value that means "stage i is next".

    The engine builds `_stage_by_before` by walking `on_success`, so a stage's
    on_success is the NEXT stage's before-key — NOT the next stage's id. Production
    spells these as gerunds (`implementing`, `verifying`); the shape is what matters,
    so this harness uses a mechanical one. Getting this wrong does not fail loudly:
    every item simply resolves to no stage and is SKIPPED, and a card test then
    measures a reporter that was never called.
    """
    return "queued" if i == 0 else f"before-{chain[i]}"


def _stages(chain=_CHAIN):
    out = []
    for i, sid in enumerate(chain):
        gate = "human" if i == len(chain) - 1 else None
        nxt = _before(chain, i + 1) if i + 1 < len(chain) else "pr-open"
        out.append(Stage(id=sid, run="cmd:true", on_success=nxt, gate=gate))
    return out


def _card_cfg(**kw):
    kw.setdefault("incident", "INC-001")
    kw.setdefault("labels", dict(_LABELS))
    return CardConfig(**kw)


def _stream(transport, *, card=None, chain=_CHAIN, events=("armed", "stage", "reject", "park", "gate")):
    return StreamReporter(
        name="channel", transport=transport, events=events, project="demo-loop",
        chain=chain, card=card, now=lambda: _FROZEN,
    )


def _engine(tmp_path, items, *, stages=None, reporters=None, runner=None, **cfg):
    board = FakeBoardClient(items=items)
    runner = runner or FakeStageRunner(board=board)
    cfg.setdefault("record", RecordConfig(enabled=False))
    config = EngineConfig(stages=stages or _stages(), trigger_status="Todo", **cfg)
    engine = Engine(config, board, runner, state_dir=tmp_path, reporters=reporters)
    return engine, board, runner


def _run(engine, ticks=8):
    for _ in range(ticks):
        engine.tick()


def _content(card):
    return card["attachments"][0]["content"]


def _texts(node):
    """Every rendered string in a card, wherever it sits in the tree."""
    out = []
    if isinstance(node, dict):
        if node.get("type") == "TextBlock":
            out.append(str(node.get("text", "")))
        for key in ("body", "items", "columns", "actions", "facts", "attachments", "content"):
            out.extend(_texts(node.get(key)))
        if node.get("type") == "FactSet":
            for fact in node.get("facts", ()):
                out.append(f"{fact.get('title')} {fact.get('value')}")
        for key in ("title", "url"):
            if node.get(key):
                out.append(str(node[key]))
    elif isinstance(node, list):
        for child in node:
            out.extend(_texts(child))
    return out


def _facts(card):
    for block in _content(card)["body"]:
        if block.get("type") == "FactSet":
            return {f["title"]: f["value"] for f in block["facts"]}
    return {}


def _headline(card):
    """The subtle line under the incident band — where the step number lives."""
    for block in _content(card)["body"]:
        if block.get("type") == "Container":
            for inner in block.get("items", ()):
                if inner.get("isSubtle"):
                    return inner["text"]
    raise AssertionError("no headline container in the card")


# === T1: no card configured, nothing built, nothing said ===================


def test_t1_without_a_card_block_no_card_is_built(tmp_path):
    """A `report:` target with no `card:` behaves exactly as it did before: one text
    row per event, and the transport is never handed a card at all."""
    transport = CardTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="Scrap", status="Doing", pipeline=_before(_CHAIN, 1), issue_number=7)],
        reporters=[_stream(transport, card=None)],
    )

    engine.tick()

    assert transport.sent, "the reporter never fired"
    assert transport.cards == []
    assert all(card is None for _, card in transport.sent)


def test_t1_a_transport_that_never_heard_of_cards_still_works(tmp_path):
    """The card is an ADDITION to the seam, not a new contract every wire must
    implement. Without a `card:` block the reporter calls `send(text)` — one
    argument — so a transport written before this module keeps working."""
    transport = TextOnlyTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="Scrap", status="Doing", pipeline=_before(_CHAIN, 1), issue_number=7)],
        reporters=[_stream(transport, card=None)],
    )

    engine.tick()

    assert len(transport.sent) == 1
    assert "| implement |" in transport.sent[0]


def test_t1_no_report_block_at_all_builds_nothing_and_warns_about_nothing(tmp_path, capsys):
    cfg = load_pipeline_from_dict(
        {"pipeline": {"project": "demo-loop", "stages": [
            {"name": "spec", "run": "cmd:true", "on_success": "implementing"},
            {"name": "pr", "run": "cmd:true", "on_success": "pr-open", "gate": "human"},
        ]}}
    )
    board = FakeBoardClient(items=[BoardItem(id="A", title="x", status="Doing", pipeline="queued")])
    engine = Engine(cfg, board, FakeStageRunner(board=board), state_dir=tmp_path)

    engine.tick()

    assert engine.reporters == []
    assert capsys.readouterr().err == ""


# === T2: one card per stage, with that stage's values ======================


def test_t2_exactly_one_card_per_stage_with_that_stages_values(tmp_path):
    transport = CardTransport()
    runner = _MeasuredRunner()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="Scrap on the line", status="Todo",
                   issue_number=7, url="https://example.invalid/issues/7")],
        runner=runner,
        reporters=[_stream(transport, card=_card_cfg(), events=("stage", "gate"))],
    )

    _run(engine)

    # One card per stage that actually ran, and no second card for any of them.
    # `gate` is in the filter because the LAST stage never emits `stage`: it reaches
    # its human gate and reports THAT. Watching only `stage` loses the one event
    # carrying the pull-request link, which is the whole point of the last card.
    stages_seen = [_facts(c)[_LABELS["stage"]] for c in transport.cards]
    assert stages_seen == runner.ran_stage_ids
    assert len(stages_seen) == len(set(stages_seen))

    first = transport.cards[0]
    facts = _facts(first)
    assert facts[_LABELS["stage"]] == "spec"
    assert facts[_LABELS["kind"]] == "machine"
    assert facts[_LABELS["criteria"]] == "spec.md@abc1234"
    assert facts[_LABELS["duration"]] == "42s"
    assert "implement" in facts[_LABELS["outcome"]]          # what happens next
    assert "#7" in " ".join(_texts(first))                    # which item


def test_t2_the_button_points_at_the_item_on_every_card(tmp_path):
    """One incident, one destination. When Teams cannot hold the thread, the shared
    target is what makes five posts read as one story."""
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="Scrap", status="Todo", issue_number=7,
                   url="https://example.invalid/issues/7")],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg())],
    )

    _run(engine)

    urls = {a["url"] for c in transport.cards for a in _content(c).get("actions", ())}
    assert urls == {"https://example.invalid/issues/7"}
    assert all(a["type"] == "Action.OpenUrl" for c in transport.cards
               for a in _content(c).get("actions", ()))


def test_t2_a_card_without_a_url_carries_no_button(tmp_path):
    """A button that opens nothing gets tapped on stage and does nothing, which is
    worse than no button."""
    card = build_card("stage", incident="INC-001", title="x", chain=_CHAIN, current="spec",
                      fields=dict(when="w", stage="spec", kind="machine", criteria="—",
                                  took="1s", outcome="pass → implementing"),
                      labels=_LABELS, url="")
    assert "actions" not in _content(card)


def test_t2_the_card_is_version_1_4_and_full_width(tmp_path):
    """1.5 affordances are deliberately absent: a 1.5 card can fail to render at all
    on some clients, and 1.4 is the only shape proven on this channel."""
    card = build_card("stage", incident="INC-001", title="x", chain=_CHAIN, current="spec",
                      fields=dict(when="w", stage="spec", kind="machine", criteria="—",
                                  took="1s", outcome="pass"),
                      labels=_LABELS, url="")
    content = _content(card)
    assert content["version"] == "1.4"
    assert content["msteams"] == {"width": "Full"}
    blob = json.dumps(card)
    assert "showBorder" not in blob and "roundedCorners" not in blob


# === T3: a broken card sink never decides whether work advances =============


def test_t3_a_throwing_card_sink_neither_stops_the_run_nor_repeats_a_stage(tmp_path):
    transport = CardTransport(boom=True)
    runner = _MeasuredRunner()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=7)],
        runner=runner,
        reporters=[_stream(transport, card=_card_cfg())],
    )

    _run(engine)

    assert transport.cards, "the sink never saw a card"
    assert runner.ran_stage_ids == list(_CHAIN)              # every stage exactly once
    assert board._items["A"].pipeline == "pr-open"           # the run reached its gate


def test_t3_the_failure_names_the_sink_in_the_ledger_and_never_on_the_board(tmp_path):
    transport = CardTransport(boom=True)
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline=_before(_CHAIN, 1), issue_number=7)],
        reporters=[_stream(transport, card=_card_cfg())],
    )

    res = engine.tick()

    assert "channel" in res.notes and "502" in res.notes
    assert board.list_comments("A") == []


# === T7: the band's incident may come from the ENVIRONMENT =================


def test_t7_incident_env_names_a_variable_and_the_environment_holds_the_value(monkeypatch, tmp_path):
    """One run, one incident, and the incident id is minted OUTSIDE this engine.

    The alarm that starts a run invents `INC-001`; the engine learns it from the
    environment it was spawned in. Writing it into the project YAML would freeze the
    FIRST incident into every later run's cards, silently, because a stale band is
    still a perfectly rendered band. Same pattern as `url_env`: config names the
    variable, the environment holds the value.
    """
    monkeypatch.setenv("DEMO_INCIDENT", "INC-042")
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=7)],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg(incident="", incident_env="DEMO_INCIDENT"))],
    )

    _run(engine)

    assert transport.cards
    for card in transport.cards:
        assert "Case INC-042" in " ".join(_texts(card))


def test_t7_a_literal_incident_wins_over_the_variable(tmp_path, monkeypatch):
    """Explicit beats derived, so a project that has no minting step can still say
    what its runs are called."""
    monkeypatch.setenv("DEMO_INCIDENT", "INC-042")
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=7)],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg(incident="FIX", incident_env="DEMO_INCIDENT"))],
    )

    _run(engine)

    assert all("Case FIX" in " ".join(_texts(c)) for c in transport.cards)


def test_t7_an_unset_variable_falls_back_to_the_item_and_never_prints_the_name(tmp_path, monkeypatch):
    """The card must not degrade into `Case DEMO_INCIDENT` or `Case None`. An
    absent value means the run has no incident id, and the item reference is the
    honest constant to hold the story together instead."""
    monkeypatch.delenv("DEMO_INCIDENT", raising=False)
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=7)],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg(incident="", incident_env="DEMO_INCIDENT"))],
    )

    _run(engine)

    assert transport.cards
    for card in transport.cards:
        blob = " ".join(_texts(card))
        assert "DEMO_INCIDENT" not in blob and "None" not in blob
        assert "Case #7" in blob


# === T4: the digest is empty at RUN START ==================================


def test_t4_an_aborted_earlier_run_does_not_bleed_into_the_next(tmp_path):
    """The spool is cleared on flush — but a run that never REACHES its flush event
    leaves one behind. A tick is a process, so the leftover survives on disk and the
    next run's digest would open with a stranger's rows.

    ARM is the run start, and clearing there is the only point that covers the run
    which never ended.
    """
    transport = CardTransport()
    reporter = DigestReporter(
        name="summary", transport=transport, events=("armed", "stage", "gate"),
        flush_on=("gate",), state_dir=tmp_path, project="demo-loop", chain=_CHAIN,
        now=lambda: _FROZEN,
    )
    stale_item = BoardItem(id="A", title="x", status="Doing", pipeline=_before(_CHAIN, 1))
    reporter.emit("stage", stale_item, stage=_stages()[1], result=StageResult(ok=True),
                  to="verifying", outcome="pass")
    assert reporter.spool_path(stale_item).exists()          # the aborted run's leftovers
    assert transport.sent == []                              # it never flushed

    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=7)],
        runner=_MeasuredRunner(),
        reporters=[reporter],
        pr_status="In Review",
    )
    _run(engine)

    assert len(transport.sent) == 1, "the digest did not send exactly once"
    body = transport.sent[0][0]
    assert "armed" in body
    assert body.count("| verifying |") == 0                  # the stale row is gone
    assert len([ln for ln in body.splitlines() if ln.startswith("|")]) == len(_CHAIN) + 1


def test_t4_the_spool_reset_is_per_item_not_per_board(tmp_path):
    """Arming item B must not throw away the run item A has in flight."""
    transport = CardTransport()
    reporter = DigestReporter(
        name="summary", transport=transport, events=("armed", "stage", "gate"),
        flush_on=("gate",), state_dir=tmp_path, project="demo-loop", chain=_CHAIN,
    )
    a = BoardItem(id="A", title="a", status="Doing", pipeline=_before(_CHAIN, 1))
    b = BoardItem(id="B", title="b", status="Todo")
    reporter.emit("stage", a, stage=_stages()[1], result=StageResult(ok=True),
                  to="verifying", outcome="pass")
    reporter.emit("armed", b, result=StageResult(ok=True), to="queued")

    assert reporter.spool_path(a).read_text(encoding="utf-8").strip() != ""


# === T5: one incident, ascending steps, a denominator from the pipeline ====


def test_t5_all_cards_share_the_incident_and_climb_the_chain(tmp_path):
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="Scrap", status="Todo", issue_number=7)],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg())],
    )

    _run(engine)

    heads = [_headline(c) for c in transport.cards]
    assert len(heads) >= len(_CHAIN)
    assert all("Case INC-001" in " ".join(_texts(c)) for c in transport.cards)

    numbered = [h for h in heads if "Phase" in h]
    steps = [int(h.split("Phase ")[1].split(" out of ")[0]) for h in numbered]
    assert steps == sorted(steps), heads
    assert steps[0] == 1 and steps[-1] == len(_CHAIN)


def test_t5_the_denominator_is_the_pipeline_not_a_number_somebody_typed(tmp_path):
    """The count has ONE source: the stage chain the engine actually runs. Add a
    stage and every card says so, without anybody editing a label."""
    six = _CHAIN + ("smoke",)
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=7)],
        stages=_stages(six),
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg(), chain=six)],
    )

    _run(engine, ticks=10)

    assert transport.cards
    assert all(f"out of {len(six)}" in _headline(c) for c in transport.cards)
    assert f"out of {len(_CHAIN)}" not in " ".join(_headline(c) for c in transport.cards)


def test_t5_a_step_label_carrying_a_literal_count_is_refused_at_load():
    """The failure this guards against is on record: three declarations of the same
    count in two files, one of them prose, and nothing compared them. A label with a
    number IN it is that third declaration, so it never loads."""
    from engine.config import validate_report

    with pytest.raises(ValueError, match="step"):
        validate_report({"targets": [{
            "name": "channel", "type": "file", "path": "/tmp/x.log",
            "card": {"labels": {"step": "Step {n} of 6"}},
        }]})

    with pytest.raises(ValueError, match="step"):
        validate_report({"targets": [{
            "name": "channel", "type": "file", "path": "/tmp/x.log",
            "card": {"labels": {"step": "Step {n}"}},
        }]})


def test_t5_the_progress_bar_has_one_column_per_stage(tmp_path):
    """The same count, seen instead of read. From the third row of a room nobody
    reads 'Phase 3 out of 5', but a bar with three of five columns filled is legible."""
    card = build_card("stage", incident="INC-001", title="x", chain=_CHAIN, current="verify",
                      fields=dict(when="w", stage="verify", kind="machine", criteria="—",
                                  took="1s", outcome="pass → reviewing"),
                      labels=_LABELS, url="")
    bars = [b for b in _content(card)["body"] if b.get("type") == "ColumnSet"]
    assert len(bars) == 1
    columns = bars[0]["columns"]
    assert len(columns) == len(_CHAIN)
    assert [c["style"] for c in columns] == ["good", "good", "accent", "emphasis", "emphasis"]


# === T6: no secret in a card, a row, or a dump =============================


def test_t6_a_secret_in_a_stage_value_never_reaches_the_card(tmp_path):
    leaked = "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    class LeakyRunner:
        def run(self, stage, item):
            return StageResult(ok=True, duration_s=1.0, criteria_ref=f"spec.md@{leaked}")

    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="queued", issue_number=7)],
        runner=LeakyRunner(),
        reporters=[_stream(transport, card=_card_cfg(), events=("stage",))],
    )

    engine.tick()

    assert transport.cards, "the sink never saw a card"
    blob = json.dumps(transport.cards, ensure_ascii=False)
    assert leaked not in blob
    assert "[redacted:secret]" in blob
    assert leaked not in " ".join(t for t, _ in transport.sent)


def test_t6_the_card_title_is_scrubbed_and_flattened_like_every_other_value(tmp_path):
    """The item title is board text, typed by anyone with write access. It reaches
    the card headline through clean_cell: redacted, one line."""
    leaked = "ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title=f"fix login\nwith {leaked}", status="Doing",
                   pipeline="queued", issue_number=7)],
        reporters=[_stream(transport, card=_card_cfg(), events=("stage",))],
    )

    engine.tick()

    assert transport.cards, "the sink never saw a card"
    head = _headline(transport.cards[0])
    assert leaked not in json.dumps(transport.cards, ensure_ascii=False)
    assert "\n" not in head and "fix login with [redacted:secret]" in head, head


def test_t6_the_address_never_reaches_the_card_the_row_or_the_dump(tmp_path, monkeypatch, capsys):
    """The card is built from board values; the address is held by the environment.
    A dry-run dump prints the PAYLOAD, so it must print no address either."""
    url = "https://example.invalid/workflows/abc?sig=SUPERSECRETSIGNATURE"
    monkeypatch.setenv("BP_TEST_HOOK", url)
    wire = WebhookTransport("BP_TEST_HOOK")                  # armed=False is the default

    wire.send("| row |", card={"type": "message", "attachments": []})

    out = capsys.readouterr()
    assert url not in out.out and url not in out.err
    assert "SUPERSECRETSIGNATURE" not in out.out + out.err
    assert "BP_TEST_HOOK" in out.err                          # the NAME is fine to print


def test_t6_an_unreachable_wire_reports_without_quoting_the_address(monkeypatch):
    url = "https://example.invalid/workflows/abc?sig=SUPERSECRETSIGNATURE"
    monkeypatch.setenv("BP_TEST_HOOK", url)
    wire = WebhookTransport("BP_TEST_HOOK", armed=True)

    def explode(req, timeout=None):
        from urllib.error import URLError
        raise URLError(f"connection refused for {url}")

    monkeypatch.setattr("urllib.request.urlopen", explode)

    with pytest.raises(RuntimeError) as e:
        wire.send("| row |", card={"type": "message"})
    assert "SUPERSECRETSIGNATURE" not in str(e.value)


# === the arming gate: nothing goes out without the flag ====================


def test_dry_run_is_the_default_and_opens_no_socket(monkeypatch, capsys):
    monkeypatch.setenv("BP_TEST_HOOK", "https://example.invalid/hook")

    def explode(*a, **kw):
        raise AssertionError("a dry run opened a socket")

    monkeypatch.setattr("urllib.request.urlopen", explode)

    WebhookTransport("BP_TEST_HOOK").send("| row |", card={"type": "message", "x": 1})

    err = capsys.readouterr().err
    assert "dry-run" in err
    assert '"x": 1' in err or '"x":1' in err                  # the payload IS shown


def test_the_flag_is_what_arms_the_wire(monkeypatch):
    sent = {}
    monkeypatch.setenv("BP_TEST_HOOK", "https://example.invalid/hook")

    class Resp:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        sent["url"] = req.full_url
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    WebhookTransport("BP_TEST_HOOK", armed=True).send("| row |", card={"type": "message", "x": 1})

    assert sent["body"] == {"type": "message", "x": 1}         # the CARD, not {"text": …}
    assert sent["url"] == "https://example.invalid/hook"


def test_build_reporters_is_disarmed_unless_told_otherwise(tmp_path):
    from engine.config import ReportTarget

    targets = (ReportTarget(name="channel", type="webhook", url_env="BP_TEST_HOOK"),)
    assert build_reporters(targets, state_dir=tmp_path)[0].transport.armed is False
    assert build_reporters(targets, state_dir=tmp_path, armed=True)[0].transport.armed is True


# === one source, two renderings — measured at the SOURCE ===================


def test_the_card_is_derived_from_the_same_function_the_sticky_renders_from(tmp_path, monkeypatch):
    """`test_n5` measures that the two renderings AGREE. A faithful private copy of
    the derivation agrees too, on the day it is written.

    This measures the derivation itself: `record.outcome_text` is monkeypatched, and
    BOTH the sticky comment and the card must move. A reporter with its own formatter
    keeps printing the real text and fails here.
    """
    monkeypatch.setattr(record_mod, "outcome_text",
                        lambda *a, **kw: "MOVED-BY-THE-ONE-SOURCE")

    transport = CardTransport()
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="queued", issue_number=7)],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, card=_card_cfg(), events=("stage",))],
        record=RecordConfig(enabled=True, events=("stage",)),
    )
    engine.recorder._now = lambda: _FROZEN

    engine.tick()

    assert transport.cards, "the sink never saw a card"
    assert "MOVED-BY-THE-ONE-SOURCE" in board.list_comments("A")[0]["body"]
    assert "MOVED-BY-THE-ONE-SOURCE" in " ".join(_texts(transport.cards[0]))
    assert "MOVED-BY-THE-ONE-SOURCE" in transport.sent[0][0]


def test_the_label_set_is_one_list_not_two():
    """A label the config may set but the card never reads is a knob that does
    nothing; a label the card reads but the config refuses is a card that cannot be
    translated. Both are the same drift, so both sides read one tuple."""
    from engine.config import LABEL_KEYS

    assert set(LABEL_KEYS) == set(DEFAULT_LABELS)
    assert set(_LABELS) == set(DEFAULT_LABELS)


# === end to end through the config, the way the live run is wired ==========


def test_a_configured_card_target_renders_through_the_engines_own_build(tmp_path):
    log = tmp_path / "channel.log"
    cfg = load_pipeline_from_dict(
        {"pipeline": {
            "project": "demo-loop",
            "stages": [
                {"name": "spec", "run": "cmd:true", "on_success": "implementing"},
                {"name": "implement", "run": "cmd:true", "on_success": "verifying"},
                {"name": "pr", "run": "cmd:gh pr create", "on_success": "pr-open", "gate": "human"},
            ],
            "report": {"targets": [{
                "name": "channel", "type": "file", "path": str(log),
                "card": {"incident": "INC-001", "labels": _LABELS},
            }]},
        }}
    )
    # This one config spells its own before-keys as gerunds, the way production does,
    # so the item names THAT key rather than the harness's mechanical one.
    board = FakeBoardClient(items=[BoardItem(id="A", title="Scrap", status="Doing",
                                             pipeline="implementing", issue_number=7)])
    engine = Engine(cfg, board, FakeStageRunner(board=board), state_dir=tmp_path)

    assert [r.name for r in engine.reporters] == ["channel"]
    assert engine.reporters[0].chain == ("spec", "implement", "pr")

    engine.tick()

    text = log.read_text(encoding="utf-8")
    assert "| implement |" in text                            # the row is still there
    card = json.loads([ln for ln in text.splitlines() if ln.startswith("{")][0])
    assert "Case INC-001" in " ".join(_texts(card))
    assert "Phase 2 out of 3" in _headline(card)
