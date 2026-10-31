# SPDX-License-Identifier: MIT
"""Access by workspace: a person named under `members:` sees and changes only the areas of their workspaces.

The owner's cockpit stays as it was. For a person everything is refused or left out unless access.py lists it, so
the leak tests below walk every route and every event with a marker planted in the other area, and the guards fail
as soon as a route, verb, event or field exists that nobody has classified.

Run: pytest -q scripts/tests/test_bridge_cockpit_access.py
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, a2a_peers, ok, private_key_dir  # noqa: E402,F401
from lib.bridge_cockpit import access as ac  # noqa: E402
from lib.bridge_cockpit import actions_base as ab  # noqa: E402
from lib.bridge_cockpit import details  # noqa: E402
from lib.bridge_cockpit import server as srv  # noqa: E402
import workspace as engine  # noqa: E402

MARK = "ZEBRAMARK"                # stands in everything of the other area
LIB = Path(ac.__file__).parent
OWN_INBOX = "20261009-0900-home-note-a1b2"
OTHER_INBOX = "20261009-0910-job-note-c3d4"
MIXED_INBOX = "20261009-0920-mixed-note-e5f6"
CONFIG = """cockpit:
  enabled: true
  language: en
  relay: true
workplace:
  control:
    name: Control
  workspaces:
    - {name: Home, aliases: [House], contexts: [home]}
    - {name: Job, contexts: [job]}
"""
TASKS = [
    {"slug": "home-task", "label": "Home task", "area": "Home", "area_aliases": ["House"], "priority": "P2", "status": "doing"},
    {"slug": "job-task", "label": f"{MARK} job task", "area": "Job", "priority": "P1", "status": "doing"},
    {"slug": "mixed-task", "label": f"{MARK} mixed task", "area": "Home", "area_aliases": ["Job"], "priority": "P1"},
    {"slug": "bare-task", "label": f"{MARK} bare task", "area": None, "priority": "P3"},
]


def collect(root: Path) -> dict:
    return {"profile": "morning", "title": f"{MARK} title", "collected_at": "2026-10-09T12:00",
            "sections": [{"id": "inbox", "status": "ok"}, {"id": "tasks", "status": "ok"}],
            "view": {"headline": f"{MARK} headline", "since": f"{MARK} since", "clear": [f"{MARK} clear"], "hygiene": [f"{MARK}"],
                     "workplace": f"{MARK} workplace",
                     "buckets": [{"id": "do", "title": "Do", "items": [
                         {"title": "Home note", "inbox_id": OWN_INBOX, "gate": "only-you", "urgency": "today", "area": "Home",
                          "sources": ["inbox"], "inbox_state": "open", "url": f"file://{root}/work/tasks/home-task/STATUS.md"},
                         {"title": f"{MARK} job note", "inbox_id": OTHER_INBOX, "gate": "only-you", "urgency": "today",
                          "area": "Job", "sources": ["inbox"], "inbox_state": "open"},
                         {"title": f"{MARK} no area", "inbox_id": MIXED_INBOX, "gate": "free", "sources": ["inbox"],
                          "inbox_state": "open"}]},
                         {"id": "delegate", "title": "Delegate", "items": [
                             {"title": "Home task", "task": "home-task", "sources": ["tasks"]},
                             {"title": f"{MARK} job", "task": "job-task", "sources": ["tasks"]},
                             {"title": f"{MARK} mixed", "task": "mixed-task", "sources": ["tasks"]},
                             {"title": f"{MARK} bare", "task": "bare-task", "sources": ["tasks"]}]}],
                     "agenda": [{"when": "10:00", "title": f"{MARK} client call"}],
                     "status": [{"title": f"{MARK} status", "count": 1}]},
            "pages": [{"id": "systems", "title": f"{MARK} page", "sections": [
                {"id": "checks", "kind": "command", "title": f"{MARK} checks", "status": "ok", "alarm": True, "bad": 1, "weight": 1,
                 "total": 1, "items": [{"id": "x", "title": f"{MARK} alarm", "tone": "bad", "ask": True}]}]}]}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path, config=CONFIG, serve=True, prepare=False)
    root = w.root
    (root / "workflow" / "workspaces").mkdir(parents=True)
    for ws, area, members in (("home", "Home", "members: [pat]\n"), ("job", "Job", "")):
        (root / "workflow" / "workspaces" / f"{ws}.yaml").write_text(
            f"schema_version: 1\nid: {ws}\ntitle: {area}\narea: {area}\n{members}", encoding="utf-8")
    for slug, text in (("home-task", "Home"), ("job-task", MARK), ("mixed-task", MARK), ("bare-task", MARK)):
        (root / "work" / "tasks" / slug).mkdir(parents=True)
        (root / "work" / "tasks" / slug / "STATUS.md").write_text(
            f"---\ntype: feature\nstatus: doing\nheadline: {text}\nrelated:\n  - ../{MARK}/STATUS.md\n---\n\n# {text}\n\n## Goal\n\n{text}\n",
            encoding="utf-8")
    (root / "work" / "log.md").write_text(
        f"# Log\n\n## Friday 09.10\n\n| Time | | Context | What |\n|---|---|---|---|\n| 2026-10-09 09:00 | x | home-task | {MARK} |\n",
        encoding="utf-8")
    for item, text in ((OWN_INBOX, "Home note"), (OTHER_INBOX, MARK), (MIXED_INBOX, MARK)):
        folder = root / "work" / "inbox" / item
        (folder / "events").mkdir(parents=True)
        (folder / "item.yaml").write_text(f"schema_version: 1\nsummary: {text}\nkind: decision\ngate: free\n", encoding="utf-8")
    w.runner.handlers["briefing.collect"] = lambda argv: ok(collect(w.root))
    w.runner.handlers["workplace.tasks"] = lambda argv: ok(TASKS)
    w.runner.handlers["inbox.list"] = lambda argv: ok([{"id": i, "state": "open", "task": "home-task", "summary": MARK if i != OWN_INBOX else "x"}
                                                       for i in (OWN_INBOX, OTHER_INBOX)])
    w.app.tabs.poll()
    w.app.collector.request("both")
    w.app.collector.drain()
    yield w
    w.close()


def as_person(w, person="pat") -> dict:
    return {"Cookie": f"{w.app.cookie_name}={w.app.session_value(person=person)}"}


def get(w, path, person="pat"):
    return w.request("GET", path, headers=as_person(w, person))


def post(w, path, payload, person="pat", csrf=None):
    headers = {**as_person(w, person), "X-Bridge-Token": csrf or w.app.csrf_of(person), "Origin": f"http://127.0.0.1:{w.port}",
               "Content-Type": "application/json"}
    return w.request("POST", path, body=json.dumps(payload).encode("utf-8"), headers=headers)


def rows_of(state: dict) -> list[dict]:
    return [r for s in state["model"]["sections"] for r in s["rows"]]


def sse_until_state(w, person="pat") -> tuple[list[str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", w.port, timeout=5)
    conn.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{w.port}", **as_person(w, person)})
    resp = conn.getresponse()
    data = b""
    while b"event: state" not in data or not data.endswith(b"\n\n"):
        data += resp.read1(65536)
    conn.close()
    return re.findall(r"^event: (\w+)$", data.decode("utf-8"), re.M), data


# ---------------------------------------------------------------- the owner

def test_the_owner_sees_everything_as_before(world):
    status, _, data = world.request("GET", "/api/state", headers=world.cookie)
    assert status == 200 and MARK.encode() in data
    state = json.loads(data)
    assert {r["key"] for r in rows_of(state)} >= {"task:job-task", "task:home-task"}
    assert "sessions" in state and state["model"]["headline"].startswith(MARK)


def test_the_owner_page_gets_every_event(world):
    client = world.app.hub.add()
    world.app.broadcast("note", {"text": MARK})
    assert client.queue.get_nowait()[0] == "note"
    world.app.hub.remove(client)


# ---------------------------------------------------------------- what a person sees

def test_a_person_sees_only_the_rows_of_their_area(world):
    status, _, data = get(world, "/api/state")
    assert status == 200
    keys = {r["key"] for r in rows_of(json.loads(data))}
    assert keys == {"task:home-task", f"inbox:{OWN_INBOX}"}


def test_a_row_of_two_areas_or_none_stays_out(world):
    keys = {r["key"] for r in rows_of(json.loads(get(world, "/api/state")[2]))}
    assert "task:mixed-task" not in keys and "task:bare-task" not in keys and f"inbox:{MIXED_INBOX}" not in keys


@pytest.mark.parametrize("path", sorted(ac.PERSON_GET - {"/api/events", "/api/task", "/api/inbox"}))
def test_no_marker_and_no_path_on_a_person_route(world, path):
    status, _, data = get(world, path)
    assert status == 200
    assert MARK.encode() not in data and str(world.root).encode() not in data and b"surface:" not in data


@pytest.mark.parametrize("path", sorted(ac.OWNER_GET))
def test_every_owner_route_is_closed_to_a_person(world, path):
    status, _, data = get(world, path + "?slug=job-task&id=x&q=x&ref=x")
    assert status == 403 and MARK.encode() not in data


@pytest.mark.parametrize("path", sorted(ac.OWNER_POST))
def test_every_owner_post_is_closed_to_a_person(world, path):
    status, _, data = post(world, path, {"kind": "free", "args": {"text": "x"}, "via": "quick"})
    assert status == 403 and MARK.encode() not in data


def test_a_person_cannot_ask_the_model(world):
    before = len(world.runner.of("claude.p"))
    status, _, _ = post(world, "/api/ask", {"kind": "free", "args": {"text": "read everything"}, "via": "quick"})
    assert status == 403 and len(world.runner.of("claude.p")) == before


def test_the_live_channel_carries_no_marker(world):
    names, data = sse_until_state(world)
    assert names[:2] == ["hello", "state"] and MARK.encode() not in data and str(world.root).encode() not in data


@pytest.mark.parametrize("event", sorted(ac.OWNER_EVENTS))
def test_an_owner_event_never_reaches_a_person(world, event):
    client = world.app.person_client("pat")
    world.app.broadcast(event, {"text": MARK})
    assert client.queue.empty()
    world.app.hub.remove(client)


def test_the_model_event_is_cut_for_a_person(world):
    client = world.app.person_client("pat")
    world.app.broadcast("view", world.app.collector.model)
    name, data = client.queue.get_nowait()
    assert name == "view" and MARK not in data and "task:home-task" in data
    world.app.hub.remove(client)


def test_a_filter_that_breaks_sends_nothing(world, monkeypatch):
    monkeypatch.setattr(world.app.access, "event", lambda *a: 1 / 0)
    client = world.app.person_client("pat")
    world.app.broadcast("view", {"x": MARK})
    assert client.queue.empty()
    world.app.hub.remove(client)


def test_an_own_task_opens_without_links_to_elsewhere(world):
    status, _, data = get(world, "/api/task?slug=home-task")
    body = json.loads(data)
    assert status == 200 and body["slug"] == "home-task"
    assert MARK.encode() not in data and body["related"] == [] and body["log"] == [] and "path" not in body
    assert [i["id"] for i in body["inbox"]] == [OWN_INBOX]


def test_a_foreign_task_or_item_does_not_open(world):
    for path in ("/api/task?slug=job-task", "/api/task?slug=job-task&file=STATUS.md", "/api/task?slug=mixed-task",
                 f"/api/inbox?id={OTHER_INBOX}", "/api/task?slug=home-task&path=work/tasks/home-task"):
        status, _, data = get(world, path)
        assert status in (403, 404) and MARK.encode() not in data, path


def test_an_own_inbox_item_opens(world):
    status, _, data = get(world, f"/api/inbox?id={OWN_INBOX}")
    assert status == 200 and MARK.encode() not in data


def test_a_person_gets_only_their_workspaces_and_areas(world):
    state = json.loads(get(world, "/api/state")[2])
    assert [i["key"] for i in state["workspaces"]["items"]] == ["Home"]
    boot = json.loads(get(world, "/api/bootstrap")[2])
    assert boot["config"]["areas"] == ["Home"] and "Job" not in json.dumps(boot)


# ---------------------------------------------------------------- what a person may change

def test_a_verb_on_an_own_row_runs(world):
    status, _, data = post(world, "/api/action", {"verb": "priority", "args": {"key": "task:home-task", "value": "P1"}})
    assert status == 200 and json.loads(data) == {"ok": True}


def test_a_verb_on_a_foreign_row_is_refused(world):
    calls = len(world.runner.calls)
    for key in ("task:job-task", "task:mixed-task", f"inbox:{OTHER_INBOX}", "ref:example/repo#1"):
        status, _, _ = post(world, "/api/action", {"verb": "priority", "args": {"key": key, "value": "P1"}})
        assert status == 403, key
    status, _, _ = post(world, "/api/action", {"verb": "settle", "args": {"keys": ["task:home-task", "task:job-task"], "outcome": "done"}})
    assert status == 403 and len(world.runner.calls) == calls


@pytest.mark.parametrize("verb", sorted(ac.OWNER_VERBS))
def test_an_owner_verb_is_refused_before_its_arguments(world, verb):
    status, _, _ = post(world, "/api/action", {"verb": verb, "args": {}})
    assert status == 403


def test_the_owner_key_is_no_way_in_for_a_person(world):
    status, _, _ = post(world, "/api/action", {"verb": "priority", "args": {"key": "task:home-task", "value": "P1"}}, csrf=world.app.csrf)
    assert status == 401


def test_a_row_that_would_also_end_a_foreign_ask_is_refused(world):
    world.app.collector.index["task:home-task"]["out"]["also_inbox"] = [{"id": OTHER_INBOX, "title": MARK}]
    status, _, data = post(world, "/api/action", {"verb": "settle", "args": {"keys": ["task:home-task"], "outcome": "done"}})
    assert status == 403 and MARK.encode() not in data


def test_the_workspace_a_person_sees_names_no_other(world):
    path = world.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "parent: job\n", encoding="utf-8")
    item = json.loads(get(world, "/api/state")[2])["workspaces"]["items"][0]
    assert item["key"] == "Home" and not item.get("parent") and "job" not in json.dumps(item).lower()


def test_stale_names_nothing(world):
    world.app.collector.model["stale"] = [MARK]
    assert json.loads(get(world, "/api/state")[2])["model"]["stale"] is False


def test_a_file_of_an_own_task_is_scrubbed(world):
    (world.root / "work" / "tasks" / "home-task" / "notes.md").write_text(f"key {world.app.token} at {world.root}/x\n", encoding="utf-8")
    status, _, data = get(world, "/api/task?slug=home-task&file=notes.md")
    assert status == 200 and world.app.token.encode() not in data and str(world.root).encode() not in data


# ---------------------------------------------------------------- who a person is

def test_a_person_login_link_works_once_and_sets_a_person_cookie(world):
    code = srv.login_code(world.app.token, world.clock(), person="pat")
    status, headers, _ = world.request("GET", f"/?code={code}")
    assert status == 303
    value = headers["Set-Cookie"].split(";")[0].split("=", 1)[1]
    assert world.app.session_person(value) == "pat" and not world.app.session_ok(value)
    assert world.request("GET", f"/?code={code}")[0] == 401


def test_a_person_cookie_cannot_be_turned_into_another_or_the_owner(world):
    value = world.app.session_value(person="pat")
    forged = "owner" + value[3:]
    assert world.app.session_person(forged) is None and world.app.session_person(value.split(".", 1)[1]) is None
    assert not world.app.session_ok(value)
    assert world.request("GET", "/api/state", headers={"Cookie": f"{world.app.cookie_name}={forged}"})[0] == 401


def test_an_old_person_cookie_ends(world):
    value = world.app.session_value(person="pat", now_s=world.app.now_s() - srv.COOKIE_AGE_S - 60)
    assert world.app.session_person(value) is None


def test_a_person_without_a_workspace_gets_nothing(world):
    for path in ("/api/state", "/api/bootstrap", "/api/events"):
        assert get(world, path, person="nobody")[0] == 403


def test_taking_a_person_off_the_workspace_works_at_once(world):
    assert get(world, "/api/state")[0] == 200
    path = world.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("members: [pat]\n", ""), encoding="utf-8")
    assert get(world, "/api/state")[0] == 403
    client = world.app.person_client("pat")
    world.app.broadcast("view", world.app.collector.model)
    assert client.queue.empty()
    world.app.hub.remove(client)


def test_a_resting_or_archived_workspace_closes(world):
    world.app.workspaces.activate("Home", False)
    assert get(world, "/api/state")[0] == 403
    world.app.workspaces.activate("Home", True)
    assert get(world, "/api/state")[0] == 200
    path = world.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "archived_at: '2026-10-01T00:00:00Z'\n", encoding="utf-8")
    assert get(world, "/api/state")[0] == 403


def test_a_broken_workspace_file_closes_and_does_not_open(world):
    (world.root / "workflow" / "workspaces" / "home.yaml").write_text("{ not yaml", encoding="utf-8")
    assert get(world, "/api/state")[0] == 403


def test_a_page_of_a_person_cannot_touch_another_page(world):
    other = world.app.hub.add()
    status, _, _ = post(world, "/api/presence", {"client": other.id, "visible": False})
    assert status == 404 and other.visible
    world.app.hub.remove(other)


# ---------------------------------------------------------------- the guards: nothing new goes unclassified

def test_every_route_of_the_server_is_classified():
    text = (LIB / "server.py").read_text(encoding="utf-8")
    seen = set(re.findall(r'path == "(/api/[a-z_/-]+)"', text))
    assert seen, "the pattern no longer finds the routes"
    known = ac.PERSON_GET | ac.OWNER_GET | ac.PERSON_POST | ac.OWNER_POST | ac.PUBLIC
    assert seen - known == set()
    assert not (ac.PERSON_GET & ac.OWNER_GET) and not (ac.PERSON_POST & ac.OWNER_POST)


def test_every_verb_is_classified():
    assert set(ab.SPEC) - set(ac.PERSON_VERBS) - ac.OWNER_VERBS == set()
    assert set(ac.PERSON_VERBS) & ac.OWNER_VERBS == set()
    for verb, names in ac.PERSON_VERBS.items():
        assert names and set(names) <= set(ab.SPEC[verb]), verb


def test_every_event_is_classified():
    seen = set()
    for path in LIB.glob("*.py"):
        seen |= set(re.findall(r'broadcast\(\s*"([a-z_]+)"', path.read_text(encoding="utf-8")))
    assert seen, "the pattern no longer finds the events"
    assert seen - ac.PERSON_EVENTS - ac.OWNER_EVENTS == set()


def test_every_field_is_classified(world):
    state = world.app.state_payload()
    assert set(state) - ac.STATE_PERSON - set(ac.STATE_NEUTRAL) == set()
    model = state["model"]
    assert set(model) - ac.MODEL_FIELDS - set(ac.MODEL_NEUTRAL) - ac.MODEL_COUNTED - ac.MODEL_ROWS == set()
    row = rows_of(state)[0]
    assert set(row) - ac.ROW_FIELDS - set(ac.ROW_NEUTRAL) == set()
    detail = details.task_detail(world.root, "home-task", [])
    assert set(detail) - ac.TASK_FIELDS - set(ac.TASK_NEUTRAL) - ac.TASK_DROPPED == set()


# ---------------------------------------------------------------- members: on the workspace

def defs(**extra):
    return {"up": {"id": "up", "title": "Up", "area": "Up", **extra.get("up", {})},
            "down": {"id": "down", "title": "Down", "parent": "up", **extra.get("down", {})}}


def test_a_child_inherits_the_members_and_may_narrow_them():
    row = engine.effective(defs(up={"members": ["ann", "ben"]}), "down")
    assert row["members"] == ["ann", "ben"] and "members" in row["inherited"]
    narrow = defs(up={"members": ["ann", "ben"]}, down={"members": ["ann"]})
    assert engine.effective(narrow, "down")["members"] == ["ann"] and engine.rule_problems(narrow, "down") == []


def test_a_child_may_not_add_a_member_to_a_parent_that_names_some():
    wider = defs(up={"members": ["ann"]}, down={"members": ["ann", "ben"]})
    assert engine.rule_problems(wider, "down") == ["members ben are not on the parent"]


def test_under_a_parent_without_members_a_child_names_its_own_and_the_parent_stays_closed():
    own = defs(down={"members": ["ann"]})
    assert engine.rule_problems(own, "down") == [] and engine.effective(own, "up")["members"] == []


def test_members_need_an_area():
    assert engine.rule_problems({"x": {"id": "x", "members": ["ann"]}}, "x") == ["members need an area to open"]


@pytest.mark.parametrize("value", ["ann", ["Ann"], ["ann", "ann"], ["a b"], [1]])
def test_a_bad_list_of_members_fails(value):
    good = {"schema_version": 1, "id": "x", "title": "X"}
    assert engine._fallback_validate(good)[0] is True
    assert engine._fallback_validate({**good, "members": value})[0] is False
