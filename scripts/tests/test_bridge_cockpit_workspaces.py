"""Workspace rules: the fields a workspace adds to its definition, what a child inherits, archive, restore and delete.

Drives the real scripts/workspace.py on a throwaway user/* repo, so the branch gate is the real one.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ENGINE = Path(__file__).resolve().parents[1] / "workspace.py"


def git(cwd, *argv):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *argv], cwd=cwd, env=env, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "bridge"
    (root / "workflow/workspaces").mkdir(parents=True)
    git(root, "init", "-q", "-b", "user/test")
    git(root, "commit", "-q", "--allow-empty", "-m", "start")
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path / "wsreg"))
    monkeypatch.delenv("BRIDGE_OVERLAY_ALLOW_ANY_BRANCH", raising=False)
    return root


def ws(root, *argv):
    return subprocess.run(["python3", str(ENGINE), "--repo-root", str(root), *argv], capture_output=True, text=True)


def define(root, ws_id, **fields):
    data = {"schema_version": 1, "id": ws_id, "title": ws_id.title(), **fields}
    (root / f"workflow/workspaces/{ws_id}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def show(root, ws_id):
    res = ws(root, "show", ws_id, "--json")
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_a_child_inherits_what_it_does_not_set(repo):
    define(repo, "acme", area="Acme", refs={"persona": "work", "design": "acme"},
           writing={"style_skill": "acme-style", "mail_profile": "acme"},
           boundary={"level": "room", "skills": ["mail-draft", "acme-ops"], "off_topic": "refuse"})
    define(repo, "acme-billing", parent="acme", area="Billing", refs={"project": "billing"},
           boundary={"skills": ["acme-ops"]})
    got = show(repo, "acme-billing")
    assert got["refs"] == {"persona": "work", "design": "acme", "project": "billing"}
    assert got["writing"] == {"style_skill": "acme-style", "mail_profile": "acme"}
    assert got["boundary"] == {"level": "room", "skills": ["acme-ops"], "off_topic": "refuse"}
    assert got["area"] == "Billing"
    assert "writing.style_skill" in got["inherited"] and "refs.project" not in got["inherited"]


def test_a_child_without_an_area_stands_under_its_parents(repo):
    define(repo, "acme", area="Acme")
    define(repo, "acme-billing", parent="acme")
    assert show(repo, "acme-billing")["area"] == "Acme"


def test_validate_passes_a_narrower_child(repo):
    define(repo, "acme", boundary={"level": "room", "skills": ["a", "b"]})
    define(repo, "acme-billing", parent="acme", boundary={"level": "wall", "skills": ["a"]})
    res = ws(repo, "validate")
    assert res.returncode == 0, res.stdout


@pytest.mark.parametrize("child,needle", [
    ({"boundary": {"level": "view"}}, "looser"),
    ({"boundary": {"skills": ["a", "c"]}}, "c"),
    ({"parent": "nobody"}, "nobody"),
])
def test_validate_refuses_a_child_that_widens_or_dangles(repo, child, needle):
    define(repo, "acme", boundary={"level": "room", "skills": ["a", "b"]})
    define(repo, "acme-billing", **{"parent": "acme", **child})
    res = ws(repo, "validate")
    assert res.returncode == 1
    assert "FAIL" in res.stdout and needle in res.stdout


def test_validate_refuses_a_third_level(repo):
    define(repo, "a")
    define(repo, "b", parent="a")
    define(repo, "c", parent="b")
    res = ws(repo, "validate")
    assert res.returncode == 1 and "two levels" in res.stdout


def test_create_takes_area_and_parent(repo):
    define(repo, "acme")
    res = ws(repo, "create", "acme-billing", "--area", "Billing", "--parent", "acme")
    assert res.returncode == 0, res.stderr
    got = show(repo, "acme-billing")
    assert (got["area"], got["parent"]) == ("Billing", "acme")


def test_create_refuses_an_unknown_parent(repo):
    res = ws(repo, "create", "acme-billing", "--parent", "acme")
    assert res.returncode == 1
    assert not (repo / "workflow/workspaces/acme-billing.yaml").exists()


def test_list_json_carries_every_workspace_with_its_children(repo):
    define(repo, "acme", area="Acme")
    define(repo, "acme-billing", parent="acme")
    rows = {r["id"]: r for r in json.loads(ws(repo, "list", "--json").stdout)}
    assert rows["acme"]["children"] == ["acme-billing"]
    assert rows["acme-billing"]["archived"] is False


def test_archive_and_restore_keep_the_file(repo):
    define(repo, "acme")
    assert ws(repo, "archive", "acme").returncode == 0
    assert show(repo, "acme")["archived"] is True
    assert ws(repo, "restore", "acme").returncode == 0
    assert show(repo, "acme")["archived"] is False
    assert "archived_at" not in yaml.safe_load((repo / "workflow/workspaces/acme.yaml").read_text(encoding="utf-8"))


def test_archive_refuses_a_parent_with_a_live_child(repo):
    define(repo, "acme")
    define(repo, "acme-billing", parent="acme")
    res = ws(repo, "archive", "acme")
    assert res.returncode == 1 and "acme-billing" in res.stderr


def test_restore_refuses_a_child_of_an_archived_parent(repo):
    define(repo, "acme")
    define(repo, "acme-billing", parent="acme", archived_at="2026-01-01T00:00:00Z")
    assert ws(repo, "archive", "acme").returncode == 0
    res = ws(repo, "restore", "acme-billing")
    assert res.returncode == 1 and "acme" in res.stderr


def test_the_verbs_keep_to_the_branch_gate(repo):
    define(repo, "acme")
    git(repo, "checkout", "-q", "-b", "main")
    for verb in ("archive", "restore", "delete"):
        assert ws(repo, verb, "acme").returncode == 1
    assert (repo / "workflow/workspaces/acme.yaml").exists()


def test_delete_keeps_a_copy_in_the_trash(repo):
    define(repo, "acme")
    res = ws(repo, "delete", "acme")
    assert res.returncode == 0, res.stderr
    assert not (repo / "workflow/workspaces/acme.yaml").exists()
    assert list((repo / ".bridge/trash").glob("acme-*/acme.yaml"))


def test_delete_refuses_while_a_child_stands(repo):
    define(repo, "acme")
    define(repo, "acme-billing", parent="acme")
    res = ws(repo, "delete", "acme")
    assert res.returncode == 1 and "acme-billing" in res.stderr
    assert (repo / "workflow/workspaces/acme.yaml").exists()


def test_delete_refuses_a_subscribed_overlay(repo):
    define(repo, "acme", overlays=[{"name": "org"}])
    res = ws(repo, "delete", "acme")
    assert res.returncode == 1 and "org" in res.stderr


def clone(repo, tmp_path, ws_id="acme"):
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    (origin / "f").write_text("x")
    git(origin, "add", "f")
    git(origin, "commit", "-q", "-m", "one")
    assert ws(repo, "create", ws_id).returncode == 0
    res = ws(repo, "subscribe", ws_id, f"file://{origin}", "--role", "code")
    assert res.returncode == 0, res.stderr
    return repo / f".bridge/workspaces/{ws_id}/origin"


def test_delete_moves_a_clean_pushed_clone_to_the_trash(repo, tmp_path):
    path = clone(repo, tmp_path)
    res = ws(repo, "delete", "acme")
    assert res.returncode == 0, res.stderr
    assert not path.exists()
    assert list((repo / ".bridge/trash").glob("acme-*/clones/origin/f"))
    assert "acme" not in (yaml.safe_load((repo / "workspaces.lock.yaml").read_text(encoding="utf-8")) or {}).get("workspaces", {})


@pytest.mark.parametrize("dirty", ["uncommitted", "unpushed"])
def test_delete_refuses_work_that_only_the_clone_holds(repo, tmp_path, dirty):
    path = clone(repo, tmp_path)
    (path / "new").write_text("y")
    if dirty == "unpushed":
        git(path, "add", "new")
        git(path, "commit", "-q", "-m", "two")
    res = ws(repo, "delete", "acme")
    assert res.returncode == 1 and "origin" in res.stderr
    assert (repo / "workflow/workspaces/acme.yaml").exists() and path.exists()


def test_dry_run_says_what_stops_a_delete_and_changes_nothing(repo):
    define(repo, "acme")
    define(repo, "acme-billing", parent="acme")
    res = ws(repo, "delete", "acme", "--dry-run", "--json")
    assert res.returncode == 0
    got = json.loads(res.stdout)
    assert got["blockers"] and "acme-billing" in got["blockers"][0]
    assert (repo / "workflow/workspaces/acme.yaml").exists()


def test_schema_takes_the_new_fields(repo):
    pytest.importorskip("jsonschema")
    import jsonschema
    schema = yaml.safe_load((ENGINE.parents[1] / "docs/schemas/workspace.schema.yaml").read_text(encoding="utf-8"))
    good = {"schema_version": 1, "id": "a", "title": "A", "area": "A", "parent": "b", "archived_at": "2026-01-01T00:00:00Z",
            "refs": {"context": "c", "mandant": "m", "persona": "p", "project": "q", "briefing": "b", "design": "d"},
            "writing": {"style_skill": "s", "mail_profile": "m"},
            "boundary": {"level": "wall", "skills": ["s"], "off_topic": "hand_over", "shared_repos": ["r"], "mixed_records": "ask"}}
    jsonschema.validate(good, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**good, "boundary": {"level": "fort"}}, schema)


# ---------------------------------------------------------------- the cockpit: Settings, Workspaces

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.runner import RunResult  # noqa: E402

AREAS_CFG = """
workplace:
  workspaces:
    - {name: Acme, description: "a customer"}
    - {name: Billing, description: "part of it"}
    - {name: Home, description: "the house"}
"""


@pytest.fixture
def cockpit(tmp_path):
    w = World(tmp_path, config=AREAS_CFG)
    (w.root / "workflow/workspaces").mkdir(parents=True, exist_ok=True)
    yield w
    w.close()


def items(w):
    return {i["area"]: i for i in w.app.workspaces.state()["items"]}


def test_every_area_stands_in_the_list_with_or_without_a_file(cockpit):
    define(cockpit.root, "acme", area="Acme", boundary={"level": "room"}, writing={"style_skill": "acme-style"})
    got = items(cockpit)
    assert set(got) >= {"Acme", "Billing", "Home"}
    assert (got["Acme"]["id"], got["Acme"]["level"], got["Acme"]["style"]) == ("acme", "room", "acme-style")
    assert got["Home"]["id"] is None


def test_a_file_change_shows_without_a_restart(cockpit):
    assert items(cockpit)["Home"]["id"] is None
    define(cockpit.root, "home", area="Home")
    assert items(cockpit)["Home"]["id"] == "home"


def test_a_switch_is_kept_beside_the_config_and_survives_a_restart(cockpit):
    before = (cockpit.root / "bridge-config.yaml").read_text(encoding="utf-8")
    res = cockpit.act("workspace_switch", area="Home", on=False)
    assert res["workspaces"]["off"] == ["Home"]
    assert (cockpit.root / "bridge-config.yaml").read_text(encoding="utf-8") == before
    assert cockpit.app.workspaces.__class__(cockpit.app).state()["off"] == ["Home"]
    assert cockpit.act("workspace_switch", area="Home", on=True)["workspaces"]["off"] == []


def test_a_switch_takes_the_area_in_any_spelling_and_refuses_an_unknown_one(cockpit):
    assert cockpit.act("workspace_switch", area="home", on=False)["workspaces"]["off"] == ["Home"]
    with pytest.raises(ActionError):
        cockpit.act("workspace_switch", area="Nowhere", on=False)


def test_an_off_parent_holds_its_child_and_an_archived_one_counts_as_off(cockpit):
    define(cockpit.root, "acme", area="Acme")
    define(cockpit.root, "acme-billing", parent="acme", area="Billing")
    define(cockpit.root, "home", area="Home", archived_at="2026-01-01T00:00:00Z")
    cockpit.act("workspace_switch", area="Acme", on=False)
    state = cockpit.app.workspaces.state()
    assert sorted(state["off"]) == ["Acme", "Billing", "Home"]
    got = {i["area"]: i for i in state["items"]}
    assert got["Billing"]["held_by"] == "Acme"
    assert got["Home"]["archived"] is True


def test_archive_restore_and_delete_go_through_the_engine(cockpit):
    define(cockpit.root, "home", area="Home")
    cockpit.act("workspace_archive", slug="home")
    cockpit.act("workspace_restore", slug="home")
    cockpit.act("workspace_delete", slug="home")
    calls = [c for c in cockpit.runner.calls if any(str(a).endswith("workspace.py") for a in c)]
    assert [c[-2:] for c in calls] == [["archive", "home"], ["restore", "home"], ["delete", "home"]]


def test_delete_refuses_while_a_tab_of_the_area_is_open(cockpit):
    define(cockpit.root, "home", area="Home")
    with cockpit.app.tabs.lock:
        cockpit.app.tabs.tabs = [*cockpit.app.tabs.tabs, {"ref": "tab:9", "name": "x", "workspace": "Home"}]
    with pytest.raises(ActionError) as raised:
        cockpit.act("workspace_delete", slug="home")
    assert raised.value.status == 409
    assert not [c for c in cockpit.runner.calls if "delete" in c]


def test_an_engine_refusal_reaches_the_page_in_its_words(cockpit):
    define(cockpit.root, "home", area="Home")
    refused = RunResult(False, 1, "", "workspace: cannot delete 'home': children: x.\n", 0)
    cockpit.runner.handlers["workspace.--repo-root"] = lambda argv: refused
    with pytest.raises(ActionError) as raised:
        cockpit.act("workspace_delete", slug="home")
    assert "children: x" in raised.value.message


def test_sources_are_inherited_and_reach_the_page(cockpit):
    define(cockpit.root, "acme", area="Acme", sources={"calendars": ["Work"], "cost_center": "acme-cloud"})
    define(cockpit.root, "acme-billing", parent="acme", area="Billing")
    got = items(cockpit)
    assert got["Acme"]["calendars"] == ["Work"]
    assert (got["Billing"]["calendars"], got["Billing"]["cost_center"]) == (["Work"], "acme-cloud")
    assert got["Home"]["calendars"] is None


def test_the_tags_of_an_area_come_from_its_config(tmp_path):
    cfg = """
workplace:
  workspaces:
    - {name: Acme, aliases: [AC], contexts: [acme-ops], repos: ["org/acme-*", "org/billing"]}
"""
    w = World(tmp_path, config=cfg)
    try:
        assert dict(w.app.cfg.area_tags)["Acme"] == ("Acme", "AC", "acme-ops", "acme-*", "billing")
    finally:
        w.close()
