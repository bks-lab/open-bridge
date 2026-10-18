# SPDX-License-Identifier: MIT
"""Contract between the cockpit and the scripts it runs (scripts/lib/bridge_cockpit/ against
briefing.py, inbox.py, task.py and workplace.py).

The other cockpit tests answer from fixed lambdas and compare the recorded argv with an argv they
rebuild themselves, so a flag renamed in a script keeps every one of them green. This module
closes that gap from both sides:

- every argv shape the cockpit emits goes through the real parser of its script: the cockpit is
  driven through its verbs, passes and endpoints, and each recorded argv is parsed by the script's
  own `main` with `parse_args` stopped right after parsing, so nothing runs. A source scan names
  every verb the cockpit code can emit, and each one must be emitted by some scenario here;
- the real `briefing.py collect` and `workplace.py caps` run against a temporary Bridge, and the
  fields the cockpit reads (and the fixtures of test_bridge_cockpit.py assume) are asserted on
  their output.

Hermetic: no network, no terminal driver (a stub command driver answers caps and tabs).

Run: python3 -m pytest scripts/tests/test_bridge_cockpit_contract.py -q
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import importlib.util
import io
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
for path in (ROOT / "scripts", HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_bridge_cockpit as tbc  # noqa: E402
from test_bridge_cockpit import (  # noqa: E402,F401  (the autouse fixture comes along)
    CHECK_KEY, ONLY_ID, TOMORROW, YES_ID, World, collect_fixture, ok, private_key_dir)
from lib.bridge_cockpit.runner import Runner  # noqa: E402
from lib.bridge_cockpit.server import make_server  # noqa: E402

COCKPIT = ROOT / "scripts" / "lib" / "bridge_cockpit"
TARGETS = ("briefing.py", "inbox.py", "task.py", "workplace.py")


# ---------------------------------------------------------------- the real parsers

class ContractError(AssertionError):
    """A script refuses an argv the cockpit emits."""


class _Parsed(Exception):
    def __init__(self, ns: argparse.Namespace):
        super().__init__()
        self.ns = ns


def load_script(name: str, source: str | None = None):
    """A module of scripts/<name>; with `source`, built from that text instead (a patched script)."""
    path = ROOT / "scripts" / name
    mod_name = f"_contract_{path.stem}" + ("_patched" if source is not None else "")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod                      # dataclasses look their module up while it loads
    held = sys.modules.get("briefing")               # briefing.py registers itself under that name too
    try:
        if source is None:
            spec.loader.exec_module(mod)
        else:
            exec(compile(source, str(path), "exec"), mod.__dict__)  # noqa: S102 (the repo's own script)
    finally:
        if held is None:
            if sys.modules.get("briefing") is mod:
                del sys.modules["briefing"]
        else:
            sys.modules["briefing"] = held
    return mod


@functools.lru_cache(maxsize=None)
def real_script(name: str):
    return load_script(name)


def parse(argv: list[str], script=None) -> argparse.Namespace:
    """What the script's own parser makes of a cockpit argv. Its `main` runs up to `parse_args` and
    stops there, so an unknown flag, a missing one or a value outside its choices fails as it would
    on a machine (exit 2), and nothing is executed."""
    name = Path(argv[1]).name
    mod = script or real_script(name)
    real_parse = argparse.ArgumentParser.parse_args

    def stop(self, args=None, namespace=None):
        raise _Parsed(real_parse(self, args, namespace))
    err = io.StringIO()
    with mock.patch.object(argparse.ArgumentParser, "parse_args", stop), contextlib.redirect_stderr(err):
        try:
            mod.main(argv[2:])
        except _Parsed as done:
            return done.ns
        except SystemExit:
            why = err.getvalue().strip().splitlines()[-1:] or ["exit 2"]
            raise ContractError(f"{name} refuses {argv[2:]}: {why[0]}") from None
    raise ContractError(f"{name} main() returned before parsing {argv[2:]}")


def is_target(argv: list[str]) -> bool:
    return len(argv) > 1 and argv[0] == sys.executable and Path(argv[1]).name in TARGETS


# ---------------------------------------------------------------- what the cockpit code can emit

# the argv builders of the cockpit, called with a literal verb
HELPER_RES = {"inbox": re.compile(r"\binbox\(\s*\"([a-z-]+)\""),
              "task": re.compile(r"\btask_cmd\(\s*\"([a-z-]+)\""),
              "workplace": re.compile(r"\bworkplace\(\s*\"([a-z-]+)\"")}
# an argv of one of the four scripts written out in place: [python, script(...), "--root", str(root), (*by,) "<verb>"]
RAW_RE = re.compile(r"script\((?:\"scripts/(?:briefing|inbox|task|workplace)\.py\"|script)\),\s*"
                    r"\"--root\",\s*str\([\w.]+\),\s*(?:\*\w+,\s*)?\"([a-z][a-z-]*)\"")


def verbs_in_source() -> tuple[set[str], set[str]]:
    """(script.verb for every builder call, verb for every argv written out) in the cockpit code."""
    keyed, raw = set(), set()
    for path in sorted(COCKPIT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for script, rx in HELPER_RES.items():
            keyed |= {f"{script}.{v}" for v in rx.findall(text)}
        raw |= set(RAW_RE.findall(text))
    return keyed, raw


# ---------------------------------------------------------------- scenarios: the cockpit, driven

def wait_review(w: World) -> None:
    deadline = time.monotonic() + 5
    while w.app.review.running and time.monotonic() < deadline:
        time.sleep(0.01)


def s_passes(w: World) -> None:
    """The three pass kinds, the second ask for the triage view, the sweep after a full pass."""
    swept = "20261015-1300-checks-gone-row-e5f6"
    w.runner.handlers["inbox.list"] = lambda argv: ok([
        {"id": swept, "state": "open", "from": "bridge-cockpit", "key": "briefing:morning:checks:gone-row"}])
    w.app.inbox_cache = (0.0, None)
    for kind in ("full", "quick", "delta"):
        w.app.collector.request(kind)
        w.app.collector.drain()
    asked = []

    def first_without_view(argv):
        asked.append(argv)
        data = collect_fixture(w.root)
        if len(asked) == 1:
            data.pop("view")
        return ok(data)
    w.runner.handlers["briefing.collect"] = first_without_view
    w.app.collector.ask_triage = False
    w.app.collector.request("quick")
    w.app.collector.drain()
    assert any("--style" in a for a in asked)


def s_caps(w: World) -> None:
    w.app.driver_caps(fresh=True)


def s_start(w: World) -> None:
    w.act("do_it", keys=[f"inbox:{YES_ID}", "task:other-task"], target="tab")
    w.act("start_agent", keys=[f"inbox:{tbc.YES2_ID}"])
    w.act("advise", keys=["task:demo-task"])
    w.act("collect_context", key="task:filed-task")


def s_launch_model(w: World) -> None:
    w.act("start_agent", keys=["task:other-task"], model="haiku", effort="xhigh")


def s_team(w: World) -> None:
    w.act("team_role", key="task:other-task", team="build")


def s_resume(w: World) -> None:
    w.app.store.link_session(tbc.SID2, "demo-task", "earlier work", "/tmp/elsewhere", "hand")
    w.act("session_resume", session=tbc.SID2)


def s_filed(w: World) -> None:
    """A row with nothing to start on is filed first: a page row and a problem from the chat."""
    w.runner.handlers["inbox.add"] = lambda argv: ok("20261017-1200-filed-row-a1b2\n")
    w.act("do_it", keys=[CHECK_KEY])
    w.act("chat_tab", text="Fix the printer queue\nIt hangs since the update.")


def s_waits(w: World) -> None:
    w.act("later", key=f"inbox:{YES_ID}", until=TOMORROW)
    w.act("runs_on", keys=[f"inbox:{tbc.YES2_ID}"], until=TOMORROW, on="an answer from the vendor")
    w.act("runs_on", keys=["task:demo-task"], until=TOMORROW, on="the vendor")
    w.act("task_running", slug="demo-task")


def s_to_task(w: World) -> None:
    w.runner.handlers["task.new"] = lambda argv: ok(json.dumps({"slug": "tidy-labels", "status": "backlog"}))
    w.act("to_task", key=f"inbox:{YES_ID}")


def s_inbox_edits(w: World) -> None:
    w.act("urgency", key=f"inbox:{YES_ID}", value="now")
    w.act("note", key=f"inbox:{YES_ID}", text="--yes; a note that looks like a flag")
    w.act("drop", key=f"inbox:{YES_ID}", reason="family")
    w.act("inbox_unmute", id="20261017-1800-mini-daily-health-ab12")
    w.act("done", key=f"inbox:{ONLY_ID}")


def s_task_edits(w: World) -> None:
    w.act("priority", key="task:other-task", value="P0")
    w.act("note", key="task:other-task", text="ask the vendor")
    w.act("task_close", keys=["task:demo-task"], reason="superseded", text="moved into #12")
    w.act("task_close", keys=["task:other-task"], reason="done")


def s_settle(w: World) -> None:
    w.act("settle", keys=[f"inbox:{YES_ID}"], outcome="done")
    w.act("settle", keys=[f"inbox:{ONLY_ID}"], outcome="not_doing")
    w.act("settle", keys=["task:other-task"], outcome="done")


def s_reopen(w: World) -> None:
    w.act("settle", keys=["task:other-task"], outcome="done")
    w.act("settle", keys=[f"inbox:{YES_ID}"], outcome="done")
    w.act("task_reopen", slug="other-task", **{"as": "backlog", "note": "still to do"})
    w.act("inbox_reopen", id=YES_ID, note="not done after all")


def s_review(w: World) -> None:
    w.runner.handlers["task.review"] = lambda argv: ok({"reviewed": 1, "to_close": 0})
    w.act("task_review")
    wait_review(w)
    w.act("task_review", keys=["task:demo-task"], escalate=True)
    wait_review(w)
    w.act("task_review", keys=["task:demo-task"], fresh=True)
    wait_review(w)
    tbc.write_review(w.root, [tbc.verdict("demo-task", "close")])
    w.app.collector.rebuild()
    w.act("task_keep", keys=["task:demo-task"])


def s_tabs(w: World) -> None:
    w.act("tab_yes", tab_ref="surface:7")
    w.act("tab_no", tab_ref="surface:7")
    w.act("tab_jump", tab_ref="surface:7")
    w.act("tab_send", tab_ref="surface:7", text="--please continue")
    w.act("tab_go_on", tab_ref="surface:13")
    w.act("adopt", key="task:other-task", tab_ref="surface:11")
    w.act("tab_close", tab_ref="surface:8")
    w.act("start_control")


def s_rows(w: World) -> None:
    w.runner.handlers["briefing.act"] = lambda argv: ok(json.dumps(
        {"ok": True, "did": "turned down", "undo": "restore:sent.2026-09-25._"}))
    res = w.act("row_action", page="tasks", section="apps", index=0, action="turned_down")
    w.runner.handlers["briefing.act"] = lambda argv: ok(json.dumps({"ok": True, "did": "undone"}))
    w.act("row_undo", **res["undo"][0]["undo"]["args"])


def s_reads(w: World) -> None:
    """What the pages read: the inbox listing and its noise, a tab's screen, a GitHub row's detail."""
    w.runner.handlers["inbox.stats"] = lambda argv: ok([])
    w.runner.handlers["inbox.mute"] = lambda argv: ok([])
    w.app.inbox_cache = (0.0, None)
    w.app.inbox_listing()
    assert w.app.inbox_noise() is not None
    w.runner.handlers["workplace.screen"] = lambda argv: ok({"text": "> done"})
    assert w.request("GET", "/api/tab/screen?ref=surface:7", headers=w.cookie)[0] == 200
    w.runner.handlers["briefing.detail"] = lambda argv: ok({"ok": True, "ref": "example/repo#12"})
    for query in ("ref=example/repo%2312", "ref=example/repo%2312&fresh=1"):
        assert w.request("GET", f"/api/github?{query}", headers=w.cookie)[0] == 200


def s_workspaces(w: World) -> None:
    """The workspace chat asks the terminal for its workspaces on a tab poll."""
    w.runner.handlers["workplace.workspaces"] = lambda argv: ok([{"ref": "workspace:1", "title": "Bridge"}])
    w.app.tabs.poll()


def s_returns(w: World) -> None:
    """How a start ended, in the task's notes and the inbox item's events."""
    w.app.collector.log_return({"item": "demo-task", "stage": "lost"})
    w.app.collector.log_return({"item": YES_ID, "stage": "result",
                                "result": {"kind": "filed", "text": "--the result", "key": "tab-x-result"}})


@dataclass
class Scenario:
    drive: Callable[[World], None]
    emits: set[str]
    config: str | None = None


EFFORT_CFG = tbc.LAUNCH_CFG.format(more="    effort: true\n")
WORKSPACES_CFG = "cockpit:\n  enabled: true\n  language: en\n  chat_layout: workspaces\n"

SCENARIOS = {
    "passes": Scenario(s_passes, {"briefing.collect", "workplace.tasks", "workplace.teams", "workplace.status",
                                  "inbox.list", "inbox.close"}),
    "caps": Scenario(s_caps, {"workplace.caps"}),
    "start": Scenario(s_start, {"inbox.approve", "workplace.launch", "task.note", "inbox.note"}),
    "launch_model": Scenario(s_launch_model, {"workplace.launch"}, config=EFFORT_CFG),
    "team": Scenario(s_team, {"workplace.launch"}),
    "resume": Scenario(s_resume, {"workplace.launch"}),
    "filed": Scenario(s_filed, {"inbox.add", "workplace.launch"}),
    "waits": Scenario(s_waits, {"inbox.defer", "task.wait"}),
    "to_task": Scenario(s_to_task, {"task.new"}),
    "inbox_edits": Scenario(s_inbox_edits, {"inbox.urgency", "inbox.note", "inbox.drop", "inbox.unmute", "inbox.close"}),
    "task_edits": Scenario(s_task_edits, {"task.priority", "task.note", "task.close"}),
    "settle": Scenario(s_settle, {"inbox.close", "inbox.drop", "task.close"}),
    "reopen": Scenario(s_reopen, {"task.reopen", "inbox.reopen"}),
    "review": Scenario(s_review, {"task.review"}),
    "tabs": Scenario(s_tabs, {"workplace.key", "workplace.focus", "workplace.send", "workplace.adopt",
                              "workplace.close", "workplace.control"}),
    "rows": Scenario(s_rows, {"briefing.act"}),
    "reads": Scenario(s_reads, {"inbox.list", "inbox.stats", "inbox.mute", "workplace.screen", "briefing.detail"}),
    "returns": Scenario(s_returns, {"task.note", "inbox.note"}),
    "workspaces": Scenario(s_workspaces, {"workplace.workspaces"}, config=WORKSPACES_CFG),
}

# argv the scenarios must produce in these exact shapes, beyond the verb: the optional parts of a launch
LAUNCH_SHAPES = {"start": "--here", "launch_model": "--effort", "team": "--role", "resume": "--cwd"}


def run_scenario(name: str, base: Path) -> tuple[World, list[list[str]]]:
    sc = SCENARIOS[name]
    w = World(base, config=sc.config)
    try:
        sc.drive(w)
    finally:
        w.close()
    return w, [c for c in w.runner.calls if is_target(c)]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_argv_the_cockpit_emits_parses_with_the_scripts_own_parser(name, tmp_path):
    w, calls = run_scenario(name, tmp_path)
    emitted = {w.runner.key(c) for c in calls}
    assert SCENARIOS[name].emits <= emitted, f"not emitted: {sorted(SCENARIOS[name].emits - emitted)}"
    if name in LAUNCH_SHAPES:
        assert any(LAUNCH_SHAPES[name] in c for c in w.runner.of("workplace.launch"))
    problems = []
    for argv in calls:
        try:
            ns = parse(argv)
        except ContractError as exc:
            problems.append(str(exc))
            continue
        assert ns.cmd == w.runner.key(argv).split(".", 1)[1]
    assert not problems, "\n".join(problems)


def test_every_verb_in_the_cockpit_code_is_driven_by_a_scenario():
    """A new call site with a new verb needs a scenario here, or its argv would go unchecked."""
    keyed, raw = verbs_in_source()
    assert len(keyed) >= 25 and {"collect", "act", "detail", "review", "note"} <= raw   # the scan still sees them
    driven = set().union(*(sc.emits for sc in SCENARIOS.values()))
    assert keyed - driven == set()
    assert {v for v in raw if not any(k.endswith(f".{v}") for k in driven)} == set()


def test_a_flag_renamed_in_inbox_py_fails_the_contract(tmp_path):
    w = World(tmp_path)
    try:
        w.act("drop", key=f"inbox:{YES_ID}", reason="family")
    finally:
        w.close()
    (argv,) = w.runner.of("inbox.drop")
    assert parse(argv).reason == "family"
    source = (ROOT / "scripts" / "inbox.py").read_text(encoding="utf-8")
    flag = 'sp.add_argument("--reason", choices=DROP_REASONS,'
    assert source.count(flag) == 1
    renamed = load_script("inbox.py", source.replace(flag, 'sp.add_argument("--why", choices=DROP_REASONS,'))
    with pytest.raises(ContractError, match="unrecognized arguments: --reason family"):
        parse(argv, renamed)


def test_a_missing_required_flag_or_a_value_outside_the_choices_fails(tmp_path):
    w = World(tmp_path)
    try:
        w.act("do_it", keys=["task:other-task"])
    finally:
        w.close()
    (argv,) = w.runner.of("workplace.launch")
    i = argv.index("--items")
    with pytest.raises(ContractError, match="required: --items"):
        parse(argv[:i] + argv[i + 2:])
    with pytest.raises(ContractError, match="invalid choice"):
        parse([*argv[:argv.index("--mode") + 1], "sprint", *argv[argv.index("--mode") + 2:]])


# ---------------------------------------------------------------- real output of collect and caps

DRIVER_CAPS = ["tabs", "sessions", "open", "launch", "send", "rename", "focus", "key", "screen", "close"]
DRIVER = f"""import json, sys
verb = json.loads(sys.stdin.read() or "{{}}").get("verb")
print(json.dumps({{"caps": {DRIVER_CAPS!r}}} if verb == "caps" else {{"tabs": []}} if verb == "tabs"
                 else {{"sessions": {{}}}} if verb == "sessions" else {{"report": []}}))
"""

# what the cockpit reads of `briefing.py collect --json` (model.parse_view, parse_pages, parse_info and the
# collector), level by level; every one must be in the real output of an inbox and a tasks section
READS = {
    "top": {"profile", "title", "sections", "view", "pages"},
    "section": {"id", "status"},
    "view": {"headline", "since", "buckets", "agenda", "status", "clear", "hygiene", "workplace"},
    "bucket": {"id", "title", "items"},
    "row": {"title", "why", "sources", "inbox_id", "gate", "task", "url", "urgency", "has_action", "inbox_state",
            "inbox_key", "mark", "due", "new", "changed"},
    "page": {"id", "title", "sections"},
    "page_section": {"id", "kind", "title", "status", "reason", "alarm", "empty", "items", "total", "weight", "bad",
                     "as_of"},
    "page_item": {"id", "title", "detail", "when", "tone", "url", "task", "ask", "actionable", "mark", "inbox",
                  "priority", "state", "lines"},
}
# keys the fixture uses that only other kinds of rows carry: a GitHub row (ref), a command section with its
# own view (view), the rows of a command or accounts section (tags, account, row_id, actions)
ONLY_ELSEWHERE = {"row": {"ref"}, "page_section": {"view"}, "page_item": {"tags", "account", "row_id", "actions"}}


def levels(data: dict) -> dict[str, set[str]]:
    """The keys of a collect answer, level by level, joined over every entry of a level."""
    out = {k: set() for k in READS}
    out["top"] = set(data)
    view = data.get("view") or {}
    out["view"] = set(view)
    for s in data.get("sections") or []:
        out["section"] |= set(s)
    for b in view.get("buckets") or []:
        out["bucket"] |= set(b)
        for it in b.get("items") or []:
            out["row"] |= set(it)
    for p in data.get("pages") or []:
        out["page"] |= set(p)
        for s in p.get("sections") or []:
            out["page_section"] |= set(s)
            for it in s.get("items") or []:
                out["page_item"] |= set(it)
    return out


def real_bridge(base: Path) -> tuple[Path, str]:
    """A Bridge with one inbox item (filed by the real inbox.py), one task, an inbox-and-tasks profile and
    a command driver that answers like a terminal driver without a terminal."""
    root = base / "bridge"
    (root / "work" / "tasks" / "demo-task").mkdir(parents=True)
    (root / "work" / "streams").mkdir(parents=True)
    (root / "workflow" / "briefings").mkdir(parents=True)
    driver = base / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    (root / "bridge-config.yaml").write_text(
        "cockpit:\n  enabled: true\n  language: en\n  relay: false\n"
        f"workplace:\n  driver:\n    command: [{json.dumps(sys.executable)}, {json.dumps(str(driver))}]\n",
        encoding="utf-8")
    (root / "workflow" / "briefings" / "morning.yaml").write_text(
        "schema_version: 1\nscope: user\nid: morning\ndefault: true\n"
        "sections:\n  - {kind: inbox}\n  - {kind: tasks, status: [doing]}\nview: {style: triage}\n", encoding="utf-8")
    (root / "work" / "tasks" / "demo-task" / "STATUS.md").write_text(
        "---\ntype: feature\nstatus: doing\npriority: P1\ncreated: 2026-10-01\nlast_updated: 2026-10-08\n"
        "headline: Demo task\n---\n\n# Demo task\n", encoding="utf-8")
    filed = subprocess.run([sys.executable, str(ROOT / "scripts" / "inbox.py"), "--root", str(root), "--by", "test",
                            "add", "--from", "briefing/demo", "--kind", "decision", "--summary", "Tidy labels",
                            "--gate", "your-yes", "--key", "demo-labels"],
                           capture_output=True, text=True, timeout=60, check=True)
    return root, filed.stdout.strip().splitlines()[-1]


@pytest.fixture
def real(tmp_path):
    root, item = real_bridge(tmp_path)
    runner = Runner(root, cmux=None, claude=None, codex=None, code=ROOT)
    server = make_server(root, port=0, runner=runner, state_dir=tmp_path / "state", background=False,
                         key_dir=tmp_path / "keys")
    yield server.app, item
    server.app.stop()
    server.server_close()


def test_the_real_collect_answers_every_field_the_cockpit_reads(real):
    app, item = real
    run = app.run(app.collector.collect_argv("full", False), 120)
    assert run.ok, run.err
    data = json.loads(run.out)
    got = levels(data)
    for level, keys in READS.items():
        assert keys - got[level] == set(), f"{level}: briefing collect no longer answers {sorted(keys - got[level])}"
    rows = [it for b in data["view"]["buckets"] for it in b["items"]]
    assert [r["inbox_id"] for r in rows] == [item]
    tasks = [it for p in data["pages"] for s in p["sections"] for it in s["items"] if it.get("task")]
    assert [t["task"] for t in tasks] == ["demo-task"]


def test_the_fixture_of_the_cockpit_tests_assumes_no_field_the_real_collect_lacks(real, tmp_path):
    app, _ = real
    run = app.run(app.collector.collect_argv("full", False), 120)
    got, assumed = levels(json.loads(run.out)), levels(collect_fixture(tmp_path))
    for level in READS:
        extra = assumed[level] - got[level] - ONLY_ELSEWHERE.get(level, set())
        assert extra == set(), f"{level}: the fixture assumes {sorted(extra)}, the real collect has none of it"


def test_a_real_pass_reaches_the_model_and_caps_come_from_the_driver(real):
    app, item = real
    app.tabs.poll()
    app.collector.request("both")
    app.collector.drain()
    assert app.collector.last_error is None
    keys = {r["key"] for sec in app.collector.model["sections"] for r in sec["rows"]}
    assert f"inbox:{item}" in keys
    run = app.run(app.workplace("caps", "--json"), 30)
    assert run.ok, run.err
    assert json.loads(run.out) == {"caps": DRIVER_CAPS}
    assert app.driver_caps(fresh=True) == DRIVER_CAPS


def test_the_undo_of_a_task_closed_in_review_parses_with_task_py(tmp_path):
    """#384: the undo restores the status before the close, so `--as review` must be a choice task.py has."""
    w = World(tmp_path)
    try:
        task = w.root / "work" / "tasks" / "other-task"
        task.mkdir(parents=True, exist_ok=True)
        (task / "STATUS.md").write_text("---\nstatus: review\n---\n", encoding="utf-8")
        undo = w.act("task_close", keys=["task:other-task"], reason="done")["undo"][0]["undo"]
        w.act(undo["verb"], **undo["args"])
    finally:
        w.close()
    reopen = [c for c in w.runner.calls if is_target(c) and w.runner.key(c) == "task.reopen"]
    assert len(reopen) == 1 and parse(reopen[0]).as_status == "review"
