# SPDX-License-Identifier: MIT
"""Contract for skills/cmux/scripts/cmux_driver.py, the cmux workplace driver.

The driver speaks the JSON protocol of scripts/workplace.py. Every test runs
against a FAKE `cmux` executable put first on PATH in a temp dir, which logs its
argv and answers from fixture files; the real cmux is never called. HOME and all
cmux file locations point into the temp dir too.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
SKILL = HERE.parents[1]
REPO = HERE.parents[3]
DRIVER = SKILL / "scripts" / "cmux_driver.py"

sys.path.insert(0, str(SKILL / "scripts"))
import cmux_driver as drv  # noqa: E402


def load_core():
    spec = importlib.util.spec_from_file_location("workplace_core", REPO / "scripts" / "workplace.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["workplace_core"] = module
    spec.loader.exec_module(module)
    return module


FAKE_CMUX = textwrap.dedent("""\
    import json, os, sys
    args = sys.argv[1:]
    with open(os.environ["FAKE_CMUX_LOG"], "a") as log:
        log.write(json.dumps(args) + "\\n")
    def answer(name):
        path = os.environ.get(name)
        return open(path).read() if path and os.path.exists(path) else ""
    joined = " ".join(args)
    fails = [f for f in os.environ.get("FAKE_CMUX_FAIL", "").split(",") if f]
    if any(joined.startswith(f) for f in fails):
        print("Error: not_found: simulated failure for " + joined, file=sys.stderr)
        sys.exit(1)
    if "--command" in args and not os.environ.get("FAKE_CMUX_LOST"):
        # like a shell that came up: run the start marker of a launcher file (never the agent)
        import re
        typed = args[args.index("--command") + 1]
        m = re.fullmatch(r"/bin/sh '([^']+)'", typed)
        if m and os.path.exists(m.group(1)):
            for line in open(m.group(1), encoding="utf-8"):
                hit = re.fullmatch(r": > '([^']+)'", line.strip())
                if hit:
                    open(hit.group(1), "w").close()
    if args[:1] == ["ping"]:
        print("PONG")
    elif args[:1] == ["tree"] and "--json" in args:
        tree = json.loads(answer("FAKE_CMUX_TREE"))
        if "--all" not in args:              # like cmux: current window only
            tree["windows"] = tree["windows"][:1]
        print(json.dumps(tree))
    elif args[:1] == ["tree"]:
        print("surface:61")
    elif args[:3] == ["--json", "workspace", "list"]:
        print(answer("FAKE_CMUX_WSJSON"))
    elif args[:2] == ["--json", "list-notifications"]:
        print(answer("FAKE_CMUX_NOTES") or "[]")
    elif args[:1] == ["sidebar-state"]:
        ref = args[args.index("--workspace") + 1]
        print(json.loads(answer("FAKE_CMUX_SIDEBAR") or "{}").get(ref, ""))
    elif args[:2] == ["workspace", "list"]:  # like cmux: current window only
        print(answer("FAKE_CMUX_WS"))
    elif args[:2] == ["workspace", "create"]:
        print("OK workspace:50")
    elif args[:1] == ["new-surface"]:
        print("OK surface:60 pane:1 workspace:50")
    else:
        print("OK")
    """)


def _pane(*surfaces):
    return {"surface_count": len(surfaces), "surfaces": list(surfaces)}


TREE = {"caller": {"surface_ref": "surface:92", "workspace_ref": "workspace:3", "window_ref": "window:1"},
        "windows": [
    {"ref": "window:1", "workspaces": [
        {"title": "Platform", "ref": "workspace:3", "panes": [_pane(
            {"ref": "surface:91", "type": "terminal", "title": "\u2733 Fix login"},
            {"ref": "surface:92", "type": "terminal", "title": "user@host:~"},
            {"ref": "surface:7", "type": "browser", "title": "Docs"})]},
        {"title": "Customer A", "ref": "workspace:4", "panes": [_pane(
            {"ref": "surface:95", "type": "terminal", "title": "Invoice export"},
            {"ref": "surface:96", "type": "terminal", "title": "user@host:~"})]}]},
    {"ref": "window:2", "workspaces": [
        {"title": "Customer B", "ref": "workspace:5", "panes": [_pane(
            {"ref": "surface:97", "type": "terminal", "title": "Report draft"})]}]},
]}

SESSION = {"windows": [{"tabManager": {"workspaces": [
    {"customTitle": "Platform", "workspaceId": "WS-UUID-1",
     "panels": [{"id": "1C53A0D3", "type": "terminal", "title": "✳ Fix login", "terminal": {}},
                {"id": "2B000000", "type": "terminal", "title": "user@host:~", "terminal": {}}],
     "layout": {"type": "pane", "pane": {"panelIds": ["1C53A0D3", "2B000000"]}}},
]}}]}

HOOKS = {"activeSessionsBySurface": {"1C53A0D3": {"sessionId": "s1"}},
         "sessions": {"s1": {"hookEventName": "Stop", "lastBody": "Login fixed, tests green"}}}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """A temp world: fake cmux on PATH, cmux files in tmp, nothing of the real machine."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cmux = bin_dir / "cmux"
    cmux.write_text(f"#!{sys.executable}\n" + FAKE_CMUX)
    cmux.chmod(0o755)
    files = {
        "FAKE_CMUX_LOG": tmp_path / "cmux.log",
        "FAKE_CMUX_TREE": tmp_path / "tree.json",
        "FAKE_CMUX_WS": tmp_path / "ws.txt",
        "FAKE_CMUX_WSJSON": tmp_path / "ws.json",
        "FAKE_CMUX_NOTES": tmp_path / "notes.json",
        "FAKE_CMUX_SIDEBAR": tmp_path / "sidebar.json",
        "CMUX_SESSION_FILE": tmp_path / "session.json",
        "CMUX_HOOKS_FILE": tmp_path / "hooks.json",
        "CMUX_LAYOUT_DIR": tmp_path / "layouts",
    }
    files["FAKE_CMUX_TREE"].write_text(json.dumps(TREE))
    files["FAKE_CMUX_WS"].write_text("  workspace:3 Platform\n* workspace:4 Customer A [selected]\n")
    files["CMUX_SESSION_FILE"].write_text(json.dumps(SESSION))
    files["CMUX_HOOKS_FILE"].write_text(json.dumps(HOOKS))
    env = {**os.environ, "PATH": str(bin_dir), "HOME": str(tmp_path), "CMUX_BIN": str(cmux),
           "CMUX_SURFACE_ID": "", "CMUX_LAUNCH_WAIT_SEC": "1",
           **{k: str(v) for k, v in files.items()}}

    class World:
        fail = ""
        lost = False

        def call(self, request: dict) -> subprocess.CompletedProcess:
            run_env = {**env, "FAKE_CMUX_FAIL": self.fail, "FAKE_CMUX_LOST": "1" if self.lost else ""}
            return subprocess.run([sys.executable, str(DRIVER)], input=json.dumps(request),
                                  capture_output=True, text=True, env=run_env, timeout=60)

        def answer(self, request: dict) -> dict:
            done = self.call(request)
            assert done.returncode == 0, done.stderr
            return json.loads(done.stdout)

        def argv(self) -> list:
            log = files["FAKE_CMUX_LOG"]
            return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    world = World()
    world.cmux = cmux
    world.files = files
    world.env = env
    return world


# ---------------------------------------------------------------- verbs over the protocol

def test_tabs_join_socket_refs_with_session_state_by_stripped_title(fake):
    tabs = fake.answer({"verb": "tabs"})["tabs"]
    by_name = {t["name"]: t for t in tabs}
    login = by_name["Fix login"]
    # ref from the socket (surface:91), state and last line from the session file (UUID 1C53A0D3)
    assert login["ref"] == "surface:91" and login["ws_ref"] == "workspace:3"
    assert login["state"] == "waiting" and login["last"] == "Login fixed, tests green"
    assert by_name["Invoice export"]["state"] == "shell"
    assert "Docs" not in by_name   # browser tabs are not agent tabs
    assert all(t["state"] in ("working", "waiting", "needs-you", "shell") for t in tabs)


def test_sessions_come_from_layout_snapshots(fake):
    snap_dir = fake.files["CMUX_LAYOUT_DIR"]
    snap_dir.mkdir()
    layout = {"windows": [{"workspaces": [{"title": "Platform", "panes": [[
        {"kind": "claude", "title": "Fix login", "session_id": "aaaaaaaa-1111-2222-3333-444444444444"}]]}]}]}
    (snap_dir / "layout-20260101-120000.json").write_text(json.dumps({"taken_at": 1, "layout": layout}))
    assert fake.answer({"verb": "sessions"}) == {
        "sessions": {"Fix login": "aaaaaaaa-1111-2222-3333-444444444444"}}


def test_open_reuses_open_tabs_creates_new_ones_and_never_closes(fake):
    plan = {"control": {"name": "Control"}, "workspaces": [
        {"name": "Platform", "cwd": "/repo", "tabs": [
            {"slug": "fix-login", "label": "Fix login", "action": "open", "ref": "surface:95",
             "workspace": "Customer A", "ws_ref": "workspace:4"},
            {"slug": "new-api", "label": "New API", "action": "new",
             "command": "cd -- /repo && my-agent -n new-api 'go'"},
            {"slug": "old-one", "label": "Old one", "action": "resume",
             "command": "cd -- /repo && my-agent --resume abc"}]}]}
    report = fake.answer({"verb": "open", "plan": plan, "only": None, "resume": False, "here": None})["report"]
    argv = fake.argv()
    assert not any("close" in " ".join(a) for a in argv)
    new_tabs = [a for a in argv if a[0] == "new-surface"]
    assert len(new_tabs) == 1                            # the open tab is reused, resume is not asked
    command = new_tabs[0][new_tabs[0].index("--command") + 1]
    assert command.startswith("cd -- /repo && my-agent -n new-api") and command.endswith(drv.KEEP_SHELL)
    assert ["move-surface", "--surface", "surface:95", "--workspace", "workspace:3", "--focus", "false"] in argv
    assert any(a[:2] == ["workspace", "create"] and "Control" in a for a in argv)
    assert any("New API" in line for line in report)


def test_open_with_here_moves_the_calling_tab_into_control_last(fake):
    plan = {"control": {"name": "Control"}, "workspaces": [
        {"name": "Platform", "cwd": "/repo", "tabs": [
            {"slug": "a", "label": "A", "action": "new", "command": "cd -- /repo && my-agent"}]}]}
    fake.answer({"verb": "open", "plan": plan, "only": None, "resume": False, "here": "surface:92"})
    moves = [a for a in fake.argv() if a[0] == "move-surface"]
    assert moves[-1][:3] == ["move-surface", "--surface", "surface:92"]
    create = next(a for a in fake.argv() if a[:2] == ["workspace", "create"])
    assert "--command" not in create          # the control tab is the caller, no extra agent


def test_send_types_text_then_enter_in_the_tabs_workspace(fake):
    assert fake.answer({"verb": "send", "tab": "surface:91", "text": "go on"})["report"]
    argv = fake.argv()
    assert ["send", "--workspace", "workspace:3", "--surface", "surface:91", "go on"] in argv
    assert ["send-key", "--workspace", "workspace:3", "--surface", "surface:91", "Enter"] in argv


def test_rename_addresses_the_tab_in_its_workspace(fake):
    fake.answer({"verb": "rename", "tab": "surface:95", "title": "Invoices"})
    assert ["tab-action", "--action", "rename", "--tab", "surface:95", "--title", "Invoices",
            "--workspace", "workspace:4"] in fake.argv()


# ---------------------------------------------------------------- failure is unknown, not empty

def test_without_cmux_the_driver_answers_a_json_error_not_a_traceback(fake, tmp_path):
    env = {**fake.env, "PATH": str(tmp_path / "empty"), "CMUX_BIN": str(tmp_path / "missing")}
    done = subprocess.run([sys.executable, str(DRIVER)], input='{"verb": "tabs"}',
                          capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 1
    assert "cmux" in json.loads(done.stdout)["error"]
    assert "Traceback" not in done.stderr


def test_core_reads_a_failed_driver_as_unknown(monkeypatch, tmp_path):
    core = load_core()
    monkeypatch.setenv("PATH", str(tmp_path))       # no cmux anywhere
    monkeypatch.setenv("CMUX_BIN", str(tmp_path / "missing"))
    driver = core.CommandDriver([sys.executable, str(DRIVER)])
    assert driver.tabs_or_none() is None
    assert driver.sessions_or_none() is None
    assert "cmux" in driver.error


def test_no_tree_and_no_session_file_is_an_error_not_an_empty_list(fake):
    fake.fail = "tree"
    fake.files["CMUX_SESSION_FILE"].unlink()
    done = fake.call({"verb": "tabs"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_tree_failing_with_ping_alive_falls_back_to_the_session_file(fake):
    fake.fail = "tree"
    tabs = fake.answer({"verb": "tabs"})["tabs"]
    assert {t["name"] for t in tabs} == {"Fix login", "user@host:~"}


def test_socket_down_is_an_error_not_the_stale_session_file(fake):
    # Finding 6: the session file persists after cmux quits; showing it as live tabs is a lie.
    fake.fail = "tree,ping"
    done = fake.call({"verb": "tabs"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_unknown_verb_is_an_error(fake):
    done = fake.call({"verb": "explode"})
    assert done.returncode == 1 and "unknown verb" in json.loads(done.stdout)["error"]


# ---------------------------------------------------------------- pure functions

def test_live_tabs_states_in_core_vocabulary():
    hooks = {"activeSessionsBySurface": {"A": {"sessionId": "s"}},
             "sessions": {"s": {"hookEventName": "PermissionRequest"}}}
    session = {"windows": [{"tabManager": {"workspaces": [{"customTitle": "W", "panels": [
        {"id": "A", "type": "terminal", "title": "✳ asks"},
        {"id": "B", "type": "terminal", "title": "⠋ busy"},
        {"id": "C", "type": "terminal", "title": "✳ idle"},
        {"id": "D", "type": "terminal", "title": "user@host:~"}]}]}}]}
    states = {t["surface"]: t["state"] for t in drv.live_tabs(session, hooks)}
    assert states == {"A": "needs-you", "B": "working", "C": "waiting", "D": "shell"}


def test_apply_calls_has_no_close_operation_for_any_plan():
    plan = drv.to_cmux_plan({"control": {"name": "Control"}, "workspaces": [
        {"name": "W", "tabs": [
            {"slug": "a", "label": "A", "action": "open", "ref": "surface:1", "workspace": "X"},
            {"slug": "b", "label": "B", "action": "new", "command": "my-agent"},
            {"slug": "c", "label": "C", "action": "resume", "command": "my-agent --resume c"}]}]})
    ops = {c["op"] for c in drv.apply_calls(plan, {}, "/repo", here="surface:9", resume=True)}
    assert ops <= {"create", "decorate", "order", "move", "rename", "tab", "tab_order", "note"}


def test_to_cmux_plan_keeps_the_shell_once():
    core = {"workspaces": [{"name": "W", "tabs": [{"slug": "b", "label": "B", "action": "new",
                                                   "command": "my-agent"}]}]}
    twice = drv.to_cmux_plan(drv.to_cmux_plan(core))
    assert twice["workspaces"][0]["tabs"][0]["command"].count("exec") == 1


def test_workspace_resolves_through_aliases():
    existing = {"example-org": "workspace:28"}
    assert drv.resolve_workspace({"name": "Platform", "aliases": ["example-org"]}, existing) == "workspace:28"
    assert drv.resolve_workspace({"name": "Misc"}, existing) is None


# ---------------------------------------------------------------- review findings

def _plan(*workspaces, control=None):
    return {"control": control or {"name": "Control"}, "workspaces": list(workspaces)}


def _open(plan, here=None, resume=False):
    return {"verb": "open", "plan": plan, "only": None, "resume": resume, "here": here}


def test_send_that_cmux_rejects_is_a_driver_error(fake):
    # Finding 1: cmux answers `Error: ...` with exit 1; that is not "sent".
    fake.fail = "send"
    done = fake.call({"verb": "send", "tab": "surface:91", "text": "go on"})
    assert done.returncode == 1 and "not_found" in json.loads(done.stdout)["error"]


def test_send_to_a_ref_that_is_not_open_is_a_driver_error(fake):
    done = fake.call({"verb": "send", "tab": "surface:999", "text": "go on"})
    assert done.returncode == 1
    assert not any(a[0] == "send" for a in fake.argv())


def test_rename_that_cmux_rejects_is_a_driver_error(fake):
    fake.fail = "tab-action"
    done = fake.call({"verb": "rename", "tab": "surface:95", "title": "Invoices"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_failed_move_is_reported_as_error_not_as_moved(fake):
    fake.fail = "move-surface"
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": [
        {"slug": "inv", "label": "Invoices", "action": "open", "ref": "surface:95",
         "workspace": "Customer A", "ws_ref": "workspace:4"}]})
    report = fake.answer(_open(plan))["report"]
    assert any(line.lstrip().startswith("ERROR") and "Invoices" in line for line in report)
    assert not any(line.strip().startswith("moved") for line in report)


def test_open_refuses_when_the_workspaces_cannot_be_read(fake):
    # Finding 1: an unreadable workspace list is not "no workspace exists".
    fake.fail = "tree,workspace list"
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": [
        {"slug": "a", "label": "A", "action": "new", "command": "my-agent"}]})
    done = fake.call(_open(plan))
    assert done.returncode == 1 and "error" in json.loads(done.stdout)
    assert not any(a[:2] == ["workspace", "create"] for a in fake.argv())


def test_workspaces_in_another_window_are_found_not_duplicated(fake):
    # Finding 2: tree and workspace list without --all see the current window only.
    plan = _plan({"name": "Customer B", "cwd": "/repo", "tabs": [
        {"slug": "b", "label": "B", "action": "new", "command": "my-agent"}]})
    fake.answer(_open(plan))
    argv = fake.argv()
    assert not any(a[:2] == ["workspace", "create"] and "Customer B" in a for a in argv)
    tab = next(a for a in argv if a[0] == "new-surface")
    assert tab[tab.index("--workspace") + 1] == "workspace:5"


def test_tabs_cover_every_window(fake):
    names = {t["name"] for t in fake.answer({"verb": "tabs"})["tabs"]}
    assert "Report draft" in names


def test_the_last_tab_of_a_workspace_is_not_moved_away(fake):
    # Finding 3: moving the last surface out closes its workspace.
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": [
        {"slug": "rep", "label": "Report", "action": "open", "ref": "surface:97",
         "workspace": "Customer B", "ws_ref": "workspace:5"}]})
    report = fake.answer(_open(plan))["report"]
    argv = fake.argv()
    assert not any(a[0] == "move-surface" and "surface:97" in a for a in argv)
    assert ["tab-action", "--action", "rename", "--tab", "surface:97", "--title", "Report",
            "--workspace", "workspace:5"] in argv
    assert any("last tab" in line for line in report)


def test_the_calling_tab_stays_when_it_is_the_last_of_its_workspace(fake):
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": []})
    report = fake.answer(_open(plan, here="surface:97"))["report"]
    assert not any(a[0] == "move-surface" and "surface:97" in a for a in fake.argv())
    assert any("last tab" in line for line in report)


def test_two_tabs_leave_a_workspace_but_the_last_one_stays(fake):
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": [
        {"slug": "x", "label": "X", "action": "open", "ref": "surface:95",
         "workspace": "Customer A", "ws_ref": "workspace:4"},
        {"slug": "y", "label": "Y", "action": "open", "ref": "surface:96",
         "workspace": "Customer A", "ws_ref": "workspace:4"}]})
    fake.answer(_open(plan))
    moved = [a[a.index("--surface") + 1] for a in fake.argv() if a[0] == "move-surface"]
    assert moved == ["surface:95"]


def test_a_workspace_holding_only_open_tabs_is_created_for_the_move(fake):
    # Finding 4: `create` only ran for new tabs, so the move went nowhere.
    plan = _plan({"name": "Research", "cwd": "/repo", "tabs": [
        {"slug": "inv", "label": "Invoices", "action": "open", "ref": "surface:95",
         "workspace": "Customer A", "ws_ref": "workspace:4"}]})
    fake.answer(_open(plan))
    argv = fake.argv()
    assert any(a[:2] == ["workspace", "create"] and "Research" in a for a in argv)
    assert ["move-surface", "--surface", "surface:95", "--workspace", "workspace:50",
            "--focus", "false"] in argv


def test_no_workspace_is_created_when_nothing_can_move_into_it(fake):
    plan = _plan({"name": "Research", "cwd": "/repo", "tabs": [
        {"slug": "rep", "label": "Report", "action": "open", "ref": "surface:97",
         "workspace": "Customer B", "ws_ref": "workspace:5"}]})
    fake.answer(_open(plan))
    argv = fake.argv()
    assert not any(a[:2] == ["workspace", "create"] and "Research" in a for a in argv)
    assert ["tab-action", "--action", "rename", "--tab", "surface:97", "--title", "Report",
            "--workspace", "workspace:5"] in argv


def test_reorder_surface_names_its_workspace(fake):
    # Finding 5
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": [
        {"slug": "fix", "label": "Fix login", "action": "open", "ref": "surface:91",
         "workspace": "Platform", "ws_ref": "workspace:3"}]})
    fake.answer(_open(plan))
    reorders = [a for a in fake.argv() if a[0] == "reorder-surface"]
    assert reorders and all(a[a.index("--workspace") + 1] == "workspace:3" for a in reorders)


def test_control_command_from_config_reaches_the_new_control_workspace(fake, tmp_path):
    # Finding 7: workplace.control.command passes through the CORE plan untouched.
    core = load_core()
    cfg = {"control": {"name": "Hub", "command": "my-agent -n control"}}
    plan = core.propose([], cfg, {}, {}, {}, core.dt.date(2026, 1, 1), tmp_path)
    fake.answer(_open(json.loads(json.dumps(plan, default=str))))
    create = next(a for a in fake.argv() if a[:2] == ["workspace", "create"] and "Hub" in a)
    assert create[create.index("--command") + 1] == "my-agent -n control" + drv.KEEP_SHELL


def test_control_without_command_or_with_here_starts_no_agent(fake):
    fake.answer(_open(_plan()))
    create = next(a for a in fake.argv() if a[:2] == ["workspace", "create"])
    assert "--command" not in create


def test_spawn_workspace_has_no_loop_flag_nothing_reads():
    # Loop note: --loop wrote a file no part of the Bridge reads.
    script = (SKILL / "scripts" / "spawn-workspace.sh").read_text()
    docs = (SKILL / "references" / "local.md").read_text()
    assert "--loop" not in script and "--loop" not in docs


# ---------------------------------------------------------------- second review

def test_renamed_agent_tab_reads_its_state_from_the_hook_file():
    # Finding 1: a custom title drops the status glyph; the hook file still knows.
    hooks = {"activeSessionsBySurface": {"A": {"sessionId": "a"}, "B": {"sessionId": "b"},
                                         "C": {"sessionId": "c"}, "D": {"sessionId": "d"}},
             "sessions": {"a": {"hookEventName": "Stop", "lastBody": "done"},
                          "b": {"hookEventName": "PreToolUse"},
                          "c": {"hookEventName": "Notification"},
                          "d": {"hookEventName": "SessionStart"}}}
    session = {"windows": [{"tabManager": {"workspaces": [{"customTitle": "W", "panels": [
        {"id": "A", "type": "terminal", "title": "Invoices", "customTitle": "Invoices"},
        {"id": "B", "type": "terminal", "title": "Build", "customTitle": "Build"},
        {"id": "C", "type": "terminal", "title": "Ask", "customTitle": "Ask"},
        {"id": "D", "type": "terminal", "title": "Fresh", "customTitle": "Fresh"},
        {"id": "E", "type": "terminal", "title": "\u280b spinner only"}]}]}}]}
    states = {t["surface"]: t["state"] for t in drv.live_tabs(session, hooks)}
    assert states == {"A": "waiting", "B": "working", "C": "needs-you", "D": "waiting", "E": "working"}


def test_renamed_agent_tab_is_not_a_shell_over_the_protocol(fake):
    session = json.loads(json.dumps(SESSION))
    panel = session["windows"][0]["tabManager"]["workspaces"][0]["panels"][0]
    panel["title"] = panel["customTitle"] = "Fix login"
    fake.files["CMUX_SESSION_FILE"].write_text(json.dumps(session))
    login = next(t for t in fake.answer({"verb": "tabs"})["tabs"] if t["name"] == "Fix login")
    assert login["state"] == "waiting"


def test_here_as_surface_uuid_resolves_through_the_tree_caller(fake):
    # Finding 2: $CMUX_SURFACE_ID is a UUID, the tree speaks surface:N.
    uuid = "2F2117C4-0000-4000-8000-000000000001"
    fake.env["CMUX_SURFACE_ID"] = uuid
    report = fake.answer(_open(_plan({"name": "Platform", "cwd": "/repo", "tabs": []}), here=uuid))["report"]
    assert ["move-surface", "--surface", "surface:92", "--workspace", "workspace:50",
            "--focus", "false"] in fake.argv()
    assert not any("last tab" in line for line in report)


def test_unknown_here_is_reported_as_unknown_and_control_still_starts_its_agent(fake):
    plan = _plan({"name": "Platform", "cwd": "/repo", "tabs": []},
                 control={"name": "Control", "command": "my-agent -n control"})
    report = fake.answer(_open(plan, here="0000AAAA-0000-4000-8000-000000000000"))["report"]
    assert any("not found" in line for line in report)
    assert not any("last tab" in line for line in report)
    create = next(a for a in fake.argv() if a[:2] == ["workspace", "create"])
    assert create[create.index("--command") + 1] == "my-agent -n control" + drv.KEEP_SHELL


def test_driver_finds_cmux_through_cmux_bin_when_not_on_path(fake, tmp_path):
    # Finding 3: an app-bundle install is not on PATH (and never under launchd).
    env = {**fake.env, "PATH": str(tmp_path / "empty"), "CMUX_BIN": str(fake.cmux)}
    done = subprocess.run([sys.executable, str(DRIVER)], input='{"verb": "tabs"}',
                          capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["tabs"]


def test_cmux_open_script_uses_cmux_bin(fake, tmp_path):
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "python3").symlink_to(sys.executable)
    env = {**fake.env, "PATH": f"{shim}:/usr/bin:/bin", "CMUX_BIN": str(fake.cmux)}
    done = subprocess.run(["bash", str(SKILL / "scripts" / "cmux-open.sh"), "where", "--workspace", "Platform"],
                          capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "target: workspace:3 (Platform)" in done.stdout


def test_control_found_by_alias_is_decorated_and_ordered_by_its_ref(fake):
    # Finding 6a
    fake.files["FAKE_CMUX_TREE"].write_text(json.dumps(TREE).replace('"Customer A"', '"Hub"'))
    report = fake.answer(_open(_plan(control={"name": "Control", "aliases": ["Hub"]})))["report"]
    argv = fake.argv()
    assert ["reorder-workspace", "--workspace", "workspace:4", "--index", "0"] in argv
    assert not any("workspace missing" in line for line in report)
    assert not any(a[:2] == ["workspace", "create"] for a in argv)


def test_socket_tab_workspace_titles_lose_their_glyph_like_the_index():
    # Finding 6b
    tree = {"windows": [{"workspaces": [{"title": "\u25d0 Platform", "ref": "workspace:3", "panes": [
        {"surfaces": [{"ref": "surface:1", "type": "terminal", "title": "x"}]}]}]}]}
    assert drv.socket_tabs(tree)[0]["workspace"] == "Platform"
    assert drv.workspace_index(tree) == {"Platform": "workspace:3"}


def test_workspace_created_for_moved_tabs_reports_its_leftover_shell(fake):
    # Finding 6c: the starting shell is left open (the driver never closes a tab), and said so.
    plan = _plan({"name": "Research", "cwd": "/repo", "tabs": [
        {"slug": "inv", "label": "Invoices", "action": "open", "ref": "surface:95",
         "workspace": "Customer A", "ws_ref": "workspace:4"}]})
    report = fake.answer(_open(plan))["report"]
    assert any("starting shell" in line for line in report)
    assert not any("close" in " ".join(a) for a in fake.argv())


# ---------------------------------------------------------------- launch verb

def _launched(typed: str) -> str:
    """The command a typed launcher line runs: the launcher file without its start marker."""
    import re
    m = re.fullmatch(r"/bin/sh '([^']+)'", typed)
    assert m, typed
    lines = Path(m.group(1)).read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith(": > "))


LAUNCH_TABS = [{"label": "Alpha", "slug": "alpha", "command": "cd -- /repo && agent -n alpha 'go'"},
               {"label": "Beta", "slug": "beta", "command": "cd -- /repo && agent -n beta 'go'"}]


def test_launch_tabs_open_in_the_callers_workspace_and_keep_a_shell(fake):
    report = fake.answer({"verb": "launch", "tabs": LAUNCH_TABS, "target": "tab", "here": None})["report"]
    argv = fake.argv()
    new = [a for a in argv if a[0] == "new-surface"]
    assert len(new) == 2
    for a in new:
        assert a[a.index("--workspace") + 1] == "workspace:3"       # tree caller, not the selected one
        assert a[a.index("--focus") + 1] == "false"
        assert _launched(a[a.index("--command") + 1]).endswith(drv.KEEP_SHELL)
    renames = [a for a in argv if a[:3] == ["tab-action", "--action", "rename"]]
    assert [a[a.index("--title") + 1] for a in renames] == ["Alpha", "Beta"]
    assert len(report) == 2 and report[0].startswith("tab Alpha (surface:60")
    assert not any("close" in " ".join(a) for a in argv)


def test_launch_here_decides_the_workspace(fake):
    fake.answer({"verb": "launch", "tabs": LAUNCH_TABS[:1], "target": "tab", "here": "surface:95"})
    (new,) = [a for a in fake.argv() if a[0] == "new-surface"]
    assert new[new.index("--workspace") + 1] == "workspace:4"


def test_launch_without_a_caller_opens_nothing(fake):
    tree = json.loads(fake.files["FAKE_CMUX_TREE"].read_text())
    tree.pop("caller")
    fake.files["FAKE_CMUX_TREE"].write_text(json.dumps(tree))
    report = fake.answer({"verb": "launch", "tabs": LAUNCH_TABS, "target": "tab", "here": None})["report"]
    assert report and report[0].startswith("ERROR")
    assert not [a for a in fake.argv() if a[0] in ("new-surface", "workspace")]


def test_launch_workspace_target_creates_one_workspace_per_tab(fake):
    report = fake.answer({"verb": "launch", "tabs": LAUNCH_TABS, "target": "workspace", "here": None})["report"]
    creates = [a for a in fake.argv() if a[:2] == ["workspace", "create"]]
    assert len(creates) == 2
    assert creates[0][creates[0].index("--name") + 1] == "Alpha"
    assert creates[0][creates[0].index("--focus") + 1] == "false"
    assert _launched(creates[0][creates[0].index("--command") + 1]).endswith(drv.KEEP_SHELL)
    assert report[0].startswith("workspace Alpha (workspace:50)")
    assert not [a for a in fake.argv() if a[0] == "new-surface"]


def test_launch_area_target_opens_each_tab_in_its_named_workspace(fake):
    tabs = [{**LAUNCH_TABS[0], "workspace": "Customer A"}, {**LAUNCH_TABS[1], "workspace": "Customer B"}]
    report = fake.answer({"verb": "launch", "tabs": tabs, "target": "area", "here": None})["report"]
    new = [a for a in fake.argv() if a[0] == "new-surface"]
    assert [a[a.index("--workspace") + 1] for a in new] == ["workspace:4", "workspace:5"]   # across windows
    assert not [a for a in fake.argv() if a[:2] == ["workspace", "create"]]
    assert all(line.startswith("tab ") for line in report)


def test_launch_area_target_creates_a_missing_area_once_and_names_the_tab(fake):
    tabs = [{**LAUNCH_TABS[0], "workspace": "Research"}, {**LAUNCH_TABS[1], "workspace": "Research"}]
    report = fake.answer({"verb": "launch", "tabs": tabs, "target": "area", "here": None})["report"]
    argv = fake.argv()
    (create,) = [a for a in argv if a[:2] == ["workspace", "create"]]
    assert create[create.index("--name") + 1] == "Research"
    assert create[create.index("--focus") + 1] == "false"
    # the first tab IS the new workspace's starting tab: no stray shell is left behind
    assert len(create[create.index("--command") + 1].encode()) < 256
    new = [a for a in argv if a[0] == "new-surface"]
    assert [a[a.index("--workspace") + 1] for a in new] == ["workspace:50"]
    renames = [a for a in argv if a[:3] == ["tab-action", "--action", "rename"]]
    assert [a[a.index("--title") + 1] for a in renames] == ["Alpha", "Beta"]
    assert any("new workspace Research" in line for line in report)
    assert not any("close" in " ".join(a) for a in argv)


def test_launch_area_target_without_a_name_falls_back_to_the_caller(fake):
    fake.answer({"verb": "launch", "tabs": LAUNCH_TABS[:1], "target": "area", "here": None})
    (new,) = [a for a in fake.argv() if a[0] == "new-surface"]
    assert new[new.index("--workspace") + 1] == "workspace:3"


def test_launch_area_target_finds_a_workspace_by_its_alias(fake):
    tabs = [{**LAUNCH_TABS[0], "workspace": "Customers", "aliases": ["Customer A"]}]
    fake.answer({"verb": "launch", "tabs": tabs, "target": "area", "here": None})
    (new,) = [a for a in fake.argv() if a[0] == "new-surface"]
    assert new[new.index("--workspace") + 1] == "workspace:4"
    assert not [a for a in fake.argv() if a[:2] == ["workspace", "create"]]


def test_tabs_mark_the_tab_this_process_runs_in(monkeypatch):
    tree = {"windows": [{"workspaces": [{"title": "Control", "ref": "workspace:1", "panes": [{"surfaces": [
        {"type": "terminal", "ref": "surface:1", "id": "AAA", "title": "dashboard"},
        {"type": "terminal", "ref": "surface:2", "id": "BBB", "title": "Claude Code"}]}]}]}]}
    monkeypatch.setattr(drv, "read_tree", lambda: tree)
    monkeypatch.setattr(drv, "_load_json", lambda path: {})
    monkeypatch.setenv("CMUX_SURFACE_ID", "AAA")
    assert [t["is_self"] for t in drv.tabs()] == [True, False]
    monkeypatch.delenv("CMUX_SURFACE_ID")
    assert [t["is_self"] for t in drv.tabs()] == [False, False]


# ---------------------------------------------------------------- typing a command into a starting shell

# A real prompt: quotes, an umlaut, a newline, shell metacharacters, and far over the 1024 bytes
# a starting shell's line buffer (MAX_CANON) keeps; the rest and the Enter would be lost.
LONG_TEXT = ("You're the tab for 'alpha'. \u00dcber \"quotes\" $HOME `ticks` & ; |\nsecond line " + "x" * 1400)


def _typed(argv: list) -> list:
    return [a[a.index("--command") + 1] for a in argv if "--command" in a]


@pytest.mark.parametrize("target, extra", [("tab", {}), ("workspace", {}), ("area", {"workspace": "Customer A"}),
                                           ("area", {"workspace": "Research"})])
@pytest.mark.parametrize("text", [LONG_TEXT, LONG_TEXT.replace("\u00dc", "U")], ids=["umlaut", "ascii"])
def test_launch_types_only_a_short_line_and_the_command_arrives_intact(fake, tmp_path, target, extra, text):
    import shlex
    out = tmp_path / "arrived.txt"
    command = f"cd -- {shlex.quote(str(tmp_path))} && printf '%s' {shlex.quote(text)} > {shlex.quote(str(out))}"
    report = fake.answer({"verb": "launch", "tabs": [{"label": "Alpha", "slug": "alpha", "command": command, **extra}],
                          "target": target, "here": None})["report"]
    assert not any(line.startswith("ERROR") for line in report), report
    (typed,) = _typed(fake.argv())
    assert len(typed.encode()) < 256 and typed.isascii() and "\n" not in typed
    # run the typed line the way the new shell would; SHELL=true ends the KEEP_SHELL tail at once
    subprocess.run(typed, shell=True, env={**fake.env, "SHELL": "/usr/bin/true"}, check=True, timeout=30)
    assert out.read_text(encoding="utf-8") == text


def test_open_types_only_short_lines_too(fake):
    plan = {"control": {"name": "Control", "command": "cd -- /repo && agent " + "c" * 1200}, "workspaces": [
        {"name": "Research", "cwd": "/repo", "tabs": [
            {"slug": "a", "label": "A", "action": "new", "command": "cd -- /repo && agent " + "a" * 1200},
            {"slug": "b", "label": "B", "action": "new", "command": "cd -- /repo && agent " + "b" * 1200}]}]}
    fake.answer({"verb": "open", "plan": plan, "only": None, "resume": False, "here": None})
    typed = _typed(fake.argv())
    assert len(typed) >= 3 and all(len(t.encode()) < 256 for t in typed)


def test_a_launch_whose_command_never_starts_is_an_error_and_the_tab_keeps_its_label(fake):
    fake.lost = True       # the shell swallowed the typed line (busy rc file, lost Enter)
    report = fake.answer({"verb": "launch", "tabs": LAUNCH_TABS[:1], "target": "tab", "here": None})["report"]
    assert any(line.startswith("ERROR") and "did not start" in line and "Alpha" in line for line in report), report
    # The typed line may still run after a slow shell start: the tab keeps its label, so the slug
    # index still finds it and a later click goes to that agent instead of opening a second one.
    renames = [a[a.index("--title") + 1] for a in fake.argv() if a[:3] == ["tab-action", "--action", "rename"]]
    assert renames == ["Alpha"]


def test_a_launch_that_started_reports_success(fake):
    report = fake.answer({"verb": "launch", "tabs": LAUNCH_TABS, "target": "tab", "here": None})["report"]
    assert [line.split(" (")[0] for line in report] == ["tab Alpha", "tab Beta"]


def test_launch_area_target_matches_names_and_aliases_ignoring_case(fake):
    tabs = [{**LAUNCH_TABS[0], "workspace": "customer a"},
            {**LAUNCH_TABS[1], "workspace": "Elsewhere", "aliases": ["CUSTOMER B"]}]
    fake.answer({"verb": "launch", "tabs": tabs, "target": "area", "here": None})
    new = [a for a in fake.argv() if a[0] == "new-surface"]
    assert [a[a.index("--workspace") + 1] for a in new] == ["workspace:4", "workspace:5"]
    assert not [a for a in fake.argv() if a[:2] == ["workspace", "create"]]


@pytest.mark.parametrize("target, extra, where", [("tab", {}, "Platform"),
                                                  ("area", {"workspace": "Customer A"}, "Customer A"),
                                                  ("area", {"workspace": "Research"}, "Research")])
def test_launch_report_names_the_workspace_the_tab_went_to(fake, target, extra, where):
    report = fake.answer({"verb": "launch", "tabs": [{**LAUNCH_TABS[0], **extra}], "target": target,
                          "here": None})["report"]
    (line,) = [x for x in report if x.startswith("tab Alpha")]
    assert line.endswith(f" in {where}"), report


def test_control_opens_a_new_agent_tab_in_an_existing_control_workspace(fake):
    report = fake.answer({"verb": "control", "control": {"name": "Platform"}, "command": "claude",
                          "root": "/tmp/x"})["report"]
    tab = next(a for a in fake.argv() if a[:1] == ["new-surface"])
    assert tab[tab.index("--workspace") + 1] == "workspace:3"
    assert tab[tab.index("--command") + 1].startswith("claude")
    assert not any(a[:2] == ["workspace", "create"] for a in fake.argv())
    assert not any("close" in " ".join(a) for a in fake.argv())
    assert any("tab Platform in Platform" in line for line in report)


def test_control_creates_the_missing_control_workspace_with_the_agent(fake):
    fake.answer({"verb": "control", "control": {"name": "Hub", "color": "#37474F"}, "command": "claude -n hub",
                 "root": "/tmp/x"})
    create = next(a for a in fake.argv() if a[:2] == ["workspace", "create"])
    assert create[create.index("--name") + 1] == "Hub"
    assert create[create.index("--command") + 1] == "claude -n hub" + drv.KEEP_SHELL


def test_control_without_name_or_command_is_an_error(fake):
    assert fake.call({"verb": "control", "control": {}, "command": "claude"}).returncode == 1
    assert fake.call({"verb": "control", "control": {"name": "Hub"}, "command": " "}).returncode == 1


# ---------------------------------------------------------------- the optional verbs the cockpit steers with

def test_caps_name_every_verb_this_driver_serves(fake):
    caps = fake.answer({"verb": "caps"})["caps"]
    assert {"tabs", "sessions", "open", "launch", "send", "rename", "control", "focus", "key", "screen", "close"} <= set(caps)


def test_focus_key_screen_and_close_address_the_tab_in_its_workspace(fake):
    fake.answer({"verb": "focus", "tab": "surface:91"})
    fake.answer({"verb": "key", "tab": "surface:91", "key": "1"})
    fake.answer({"verb": "key", "tab": "surface:91", "key": "escape"})
    assert fake.answer({"verb": "screen", "tab": "surface:91", "lines": 40})["text"] == "OK"
    fake.answer({"verb": "close", "tab": "surface:91"})
    argv = fake.argv()
    assert ["select-workspace", "--workspace", "workspace:3"] in argv
    assert ["focus-panel", "--panel", "surface:91", "--workspace", "workspace:3"] in argv
    assert ["send-key", "--workspace", "workspace:3", "--surface", "surface:91", "1"] in argv
    assert ["send-key", "--workspace", "workspace:3", "--surface", "surface:91", "escape"] in argv
    assert ["read-screen", "--workspace", "workspace:3", "--surface", "surface:91", "--lines", "40"] in argv
    # --force: cmux refuses a surface with a live process otherwise, and a waiting agent is one
    assert ["close-surface", "--surface", "surface:91", "--force", "--workspace", "workspace:3"] in argv


@pytest.mark.parametrize("asked, read", [(40, "40"), (3000, "3000"), (5000, "5000"), (99999, "5000"), (0, "40")])
def test_screen_reads_the_scrollback_up_to_five_thousand_lines(fake, asked, read):
    fake.answer({"verb": "screen", "tab": "surface:91", "lines": asked})
    reads = [a for a in fake.argv() if a[0] == "read-screen"]
    assert reads[-1][reads[-1].index("--lines") + 1] == read


def test_keys_type_as_a_keyboard_does(fake):
    fake.answer({"verb": "keys", "tab": "surface:91", "keys": [
        {"text": "git st"}, {"key": "tab"}, {"key": "enter"}, {"key": "ctrl+c"}, {"text": "a\\nb"}, {"paste": "one\ntwo"}]})
    argv = fake.argv()
    where = ["--workspace", "workspace:3", "--surface", "surface:91"]
    # --force: without it cmux refuses a prompt that already holds text, and that is what typing makes
    assert ["send", "--force", *where, "--", "git st"] in argv
    assert ["send-key", "--force", *where, "tab"] in argv
    assert ["send-key", "--force", *where, "enter"] in argv
    assert ["send-key", "--force", *where, "ctrl+c"] in argv
    # cmux send reads a typed backslash and n as Enter: such text takes the paste path, unchanged
    assert ["send", "--paste", "--force", *where, "--", "a\\nb"] in argv
    assert ["send", "--paste", "--force", *where, "--", "one\ntwo"] in argv


def test_keys_refuse_a_step_they_do_not_know(fake):
    done = fake.call({"verb": "keys", "tab": "surface:91", "keys": [{"key": "f13"}]})
    assert done.returncode == 1 and "key" in json.loads(done.stdout)["error"]


def test_a_key_outside_the_fixed_set_is_refused(fake):
    done = fake.call({"verb": "key", "tab": "surface:91", "key": "ctrl-c"})
    assert done.returncode == 1 and "key" in json.loads(done.stdout)["error"]


# ---------------------------------------------------------------- workspaces (read only, for the cockpit's sidebar)

WS_JSON = {"window_ref": "window:1", "workspaces": [
    {"ref": "workspace:3", "id": "WS-UUID-1", "title": "Platform", "custom_color": "#6A1B9A", "description": "Own work",
     "pinned": True, "current_directory": "/home/u/bridge", "latest_submitted_message": "ja", "selected": True,
     "latest_submitted_at": "2026-10-18T12:11:44.073Z", "index": 0, "remote": {"state": "disconnected"}},
    {"ref": "workspace:4", "id": "WS-UUID-2", "title": "Customer A", "custom_color": None, "description": None,
     "pinned": False, "current_directory": "/home/u/other-bridge", "index": 1}]}

SIDEBAR = {"workspace:3": "tab=WS-UUID-1\ncolor=#6A1B9A\ncwd=/home/u/bridge\ngit_branch=user/alice dirty\npr=none\n"
                          "status_count=2\n  program_status=claude-code · Reading files icon=bolt.fill priority=2\n"
                          "  claude_code=Running icon=bolt.fill color=#4C8DFF work=running\nlog_count=0\n",
           "workspace:4": "tab=WS-UUID-2\ngit_branch=main\npr=#12\nstatus_count=0\n"}

NOTES = [{"workspace_id": "WS-UUID-2", "is_read": False, "subtitle": "Waiting"},
         {"workspace_id": "WS-UUID-2", "is_read": False, "subtitle": "Completed"},
         {"workspace_id": "WS-UUID-1", "is_read": True, "subtitle": "Completed"}]


def test_workspaces_carry_what_the_cmux_sidebar_shows(fake):
    fake.files["FAKE_CMUX_WSJSON"].write_text(json.dumps(WS_JSON))
    fake.files["FAKE_CMUX_SIDEBAR"].write_text(json.dumps(SIDEBAR))
    fake.files["FAKE_CMUX_NOTES"].write_text(json.dumps(NOTES))
    ws = fake.answer({"verb": "workspaces"})["workspaces"]
    assert [w["title"] for w in ws] == ["Platform", "Customer A"]
    p, a = ws
    assert p == {"ref": "workspace:3", "id": "WS-UUID-1", "title": "Platform", "color": "#6A1B9A",
                 "color_name": "Purple", "description": "Own work", "pinned": True, "selected": True, "cwd": "/home/u/bridge",
                 "branch": "user/alice", "dirty": True, "pr": None, "unread": 0,
                 "latest": {"text": "ja", "at": "2026-10-18T12:11:44.073Z"},
                 "statuses": [{"name": "program_status", "text": "claude-code · Reading files", "color": None},
                              {"name": "claude_code", "text": "Running", "color": "#4C8DFF"}]}
    assert a["branch"] == "main" and a["dirty"] is False and a["pr"] == "#12" and a["unread"] == 2
    assert a["color"] is None and a["color_name"] is None and a["latest"] is None and a["statuses"] == []
    # read only: nothing that types, focuses or selects
    assert not [c for c in fake.argv() if c[:1] and c[0] in ("send", "send-key", "focus-panel", "select-workspace")]


def test_a_workspace_whose_sidebar_cannot_be_read_still_shows(fake):
    fake.files["FAKE_CMUX_WSJSON"].write_text(json.dumps(WS_JSON))
    fake.fail = "sidebar-state"
    ws = fake.answer({"verb": "workspaces"})["workspaces"]
    assert [w["title"] for w in ws] == ["Platform", "Customer A"] and ws[0]["branch"] is None


def test_workspaces_are_unknown_when_cmux_refuses_the_list(fake):
    fake.fail = "--json workspace"
    done = fake.call({"verb": "workspaces"})
    assert done.returncode != 0 and "error" in json.loads(done.stdout)


def test_caps_name_workspaces(fake):
    assert "workspaces" in fake.answer({"verb": "caps"})["caps"]


# ---------------------------------------------------------------- rename a workspace, where a tab's state came from

def test_rename_workspace_calls_workspace_rename_with_title(fake):
    report = fake.answer({"verb": "rename_workspace", "workspace": "workspace:4", "title": "Invoices"})["report"]
    assert ["workspace", "rename", "workspace:4", "--title", "Invoices"] in fake.argv()
    assert report and "Invoices" in report[0]


def test_rename_workspace_that_cmux_rejects_is_a_driver_error(fake):
    fake.fail = "workspace rename"
    done = fake.call({"verb": "rename_workspace", "workspace": "workspace:99", "title": "Invoices"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_rename_workspace_needs_a_ref_and_a_title(fake):
    for req in ({"workspace": "", "title": "X"}, {"workspace": "workspace:4", "title": ""}, {"title": "X"}):
        done = fake.call({"verb": "rename_workspace", **req})
        assert done.returncode == 1 and "error" in json.loads(done.stdout)
    assert not [a for a in fake.argv() if a[:2] == ["workspace", "rename"]]


def test_tabs_report_where_the_state_came_from(fake):
    by_name = {t["name"]: t for t in fake.answer({"verb": "tabs"})["tabs"]}
    assert by_name["Fix login"]["state_source"] == "hook"          # the hook file knows this surface
    assert by_name["Invoice export"]["state_source"] == "glyph"    # nothing but its title to go by
    hooks = {"activeSessionsBySurface": {}, "sessions": {}}
    session = {"windows": [{"tabManager": {"workspaces": [{"customTitle": "W", "panels": [
        {"id": "A", "type": "terminal", "title": "✳ idle"}, {"id": "B", "type": "terminal", "title": "user@host:~"}]}]}}]}
    sources = {t["surface"]: (t["state"], t["state_source"]) for t in drv.live_tabs(session, hooks)}
    assert sources == {"A": ("waiting", "glyph"), "B": ("shell", "glyph")}


def test_caps_name_rename_workspace(fake):
    assert "rename_workspace" in fake.answer({"verb": "caps"})["caps"]


# ---------------------------------------------------------------- move a tab, colour and describe a workspace

def test_move_tab_calls_move_surface_without_focus(fake):
    report = fake.answer({"verb": "move_tab", "tab": "surface:95", "workspace": "workspace:3"})["report"]
    assert ["move-surface", "--surface", "surface:95", "--workspace", "workspace:3", "--focus", "false"] in fake.argv()
    assert report and not report[0].startswith("ERROR")
    fake.answer({"verb": "move_tab", "tab": "surface:91", "workspace": "workspace:4", "index": 1})
    assert ["move-surface", "--surface", "surface:91", "--workspace", "workspace:4", "--focus", "false",
            "--index", "1"] in fake.argv()


def test_move_tab_refuses_the_last_tab_of_a_workspace(fake):
    # Customer B (workspace:5) holds one tab only: moving it would drop that workspace
    report = fake.answer({"verb": "move_tab", "tab": "surface:97", "workspace": "workspace:3"})["report"]
    assert report[0].startswith("ERROR") and "last tab" in report[0]
    assert not [a for a in fake.argv() if a[:1] == ["move-surface"]]


def test_move_tab_needs_open_refs(fake):
    for req in ({"tab": "surface:404", "workspace": "workspace:3"}, {"tab": "surface:95", "workspace": "workspace:99"},
                {"tab": "", "workspace": "workspace:3"}, {"tab": "surface:95", "workspace": "workspace:3", "index": -1}):
        done = fake.call({"verb": "move_tab", **req})
        assert done.returncode == 1 and "error" in json.loads(done.stdout), req
    assert not [a for a in fake.argv() if a[:1] == ["move-surface"]]


def test_set_color_sends_the_hex_and_clear_color(fake):
    fake.answer({"verb": "set_color", "workspace": "workspace:4", "color": "Teal"})
    fake.answer({"verb": "set_color", "workspace": "workspace:4", "color": None})
    assert ["workspace-action", "--workspace", "workspace:4", "--action", "set-color", "--color", "#006B6B"] in fake.argv()
    assert ["workspace-action", "--workspace", "workspace:4", "--action", "clear-color"] in fake.argv()
    done = fake.call({"verb": "set_color", "workspace": "workspace:4", "color": "#123456"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_set_description_and_clear_description(fake):
    fake.answer({"verb": "set_description", "workspace": "workspace:4", "text": "Invoices and exports"})
    fake.answer({"verb": "set_description", "workspace": "workspace:4", "text": None})
    assert ["workspace-action", "--workspace", "workspace:4", "--action", "set-description",
            "--description", "Invoices and exports"] in fake.argv()
    assert ["workspace-action", "--workspace", "workspace:4", "--action", "clear-description"] in fake.argv()
    done = fake.call({"verb": "set_description", "workspace": "", "text": "x"})
    assert done.returncode == 1


def test_workspaces_report_a_palette_name_for_a_known_hex(fake):
    rows = json.loads(json.dumps(WS_JSON))
    rows["workspaces"][1]["custom_color"] = "#123456"
    fake.files["FAKE_CMUX_WSJSON"].write_text(json.dumps(rows))
    p, a = fake.answer({"verb": "workspaces"})["workspaces"]
    assert (p["color"], p["color_name"]) == ("#6A1B9A", "Purple")
    assert (a["color"], a["color_name"]) == ("#123456", None)


def test_the_driver_palette_is_the_workplace_palette():
    assert drv.PALETTE == load_core().COLORS


def test_caps_name_the_layout_verbs(fake):
    assert {"move_tab", "set_color", "set_description"} <= set(fake.answer({"verb": "caps"})["caps"])


# ---------------------------------------------------------------- a new tab, a new workspace, a workspace closed

def test_caps_name_the_verbs_that_make_and_close(fake):
    assert {"new_tab", "new_workspace", "close_workspace"} <= set(fake.answer({"verb": "caps"})["caps"])


def test_new_tab_opens_one_titled_tab_in_the_named_workspace_and_answers_its_ref(fake):
    answer = fake.answer({"verb": "new_tab", "workspace": "workspace:4", "title": "Scratch",
                          "command": "cd -- /repo && agent -n scratch"})
    assert answer["ref"] == "surface:60"
    assert answer["report"] == ["tab Scratch (surface:60) in Customer A"]
    argv = fake.argv()
    (new,) = [a for a in argv if a[0] == "new-surface"]
    assert new[new.index("--workspace") + 1] == "workspace:4"
    assert new[new.index("--focus") + 1] == "false"                 # a new tab never takes the focus
    assert _launched(new[new.index("--command") + 1]) == "cd -- /repo && agent -n scratch" + drv.KEEP_SHELL
    assert ["tab-action", "--action", "rename", "--tab", "surface:60", "--title", "Scratch",
            "--workspace", "workspace:4"] in argv
    assert not any(a[0] in ("select-workspace", "focus-panel") or "close" in " ".join(a) for a in argv)


def test_new_tab_without_a_command_is_a_plain_shell_and_without_a_title_keeps_its_own(fake):
    answer = fake.answer({"verb": "new_tab", "workspace": "workspace:3", "title": None, "command": None})
    assert answer["ref"] == "surface:60" and answer["report"] == ["tab surface:60 in Platform"]
    (new,) = [a for a in fake.argv() if a[0] == "new-surface"]
    assert new == ["new-surface", "--workspace", "workspace:3", "--focus", "false"]
    assert not [a for a in fake.argv() if a[:3] == ["tab-action", "--action", "rename"]]


def test_new_tab_types_only_a_short_line_and_the_command_arrives_intact(fake, tmp_path):
    import shlex
    out = tmp_path / "arrived.txt"
    command = f"cd -- {shlex.quote(str(tmp_path))} && printf '%s' {shlex.quote(LONG_TEXT)} > {shlex.quote(str(out))}"
    answer = fake.answer({"verb": "new_tab", "workspace": "workspace:3", "title": "Long", "command": command})
    assert not any(line.startswith("ERROR") for line in answer["report"]), answer
    (typed,) = _typed(fake.argv())
    assert len(typed.encode()) < 256 and typed.isascii() and "\n" not in typed
    subprocess.run(typed, shell=True, env={**fake.env, "SHELL": "/usr/bin/true"}, check=True, timeout=30)
    assert out.read_text(encoding="utf-8") == LONG_TEXT


def test_new_tab_whose_command_never_starts_is_an_error_line_but_still_answers_the_tab(fake):
    fake.lost = True
    answer = fake.answer({"verb": "new_tab", "workspace": "workspace:3", "title": "Late", "command": "agent"})
    assert answer["ref"] == "surface:60"
    assert any(line.startswith("ERROR") and "did not start" in line and "Late" in line for line in answer["report"])


def test_new_tab_needs_an_open_workspace_and_a_clean_title(fake):
    for req in ({"workspace": "workspace:99"}, {"workspace": ""}, {}, {"workspace": "workspace:3", "title": 7},
                {"workspace": "workspace:3", "command": 7}):
        done = fake.call({"verb": "new_tab", **req})
        assert done.returncode == 1 and "error" in json.loads(done.stdout), req
    assert not [a for a in fake.argv() if a[0] == "new-surface"]


def test_new_tab_that_cmux_refuses_is_a_driver_error(fake):
    fake.fail = "new-surface"
    done = fake.call({"verb": "new_tab", "workspace": "workspace:3", "title": "X", "command": None})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_new_workspace_creates_one_with_title_folder_colour_and_command_and_answers_both_refs(fake, tmp_path):
    answer = fake.answer({"verb": "new_workspace", "title": "Research", "color": "Teal", "cwd": str(tmp_path),
                          "command": "cd -- /repo && agent -n research"})
    assert answer["ws_ref"] == "workspace:50" and answer["ref"] == "surface:61"
    assert answer["report"] == ["workspace Research (workspace:50)"]
    argv = fake.argv()
    (create,) = [a for a in argv if a[:2] == ["workspace", "create"]]
    assert create[create.index("--name") + 1] == "Research"
    assert create[create.index("--cwd") + 1] == str(tmp_path)
    assert create[create.index("--focus") + 1] == "false"
    assert _launched(create[create.index("--command") + 1]) == "cd -- /repo && agent -n research" + drv.KEEP_SHELL
    assert ["workspace-action", "--workspace", "workspace:50", "--action", "set-color", "--color", "#006B6B"] in argv
    assert not any(a[0] in ("select-workspace", "focus-panel") or "close" in " ".join(a) for a in argv)


def test_new_workspace_without_a_command_is_a_plain_shell_in_the_bridge_folder(fake):
    answer = fake.answer({"verb": "new_workspace", "title": "Plain"})
    assert answer["ws_ref"] == "workspace:50" and answer["ref"] == "surface:61"
    (create,) = [a for a in fake.argv() if a[:2] == ["workspace", "create"]]
    assert "--command" not in create and create[create.index("--cwd") + 1] == str(drv.ROOT)
    assert not [a for a in fake.argv() if a[0] == "workspace-action"]


def test_new_workspace_whose_command_never_starts_is_an_error_line_but_still_answers_both_refs(fake):
    fake.lost = True
    answer = fake.answer({"verb": "new_workspace", "title": "Late", "command": "agent"})
    assert answer["ws_ref"] == "workspace:50" and answer["ref"] == "surface:61"
    assert any(line.startswith("ERROR") and "did not start" in line for line in answer["report"])


def test_new_workspace_that_cmux_refuses_is_a_driver_error(fake):
    fake.fail = "workspace create"
    done = fake.call({"verb": "new_workspace", "title": "X"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)


def test_new_workspace_needs_a_title_and_takes_a_palette_colour_only(fake):
    for req in ({}, {"title": ""}, {"title": "  "}, {"title": 7}, {"title": "X", "color": "#123456"},
                {"title": "X", "color": "teal"}, {"title": "X", "command": 7}, {"title": "X", "cwd": 7}):
        done = fake.call({"verb": "new_workspace", **req})
        assert done.returncode == 1 and "error" in json.loads(done.stdout), req
    assert not [a for a in fake.argv() if a[:2] == ["workspace", "create"]]


def test_close_workspace_closes_that_one_by_its_ref(fake):
    report = fake.answer({"verb": "close_workspace", "workspace": "workspace:4"})["report"]
    assert report == ["workspace:4 closed"]
    assert [a for a in fake.argv() if "close" in " ".join(a)] == [["close-workspace", "--workspace", "workspace:4"]]


def test_close_workspace_needs_an_open_ref_and_never_closes_the_last_one_of_a_window(fake):
    for req in ({"workspace": "workspace:99"}, {"workspace": ""}, {}):
        done = fake.call({"verb": "close_workspace", **req})
        assert done.returncode == 1 and "error" in json.loads(done.stdout), req
    # Customer B is the only workspace of its window: closing it would close the window
    report = fake.answer({"verb": "close_workspace", "workspace": "workspace:5"})["report"]
    assert report[0].startswith("ERROR") and "last workspace" in report[0]
    assert not [a for a in fake.argv() if a[:1] == ["close-workspace"]]


def test_close_workspace_that_cmux_refuses_is_a_driver_error(fake):
    fake.fail = "close-workspace"
    done = fake.call({"verb": "close_workspace", "workspace": "workspace:4"})
    assert done.returncode == 1 and "error" in json.loads(done.stdout)
