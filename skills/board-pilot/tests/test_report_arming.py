"""The arming gate for outward sinks: the one switch that turns a rehearsal real.

`report.py` has always documented this gate ("only the CLI's explicit
--report-send builds armed sinks"), and `build_reporters` has always taken the
flag. Nothing ever passed it. So a declared webhook target loaded, filtered
events, rendered a card, printed the payload to stderr — and posted nothing, on
every path, with a dry-run line that reads like a successful send if you are not
looking for the word.

That is the worst shape a switch can have: fully built, fully green, permanently
off, and the only evidence is a log line saying it did nothing.

These tests measure the flag END TO END, in the two places it can be lost:

  R1  Engine  — the default is DISARMED, and `report_send=True` arms the webhook
                sinks it builds (and nothing else about them changes);
  R2  CLI     — `--report-send` reaches the Engine, and its ABSENCE reaches it too;
  R3  scope   — arming is per RUN, not per target: a file sink and an external sink
                are untouched by it, because neither has anything to arm.

R2 is the half that was missing. A test that only proved R1 would have been green
for the whole time the feature did not work.
"""
from pathlib import Path

import pytest

from engine import cli
from engine.board import FakeBoardClient
from engine.config import load_pipeline_from_dict
from engine.interfaces import BoardItem
from engine.report import FileTransport, WebhookTransport
from engine.runner import FakeStageRunner
from engine.tick import Engine

yaml = pytest.importorskip("yaml")


_PIPELINE = {
    "project": "demo",
    "trigger": {"on_status": "Todo"},
    "stages": [
        {"name": "verify", "run": "cmd:true", "on_success": "pr-ready"},
        {"name": "pr", "run": "cmd:true", "on_success": "pr-open", "gate": "human"},
    ],
    "report": {"targets": [
        {"name": "channel", "type": "webhook", "url_env": "DEMO_HOOK",
         "events": ["stage", "gate"]},
    ]},
}


def _engine(tmp_path, **kw):
    cfg = load_pipeline_from_dict({"pipeline": _PIPELINE})
    board = FakeBoardClient(items=[BoardItem(id="A", title="x", status="Todo")])
    return Engine(cfg, board, FakeStageRunner(board=board), state_dir=tmp_path, **kw)


def _transports(engine):
    return [r.transport for r in engine.reporters]


# === R1: the Engine's own default, and the one word that changes it ==========


def test_r1_an_engine_built_without_the_flag_rehearses(tmp_path):
    """The default is the gate. Every path that is not an explicit ask rehearses,
    including every test in this suite and every library caller."""
    engine = _engine(tmp_path)

    assert [type(t) for t in _transports(engine)] == [WebhookTransport]
    assert all(t.armed is False for t in _transports(engine))


def test_r1_report_send_arms_the_webhook_sinks(tmp_path):
    engine = _engine(tmp_path, report_send=True)

    assert all(t.armed is True for t in _transports(engine))


def test_r1_arming_changes_nothing_else_about_the_target(tmp_path):
    """The flag decides whether bytes leave. It must not quietly widen the event
    filter, rename the sink or resolve an address at construction — the last of
    which would fail engine start on a box where the variable is merely not
    exported yet."""
    off, on = _engine(tmp_path / "a"), _engine(tmp_path / "b", report_send=True)

    assert [r.name for r in off.reporters] == [r.name for r in on.reporters]
    assert [r.events for r in off.reporters] == [r.events for r in on.reporters]
    assert [t.url_env for t in _transports(on)] == ["DEMO_HOOK"]


# === R2: the flag survives the CLI, in both directions =======================


class _EngineSpy:
    """Captures how cli constructed the Engine, then stops the run."""

    last: "dict | None" = None

    def __init__(self, config, board, runner, state_dir, *args, **kwargs):
        type(self).last = dict(kwargs)

    def tick(self, *a, **kw):
        from engine.tick import TickResult

        return TickResult()


class _BoardStub:
    def __init__(self, *a, **kw):
        pass


class _RunnerStub:
    def __init__(self, *a, **kw):
        pass


def _drive(tmp_path: Path, monkeypatch, extra_argv) -> dict:
    project = tmp_path / "project.yaml"
    project.write_text(
        yaml.safe_dump({"board": {"owner": "acme", "project_number": 1, "repo": "acme/w"},
                        "pipeline": _PIPELINE}),
        encoding="utf-8",
    )
    monkeypatch.setattr("engine.claude_runner.ClaudeStageRunner", _RunnerStub)
    monkeypatch.setattr("engine.gh_board.GhBoardClient", _BoardStub)
    monkeypatch.setattr("engine.tick.Engine", _EngineSpy)
    _EngineSpy.last = None

    rc = cli.run(["--project", str(project), "--state-dir", str(tmp_path / "state"),
                  "--once", *extra_argv])

    assert rc == 0
    assert _EngineSpy.last is not None, "cli never constructed the Engine"
    return _EngineSpy.last


def test_r2_the_cli_flag_reaches_the_engine(tmp_path, monkeypatch):
    assert _drive(tmp_path, monkeypatch, ["--report-send"]).get("report_send") is True


def test_r2_without_the_flag_the_cli_says_so_explicitly(tmp_path, monkeypatch):
    """Not merely "absent". The CLI passes False, so the disarmed state is a
    DECISION that travelled, not a default that happened to agree at the far end."""
    assert _drive(tmp_path, monkeypatch, []).get("report_send") is False


# === R3: arming is about sending, so it touches only what sends ==============


def test_r3_a_file_sink_is_not_a_thing_that_can_be_armed(tmp_path):
    """A file target writes locally either way — there is no address, no secret and
    nothing to hold back. Arming must not become a second enable switch."""
    cfg = load_pipeline_from_dict({"pipeline": {
        **_PIPELINE,
        "report": {"targets": [{"name": "probe", "type": "file",
                                "path": str(tmp_path / "probe.log"), "events": ["stage"]}]},
    }})
    board = FakeBoardClient(items=[BoardItem(id="A", title="x", status="Todo")])
    engine = Engine(cfg, board, FakeStageRunner(board=board), state_dir=tmp_path,
                    report_send=False)

    assert [type(t) for t in _transports(engine)] == [FileTransport]
    engine.reporters[0].transport.send("a row")
    assert (tmp_path / "probe.log").read_text(encoding="utf-8").strip() == "a row"
