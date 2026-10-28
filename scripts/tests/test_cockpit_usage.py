# SPDX-License-Identifier: MIT
"""Contract for the cockpit's process for ongoing proposals (round 6d, item 10).

Three parts. The page writes down which control was used from which place (page, view, area, control, verb, a
count), never what it was about: no title, no text, no id of an item, no path. The server keeps those lines in
usage.jsonl beside audit.log, capped in size, and cockpit.usage.clicks: false switches it off.
scripts/cockpit-usage.py counts them with audit.log for a period (since its last run by default) and leaves one
proposal per candidate in work/_learning/proposals/, in the format /bridge-learn reads. The explain window's
"What bothers you here?" saves its sentence with the place as such a proposal (verb explain_note).

Run: pytest -q scripts/tests/test_cockpit_usage.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import store as st  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "work" / "_learning" / "_schema.proposal.yaml"
_spec = importlib.util.spec_from_file_location("cockpit_usage", ROOT / "scripts" / "cockpit-usage.py")
cu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cu)

CFG = "cockpit:\n  enabled: true\n  language: en\n{extra}"
TITLE = "Telegram bot exit 75 since Friday"


def front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n", 2)[1])


def valid(data: dict) -> None:
    """The frontmatter against the one proposal schema /bridge-learn validates with"""
    jsonschema = pytest.importorskip("jsonschema")
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        json.loads(json.dumps(data, default=str)))


# ---------------------------------------------------------------- the click origin log (store.py, /api/clicks)

def test_a_click_keeps_its_place_and_control_and_drops_what_it_was_about(tmp_path):
    log = tmp_path / "usage.jsonl"
    events = [
        {"kind": "click", "page": "@chat", "area": "chatList", "control": "chat-row", "n": 2, "title": TITLE},
        {"kind": "click", "page": "briefing", "view": "flow", "area": "flowCard", "control": "verb", "text": "a b"},
        {"kind": "verb", "page": "@workers", "area": "wrow", "control": "wrow-ask", "verb": "worker_advise"},
        # a title, an item key or a path in a field that holds a name: the whole event is dropped
        {"kind": "click", "page": "@chat", "area": "chatList", "control": TITLE},
        {"kind": "click", "page": "@chat", "area": "inbox:a1b2c3", "control": "row"},
        {"kind": "click", "page": "work/tasks/demo", "area": "x", "control": "row"},
        {"kind": "verb", "page": "@chat", "area": "chatList", "control": "row", "verb": "no_such_verb"},
        {"kind": "scroll", "page": "@chat", "area": "chatList", "control": "row"},
        "not an event",
    ]
    kept = st.append_clicks(log, events, dt.datetime(2026, 10, 28, 7, 34, 12).timestamp() * 1000,
                            verbs={"worker_advise", "advise"})
    assert kept == 3
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x["area"] for x in lines] == ["chatList", "flowCard", "wrow"]
    assert lines[0] == {"at": "2026-10-28T07:34", "kind": "click", "page": "@chat", "view": "-", "area": "chatList",
                        "control": "chat-row", "verb": "-", "n": 2}
    assert lines[2]["verb"] == "worker_advise"
    raw = log.read_text(encoding="utf-8")
    assert TITLE not in raw and "title" not in raw and "a b" not in raw and "inbox:" not in raw


def test_the_click_log_is_capped_and_keeps_one_older_file(tmp_path):
    log = tmp_path / "usage.jsonl"
    one = [{"kind": "click", "page": "@chat", "area": "chatList", "control": "chat-row"}]
    for _ in range(40):
        st.append_clicks(log, one, 0, max_bytes=1000)
    assert log.stat().st_size < 1000 + 200
    assert (tmp_path / "usage.jsonl.1").exists()
    assert not (tmp_path / "usage.jsonl.2").exists()


def test_a_batch_is_small_and_counts_are_bounded(tmp_path):
    log = tmp_path / "usage.jsonl"
    with pytest.raises(ValueError):
        st.append_clicks(log, {"page": "@chat"}, 0)
    with pytest.raises(ValueError):
        st.append_clicks(log, [{"kind": "click", "page": "@chat"}] * (st.CLICKS_MAX + 1), 0)
    st.append_clicks(log, [{"kind": "click", "page": "@chat", "n": 10 ** 9}, {"kind": "click", "page": "@chat", "n": "x"}], 0)
    assert [json.loads(x)["n"] for x in log.read_text().splitlines()] == [st.CLICK_N_MAX, 1]


def test_the_endpoint_writes_beside_audit_log_and_the_switch_turns_it_off(tmp_path):
    w = World(tmp_path / "on", config=CFG.format(extra=""), prepare=False)
    try:
        audit = w.app.state_dir / "audit.log"
        before = audit.read_text() if audit.exists() else ""
        status, _, data = w.post("/api/clicks", {"events": [
            {"kind": "click", "page": "@chat", "area": "chatList", "control": "chat-row", "title": TITLE},
            {"kind": "verb", "page": "@chat", "area": "chatList", "control": "chat-row", "verb": "advise"}]})
        assert status == 200 and json.loads(data) == {"ok": True, "kept": 2}
        raw = (w.app.state_dir / "usage.jsonl").read_text(encoding="utf-8")
        assert len(raw.splitlines()) == 2 and TITLE not in raw
        assert (audit.read_text() if audit.exists() else "") == before      # audit.log stays as it is
        assert w.post("/api/clicks", {"events": "x"})[0] == 400
        assert w.post("/api/clicks", {"events": [], "page": "@chat"})[0] == 400
    finally:
        w.close()
    w = World(tmp_path / "off", config=CFG.format(extra="  usage:\n    clicks: false\n"), prepare=False)
    try:
        status, _, data = w.post("/api/clicks", {"events": [{"kind": "click", "page": "@chat", "control": "chat-row"}]})
        assert status == 200 and json.loads(data) == {"ok": True, "kept": 0, "off": True}
        assert not (w.app.state_dir / "usage.jsonl").exists()
    finally:
        w.close()


def test_the_switch_is_on_by_default_and_a_wrong_value_warns(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    (root / "bridge-config.yaml").write_text(CFG.format(extra=""), encoding="utf-8")
    assert load_web_config(root).usage_clicks is True
    (root / "bridge-config.yaml").write_text(CFG.format(extra="  usage:\n    clicks: false\n"), encoding="utf-8")
    cfg = load_web_config(root)
    assert cfg.usage_clicks is False and cfg.config_warnings == ()
    (root / "bridge-config.yaml").write_text(CFG.format(extra="  usage:\n    clicks: maybe\n"), encoding="utf-8")
    cfg = load_web_config(root)
    assert cfg.usage_clicks is True and any("usage.clicks" in x for x in cfg.config_warnings)


def test_the_page_learns_the_switch_at_bootstrap(tmp_path):
    w = World(tmp_path, config=CFG.format(extra="  usage:\n    clicks: false\n"), prepare=False)
    try:
        status, _, data = w.request("GET", "/api/bootstrap", headers=w.cookie)
        assert status == 200 and json.loads(data)["config"]["clicks"] is False
    finally:
        w.close()


# ---------------------------------------------------------------- "What bothers you here?" (verb explain_note)

def test_the_explain_note_is_a_pending_proposal_with_its_place(tmp_path):
    w = World(tmp_path, config=CFG.format(extra=""), serve=False, prepare=False)
    try:
        r = w.act("explain_note", text="The question is gone after a reload", page="@chat", area="chatList")
        assert r["ok"] is True and not r["note"]                 # the window confirms itself, no toast
        files = list((w.root / "work" / "_learning" / "proposals").glob("*.md"))
        assert len(files) == 1
        data = front(files[0])
        valid(data)
        assert data["id"] == files[0].stem and data["id"].endswith("-cockpit-usage-note-chat-chatlist")
        assert data["status"] == "pending" and data["source"]["type"] == "cockpit-usage"
        assert data["scope"] == "user" and data["proposal_type"] == "needs-triage"
        body = files[0].read_text(encoding="utf-8")
        assert "The question is gone after a reload" in body and "@chat" in body and "chatList" in body
        # a second note on the same place is a file of its own
        w.act("explain_note", text="Still gone", page="@chat", area="chatList")
        assert len(list((w.root / "work" / "_learning" / "proposals").glob("*.md"))) == 2
        # the audit line names the place, never the sentence
        audit = (w.app.state_dir / "audit.log").read_text(encoding="utf-8")
        assert "explain_note" in audit and "reload" not in audit and "Still" not in audit
        with pytest.raises(ActionError):
            w.act("explain_note", text="x", page="../etc")
        with pytest.raises(ActionError):
            w.act("explain_note", text="", page="@chat")
    finally:
        w.close()


# ---------------------------------------------------------------- scripts/cockpit-usage.py

NOW = dt.datetime(2026, 10, 28, 12, 0, 0)


def bridge(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "bridge"
    state = root / ".bridge" / "cockpit"
    state.mkdir(parents=True)
    (root / "work" / "_learning" / "proposals").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text("language: en\n", encoding="utf-8")
    web = root / "scripts" / "web"
    web.mkdir(parents=True)
    (web / "logic.js").write_text(
        "const HINTS = {\n"
        "  '@chat': [['chatModel', '.chatpage .seg'], ['chatList', '.chat-list'], ['chatBox', '.tabview-send']],\n"
        "  '@agents': [['agentList', '.agents-list']],\n"
        "  '@flow': [['flowSide', '.flow-side'], ['flowCard', '.flow-card']],\n"
        "}\n", encoding="utf-8")
    return root, state


def click(at: dt.datetime, page: str, area: str, control: str, n: int = 1, view: str = "-", kind: str = "click",
          verb: str = "-") -> str:
    return json.dumps({"at": at.isoformat(timespec="minutes"), "kind": kind, "page": page, "view": view,
                       "area": area, "control": control, "verb": verb, "n": n})


def view_line(at: dt.datetime, page: str, view: str = "-") -> str:
    return f"{at.isoformat(timespec='seconds')} page_view {page} view={view}"


def fill(state: Path) -> None:
    t = NOW - dt.timedelta(days=3)
    old = NOW - dt.timedelta(days=30)
    clicks = [click(old, "@chat", "chatList", "chat-sort"),            # before the period: a control once used
              click(t, "@chat", "chatList", "chat-row", n=5),
              click(t, "@chat", "chatBox", "send", n=2),
              click(t, "briefing", "flowCard", "verb", n=3, view="flow"),
              click(t, "briefing", "flowCard", "verb", view="flow", kind="verb", verb="advise")]
    (state / "usage.jsonl").write_text("\n".join(clicks) + "\n", encoding="utf-8")
    s = lambda sec: t + dt.timedelta(seconds=sec)  # noqa: E731
    audit = [view_line(old, "@check"),                                  # before the period: a page once opened
             view_line(s(0), "@chat"), view_line(s(60), "briefing", "flow"),
             # opened and left at once, three times
             view_line(s(100), "@agents"), view_line(s(102), "@chat"),
             view_line(s(200), "@agents"), view_line(s(203), "@chat"),
             view_line(s(300), "@agents"), view_line(s(301), "@chat"),
             # back and forth between two pages, three times
             view_line(s(400), "@workers"), view_line(s(410), "@sessions"), view_line(s(420), "@workers"),
             view_line(s(430), "@sessions"), view_line(s(440), "@workers"), view_line(s(450), "@sessions"),
             f"{s(500).isoformat(timespec='seconds')} advise task:demo exits=0 ok=true",
             view_line(s(600), "@chat")]
    (state / "audit.log").write_text("\n".join(audit) + "\n", encoding="utf-8")


def test_the_report_counts_per_place_and_finds_the_candidates(tmp_path):
    root, state = bridge(tmp_path)
    fill(state)
    rep = cu.report(root, state, NOW - dt.timedelta(days=14), NOW)
    chat = rep["places"]["@chat"]
    assert chat["views"] == 5 and chat["clicks"] == 7
    assert chat["areas"] == {"chatList": 5, "chatBox": 2}
    assert chat["controls"] == {"chatList/chat-row": 5, "chatBox/send": 2}
    assert rep["places"]["briefing/flow"]["verbs"] == {"advise": 1}
    kinds = {(c["kind"], c["place"], c.get("area"), c.get("control")) for c in rep["candidates"]}
    assert ("unused_area", "@chat", "chatModel", None) in kinds         # the page is used, this area never
    assert ("unused_control", "@chat", "chatList", "chat-sort") in kinds  # used before the period, not in it
    assert ("unused_page", "@check", None, None) in kinds              # opened before the period, not in it
    assert ("left_at_once", "@agents", None, None) in kinds
    assert ("back_and_forth", "@sessions+@workers", None, None) in kinds
    assert ("unused_area", "briefing/flow", "flowSide", None) not in kinds   # opened once: too little to say
    assert not any(c["kind"] == "unused_area" and c["area"] == "chatList" for c in rep["candidates"])


def test_a_new_click_log_calls_no_area_unused(tmp_path):
    # the page views go back further than the click log: nobody can say an area went unused before it ran
    root, state = bridge(tmp_path)
    fill(state)
    lines = (state / "usage.jsonl").read_text().splitlines()
    (state / "usage.jsonl").write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    rep = cu.report(root, state, NOW - dt.timedelta(days=14), NOW)
    kinds = {c["kind"] for c in rep["candidates"]}
    assert "unused_area" not in kinds and "unused_control" not in kinds
    assert "left_at_once" in kinds and "unused_page" in kinds


def test_proposals_are_written_in_the_bridge_learn_format_and_not_twice(tmp_path):
    root, state = bridge(tmp_path)
    fill(state)
    out = cu.main(["--root", str(root), "--days", "14", "--now", NOW.isoformat()])
    assert out == 0
    files = sorted((root / "work" / "_learning" / "proposals").glob("*.md"))
    assert files, "candidates leave proposals"
    for f in files:
        data = front(f)
        valid(data)
        assert data["id"] == f.stem and data["id"].startswith("2026-10-28-cockpit-usage-")
        assert data["source"]["type"] == "cockpit-usage" and data["severity"] == "P3" and data["status"] == "pending"
        assert ".bridge/cockpit/usage.jsonl" in data["source"]["evidence"]
        assert data["target"] == {"type": "config", "path": "bridge-config.yaml", "action": "edit"}
    names = {f.stem for f in files}
    assert "2026-10-28-cockpit-usage-unused-area-chat-chatmodel" in names
    assert "2026-10-28-cockpit-usage-left-at-once-agents" in names
    # the last run is kept: the next run counts from there, and a candidate already proposed is not written again
    assert json.loads((state / "usage-run.json").read_text())["last"] == NOW.isoformat(timespec="seconds")
    assert cu.main(["--root", str(root), "--days", "14", "--now", (NOW + dt.timedelta(hours=1)).isoformat()]) == 0
    assert sorted((root / "work" / "_learning" / "proposals").glob("*.md")) == files


def test_a_rejected_candidate_stays_away(tmp_path):
    root, state = bridge(tmp_path)
    fill(state)
    rejected = root / "work" / "_learning" / "proposals" / "rejected"
    rejected.mkdir()
    (rejected / "2026-10-01-cockpit-usage-left-at-once-agents.md").write_text("---\nid: x\n---\n", encoding="utf-8")
    cu.main(["--root", str(root), "--days", "14", "--now", NOW.isoformat()])
    assert not (root / "work" / "_learning" / "proposals" / "2026-10-28-cockpit-usage-left-at-once-agents.md").exists()


def test_dry_run_prints_and_writes_nothing(tmp_path, capsys):
    root, state = bridge(tmp_path)
    fill(state)
    assert cu.main(["--root", str(root), "--days", "14", "--dry-run", "--now", NOW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "would write" in out and "cockpit-usage-left-at-once-agents" in out
    assert not list((root / "work" / "_learning" / "proposals").glob("*.md"))
    assert not (state / "usage-run.json").exists()


def test_the_period_defaults_to_since_the_last_run(tmp_path):
    root, state = bridge(tmp_path)
    fill(state)
    (state / "usage-run.json").write_text(json.dumps({"last": (NOW - dt.timedelta(days=1)).isoformat()}), encoding="utf-8")
    start, _end = cu.period(state, None, None, NOW)
    assert start == NOW - dt.timedelta(days=1)
    (state / "usage-run.json").unlink()
    assert cu.period(state, None, None, NOW)[0] == NOW - dt.timedelta(days=cu.FIRST_DAYS)
    assert cu.period(state, 7, None, NOW)[0] == NOW - dt.timedelta(days=7)
    assert cu.period(state, None, "2026-10-20", NOW)[0] == dt.datetime(2026, 10, 20)
    # since a run an hour ago nothing happened: the counts are empty, nothing was left at once, and what was not
    # used is still judged over the last two weeks, not over the hour
    rep = cu.report(root, state, NOW - dt.timedelta(hours=1), NOW)
    assert rep["places"] == {}
    kinds = {c["kind"] for c in rep["candidates"]}
    assert "left_at_once" not in kinds and "back_and_forth" not in kinds
    assert {(c["place"], c["area"]) for c in rep["candidates"] if c["kind"] == "unused_area"} >= {("@chat", "chatModel")}
    assert not any(c["kind"] == "unused_page" and c["place"] == "@chat" for c in rep["candidates"])


def test_the_rotated_files_are_read_too_and_a_broken_line_is_skipped(tmp_path):
    root, state = bridge(tmp_path)
    t = NOW - dt.timedelta(days=1)
    (state / "usage.jsonl.1").write_text(click(t, "@chat", "chatList", "chat-row", n=4) + "\nnot json\n", encoding="utf-8")
    (state / "usage.jsonl").write_text(click(t, "@chat", "chatList", "chat-row") + "\n", encoding="utf-8")
    (state / "audit.log.1").write_text(view_line(t, "@chat") + "\ngarbage line\n", encoding="utf-8")
    rep = cu.report(root, state, NOW - dt.timedelta(days=2), NOW)
    assert rep["places"]["@chat"]["clicks"] == 5 and rep["places"]["@chat"]["views"] == 1


def test_write_note_follows_the_format_for_a_place_without_an_area(tmp_path):
    root, _state = bridge(tmp_path)
    path = cu.write_note(root, "Too many buttons", "briefing", "flow", None, dt.date(2026, 10, 28), "de")
    data = front(path)
    valid(data)
    assert path.stem == "2026-10-28-cockpit-usage-note-briefing-flow"
    assert data["severity"] == "P2"
    assert "Too many buttons" in path.read_text(encoding="utf-8")
