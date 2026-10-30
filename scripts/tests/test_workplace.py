# SPDX-License-Identifier: MIT
"""Contract for scripts/workplace.py: plan the day's tabs from the tasks, act through a driver.

The plan (which task gets a tab, in which workspace, new or resumed) is CORE and
knows no terminal. Everything a terminal does goes through a driver command that
speaks JSON on stdin/stdout, the same shape as agents/_runtime/approval.py. With
no driver configured the built-in `none` driver prints what to start by hand, so
a Bridge without any multiplexer gets the same plan.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workplace", ROOT / "scripts" / "workplace.py")
assert spec is not None and spec.loader is not None
wp = importlib.util.module_from_spec(spec)
sys.modules["workplace"] = wp
sys.dont_write_bytecode = True
spec.loader.exec_module(wp)

TODAY = dt.date(2026, 10, 4)
CFG = {
    "workspaces": [
        {"name": "Bigcorp", "contexts": ["bigcorp"], "color": "#1565C0"},
        {"name": "Platform", "slugs": ["platform-*"]},
        {"name": "Misc", "default": True},
    ],
    "limits": {"max_workspaces": 2, "max_tabs": 2, "stale_days": 10, "activity_days": 7},
}


def task(root: Path, slug: str, **fm) -> None:
    d = root / "work" / "tasks" / slug
    d.mkdir(parents=True)
    fields = {"slug": slug, "status": "doing", "last_updated": "2026-10-03", **fm}
    body = "\n".join(f"{k}: {json.dumps(v) if isinstance(v, str) and ':' in v else v}" for k, v in fields.items())
    (d / "STATUS.md").write_text(f"---\n{body}\n---\n\n# {slug.replace('-', ' ').title()}\n", encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    task(tmp_path, "payments-incident", context="bigcorp", priority="P0")
    task(tmp_path, "bigcorp-report", context="bigcorp")
    task(tmp_path, "bigcorp-old", context="bigcorp", last_updated="2026-08-01")
    task(tmp_path, "platform-upgrade")
    task(tmp_path, "waiting-on-vendor", blocked_by="vendor answers")
    task(tmp_path, "parked", status="backlog")
    (tmp_path / "work" / "log.md").write_text(textwrap.dedent("""\
        | 2026-10-04 09:00 | 🐛 | bigcorp | payments-incident triaged |
        | 2026-10-04 10:00 | 🐛 | bigcorp | payments-incident fix on a branch |
        | 2026-10-03 10:00 | 📝 | bigcorp | bigcorp-report drafted |
        """), encoding="utf-8")
    return tmp_path


def test_plan_groups_tasks_into_workspaces_by_slug_then_context_then_default(repo):
    plan = wp.build_plan(repo, CFG, TODAY, wp.NoneDriver())
    names = [w["name"] for w in plan["workspaces"]]
    assert names[0] == "Bigcorp"
    bigcorp = plan["workspaces"][0]
    assert [t["slug"] for t in bigcorp["tabs"]] == ["payments-incident", "bigcorp-report"]
    assert "Platform" in names


def test_blocked_stale_and_backlog_get_no_tab(repo):
    plan = wp.build_plan(repo, CFG, TODAY, wp.NoneDriver())
    tabbed = {t["slug"] for w in plan["workspaces"] for t in w["tabs"]}
    assert "waiting-on-vendor" not in tabbed and "parked" not in tabbed and "bigcorp-old" not in tabbed
    assert [t["slug"] for t in plan["blocked"]] == ["waiting-on-vendor"]
    assert [t["slug"] for t in plan["stale"]] == ["bigcorp-old"]


def test_open_tab_from_the_driver_is_reused_and_a_known_session_is_resumed(repo):
    class Fake(wp.NoneDriver):
        def tabs(self):
            return [{"name": "payments-incident", "workspace": "Bigcorp", "ref": "s:1", "state": "waiting"}]

        def sessions(self):
            return {"bigcorp-report": "abc-123"}

    plan = wp.build_plan(repo, CFG, TODAY, Fake())
    tabs = {t["slug"]: t for t in plan["workspaces"][0]["tabs"]}
    assert tabs["payments-incident"]["action"] == "open"
    assert tabs["payments-incident"]["ref"] == "s:1"
    assert tabs["bigcorp-report"]["action"] == "resume"
    assert "abc-123" in tabs["bigcorp-report"]["command"]


def test_every_new_tab_carries_the_command_that_starts_its_agent(repo):
    plan = wp.build_plan(repo, CFG, TODAY, wp.NoneDriver())
    tab = plan["workspaces"][0]["tabs"][0]
    assert tab["action"] == "new"
    assert "payments-incident" in tab["command"] and "claude" in tab["command"]


def test_agent_command_is_configurable(repo):
    cfg = {**CFG, "agent": {"new": "codex {prompt}", "resume": "codex resume {session}"}}
    plan = wp.build_plan(repo, cfg, TODAY, wp.NoneDriver())
    assert plan["workspaces"][0]["tabs"][0]["command"].startswith("cd ")
    assert "codex " in plan["workspaces"][0]["tabs"][0]["command"]


def test_none_driver_opens_nothing_and_says_what_to_start(repo, capsys):
    plan = wp.build_plan(repo, CFG, TODAY, wp.NoneDriver())
    report = wp.NoneDriver().open(plan, only=None, resume=False, here=None)
    text = "\n".join(report)
    assert "payments-incident" in text and "no driver" in text.lower()


def test_command_driver_speaks_json_on_stdin_and_stdout(tmp_path):
    script = tmp_path / "driver.py"
    script.write_text(textwrap.dedent("""\
        import json, sys
        req = json.load(sys.stdin)
        if req["verb"] == "tabs":
            print(json.dumps({"tabs": [{"name": "x", "workspace": "W", "ref": "r", "state": "working"}]}))
        elif req["verb"] == "send":
            print(json.dumps({"report": ["sent " + req["text"] + " to " + req["tab"]]}))
        else:
            print(json.dumps({}))
        """))
    drv = wp.CommandDriver([sys.executable, str(script)])
    assert drv.tabs()[0]["state"] == "working"
    assert drv.send("x", "go on") == ["sent go on to x"]
    assert drv.sessions() == {}


def test_command_driver_failure_is_reported_not_raised(tmp_path):
    drv = wp.CommandDriver(["/definitely/not/here"])
    assert drv.tabs() == []
    assert "failed" in " ".join(drv.send("x", "y")).lower()


def test_driver_from_config():
    assert isinstance(wp.driver_from(None), wp.NoneDriver)
    assert isinstance(wp.driver_from("none"), wp.NoneDriver)
    assert isinstance(wp.driver_from({"command": ["true"]}), wp.CommandDriver)
    with pytest.raises(ValueError):
        wp.driver_from({"command": "not a list"})


def test_status_joins_driver_tabs_with_tasks_and_the_inbox(repo):
    class Fake(wp.NoneDriver):
        def tabs(self):
            return [{"name": "payments-incident", "workspace": "Bigcorp", "ref": "s:1", "state": "needs-you",
                     "last": "allow deploy?"}]

    rows = wp.status_rows(repo, CFG, Fake())
    assert rows[0]["slug"] == "payments-incident" and rows[0]["state"] == "needs-you"


def test_load_config_reads_the_workplace_block(tmp_path):
    (tmp_path / "bridge-config.yaml").write_text("workplace:\n  driver: none\n  limits: {max_tabs: 1}\n")
    cfg = wp.load_cfg(tmp_path)
    assert cfg["driver"] == "none" and cfg["limits"]["max_tabs"] == 1
    assert wp.load_cfg(tmp_path / "missing") == {}


def test_a_failed_driver_is_unknown_not_empty(tmp_path):
    drv = wp.CommandDriver(["/definitely/not/here"])
    assert drv.tabs_or_none() is None
    assert drv.sessions_or_none() is None


def test_plan_with_an_unknown_tab_view_says_so_and_refuses_to_open(repo):
    class Broken(wp.NoneDriver):
        name = "broken"

        def tabs_or_none(self):
            return None

    plan = wp.build_plan(repo, CFG, TODAY, Broken())
    assert plan["driver_error"]
    assert wp.main(["--root", str(repo), "open", "--yes"]) in (0, 1)   # smoke: never raises


def test_open_yes_is_refused_when_open_tabs_are_unknown(repo, capsys):
    (repo / "bridge-config.yaml").write_text("workplace:\n  driver: {command: ['/definitely/not/here']}\n")
    assert wp.main(["--root", str(repo), "open", "--yes"]) == 1
    assert "unknown" in capsys.readouterr().err.lower()


def test_status_prints_the_driver_error(repo, capsys):
    (repo / "bridge-config.yaml").write_text("workplace:\n  driver: {command: ['/definitely/not/here']}\n")
    assert wp.main(["--root", str(repo), "status"]) == 1
    assert "failed" in capsys.readouterr().err.lower()


def test_sessions_that_are_not_a_mapping_are_unknown(tmp_path):
    script = tmp_path / "d.py"
    script.write_text("import json,sys; json.load(sys.stdin); print(json.dumps({'sessions': ['x']}))")
    assert wp.CommandDriver([sys.executable, str(script)]).sessions_or_none() is None


def _scripted_driver(repo, tmp_path, answer: str, exit_code: int = 0):
    """A driver that lists no tabs and answers every other verb with `answer`."""
    script = tmp_path / "drv.py"
    script.write_text(
        "import json, sys\n"
        "req = json.load(sys.stdin)\n"
        "if req['verb'] == 'tabs':\n    print(json.dumps({'tabs': []})); sys.exit(0)\n"
        "if req['verb'] == 'sessions':\n    print(json.dumps({'sessions': {}})); sys.exit(0)\n"
        f"print({answer!r}); sys.exit({exit_code})\n")
    (repo / "bridge-config.yaml").write_text(
        f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n")


@pytest.mark.parametrize("answer, code, expected", [
    ('{"report": ["opened alpha"]}', 0, 0),
    ('{"report": ["opened alpha", "ERROR move alpha: refused"]}', 0, 1),
    ('{"error": "cmux refused"}', 1, 1),
])
def test_open_send_adopt_exit_non_zero_when_the_driver_failed(repo, tmp_path, answer, code, expected):
    """A workload or script must see the failure a person reads, not exit 0."""
    _scripted_driver(repo, tmp_path, answer, code)
    assert wp.main(["--root", str(repo), "open", "--yes"]) == expected
    assert wp.main(["--root", str(repo), "send", "some-tab", "hello"]) == expected


# ---------------------------------------------------------------- tasks

def test_tasks_list_every_active_task_with_area_priority_and_flags(repo):
    rows = {t["slug"]: t for t in wp.task_rows(repo, CFG, TODAY)}
    assert set(rows) == {"payments-incident", "bigcorp-report", "bigcorp-old", "platform-upgrade", "waiting-on-vendor"}
    pay = rows["payments-incident"]
    assert pay["area"] == "Bigcorp" and pay["priority"] == "P0" and pay["label"]
    # the full heading beside the short tab label, so a page can show the whole name
    assert pay["title"] and len(pay["title"]) >= len(pay["label"].rstrip("…"))
    assert pay["blocked_by"] is None and pay["stale"] is False and pay["score"] > rows["bigcorp-report"]["score"]
    assert rows["platform-upgrade"]["area"] == "Platform"
    assert rows["waiting-on-vendor"]["area"] == "Misc" and rows["waiting-on-vendor"]["blocked_by"] == "vendor answers"
    assert rows["bigcorp-old"]["stale"] is True
    assert rows["payments-incident"]["area_aliases"] == []


def test_tasks_carry_status_next_step_and_last_change(repo, tmp_path):
    task(tmp_path, "with-next", next="Call the vendor")
    d = tmp_path / "work" / "tasks" / "as-mapping"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: as-mapping\nstatus: review\nlast_updated: 2026-10-02\n"
                                 "next:\n  what: Merge the change\n  who: me\n---\n\n# As mapping\n", encoding="utf-8")
    rows = {t["slug"]: t for t in wp.task_rows(repo, CFG, TODAY)}
    assert (rows["with-next"]["next"], rows["with-next"]["status"], rows["with-next"]["updated"]) == \
        ("Call the vendor", "doing", "2026-10-03")
    assert (rows["as-mapping"]["next"], rows["as-mapping"]["status"]) == ("Merge the change", "review")
    assert rows["payments-incident"]["next"] is None


def test_tasks_name_the_aliases_of_their_area(repo):
    cfg = {"workspaces": [{"name": "Bigcorp", "contexts": ["bigcorp"], "aliases": ["BC", "Big"]}]}
    rows = {t["slug"]: t for t in wp.task_rows(repo, cfg, TODAY)}
    assert rows["payments-incident"]["area_aliases"] == ["BC", "Big"]


def test_an_area_in_the_status_head_wins_over_slugs_and_contexts(repo):
    task(repo, "platform-bigcorp-bridge", context="bigcorp", area="Misc")
    rows = {t["slug"]: t for t in wp.task_rows(repo, CFG, TODAY)}
    assert rows["platform-bigcorp-bridge"]["area"] == "Misc"


def test_an_area_names_its_workspace_by_alias_and_whatever_its_case(repo):
    cfg = {"workspaces": [{"name": "Bigcorp", "contexts": ["bigcorp"]},
                          {"name": "Platform", "slugs": ["platform-*"], "aliases": ["PF"]}]}
    task(repo, "bigcorp-by-alias", context="bigcorp", area="pf")
    task(repo, "bigcorp-by-name", context="bigcorp", area="platform")
    rows = {t["slug"]: t for t in wp.task_rows(repo, cfg, TODAY)}
    assert rows["bigcorp-by-alias"]["area"] == "Platform"
    assert rows["bigcorp-by-name"]["area"] == "Platform"


def test_an_unknown_area_falls_back_to_the_rules(repo):
    task(repo, "bigcorp-typo", context="bigcorp", area="Nowhere")
    rows = {t["slug"]: t for t in wp.task_rows(repo, CFG, TODAY)}
    assert rows["bigcorp-typo"]["area"] == "Bigcorp"


def test_tasks_json_is_sorted_by_priority_then_score(repo, capsys):
    (repo / "bridge-config.yaml").write_text("workplace:\n  workspaces: []\n")
    assert wp.main(["--root", str(repo), "tasks", "--json"]) == 0
    slugs = [t["slug"] for t in json.loads(capsys.readouterr().out)]
    assert slugs[0] == "payments-incident"


# ---------------------------------------------------------------- teams

def test_teams_ship_five_defaults_each_with_ordered_roles():
    teams = {t["id"]: t for t in wp.teams({})}
    assert set(teams) == {"build", "tdd", "research", "reply", "ops"}
    assert [r["id"] for r in teams["build"]["roles"]] == ["implement", "review"]
    assert [r["id"] for r in teams["tdd"]["roles"]] == ["tests", "implement", "review"]
    assert "feature" in teams["build"]["for_types"] and "research" in teams["research"]["for_types"]
    for t in teams.values():
        for r in t["roles"]:
            assert r["mode"] in ("report", "go") and r["brief"].isascii() and r["name"]


def test_team_and_role_names_come_from_config_and_teams_can_be_added():
    cfg = {"team_names": {"build": "Construct", "implement": "Coding"},
           "teams": {"docs": {"label": "Docs", "roles": [{"id": "write", "mode": "go", "brief": "Write it."}]}}}
    teams = {t["id"]: t for t in wp.teams(cfg)}
    assert teams["build"]["label"] == "Construct"
    assert teams["build"]["roles"][0]["name"] == "Coding"
    assert teams["tdd"]["roles"][1]["name"] == "Coding"           # a role name applies in every team
    assert teams["docs"]["roles"][0]["name"] == "write" and teams["docs"]["for_types"] == []


def test_launch_team_role_opens_a_named_tab_with_a_role_prompt(lrepo):
    cfg = {"team_names": {"review": "Check"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "report", team="build", role="review")
    assert e["label"] == "Payments Incident · Build Check"
    assert e["slug"] == "payments-incident--build-review" and e["role"] == "review" and e["team"] == "build"
    assert "-n payments-incident--build-review" in e["command"]
    assert "export BRIDGE_TAB_SLUG=payments-incident &&" in e["command"]
    cmd = e["command"]
    assert "team.md" in cmd and "review" in cmd and "work/tasks/payments-incident/STATUS.md" in cmd
    assert "Never close a tab or a workspace." in cmd


def test_launch_team_refuses_inbox_items_unknown_teams_and_roles(lrepo):
    out = wp.build_launch(lrepo, {}, [INBOX_ID], "go", team="build", role="implement")
    assert "error" in out[0] and "task" in out[0]["error"]
    (bad,) = wp.build_launch(lrepo, {}, ["payments-incident"], "go", team="nope", role="implement")
    assert "error" in bad
    (bad,) = wp.build_launch(lrepo, {}, ["payments-incident"], "go", team="build", role="nope")
    assert "error" in bad


def test_status_rows_name_the_team_role_of_a_tab(lrepo):
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": "Payments Incident · Build Review", "workspace": "W", "ref": "surface:1",
                            "state": "waiting"}]
    (row,) = wp.status_rows(lrepo, {}, driver)
    assert row["slug"] == "payments-incident" and row["team"] == "build" and row["role"] == "review"


def test_status_rows_tell_a_tdd_role_from_the_same_role_of_build(lrepo):
    # build and tdd both have implement and review; the tab must name its own team
    (e,) = wp.build_launch(lrepo, {}, ["payments-incident"], "go", team="tdd", role="implement")
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": e["label"], "workspace": "W", "ref": "surface:1", "state": "waiting"}]
    (row,) = wp.status_rows(lrepo, {}, driver)
    assert (row["slug"], row["team"], row["role"]) == ("payments-incident", "tdd", "implement")


@pytest.mark.parametrize("team, role", [("build", "review"), ("tdd", "implement")])
def test_status_rows_know_a_team_tab_by_the_session_name_the_tab_shows(lrepo, team, role):
    # claude -n <slug> titles the tab with the session slug once the agent runs
    (e,) = wp.build_launch(lrepo, {}, ["payments-incident"], "go", team=team, role=role)
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": e["slug"], "workspace": "W", "ref": "surface:1", "state": "waiting"}]
    (row,) = wp.status_rows(lrepo, {}, driver)
    assert (row["slug"], row["team"], row["role"]) == ("payments-incident", team, role)


def test_a_team_role_mode_shapes_its_prompt(lrepo):
    cfg = {"teams": {"pair": {"label": "Pair", "roles": [
        {"id": "a", "mode": "go", "brief": "Do it."}, {"id": "b", "mode": "report", "brief": "Do it."}]}}}
    (go,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "report", team="pair", role="a")
    (rep,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "report", team="pair", role="b")
    norm = lambda e: e["command"].replace("pair-a", "X").replace("pair-b", "X").replace(" a tab ", " X tab ") \
        .replace(" b tab ", " X tab ")
    assert norm(go) != norm(rep)
    assert "start on your part right away" in go["command"].lower()
    assert "at most eight lines" in rep["command"] and "right away" not in rep["command"]


def test_launch_says_that_mode_is_ignored_with_a_team(lrepo, capsys):
    # the role's mode decides; --mode next to --team is named as ignored, never applied silently
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--team", "build",
                    "--role", "review", "--mode", "go", "--json"]) == 0
    out = capsys.readouterr()
    assert "--mode is ignored with --team" in out.err
    (item,) = json.loads(out.out)["items"]
    assert "at most eight lines" in item["command"] and "right away" not in item["command"]


def test_tasks_carry_their_type(repo):
    (repo / "work" / "tasks" / "typed").mkdir(parents=True)
    (repo / "work" / "tasks" / "typed" / "STATUS.md").write_text(
        "---\nslug: typed\nstatus: doing\ntype: research\n---\n\n# Typed\n", encoding="utf-8")
    rows = {t["slug"]: t for t in wp.task_rows(repo, CFG, TODAY)}
    assert rows["typed"]["type"] == "research" and rows["payments-incident"]["type"] is None


def test_tasks_say_whether_they_are_a_stream(repo):
    d = repo / "work" / "streams" / "river"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: river\nstatus: doing\n---\n\n# River\n", encoding="utf-8")
    rows = {t["slug"]: t for t in wp.task_rows(repo, CFG, TODAY)}
    assert rows["river"]["kind"] == "streams" and rows["payments-incident"]["kind"] == "tasks"


def test_teams_json_and_launch_team_cli(lrepo, capsys):
    assert wp.main(["--root", str(lrepo), "teams", "--json"]) == 0
    assert {t["id"] for t in json.loads(capsys.readouterr().out)} >= {"build", "research"}
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--team", "build",
                    "--role", "implement", "--json"]) == 0
    (item,) = json.loads(capsys.readouterr().out)["items"]
    assert item["label"].endswith("· Build Implement")


# ---------------------------------------------------------------- launch

INBOX_ID = "20261006-1411-systems-remotes-buildhost-alpha-0855"


@pytest.fixture()
def lrepo(repo):
    d = repo / "work" / "streams" / "long-runner"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\nslug: long-runner\nstatus: doing\n---\n\n# Long runner\n", encoding="utf-8")
    for iid, state_events in ((INBOX_ID, []), ("20261006-1500-closed-thing-aaaa", ["close"])):
        idir = repo / "work" / "inbox" / iid
        idir.mkdir(parents=True)
        (idir / "item.yaml").write_text(
            "schema_version: 1\nkind: question\nsummary: x\ngate: free\nurgency: today\n"
            "created: '2026-10-06T14:11:00+02:00'\nfrom: test\n", encoding="utf-8")
        for i, verb in enumerate(state_events):
            ev = idir / "events"
            ev.mkdir(exist_ok=True)
            (ev / f"0{i}-{verb}.yaml").write_text(
                f"verb: {verb}\nby: t\nat: '2026-10-06T15:00:00+02:00'\n", encoding="utf-8")
    return repo


def test_launch_resolves_task_stream_inbox_and_unknown(lrepo):
    out = wp.build_launch(lrepo, {}, ["payments-incident", "long-runner", INBOX_ID, "nope", "20261006-1500-closed-thing-aaaa"],
                          "report")
    by = {e["item"]: e for e in out}
    assert by["payments-incident"]["kind"] == "task" and by["long-runner"]["kind"] == "task"
    assert by[INBOX_ID]["kind"] == "inbox"
    assert "error" in by["nope"] and "command" not in by["nope"]
    assert "error" in by["20261006-1500-closed-thing-aaaa"]    # closed is not open


@pytest.mark.parametrize("mode, team", [("report", None), ("go", None), ("go", "build")])
def test_task_tabs_file_their_result_in_the_inbox_linked_to_the_task(lrepo, mode, team):
    """What a tab achieves reaches anyone else only through the inbox."""
    (e,) = wp.build_launch(lrepo, {}, ["payments-incident"], mode, team=team, role="implement" if team else None)
    cmd = e["command"].replace("'\"'\"'", "'")
    assert "python3 scripts/inbox.py add --from tab:" in cmd and "--task payments-incident" in cmd
    assert "--key tab-payments-incident" in cmd and "--closer person" in cmd


def test_planned_tabs_file_their_result_too():
    tab = {"slug": "payments-incident", "action": "new", "status_path": "work/tasks/payments-incident/STATUS.md"}
    assert "--task payments-incident" in wp.tab_command(tab, Path("/r"), "/r", {})


def test_an_inbox_tab_that_only_reports_notes_its_finding_on_the_item(lrepo):
    (e,) = wp.build_launch(lrepo, {}, [INBOX_ID], "report")
    assert f"inbox.py note {INBOX_ID}" in e["command"]


@pytest.mark.parametrize("kind", ["task", "inbox"])
def test_context_mode_gathers_and_writes_back_with_sources(lrepo, kind):
    item = "payments-incident" if kind == "task" else INBOX_ID
    (e,) = wp.build_launch(lrepo, {}, [item], "context")
    cmd = e["command"]
    assert "missing context" in cmd and "source" in cmd and "work/log.md" in cmd
    if kind == "task":
        assert "task.py note payments-incident" in cmd
    else:
        assert f"inbox.py note {INBOX_ID}" in cmd
    assert "Never close a tab or a workspace." in cmd


@pytest.mark.parametrize("kind, mode", [("task", "report"), ("task", "go"), ("inbox", "report"), ("inbox", "go")])
def test_launch_prompts_are_ascii_and_name_the_item(kind, mode):
    p = wp.launch_prompt(kind, mode, "the-id", status_path="work/tasks/the-id/STATUS.md")
    assert p.isascii() and "the-id" in p and "Never close a tab or a workspace." in p
    if mode == "go":
        assert "right away" in p and "ask first" in p
    else:
        assert "wait" in p
    if kind == "inbox":
        assert "python3 scripts/inbox.py show the-id" in p
        assert "inbox.py close the-id --note" in p


def test_inbox_go_tab_reports_a_stop_on_the_item_and_honours_a_click_release():
    # live 2026-10-18: a reminder tab showed its draft only in its own chat, the cockpit saw no answer,
    # and it asked again for a yes the click on the GitHub row had already given
    p = wp.launch_prompt("inbox", "go", "the-id")
    assert "inbox.py note the-id" in p
    assert "unless the item itself says the click released" in p


def test_inbox_go_tab_closes_an_overtaken_item_itself():
    # live 2026-10-21: a go tab found its four decisions overtaken by a newer plan, noted that on the
    # item, then asked "close it?" because the item said gate: only-you / closer: person
    p = wp.launch_prompt("inbox", "go", "the-id")
    assert "already done, overtaken" in p and "without asking" in p
    assert "inbox.py reopen the-id" in p
    assert "already decided" in p and "name them in the close note" in p
    assert "closer: person" in p and "decide nothing new" in p


def test_inbox_report_tab_closes_only_an_overtaken_item():
    p = wp.launch_prompt("inbox", "report", "the-id")
    assert "already done, overtaken" in p and "inbox.py close the-id --note" in p
    assert "inbox.py reopen the-id" in p
    assert "Otherwise change nothing" in p and "wait" in p


def test_launch_task_report_prompt_is_exactly_the_open_prompt(lrepo):
    (e,) = wp.build_launch(lrepo, {}, ["payments-incident"], "report")
    status = "work/tasks/payments-incident/STATUS.md"
    expect = wp.NEW_TAB_PROMPT.format(slug="payments-incident", status_path=status,
                                      task_dir="work/tasks/payments-incident")
    assert expect in e["command"].replace("'\"'\"'", "'")
    assert e["command"].startswith(f"cd -- {lrepo} && export BRIDGE_TAB_SLUG=payments-incident && claude ")
    assert "-n payments-incident" in e["command"]


def test_launch_inbox_label_and_command(lrepo):
    (e,) = wp.build_launch(lrepo, {}, [INBOX_ID], "go")
    assert e["label"] == "Inbox systems-remotes-buildhost-0855"
    assert e["label"].startswith("Inbox systems-remotes") and len(e["label"]) <= len("Inbox ") + 30
    assert e["label"].isascii()
    assert INBOX_ID in e["command"]


def test_launch_labels_are_unique_within_one_launch(lrepo):
    cfg = {"tab_names": {"payments-incident": "Same", "bigcorp-report": "Same"}}
    out = wp.build_launch(lrepo, cfg, ["payments-incident", "bigcorp-report"], "report")
    labels = [e["label"] for e in out]
    assert len(set(labels)) == 2


def test_launch_uses_the_configured_agent_template(lrepo):
    cfg = {"agent": {"new": "codex -n {slug} {prompt}"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "report")
    assert "codex -n payments-incident" in e["command"]


def test_the_terminal_keys_and_their_text_rules_are_one_list_with_the_cockpit():
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.bridge_cockpit import actions_base as ab
    assert set(wp.TERM_KEYS) == set(ab.TERM_KEYS)
    assert {"enter", "escape", "tab", "shift+tab", "backspace", "up", "ctrl+c", "ctrl+z"} <= set(wp.TERM_KEYS)


@pytest.mark.parametrize("steps", [[{"key": "f13"}], [{"text": "a\x03"}], [{"paste": "a\x1b"}], [{"shell": "ls"}], [], "ls"])
def test_keys_never_reach_a_driver_outside_the_list(steps):
    with pytest.raises(ValueError):
        wp.check_steps(steps)


def test_keys_by_a_live_ref_ask_no_list_of_the_tabs(lrepo, monkeypatch, capsys):
    (lrepo / "bridge-config.yaml").write_text("workplace:\n  driver: {command: ['fake-driver']}\n")
    seen = []

    def fake_run(argv, input=None, **kw):
        req = json.loads(input)
        seen.append(req)
        return type("R", (), {"returncode": 0, "stdout": json.dumps({"report": ["1 steps"]}), "stderr": ""})()

    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    assert wp.main(["--root", str(lrepo), "keys", "surface:1", '[{"key": "enter"}]']) == 0
    assert seen == [{"verb": "keys", "tab": "surface:1", "keys": [{"key": "enter"}]}]
    assert wp.main(["--root", str(lrepo), "keys", "surface:1", "not json"]) == 2


def test_launch_dry_run_prints_and_hands_nothing_to_the_driver(lrepo, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(wp.NoneDriver, "launch", lambda *a, **k: calls.append(a) or [])
    assert wp.main(["--root", str(lrepo), "launch", "--items", f"payments-incident,{INBOX_ID}"]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "payments-incident" in out and INBOX_ID in out
    assert calls == []


def test_launch_unknown_item_fails_but_others_still_listed(lrepo, capsys):
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident,nope"]) == 1
    out = capsys.readouterr().out
    assert "payments-incident" in out and "nope" in out and "ERROR" in out


def test_launch_json_shape(lrepo, capsys):
    assert wp.main(["--root", str(lrepo), "launch", "--items", f"payments-incident,{INBOX_ID},nope", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["report"] == []
    items = {i["item"]: i for i in data["items"]}
    assert items["payments-incident"]["kind"] == "task" and items["payments-incident"]["command"]
    assert items[INBOX_ID]["kind"] == "inbox" and items[INBOX_ID]["label"]
    assert items["nope"]["error"]


def test_none_driver_launch_prints_the_commands(lrepo, capsys):
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "No driver configured" in out and "claude" in out


def test_command_driver_launch_payload_and_report(lrepo, monkeypatch, capsys):
    (lrepo / "bridge-config.yaml").write_text("workplace:\n  driver: {command: ['fake-driver']}\n")
    seen = []

    def fake_run(argv, input=None, **kw):
        req = json.loads(input)
        seen.append(req)
        out = {"report": ["tab X (surface:9)"]} if req["verb"] == "launch" else {}
        return type("R", (), {"returncode": 0, "stdout": json.dumps(out), "stderr": ""})()

    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    code = wp.main(["--root", str(lrepo), "launch", "--items", f"payments-incident,{INBOX_ID}", "--yes",
                    "--target", "workspace", "--here", "surface:3", "--mode", "go", "--json"])
    assert code == 0
    (req,) = [r for r in seen if r["verb"] == "launch"]
    assert req["target"] == "workspace" and req["here"] == "surface:3"
    assert [set(t) for t in req["tabs"]] == [{"label", "slug", "command", "workspace", "aliases"}] * 2
    assert "start on the next step right away" in req["tabs"][0]["command"]
    assert json.loads(capsys.readouterr().out)["report"] == ["tab X (surface:9)"]


def test_launch_entries_name_the_workspace_of_their_area(lrepo):
    """A task goes where workplace open would put it; an inbox item follows its task, else the default."""
    linked = lrepo / "work" / "inbox" / "20261006-1600-linked-thing-bbbb"
    linked.mkdir(parents=True)
    (linked / "item.yaml").write_text(
        "schema_version: 1\nkind: question\nsummary: x\ngate: free\ntask: payments-incident\n"
        "created: '2026-10-06T16:00:00+02:00'\nfrom: test\n", encoding="utf-8")
    out = wp.build_launch(lrepo, CFG, ["payments-incident", "platform-upgrade", INBOX_ID,
                                       "20261006-1600-linked-thing-bbbb"], "report")
    assert [e["workspace"] for e in out] == ["Bigcorp", "Platform", "Misc", "Bigcorp"]


def test_a_launch_follows_the_area_of_the_status_head_for_the_task_and_its_inbox_item(lrepo):
    task(lrepo, "bigcorp-but-misc", context="bigcorp", area="misc")
    linked = lrepo / "work" / "inbox" / "20261006-1700-linked-misc-cccc"
    linked.mkdir(parents=True)
    (linked / "item.yaml").write_text(
        "schema_version: 1\nkind: question\nsummary: x\ngate: free\ntask: bigcorp-but-misc\n"
        "created: '2026-10-06T17:00:00+02:00'\nfrom: test\n", encoding="utf-8")
    out = wp.build_launch(lrepo, CFG, ["bigcorp-but-misc", "20261006-1700-linked-misc-cccc"], "report")
    assert [e["workspace"] for e in out] == ["Misc", "Misc"]


def test_an_unlinked_inbox_item_goes_to_the_default_workspace_whatever_its_summary(lrepo):
    item = lrepo / "work" / "inbox" / "20261006-1700-platform-broke-cccc"
    item.mkdir(parents=True)
    (item / "item.yaml").write_text(
        "schema_version: 1\nkind: question\nsummary: platform broke\ngate: free\n"
        "created: '2026-10-06T17:00:00+02:00'\nfrom: test\n", encoding="utf-8")
    (e,) = wp.build_launch(lrepo, CFG, ["20261006-1700-platform-broke-cccc"], "report")
    assert e["workspace"] == "Misc"          # not "Platform" through the slug pattern platform-*


def test_launch_entries_carry_the_aliases_of_their_area(lrepo):
    cfg = {"workspaces": [{"name": "Bigcorp", "contexts": ["bigcorp"], "aliases": ["BC"]}]}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "report")
    assert e["aliases"] == ["BC"]


def test_launched_tabs_carry_their_slug_in_the_environment(lrepo):
    """A session can tell it was launched for one item (and stay quiet), whatever the agent template."""
    (task_entry, inbox_entry) = wp.build_launch(lrepo, {"agent": {"new": "codex {prompt}"}},
                                                ["payments-incident", INBOX_ID], "go")
    assert " && export BRIDGE_TAB_SLUG=payments-incident && codex " in task_entry["command"]
    assert f" && export BRIDGE_TAB_SLUG=inbox-{wp.inbox_slug(INBOX_ID)} && codex " in inbox_entry["command"]


@pytest.mark.parametrize("action", ["new", "resume"])
def test_planned_tabs_carry_their_slug_in_the_environment(action):
    tab = {"slug": "payments-incident", "action": action, "session_id": "s1",
           "status_path": "work/tasks/payments-incident/STATUS.md"}
    assert " && export BRIDGE_TAB_SLUG=payments-incident && claude " in wp.tab_command(tab, Path("/r"), "/r", {})


def test_launch_accepts_the_area_target(lrepo, monkeypatch):
    (lrepo / "bridge-config.yaml").write_text("workplace:\n  driver: {command: ['fake-driver']}\n")
    seen = []

    def fake_run(argv, input=None, **kw):
        seen.append(json.loads(input))
        return type("R", (), {"returncode": 0, "stdout": json.dumps({"report": ["tab X (surface:9)"]}),
                              "stderr": ""})()

    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes",
                    "--target", "area"]) == 0
    (req,) = [r for r in seen if r["verb"] == "launch"]
    assert req["target"] == "area"


def test_status_rows_name_the_open_inbox_item_of_a_launched_tab(lrepo):
    label = f"Inbox {wp.inbox_slug(INBOX_ID)}"
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": label, "workspace": "W", "ref": "surface:1", "state": "waiting"},
                           {"name": "Inbox closed-thing", "workspace": "W", "ref": "surface:2", "state": "working"}]
    rows = {r["ref"]: r for r in wp.status_rows(lrepo, {}, driver)}
    assert rows["surface:1"]["item"] == INBOX_ID
    # a tab whose item is closed still names it, so the cockpit can tell the tab is done and offer to close it
    assert rows["surface:2"]["item"] == "20261006-1500-closed-thing-aaaa"


def test_status_rows_prefer_the_open_item_when_a_closed_one_has_the_same_label(lrepo):
    closed = lrepo / "work" / "inbox" / "20261006-1500-closed-thing-aaaa"
    twin = lrepo / "work" / "inbox" / "20261008-0900-closed-thing-bbbb"
    twin.mkdir(parents=True)
    (twin / "item.yaml").write_text((closed / "item.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": "Inbox closed-thing", "workspace": "W", "ref": "surface:2", "state": "working"}]
    (row,) = wp.status_rows(lrepo, {}, driver)
    assert row["item"] == "20261008-0900-closed-thing-bbbb"


def test_status_rows_keep_the_slug_of_a_task_that_moved_to_done(lrepo):
    done = lrepo / "work" / "done" / "2026-10" / "finished-task"
    done.mkdir(parents=True)
    (done / "STATUS.md").write_text("---\nslug: finished-task\nstatus: done\n---\n\n# Finished\n", encoding="utf-8")
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": "finished-task", "workspace": "W", "ref": "surface:3", "state": "waiting"}]
    (row,) = wp.status_rows(lrepo, {}, driver)
    assert row["slug"] == "finished-task"


def test_command_driver_launch_error_line_fails_the_run(lrepo, monkeypatch):
    (lrepo / "bridge-config.yaml").write_text("workplace:\n  driver: {command: ['fake-driver']}\n")
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: type(
        "R", (), {"returncode": 0, "stdout": json.dumps({"report": ["ERROR no caller"]}), "stderr": ""})())
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes"]) == 1


def test_find_tab_takes_the_live_ref_before_name_or_slug():
    tabs = [{"name": "Claude Code", "ref": "surface:7"}, {"name": "Claude Code", "ref": "surface:9"}]
    assert wp.find_tab(tabs, "surface:9", {})["ref"] == "surface:9"
    with pytest.raises(LookupError):
        wp.find_tab(tabs, "Claude Code", {})


def test_inbox_slug_keeps_two_items_with_the_same_words_apart():
    a = wp.inbox_slug("20261007-0634-vendor-rejects-inbound-webhooks-8dcc")
    b = wp.inbox_slug("20261007-1232-vendor-rejects-inbound-webhook-at-d147")
    assert a != b and len(a) <= wp.INBOX_LABEL_MAX and len(b) <= wp.INBOX_LABEL_MAX


def test_status_rows_find_the_item_by_the_session_name_the_tab_shows(lrepo):
    # claude -n <slug> titles the tab with the slug, not with the "Inbox …" label
    driver = wp.NoneDriver()
    driver.tabs = lambda: [{"name": f"inbox-{wp.inbox_slug(INBOX_ID)}", "workspace": "W", "ref": "surface:1",
                            "state": "waiting"}]
    (row,) = wp.status_rows(lrepo, {}, driver)
    assert row["item"] == INBOX_ID


ROUTE_CFG = {"workspaces": [{"name": "Bigcorp", "description": "company"}, {"name": "Misc", "default": True}]}


def _router(answer: str) -> dict:
    return {**ROUTE_CFG, "router": {"command": [sys.executable, "-c", f"import sys; sys.stdin.read(); print({answer!r})"]}}


def test_route_lets_the_router_pick_area_and_own_workspace(lrepo):
    entries = wp.build_launch(lrepo, ROUTE_CFG, [INBOX_ID, "payments-incident"], "go")
    answer = json.dumps([{"item": INBOX_ID, "workspace": "Bigcorp", "own": False, "why": "company system"},
                         {"item": "payments-incident", "workspace": "Misc", "own": True, "why": "large"}])
    routed = {e["item"]: e for e in wp.route(lrepo, _router(answer), entries)}
    assert routed[INBOX_ID]["workspace"] == "Bigcorp" and routed[INBOX_ID]["own"] is False
    assert routed["payments-incident"]["own"] is True


def test_route_keeps_the_rules_when_the_router_names_no_known_area_or_fails(lrepo):
    entries = wp.build_launch(lrepo, ROUTE_CFG, [INBOX_ID], "go")
    before = entries[0]["workspace"]
    bad = wp.route(lrepo, _router('[{"item": "%s", "workspace": "Mars", "own": true}]' % INBOX_ID), entries)
    assert bad[0]["workspace"] == before and bad[0]["own"] is False
    junk = wp.route(lrepo, _router("no json here"), entries)
    assert junk[0]["workspace"] == before
    assert wp.route(lrepo, ROUTE_CFG, entries)[0]["workspace"] == before   # no router configured


def test_the_router_sees_the_task_heading_when_there_is_no_headline(lrepo):
    line = wp._describe(lrepo, "payments-incident")
    assert "Payments Incident" in line and "context bigcorp" in line
    (lrepo / "work/tasks/platform-upgrade/STATUS.md").write_text(
        "---\nslug: platform-upgrade\nstatus: doing\n---\n\n# <Task Title>\n", encoding="utf-8")
    assert "<Task Title>" not in wp._describe(lrepo, "platform-upgrade")


@pytest.mark.parametrize("target, where", [("tab", "-> this workspace"), ("workspace", "-> new workspace"),
                                           ("area", "-> Bigcorp")])
def test_a_launch_dry_run_says_where_each_tab_would_go(lrepo, monkeypatch, capsys, target, where):
    monkeypatch.setattr(wp, "load_cfg", lambda root: CFG)
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--target", target]) == 0
    assert f"Payments Incident {where}" in capsys.readouterr().out


def test_an_auto_dry_run_shows_the_router_answer_and_json_keeps_own_and_why(lrepo, monkeypatch, capsys):
    answer = json.dumps([{"item": INBOX_ID, "workspace": "Bigcorp", "own": False, "why": "company system"},
                         {"item": "payments-incident", "workspace": "Misc", "own": True, "why": "large"}])
    monkeypatch.setattr(wp, "load_cfg", lambda root: _router(answer))
    assert wp.main(["--root", str(lrepo), "launch", "--items", f"{INBOX_ID},payments-incident",
                    "--target", "auto"]) == 0
    out = capsys.readouterr().out
    assert "-> Bigcorp (router: company system)" in out
    assert "Payments Incident -> new workspace (router: large)" in out
    assert wp.main(["--root", str(lrepo), "launch", "--items", f"{INBOX_ID},payments-incident",
                    "--target", "auto", "--json"]) == 0
    items = {i["item"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert items["payments-incident"]["own"] is True and items["payments-incident"]["why"] == "large"
    assert items[INBOX_ID]["own"] is False and items[INBOX_ID]["why"] == "company system"


def test_launch_auto_opens_own_workspaces_and_area_tabs_in_two_calls(lrepo, monkeypatch):
    answer = json.dumps([{"item": INBOX_ID, "workspace": "Bigcorp", "own": False},
                         {"item": "payments-incident", "workspace": "Misc", "own": True}])
    cfg = _router(answer)
    monkeypatch.setattr(wp, "load_cfg", lambda root: cfg)
    calls = []

    class Fake(wp.NoneDriver):
        def launch(self, tabs, target, here=None):
            calls.append((target, [t["item"] for t in tabs]))
            return [f"{target} ok"]

    monkeypatch.setattr(wp, "driver_from", lambda spec: Fake())
    assert wp.main(["--root", str(lrepo), "launch", "--items", f"{INBOX_ID},payments-incident", "--yes",
                    "--target", "auto"]) == 0
    assert sorted(calls) == [("area", [INBOX_ID]), ("workspace", ["payments-incident"])]


# ---------------------------------------------------------------- launch never opens an agent twice

def _tab_driver(tabs: list, calls: list):
    class Fake(wp.NoneDriver):
        def tabs(self):
            return tabs

        def launch(self, batch, target, here=None):
            calls.append([t["item"] for t in batch])
            return [f"tab {t['label']} (surface:70)" for t in batch]
    return Fake()


@pytest.mark.parametrize("state, opened", [("waiting", False), ("working", False), ("needs-you", False),
                                           ("shell", True)])
def test_launch_skips_an_item_whose_agent_tab_is_open(lrepo, monkeypatch, capsys, state, opened):
    label = wp.build_launch(lrepo, {}, ["payments-incident"], "go")[0]["label"]
    calls: list = []
    open_tabs = [{"name": label, "workspace": "Bigcorp", "ref": "surface:9", "state": state}]
    monkeypatch.setattr(wp, "driver_from", lambda spec: _tab_driver(open_tabs, calls))
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    (item,) = data["items"]
    if opened:      # a tab in state shell holds no agent: the command never ran, or the agent ended
        assert calls == [["payments-incident"]] and "skipped" not in item
    else:
        assert calls == [] and item["skipped"] == "open" and item["ref"] == "surface:9"
        assert any("already open" in line and "surface:9" in line for line in data["report"])


def test_launch_again_opens_a_second_tab_on_purpose(lrepo, monkeypatch, capsys):
    label = wp.build_launch(lrepo, {}, ["payments-incident"], "go")[0]["label"]
    calls: list = []
    open_tabs = [{"name": label, "workspace": "Bigcorp", "ref": "surface:9", "state": "waiting"}]
    monkeypatch.setattr(wp, "driver_from", lambda spec: _tab_driver(open_tabs, calls))
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes", "--again"]) == 0
    assert calls == [["payments-incident"]]


def test_launch_skips_an_open_inbox_tab_but_opens_the_rest(lrepo, monkeypatch, capsys):
    calls: list = []
    open_tabs = [{"name": f"Inbox {wp.inbox_slug(INBOX_ID)}", "workspace": "W", "ref": "surface:4", "state": "working"}]
    monkeypatch.setattr(wp, "driver_from", lambda spec: _tab_driver(open_tabs, calls))
    assert wp.main(["--root", str(lrepo), "launch", "--items", f"{INBOX_ID},payments-incident", "--yes",
                    "--json"]) == 0
    assert calls == [["payments-incident"]]
    items = {i["item"]: i for i in json.loads(capsys.readouterr().out)["items"]}
    assert items[INBOX_ID]["skipped"] == "open" and "skipped" not in items["payments-incident"]


def test_a_team_role_tab_counts_only_for_its_own_role(lrepo, monkeypatch, capsys):
    (impl,) = wp.build_launch(lrepo, {}, ["payments-incident"], "go", team="build", role="implement")
    calls: list = []
    open_tabs = [{"name": impl["label"], "workspace": "Bigcorp", "ref": "surface:5", "state": "waiting"}]
    monkeypatch.setattr(wp, "driver_from", lambda spec: _tab_driver(open_tabs, calls))
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes",
                    "--team", "build", "--role", "review"]) == 0
    assert calls == [["payments-incident"]]
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--yes",
                    "--team", "build", "--role", "implement"]) == 0
    assert calls == [["payments-incident"]]


def test_the_router_gets_a_short_budget_so_a_click_never_outlasts_the_dashboard(lrepo, monkeypatch):
    seen = {}

    def fake_run(argv, input=None, **kw):
        seen["timeout"] = kw.get("timeout")
        raise wp.subprocess.TimeoutExpired(argv, kw.get("timeout"))

    entries = wp.build_launch(lrepo, ROUTE_CFG, [INBOX_ID], "go")
    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    routed = wp.route(lrepo, _router("[]"), entries)
    assert seen["timeout"] <= 45 and routed[0]["workspace"] == entries[0]["workspace"]


# ---------------------------------------------------------------- the optional verbs: caps, focus, key, screen, close

FULL_DRIVER = """\
import json, sys
req = json.load(sys.stdin)
v = req["verb"]
if v == "tabs":
    print(json.dumps({"tabs": [{"name": "alpha", "workspace": "W", "ref": "%3", "state": "needs-you", "last": "Allow?"}]}))
elif v == "sessions":
    print(json.dumps({"sessions": {}}))
elif v == "caps":
    print(json.dumps({"caps": ["tabs", "sessions", "send", "focus", "key", "screen", "close"]}))
elif v == "screen":
    print(json.dumps({"text": "line " + req["tab"] + " " + str(req["lines"])}))
elif v in ("focus", "key", "close"):
    print(json.dumps({"report": [v + " " + req["tab"] + (" " + req["key"] if v == "key" else "")]}))
else:
    print(json.dumps({"report": ["ERROR unknown verb " + v]})); sys.exit(1)
"""


def test_the_optional_verbs_go_through_the_driver(tmp_path):
    script = tmp_path / "driver.py"
    script.write_text(FULL_DRIVER)
    drv = wp.CommandDriver([sys.executable, str(script)])
    assert drv.caps() == ["tabs", "sessions", "send", "focus", "key", "screen", "close"]
    assert drv.focus("%3") == ["focus %3"]
    assert drv.key("%3", "escape") == ["key %3 escape"]
    assert drv.screen("%3", 40) == "line %3 40"
    assert drv.close("%3") == ["close %3"]


def test_a_driver_without_caps_serves_the_six_base_verbs(tmp_path):
    script = tmp_path / "driver.py"
    script.write_text("import json, sys\nprint(json.dumps({}))\n")
    assert wp.CommandDriver([sys.executable, str(script)]).caps() == list(wp.BASE_CAPS)
    assert wp.NoneDriver().caps() == []
    assert wp.NoneDriver().screen("x", 10) is None
    assert "no driver" in wp.NoneDriver().focus("x")[0].lower()


def test_a_key_outside_the_known_ones_is_refused_before_the_driver(tmp_path):
    script = tmp_path / "driver.py"
    script.write_text(FULL_DRIVER)
    drv = wp.CommandDriver([sys.executable, str(script)])
    out = drv.key("%3", "ctrl-c")
    assert out[0].startswith("ERROR") and drv.failed


def test_the_cli_runs_the_optional_verbs(repo, tmp_path, capsys):
    script = tmp_path / "driver.py"
    script.write_text(FULL_DRIVER)
    (repo / "bridge-config.yaml").write_text(f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n")
    assert wp.main(["--root", str(repo), "caps", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"caps": ["tabs", "sessions", "send", "focus", "key", "screen", "close"]}
    assert wp.main(["--root", str(repo), "key", "%3", "1"]) == 0
    assert capsys.readouterr().out.strip() == "key %3 1"
    assert wp.main(["--root", str(repo), "screen", "%3", "--lines", "5", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"text": "line %3 5"}
    assert wp.main(["--root", str(repo), "focus", "%3"]) == 0 and wp.main(["--root", str(repo), "close", "%3"]) == 0


@pytest.mark.parametrize("asked, read", [(5, 5), (3000, 3000), (5000, 5000), (99999, 5000), (0, 1)])
def test_screen_asks_the_driver_for_at_most_five_thousand_lines(repo, tmp_path, capsys, asked, read):
    script = tmp_path / "driver.py"
    script.write_text(FULL_DRIVER)
    (repo / "bridge-config.yaml").write_text(f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n")
    assert wp.main(["--root", str(repo), "screen", "%3", "--lines", str(asked), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"text": f"line %3 {read}"}


def test_a_resume_reopens_one_task_session_in_its_own_folder(lrepo):
    sid = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"
    cfg = {"agent": {"resume": "claude --resume {session} --model sonnet"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", resume=sid, resume_cwd="/tmp/some where")
    assert e["kind"] == "task" and e["resume"] == sid
    assert e["command"] == (f"cd -- '/tmp/some where' && export {wp.TAB_ENV}=payments-incident && "
                            f"claude --resume {sid} --model sonnet")
    (bad,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", resume="not-a-session")
    assert "error" in bad


# ---------------------------------------------------------------- model and effort of a launch

def test_launch_without_a_model_keeps_the_command_of_today(lrepo):
    (e,) = wp.build_launch(lrepo, {}, ["payments-incident"], "report")
    assert "--model" not in e["command"] and "--effort" not in e["command"]
    assert "model" not in e and "effort" not in e


def test_launch_model_and_effort_are_appended_to_a_claude_template(lrepo):
    (e,) = wp.build_launch(lrepo, {}, ["payments-incident"], "go", model="opus", effort="high")
    assert e["command"].endswith("--model claude-opus-5-5 --effort high")
    assert (e["model"], e["effort"]) == ("claude-opus-5-5", "high")


def test_launch_fills_model_and_effort_slots_and_drops_an_empty_slot_with_its_flag(lrepo):
    cfg = {"agent": {"new": "claude --model {model} --effort {effort} -n {slug} {prompt}",
                     "resume": "claude --resume {session} --model {model}"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", model="haiku")
    assert "claude --model claude-haiku-5-5 -n payments-incident" in e["command"]
    assert "{effort}" not in e["command"] and "--effort" not in e["command"]
    (bare,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go")
    assert "--model" not in bare["command"] and "{" not in bare["command"].split("&&")[-1].split("'")[0]
    sid = "0b8a3c1e-1111-4222-8333-944455556666"
    (r,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", resume=sid, model="sonnet")
    assert r["command"].endswith(f"claude --resume {sid} --model claude-sonnet-5-5")


def test_a_model_fixed_in_the_template_wins_and_says_so(lrepo):
    cfg = {"agent": {"new": "claude --model sonnet -n {slug} {prompt}"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", model="opus", effort="low")
    assert "claude-opus-5-5" not in e["command"] and e["command"].endswith("--effort low")
    assert e["model"] is None and "agent template" in e["pick_note"]


def test_another_agent_than_claude_gets_no_claude_flags(lrepo):
    cfg = {"agent": {"new": "codex {prompt}"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", model="opus", effort="high")
    assert "--model" not in e["command"] and "--effort" not in e["command"]
    assert e["model"] is None and e["effort"] is None and "not claude" in e["pick_note"]


def test_the_open_plan_fills_an_empty_model_slot(repo):
    cfg = {**CFG, "agent": {"new": "claude --model {model} -n {slug} {prompt}"}}
    tab = {"action": "new", "slug": "payments-incident", "status_path": "work/tasks/payments-incident/STATUS.md"}
    run = wp.tab_command(tab, repo, str(repo), cfg)
    assert "{model}" not in run and "--model" not in run


def test_launch_cli_takes_model_and_effort_and_refuses_others(lrepo, capsys):
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--model", "sonnet",
                    "--effort", "xhigh", "--json"]) == 0
    (item,) = json.loads(capsys.readouterr().out)["items"]
    assert (item["model"], item["effort"]) == ("claude-sonnet-5-5", "xhigh")
    for bad in (["--model", "gpt-5"], ["--effort", "max"]):
        with pytest.raises(SystemExit):
            wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", *bad])


def test_the_agent_block_names_the_model_and_effort_when_a_launch_asks_for_none(lrepo, repo):
    cfg = {"agent": {"new": "claude --model {model} -n {slug} {prompt}", "model": "sonnet", "effort": "high"}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go")
    assert "claude --model claude-sonnet-5-5 -n payments-incident" in e["command"] and e["command"].endswith("--effort high")
    (asked,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go", model="opus", effort="low")
    assert "--model claude-opus-5-5" in asked["command"] and asked["command"].endswith("--effort low")
    tab = {"action": "new", "slug": "payments-incident", "status_path": "work/tasks/payments-incident/STATUS.md"}
    assert "--model claude-sonnet-5-5" in wp.tab_command(tab, repo, str(repo), {**CFG, **cfg})


@pytest.mark.parametrize("agent", [{"model": "gpt-5"}, {"effort": "max"}, {"model": 3}])
def test_a_bad_agent_default_is_left_out(lrepo, agent):
    cfg = {"agent": {"new": "claude -n {slug} {prompt}", **agent}}
    (e,) = wp.build_launch(lrepo, cfg, ["payments-incident"], "go")
    assert "--model" not in e["command"] and "--effort" not in e["command"]


def test_workspaces_come_from_a_driver_that_serves_them(repo, capsys):
    script = repo / "d.py"
    script.write_text(textwrap.dedent("""\
        import json, sys
        req = json.load(sys.stdin)
        if req["verb"] == "caps":
            print(json.dumps({"caps": ["tabs", "workspaces"]}))
        elif req["verb"] == "workspaces":
            print(json.dumps({"workspaces": [{"ref": "w:1", "title": "Bigcorp", "cwd": "/x"}, "junk"]}))
        """))
    (repo / "bridge-config.yaml").write_text(f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n")
    assert wp.main(["--root", str(repo), "workspaces", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"ref": "w:1", "title": "Bigcorp", "cwd": "/x"}]


def test_workspaces_without_a_driver_that_serves_them_are_refused(repo, capsys):
    assert wp.main(["--root", str(repo), "workspaces", "--json"]) == 2
    assert "workspaces" in capsys.readouterr().err


# ---------------------------------------------------------------- rename a tab or a workspace

RENAME_TABS = [
    {"name": "Payments Incident", "workspace": "Bigcorp", "ref": "surface:4", "ws_ref": "workspace:1", "state": "waiting"},
    {"name": "user@host:~", "workspace": "Scratch", "ref": "surface:5", "ws_ref": "workspace:2", "state": "shell"},
    {"name": "Notes", "workspace": "Scratch", "ref": "surface:6", "ws_ref": "workspace:2", "state": "waiting"},
    {"name": "surface:5", "workspace": "Scratch", "ref": "surface:7", "ws_ref": "workspace:2", "state": "shell"},
]


def _rename_driver(repo, tmp_path, tabs=RENAME_TABS, workspaces=None, extra_cfg: str = "") -> Path:
    """A driver that lists `tabs` (and `workspaces` when given), records every request and renames"""
    log = tmp_path / "requests.jsonl"
    script = tmp_path / "rename_driver.py"
    script.write_text(textwrap.dedent(f"""\
        import json, sys
        req = json.load(sys.stdin)
        with open({str(log)!r}, "a") as f:
            f.write(json.dumps(req) + "\\n")
        v = req["verb"]
        if v == "tabs":
            print(json.dumps({{"tabs": {tabs!r}}}))
        elif v == "sessions":
            print(json.dumps({{"sessions": {{}}}}))
        elif v == "caps":
            print(json.dumps({{"caps": ["tabs", "sessions", "rename", "rename_workspace"]
                                        + (["workspaces"] if {workspaces is not None!r} else [])}}))
        elif v == "workspaces":
            print(json.dumps({{"workspaces": {workspaces or []!r}}}))
        elif v == "rename":
            print(json.dumps({{"report": [req["tab"] + " is now named " + req["title"]]}}))
        elif v == "rename_workspace":
            print(json.dumps({{"report": [req["workspace"] + " is now named " + req["title"]]}}))
        else:
            print(json.dumps({{"error": "unknown verb " + v}})); sys.exit(1)
        """))
    (repo / "bridge-config.yaml").write_text(
        f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n"
        "  control: {name: Control}\n"
        "  workspaces:\n    - {name: Bigcorp, contexts: [bigcorp], aliases: [bc]}\n    - {name: Misc, default: true}\n"
        + extra_cfg)
    return log


def _requests(log: Path, verb: str) -> list:
    if not log.exists():
        return []
    return [r for r in map(json.loads, log.read_text().splitlines()) if r["verb"] == verb]


def test_command_driver_sends_the_rename_workspace_payload(tmp_path):
    log = tmp_path / "req.json"
    script = tmp_path / "d.py"
    script.write_text("import json, sys\nreq = json.load(sys.stdin)\nopen(%r, 'w').write(json.dumps(req))\n"
                      "print(json.dumps({'report': ['renamed']}))\n" % str(log))
    drv = wp.CommandDriver([sys.executable, str(script)])
    assert drv.rename_workspace("workspace:2", "Research") == ["renamed"] and not drv.failed
    assert json.loads(log.read_text()) == {"verb": "rename_workspace", "workspace": "workspace:2", "title": "Research"}


def test_none_driver_rename_workspace_says_do_it_yourself():
    (line,) = wp.NoneDriver().rename_workspace("workspace:2", "Research")
    assert "no driver" in line.lower() and "Research" in line


def test_managed_names_cover_task_inbox_and_team_tabs_and_configured_workspaces(lrepo):
    cfg = {"control": {"name": "Control"},
           "workspaces": [{"name": "Bigcorp", "aliases": ["bc"]}, {"name": "Misc", "default": True}]}
    names = wp.managed_names(lrepo, cfg)
    assert {"payments-incident", "payments incident", "long-runner"} <= names["tab_names"]
    assert any(n.startswith("inbox ") for n in names["tab_names"])
    assert any(" · build implement" in n for n in names["tab_names"])
    assert names["workspace_names"] == {"bigcorp", "bc", "misc", "control"}


def test_cli_rename_takes_an_exact_ref_and_refuses_a_name(repo, tmp_path, capsys):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename", "surface:5", "--", "Scratch pad"]) == 0
    assert _requests(log, "rename") == [{"verb": "rename", "tab": "surface:5", "title": "Scratch pad"}]
    assert "surface:5 is now named Scratch pad" in capsys.readouterr().out
    # a name, a part of one, or a ref that is not open never lands on a tab found by name
    for ref in ("Notes", "note", "surface:99"):
        assert wp.main(["--root", str(repo), "rename", ref, "--", "Other"]) == 2
    assert len(_requests(log, "rename")) == 1
    assert "no open tab" in capsys.readouterr().err


def test_cli_rename_takes_a_title_starting_with_a_dash_after_double_dash(repo, tmp_path):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename", "surface:5", "--", "--draft notes"]) == 0
    assert _requests(log, "rename")[0]["title"] == "--draft notes"


@pytest.mark.parametrize("title", ["Payments Incident", "payments-incident", "PAYMENTS INCIDENT", "notes", " Notes "])
def test_cli_rename_refuses_a_managed_or_used_tab_name(repo, tmp_path, capsys, title):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename", "surface:5", "--", title]) == 2
    assert _requests(log, "rename") == []
    assert "refused" in capsys.readouterr().err


def test_cli_rename_keeps_a_tab_s_own_name_free_for_itself(repo, tmp_path):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename", "surface:6", "--", "notes"]) == 0
    assert len(_requests(log, "rename")) == 1


@pytest.mark.parametrize("ws_ref, title, why", [
    ("workspace:1", "Payments", "configured workspace"),      # the current title is configured
    ("workspace:2", "Bigcorp", "configured workspace"),       # the new title is configured
    ("workspace:2", "BC", "configured workspace"),            # an alias
    ("workspace:2", "control", "configured workspace"),       # the control workspace's name
    ("workspace:2", "Misc", "configured workspace"),
])
def test_cli_rename_workspace_refuses_a_configured_workspace_and_a_configured_new_name(repo, tmp_path, capsys,
                                                                                      ws_ref, title, why):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename-workspace", ws_ref, "--", title]) == 2
    assert _requests(log, "rename_workspace") == []
    assert f"refused: {why}, rename it in workplace.workspaces" in capsys.readouterr().err


def test_cli_rename_workspace_refuses_a_name_another_workspace_has(repo, tmp_path, capsys):
    workspaces = [{"ref": "workspace:2", "title": "Scratch"}, {"ref": "workspace:9", "title": "Research"}]
    log = _rename_driver(repo, tmp_path, workspaces=workspaces)
    assert wp.main(["--root", str(repo), "rename-workspace", "workspace:2", "--", "research"]) == 2
    assert "refused: name in use" in capsys.readouterr().err
    assert _requests(log, "rename_workspace") == []


def test_cli_rename_workspace_finds_the_title_from_tabs_by_ws_ref(repo, tmp_path, capsys):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename-workspace", "workspace:2", "--", "Research"]) == 0
    assert _requests(log, "rename_workspace") == [{"verb": "rename_workspace", "workspace": "workspace:2",
                                                    "title": "Research"}]
    # without a tab in it, the driver's own workspace list names it; without either the ref is unknown
    second = tmp_path / "second"
    second.mkdir()
    log2 = _rename_driver(repo, second, tabs=[], workspaces=[{"ref": "workspace:8", "title": "Empty"}])
    assert wp.main(["--root", str(repo), "rename-workspace", "workspace:8", "--", "Research"]) == 0
    assert _requests(log2, "rename_workspace")[0]["workspace"] == "workspace:8"
    assert wp.main(["--root", str(repo), "rename-workspace", "workspace:77", "--", "Research"]) == 2
    assert "no open workspace" in capsys.readouterr().err


@pytest.mark.parametrize("title", ["", "   ", "x" * 81, "bad\x07bell", "two\nlines", "tab\there"])
def test_cli_rename_refuses_empty_long_and_control_character_titles(repo, tmp_path, capsys, title):
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename", "surface:5", "--", title]) == 2
    assert wp.main(["--root", str(repo), "rename-workspace", "workspace:2", "--", title]) == 2
    assert _requests(log, "rename") == [] and _requests(log, "rename_workspace") == []


def test_cli_rename_refuses_a_tab_the_workplace_knows_by_its_name(repo, tmp_path, capsys):
    """a task, inbox or team tab keeps its name: renamed, the status rows would lose its task"""
    log = _rename_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "rename", "surface:4", "--", "Something else"]) == 2
    assert _requests(log, "rename") == []
    assert "refused: a task, inbox or team tab keeps its name" in capsys.readouterr().err


def test_cli_rename_workspace_takes_a_listed_workspace_without_a_title(repo, tmp_path):
    """the driver lists the ref, so it is live, even without a title and without a tab in it"""
    log = _rename_driver(repo, tmp_path, tabs=[], workspaces=[{"ref": "workspace:8"}])
    assert wp.main(["--root", str(repo), "rename-workspace", "workspace:8", "--", "Research"]) == 0
    assert _requests(log, "rename_workspace")[0]["workspace"] == "workspace:8"


# ---------------------------------------------------------------- move a tab, colour and describe a workspace

LAYOUT_TABS = [
    {"name": "Scratch", "workspace": "Scratch", "ref": "surface:5", "ws_ref": "workspace:2", "state": "shell"},
    {"name": "Notes", "workspace": "Scratch", "ref": "surface:6", "ws_ref": "workspace:2", "state": "waiting"},
    {"name": "Research", "workspace": "Research", "ref": "surface:8", "ws_ref": "workspace:3", "state": "shell"},
    {"name": "Payments Incident", "workspace": "Bigcorp", "ref": "surface:4", "ws_ref": "workspace:1",
     "state": "waiting"},
]
LAYOUT_CAPS = ["tabs", "sessions", "rename", "move_tab", "set_color", "set_description", "workspaces"]


def _layout_driver(repo, tmp_path, tabs=LAYOUT_TABS, caps=LAYOUT_CAPS, workspaces=None) -> Path:
    """A driver that lists `tabs`, announces `caps`, records every request and answers the layout verbs"""
    log = tmp_path / "layout-requests.jsonl"
    script = tmp_path / "layout_driver.py"
    script.write_text(textwrap.dedent(f"""\
        import json, sys
        req = json.load(sys.stdin)
        with open({str(log)!r}, "a") as f:
            f.write(json.dumps(req) + "\\n")
        v = req["verb"]
        if v == "tabs":
            print(json.dumps({{"tabs": {tabs!r}}}))
        elif v == "sessions":
            print(json.dumps({{"sessions": {{}}}}))
        elif v == "caps":
            print(json.dumps({{"caps": {caps!r}}}))
        elif v == "workspaces":
            print(json.dumps({{"workspaces": {workspaces or []!r}}}))
        elif v in ("move_tab", "set_color", "set_description"):
            print(json.dumps({{"report": [v + " done"]}}))
        else:
            print(json.dumps({{"error": "unknown verb " + v}})); sys.exit(1)
        """))
    (repo / "bridge-config.yaml").write_text(
        f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n"
        "  control: {name: Control}\n"
        "  workspaces:\n    - {name: Bigcorp, contexts: [bigcorp], aliases: [bc]}\n    - {name: Misc, default: true}\n")
    return log


def test_the_palette_maps_every_name_to_one_hex():
    names = list(wp.COLORS)
    assert names == ["Red", "Crimson", "Orange", "Amber", "Olive", "Green", "Teal", "Aqua", "Blue", "Navy",
                     "Indigo", "Purple", "Magenta", "Rose", "Brown", "Charcoal"]
    hexes = list(wp.COLORS.values())
    assert len(set(h.upper() for h in hexes)) == 16
    assert all(re.fullmatch(r"#[0-9A-F]{6}", h) for h in hexes)
    assert wp.COLORS["Purple"] == "#6A1B9A" and wp.COLORS["Charcoal"] == "#3E4B5E"
    assert wp.color_name("#6a1b9a") == "Purple" and wp.color_name("#123456") is None and wp.color_name(None) is None
    assert wp.palette_name("blue") == "Blue" and wp.palette_name("Sky") is None


def test_command_driver_payloads_for_move_color_description(tmp_path):
    log = tmp_path / "req.jsonl"
    script = tmp_path / "d.py"
    script.write_text("import json, sys\nreq = json.load(sys.stdin)\nopen(%r, 'a').write(json.dumps(req) + '\\n')\n"
                      "print(json.dumps({'report': ['done']}))\n" % str(log))
    drv = wp.CommandDriver([sys.executable, str(script)])
    assert drv.move_tab("surface:5", "workspace:3") == ["done"]
    assert drv.move_tab("surface:5", "workspace:3", 2) == ["done"]
    assert drv.set_color("workspace:3", "Blue") == ["done"]
    assert drv.set_color("workspace:3", None) == ["done"]
    assert drv.set_description("workspace:3", "Release work") == ["done"]
    assert drv.set_description("workspace:3", None) == ["done"]
    assert not drv.failed
    assert [json.loads(x) for x in log.read_text().splitlines()] == [
        {"verb": "move_tab", "tab": "surface:5", "workspace": "workspace:3"},
        {"verb": "move_tab", "tab": "surface:5", "workspace": "workspace:3", "index": 2},
        {"verb": "set_color", "workspace": "workspace:3", "color": "Blue"},
        {"verb": "set_color", "workspace": "workspace:3", "color": None},
        {"verb": "set_description", "workspace": "workspace:3", "text": "Release work"},
        {"verb": "set_description", "workspace": "workspace:3", "text": None},
    ]


def test_none_driver_layout_verbs_say_do_it_yourself():
    none = wp.NoneDriver()
    for lines in (none.move_tab("surface:5", "workspace:3"), none.set_color("workspace:3", "Blue"),
                  none.set_description("workspace:3", "Release work")):
        (line,) = lines
        assert "no driver" in line.lower() and "yourself" in line


def test_cli_move_tab_takes_exact_refs_and_an_optional_index(repo, tmp_path, capsys):
    log = _layout_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "move-tab", "surface:5", "workspace:3"]) == 0
    assert wp.main(["--root", str(repo), "move-tab", "surface:6", "workspace:3", "--index", "1"]) == 0
    assert _requests(log, "move_tab") == [{"verb": "move_tab", "tab": "surface:5", "workspace": "workspace:3"},
                                          {"verb": "move_tab", "tab": "surface:6", "workspace": "workspace:3",
                                           "index": 1}]
    assert "move_tab done" in capsys.readouterr().out
    # a name, a part of one, a ref that is not open, a workspace that is not open, the workspace it is in already
    for tab, ws in (("Notes", "workspace:3"), ("surface", "workspace:3"), ("surface:99", "workspace:3"),
                    ("surface:5", "Research"), ("surface:5", "workspace:77"), ("surface:5", "workspace:2")):
        assert wp.main(["--root", str(repo), "move-tab", tab, ws]) == 2, (tab, ws)
    assert wp.main(["--root", str(repo), "move-tab", "surface:5", "workspace:3", "--index", "-1"]) == 2
    assert len(_requests(log, "move_tab")) == 2
    assert "refused" in capsys.readouterr().err


def test_cli_move_tab_without_the_cap_is_refused(repo, tmp_path, capsys):
    log = _layout_driver(repo, tmp_path, caps=["tabs", "sessions", "rename"])
    assert wp.main(["--root", str(repo), "move-tab", "surface:5", "workspace:3"]) == 2
    assert "cannot" in capsys.readouterr().err
    assert _requests(log, "move_tab") == []


def test_cli_workspace_color_takes_a_palette_name_or_clear(repo, tmp_path, capsys):
    log = _layout_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "workspace-color", "workspace:2", "teal"]) == 0
    assert wp.main(["--root", str(repo), "workspace-color", "workspace:3", "--clear"]) == 0
    assert _requests(log, "set_color") == [{"verb": "set_color", "workspace": "workspace:2", "color": "Teal"},
                                           {"verb": "set_color", "workspace": "workspace:3", "color": None}]
    # not a palette name, a hex, both or neither, a ref that is not open, a configured workspace
    for args in (["workspace:2", "Sky"], ["workspace:2", "#123456"], ["workspace:2", "Teal", "--clear"],
                 ["workspace:2"], ["workspace:77", "Teal"], ["Scratch", "Teal"], ["workspace:1", "Teal"]):
        assert wp.main(["--root", str(repo), "workspace-color", *args]) == 2, args
    assert len(_requests(log, "set_color")) == 2
    assert "configured workspace" in capsys.readouterr().err


def test_cli_workspace_description_takes_text_after_double_dash_or_clear(repo, tmp_path, capsys):
    log = _layout_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "workspace-description", "workspace:2", "--", "--loose notes"]) == 0
    assert wp.main(["--root", str(repo), "workspace-description", "workspace:2", "--clear"]) == 0
    assert _requests(log, "set_description") == [
        {"verb": "set_description", "workspace": "workspace:2", "text": "--loose notes"},
        {"verb": "set_description", "workspace": "workspace:2", "text": None}]
    for args in (["workspace:2", "--", "x" * 121], ["workspace:2", "--", "two\nlines"], ["workspace:2", "--", "  "],
                 ["workspace:2"], ["workspace:1", "--", "text"], ["workspace:77", "--clear"]):
        assert wp.main(["--root", str(repo), "workspace-description", *args]) == 2, args
    assert len(_requests(log, "set_description")) == 2


def test_cli_layout_commands_report_a_driver_refusal_as_exit_one(repo, tmp_path, capsys):
    script = tmp_path / "refusing.py"
    script.write_text(textwrap.dedent(f"""\
        import json, sys
        v = json.load(sys.stdin)["verb"]
        if v == "tabs":
            print(json.dumps({{"tabs": {LAYOUT_TABS!r}}}))
        elif v == "caps":
            print(json.dumps({{"caps": {LAYOUT_CAPS!r}}}))
        else:
            print(json.dumps({{"report": ["ERROR surface:5 is the last tab of workspace:2"]}}))
        """))
    (repo / "bridge-config.yaml").write_text(f"workplace:\n  driver: {{command: ['{sys.executable}', '{script}']}}\n")
    assert wp.main(["--root", str(repo), "move-tab", "surface:5", "workspace:3"]) == 1
    assert "ERROR surface:5 is the last tab" in capsys.readouterr().out


@pytest.mark.parametrize("kind, mode", [("task", "go"), ("task", "report"), ("task", "context"), ("inbox", "go"), ("inbox", "report")])
def test_a_start_note_is_read_first_and_the_prompt_stays_ascii(lrepo, kind, mode):
    """The person's sentence for this start lives on the item (UTF-8, in its log), the ASCII prompt points at it."""
    item = "payments-incident" if kind == "task" else INBOX_ID
    (plain,) = wp.build_launch(lrepo, {}, [item], mode)
    (noted,) = wp.build_launch(lrepo, {}, [item], mode, start_note=True)
    assert "Start note:" not in plain["command"]
    cmd = noted["command"].replace("'\"'\"'", "'")
    assert "newest note that begins with 'Start note:'" in cmd and "comes before everything else" in cmd
    assert wp.launch_prompt(kind, mode, item, "work/tasks/x/STATUS.md", start_note=True).isascii()


@pytest.mark.parametrize("mode", ["go", "report"])
def test_an_inbox_start_with_an_order_never_closes_on_its_own(mode):
    """28.10.: a handed chat said "I want to analyse it more closely" and its tab closed the item after 31 s with
    "nothing to do". With the person's sentence the tab notes its result and asks before closing; a close it proposes
    is a question, a note that begins with 'Question:'. Without one the overtaken rule stays as it was."""
    plain = wp.launch_prompt("inbox", mode, INBOX_ID)
    noted = wp.launch_prompt("inbox", mode, INBOX_ID, start_note=True)
    assert "close it without asking" in plain and "do not close the item on your own" not in plain
    assert "do not close the item on your own" in noted and "a proposal to close is a question" in noted
    assert f"python3 scripts/inbox.py note {INBOX_ID} 'Question: " in noted
    # with an order the base prompt says nothing that contradicts it: no close without asking, no close when settled
    assert "close it without asking" not in noted and "When it is settled, close" not in noted
    assert "releases the close" not in noted and f"inbox.py close {INBOX_ID}" not in noted
    assert f"inbox.py show {INBOX_ID}" in noted and "Never close a tab or a workspace." in noted
    assert noted.isascii()
    # a task tab closes no inbox item: its start note prompt keeps its own words
    assert "do not close the item" not in wp.launch_prompt("task", mode, "x", "work/tasks/x/STATUS.md", start_note=True)


def test_the_go_prompt_marks_a_question_on_the_item():
    """The cockpit tells a question from a result by its head (returns.py QUESTION_HEADS): the go prompt asks for it"""
    assert "begin a question with 'Question:'" in wp.launch_prompt("inbox", "go", INBOX_ID)


def test_launch_cli_takes_start_note(lrepo, capsys):
    # a dry run (no --yes) prints the plan with the command
    assert wp.main(["--root", str(lrepo), "launch", "--items", "payments-incident", "--mode", "go",
                    "--start-note", "--json"]) in (0, 1)
    assert "Start note:" in capsys.readouterr().out


# ---------------------------------------------------------------- a new tab, a new workspace, a workspace closed

MAKE_TABS = [
    {"name": "Payments Incident", "workspace": "Bigcorp", "ref": "surface:4", "ws_ref": "workspace:1", "state": "waiting"},
    {"name": "Notes", "workspace": "Scratch", "ref": "surface:6", "ws_ref": "workspace:2", "state": "waiting"},
    {"name": "user@host:~", "workspace": "Research", "ref": "surface:8", "ws_ref": "workspace:3", "state": "shell"},
]
MAKE_CAPS = ["tabs", "sessions", "workspaces", "set_color", "new_tab", "new_workspace", "close_workspace"]
MAKE_ANSWERS = {
    "new_tab": {"report": ["tab Chat (surface:60) in Scratch"], "ref": "surface:60"},
    "new_workspace": {"report": ["workspace Fresh (workspace:50)"], "ws_ref": "workspace:50", "ref": "surface:61"},
    "close_workspace": {"report": ["workspace:2 closed"]},
}


def _make_driver(repo, tmp_path, tabs=MAKE_TABS, caps=MAKE_CAPS, workspaces=None, answers=None, agent=None) -> Path:
    """A driver that lists `tabs`, announces `caps`, records every request and answers the verbs that make and close"""
    import yaml
    tmp_path.mkdir(exist_ok=True)
    log = tmp_path / "make-requests.jsonl"
    script = tmp_path / "make_driver.py"
    replies = {**MAKE_ANSWERS, **(answers or {})}
    script.write_text(textwrap.dedent(f"""\
        import json, sys
        req = json.load(sys.stdin)
        with open({str(log)!r}, "a") as f:
            f.write(json.dumps(req) + "\\n")
        v = req["verb"]
        replies = {replies!r}
        if v == "tabs":
            print(json.dumps({{"tabs": {tabs!r}}}))
        elif v == "sessions":
            print(json.dumps({{"sessions": {{}}}}))
        elif v == "caps":
            print(json.dumps({{"caps": {caps!r}}}))
        elif v == "workspaces":
            print(json.dumps({{"workspaces": {workspaces or []!r}}}))
        elif v in replies:
            print(json.dumps(replies[v]))
        else:
            print(json.dumps({{"error": "unknown verb " + v}})); sys.exit(1)
        """))
    cfg = {"driver": {"command": [sys.executable, str(script)]}, "control": {"name": "Control"},
           "workspaces": [{"name": "Bigcorp", "contexts": ["bigcorp"], "aliases": ["bc"]}, {"name": "Misc", "default": True}]}
    if agent:
        cfg["agent"] = agent
    (repo / "bridge-config.yaml").write_text(yaml.safe_dump({"workplace": cfg}), encoding="utf-8")
    return log


def _chat(command: str) -> tuple[str, list[str]]:
    """The slug of a free chat and the words of its command after `claude`"""
    import shlex
    m = re.fullmatch(r"cd -- (\S+) && export BRIDGE_TAB_SLUG=(chat-[0-9a-f]{8}) && (claude .*)", command, re.S)
    assert m, command
    return m.group(2), shlex.split(m.group(3))


def test_command_driver_sends_the_payloads_that_make_and_close_and_keeps_the_answered_refs(tmp_path):
    log = tmp_path / "req.jsonl"
    script = tmp_path / "d.py"
    script.write_text("import json, sys\nreq = json.load(sys.stdin)\nopen(%r, 'a').write(json.dumps(req) + '\\n')\n"
                      "print(json.dumps(%r.get(req['verb'])))\n" % (str(log), MAKE_ANSWERS))
    drv = wp.CommandDriver([sys.executable, str(script)])
    assert drv.new_tab("workspace:2", "Chat", "cd -- /x && agent") == ["tab Chat (surface:60) in Scratch"]
    assert drv.refs == {"ref": "surface:60"} and not drv.failed
    assert drv.new_tab("workspace:2", None, None) and drv.refs == {"ref": "surface:60"}
    assert drv.new_workspace("Fresh", "Teal", "/x", "agent") == ["workspace Fresh (workspace:50)"]
    assert drv.refs == {"ws_ref": "workspace:50", "ref": "surface:61"}
    assert drv.close_workspace("workspace:2") == ["workspace:2 closed"] and drv.refs == {} and not drv.failed
    assert [json.loads(x) for x in log.read_text().splitlines()] == [
        {"verb": "new_tab", "workspace": "workspace:2", "title": "Chat", "command": "cd -- /x && agent"},
        {"verb": "new_tab", "workspace": "workspace:2", "title": None, "command": None},
        {"verb": "new_workspace", "title": "Fresh", "color": "Teal", "cwd": "/x", "command": "agent"},
        {"verb": "close_workspace", "workspace": "workspace:2"}]


def test_command_driver_that_fails_answers_an_error_line_and_no_ref(tmp_path):
    script = tmp_path / "d.py"
    script.write_text("import sys\nsys.exit(3)\n")
    drv = wp.CommandDriver([sys.executable, str(script)])
    (line,) = drv.new_tab("workspace:2", "Chat", None)
    assert line.startswith("ERROR") and drv.failed and drv.refs == {}


def test_none_driver_cannot_make_or_close_and_says_do_it_yourself():
    none = wp.NoneDriver()
    for lines in (none.new_tab("workspace:2", "Chat", "cmd"), none.new_workspace("Fresh", None, None, None),
                  none.close_workspace("workspace:2")):
        (line,) = lines
        assert "no driver" in line.lower() and "yourself" in line
    assert none.refs == {} and none.caps() == []


def test_cli_new_tab_shell_opens_a_plain_shell_and_answers_the_ref_as_json(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--kind", "shell", "--title=Scratch pad", "--json"]) == 0
    assert _requests(log, "new_tab") == [{"verb": "new_tab", "workspace": "workspace:2", "title": "Scratch pad",
                                          "command": None}]
    assert json.loads(capsys.readouterr().out) == {"ok": True, "report": ["tab Chat (surface:60) in Scratch"],
                                                   "ref": "surface:60"}
    # without --json the report lines, nothing else
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--kind", "shell"]) == 0
    assert capsys.readouterr().out == "tab Chat (surface:60) in Scratch\n"


def test_cli_new_tab_agent_is_the_configured_agent_with_no_task_prompt(repo, tmp_path):
    log = _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2"]) == 0          # agent is the default kind
    (req,) = _requests(log, "new_tab")
    slug, words = _chat(req["command"])
    assert words == ["claude", "-n", slug]                       # a free chat: no sentence, no prompt slot
    assert req["command"].startswith(f"cd -- {repo} && export BRIDGE_TAB_SLUG={slug} && ")
    # the sentence is the prompt, nothing of a task around it
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--text=Why is the build red?"]) == 0
    slug, words = _chat(_requests(log, "new_tab")[1]["command"])
    assert words == ["claude", "-n", slug, "Why is the build red?"]


def test_cli_new_tab_uses_the_agent_template_of_the_config_and_its_model_defaults(repo, tmp_path):
    log = _make_driver(repo, tmp_path, agent={"new": "assistant --name {slug} --say {prompt}", "model": "haiku"})
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--text=Hello there"]) == 0
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2"]) == 0
    first, second = (r["command"] for r in _requests(log, "new_tab"))
    assert first.endswith("&& assistant --name %s --say 'Hello there'" % re.search(r"chat-[0-9a-f]{8}", first).group(0))
    assert re.search(r"&& assistant --name chat-[0-9a-f]{8} --say$", second)       # the slot goes, nothing is left over
    # the model is claude's flag: a template for another agent gets none (as in launch)
    assert "--model" not in first


def test_cli_new_tab_passes_model_and_effort_as_launch_does(repo, tmp_path):
    log = _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--text=Hi", "--model", "opus", "--effort", "high"]) == 0
    slug, words = _chat(_requests(log, "new_tab")[0]["command"])
    assert words == ["claude", "-n", slug, "Hi", "--model", wp.CLAUDE_MODELS["opus"], "--effort", "high"]
    # the config's own defaults apply when the call asks for none, like a launch
    log2 = _make_driver(repo, tmp_path / "b", agent={**wp.DEFAULT_AGENT, "model": "sonnet", "effort": "low"})
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2"]) == 0
    slug, words = _chat(_requests(log2, "new_tab")[0]["command"])
    assert words == ["claude", "-n", slug, "--model", wp.CLAUDE_MODELS["sonnet"], "--effort", "low"]


HOSTILE = "it's $(touch PWNED); `rm -rf ~` \"quoted\" \\ back\nsecond line & | > < \u00fcber \u20ac {slug} {0}"


def test_the_persons_words_reach_the_agent_as_one_argument_through_a_real_shell(repo, tmp_path):
    """shell quoting, tested by running the command: the sentence arrives byte for byte, and nothing in it runs"""
    out = tmp_path / "argv.json"
    agent = tmp_path / "agent.py"
    agent.write_text("import json, sys\nopen(sys.argv[1], 'w').write(json.dumps(sys.argv[2:]))\n")
    log = _make_driver(repo, tmp_path, agent={"new": f"{sys.executable} {agent} {out} {{slug}} {{prompt}}"})
    hostile = HOSTILE.replace("PWNED", str(tmp_path / "pwned"))
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--text", hostile]) == 0
    (req,) = _requests(log, "new_tab")
    import subprocess
    subprocess.run(req["command"], shell=True, check=True, timeout=30)
    slug, sentence = json.loads(out.read_text(encoding="utf-8"))
    assert sentence == hostile and re.fullmatch(r"chat-[0-9a-f]{8}", slug)
    assert not (tmp_path / "pwned").exists()


def test_an_agent_template_without_a_prompt_slot_refuses_a_sentence_rather_than_drop_it(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path, agent={"new": "assistant --name {slug}"})
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--text=Hello there"]) == 2
    assert "no {prompt}" in capsys.readouterr().err and _requests(log, "new_tab") == []
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2"]) == 0                  # a free chat needs none


def test_a_sentence_that_starts_with_a_dash_is_not_taken_for_a_flag(repo, tmp_path):
    log = _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--text=-5 degrees: is that cold?"]) == 0
    slug, words = _chat(_requests(log, "new_tab")[0]["command"])
    assert words == ["claude", "-n", slug, "--", "-5 degrees: is that cold?"]


@pytest.mark.parametrize("args, why", [
    (["--kind", "shell", "--text=hello"], "takes no sentence"),
    (["--text="], "a sentence has"),
    (["--text=" + "x" * 2001], "a sentence has"),
    (["--text=bell\x07"], "a control code"),
    (["--title=", "--kind", "shell"], "a title has"),
    (["--title=" + "x" * 81], "a title has"),
    (["--title=two\nlines"], "control characters"),
    (["--title=Payments Incident"], "known by this name"),
    (["--title=payments-incident"], "known by this name"),
    (["--title=notes"], "name in use"),
    (["--title=user@host:~"], "name in use"),
])
def test_cli_new_tab_refuses_a_bad_sentence_or_title_before_the_driver_is_asked(repo, tmp_path, capsys, args, why):
    log = _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", *args]) == 2
    assert why in capsys.readouterr().err
    assert _requests(log, "new_tab") == []


def test_cli_new_tab_refusal_never_repeats_the_sentence(repo, tmp_path, capsys):
    _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--kind", "shell", "--text=secret words"]) == 2
    assert "secret" not in capsys.readouterr().err


def test_cli_new_tab_takes_a_live_workspace_ref_only(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path, workspaces=[{"ref": "workspace:8", "title": "Empty"}])
    for ref in ("Scratch", "scratch", "workspace:77", "workspace:"):
        assert wp.main(["--root", str(repo), "new-tab", ref, "--kind", "shell"]) == 2, ref
    assert "no open workspace" in capsys.readouterr().err and _requests(log, "new_tab") == []
    # a workspace the driver lists is live even with no tab in it
    assert wp.main(["--root", str(repo), "new-tab", "workspace:8", "--kind", "shell"]) == 0
    assert _requests(log, "new_tab")[0]["workspace"] == "workspace:8"


def test_cli_new_tab_without_the_cap_or_a_driver_is_refused(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path, caps=["tabs", "sessions"])
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2"]) == 2
    assert "cannot new tab" in capsys.readouterr().err and _requests(log, "new_tab") == []
    (repo / "bridge-config.yaml").unlink()
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2"]) == 2


def test_cli_new_tab_reports_a_driver_error_line_as_exit_one_and_still_answers_the_ref(repo, tmp_path, capsys):
    _make_driver(repo, tmp_path, answers={"new_tab": {"report": ["ERROR tab Chat: command did not start"],
                                                      "ref": "surface:60"}})
    assert wp.main(["--root", str(repo), "new-tab", "workspace:2", "--kind", "shell", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "report": ["ERROR tab Chat: command did not start"],
                                                   "ref": "surface:60"}


def test_cli_new_workspace_makes_one_and_answers_both_refs(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path)
    folder = tmp_path / "project"
    folder.mkdir()
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Fresh", "--kind", "shell", "--color", "teal",
                    f"--cwd={folder}", "--json"]) == 0
    assert _requests(log, "new_workspace") == [{"verb": "new_workspace", "title": "Fresh", "color": "Teal",
                                                "cwd": str(folder), "command": None}]
    assert json.loads(capsys.readouterr().out) == {"ok": True, "report": ["workspace Fresh (workspace:50)"],
                                                   "ws_ref": "workspace:50", "ref": "surface:61"}


def test_cli_new_workspace_agent_starts_in_its_folder_and_none_starts_no_command(repo, tmp_path):
    log = _make_driver(repo, tmp_path)
    folder = tmp_path / "project"
    folder.mkdir()
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Chat", f"--cwd={folder}", "--text=Hello",
                    "--model", "sonnet"]) == 0
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Plain", "--kind", "none"]) == 0
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Agent"]) == 0
    agent, plain, default = _requests(log, "new_workspace")
    slug, words = _chat(agent["command"])
    assert words == ["claude", "-n", slug, "Hello", "--model", wp.CLAUDE_MODELS["sonnet"]]
    assert agent["command"].startswith(f"cd -- {folder} && ") and agent["cwd"] == str(folder)
    assert plain["command"] is None and plain["cwd"] == str(repo) and plain["color"] is None
    assert default["command"].startswith(f"cd -- {repo} && ")           # the Bridge folder, as a launch


@pytest.mark.parametrize("args, why", [
    (["--title=Fresh", "--kind", "none", "--text=hi"], "takes no sentence"),
    (["--title=Fresh", "--kind", "shell", "--text=hi"], "takes no sentence"),
    (["--title=Fresh", "--color", "Sky"], "not a palette colour"),
    (["--title=Fresh", "--color", "#123456"], "not a palette colour"),
    (["--title=Fresh", "--cwd=/no/such/folder/anywhere"], "not a folder"),
    (["--title=Fresh", "--cwd=relative/path"], "not a folder"),
    (["--title="], "a title has"),
    (["--title=" + "x" * 81], "a title has"),
    (["--title=bad\x07bell"], "control characters"),
    (["--title=Bigcorp"], "configured workspace"),
    (["--title=BC"], "configured workspace"),
    (["--title=control"], "configured workspace"),
    (["--title=scratch"], "name in use"),
    (["--title=Research"], "name in use"),
])
def test_cli_new_workspace_refuses_before_the_driver_is_asked(repo, tmp_path, capsys, args, why):
    log = _make_driver(repo, tmp_path)
    assert wp.main(["--root", str(repo), "new-workspace", *args]) == 2
    assert why in capsys.readouterr().err
    assert _requests(log, "new_workspace") == []


def test_cli_new_workspace_needs_a_title(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path)
    with pytest.raises(SystemExit) as stop:
        wp.main(["--root", str(repo), "new-workspace", "--kind", "shell"])
    assert stop.value.code == 2 and "--title" in capsys.readouterr().err
    assert _requests(log, "new_workspace") == []


def test_cli_new_workspace_needs_the_cap_and_a_colour_needs_set_color(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path, caps=["tabs", "sessions", "workspaces", "new_workspace"])
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Fresh", "--color", "Teal"]) == 2
    assert "cannot set color" in capsys.readouterr().err
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Fresh"]) == 0          # no colour asked: fine
    _make_driver(repo, tmp_path / "b", caps=["tabs", "sessions"])
    assert wp.main(["--root", str(repo), "new-workspace", "--title=Other"]) == 2
    assert "cannot new workspace" in capsys.readouterr().err
    assert len(_requests(log, "new_workspace")) == 1


def test_cli_close_workspace_takes_a_live_ref_only(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path, workspaces=[{"ref": "workspace:8", "title": "Empty"}])
    assert wp.main(["--root", str(repo), "close-workspace", "workspace:2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "report": ["workspace:2 closed"]}
    assert wp.main(["--root", str(repo), "close-workspace", "workspace:8"]) == 0
    for ref in ("Scratch", "scratch", "workspace:77", "surface:6"):
        assert wp.main(["--root", str(repo), "close-workspace", ref]) == 2, ref
    assert [r["workspace"] for r in _requests(log, "close_workspace")] == ["workspace:2", "workspace:8"]
    assert "no open workspace" in capsys.readouterr().err


def test_cli_close_workspace_without_the_cap_is_refused_and_a_driver_refusal_is_exit_one(repo, tmp_path, capsys):
    log = _make_driver(repo, tmp_path, caps=["tabs", "sessions"])
    assert wp.main(["--root", str(repo), "close-workspace", "workspace:2"]) == 2
    assert "cannot close workspace" in capsys.readouterr().err and _requests(log, "close_workspace") == []
    _make_driver(repo, tmp_path / "b", answers={"close_workspace": {"report": ["ERROR workspace:2 is the last one"]}})
    assert wp.main(["--root", str(repo), "close-workspace", "workspace:2"]) == 1
    assert "ERROR workspace:2 is the last one" in capsys.readouterr().out
