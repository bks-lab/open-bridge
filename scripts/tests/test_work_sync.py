# SPDX-License-Identifier: MIT
"""scripts/work-sync.py against a real bare origin: what an always-on clone commits and pushes for a person."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "work-sync.py"
BRANCH = "user/demo"


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True, check=check)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Clones:
    def __init__(self, base: Path):
        self.origin = base / "origin.git"
        self.host = base / "host"
        self.other = base / "other"
        git(base, "init", "-q", "--bare", "-b", BRANCH, str(self.origin))
        git(base, "clone", "-q", str(self.origin), str(self.other), check=False)
        git(self.other, "checkout", "-q", "-B", BRANCH)
        write(self.other / ".gitattributes", "work/log.md merge=union\n")
        write(self.other / "work/log.md", "# log\n")
        write(self.other / "work/board.md", "board\n")
        write(self.other / "work/tasks/a/STATUS.md", "one\n")
        write(self.other / "scripts/tool.py", "x\n")
        git(self.other, "add", "-A")
        git(self.other, "commit", "-qm", "seed")
        git(self.other, "push", "-q", "origin", BRANCH)
        git(base, "clone", "-q", "-b", BRANCH, str(self.origin), str(self.host))
        git(self.host, "config", "user.email", "h@h")
        git(self.host, "config", "user.name", "host")

    def sync(self, *paths: str, actor: str = "pat", extra: tuple = ()) -> subprocess.CompletedProcess:
        argv = [sys.executable, str(SCRIPT), "--root", str(self.host), "--actor", actor, *extra]
        for path in paths:
            argv += ["--path", path]
        return subprocess.run(argv, capture_output=True, text=True, timeout=60)

    def on_origin(self, path: str) -> str:
        return git(self.origin, "show", f"{BRANCH}:{path}").stdout


@pytest.fixture
def world(tmp_path: Path) -> Clones:
    return Clones(tmp_path)


def test_commits_and_pushes_the_named_path(world):
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    done = world.sync("work/tasks/a/STATUS.md")
    assert done.returncode == 0, done.stderr
    assert world.on_origin("work/tasks/a/STATUS.md") == "two\n"
    assert "pat" in git(world.host, "log", "-1", "--format=%s").stdout


def test_leaves_every_other_dirty_file_alone(world):
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    write(world.host / "work/tasks/b/STATUS.md", "someone else's\n")
    assert world.sync("work/tasks/a/STATUS.md").returncode == 0
    assert "work/tasks/b" not in git(world.origin, "ls-tree", "-r", "--name-only", BRANCH).stdout
    assert (world.host / "work/tasks/b/STATUS.md").read_text() == "someone else's\n"


@pytest.mark.parametrize("path", ["scripts/tool.py", "bridge-config.yaml", "work/board.md", "../x", "work/tasks/../../x",
                                  "/etc/passwd", "work/log.md.bak"])
def test_refuses_a_path_outside_the_list_and_writes_nothing(world, path):
    write(world.host / "scripts/tool.py", "changed\n")
    head = git(world.host, "rev-parse", "HEAD").stdout
    done = world.sync("work/tasks/a/STATUS.md", path)
    assert done.returncode == 2
    assert git(world.host, "rev-parse", "HEAD").stdout == head


def test_a_closed_task_moves_with_its_deletion(world):
    (world.host / "work/tasks/a/STATUS.md").unlink()
    write(world.host / "work/done/2026-10/a/STATUS.md", "one\n")
    assert world.sync("work/tasks/a/STATUS.md", "work/done/2026-10/a/STATUS.md").returncode == 0
    names = git(world.origin, "ls-tree", "-r", "--name-only", BRANCH).stdout
    assert "work/done/2026-10/a/STATUS.md" in names and "work/tasks/a/STATUS.md" not in names


def test_log_rows_of_two_machines_both_stay(world):
    write(world.other / "work/log.md", "# log\nlaptop row\n")
    git(world.other, "commit", "-qam", "laptop")
    git(world.other, "push", "-q", "origin", BRANCH)
    write(world.host / "work/log.md", "# log\nhost row\n")
    done = world.sync("work/log.md")
    assert done.returncode == 0, done.stderr
    log = world.on_origin("work/log.md")
    assert "laptop row" in log and "host row" in log


def test_the_generated_board_is_put_back_so_a_pull_cannot_collide(world):
    write(world.host / "work/board.md", "regenerated here\n")
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    assert world.sync("work/tasks/a/STATUS.md").returncode == 0
    assert (world.host / "work/board.md").read_text() == "board\n"


def test_no_network_keeps_the_commit_local_with_75(world):
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    git(world.host, "remote", "set-url", "origin", str(world.origin) + ".gone")
    done = world.sync("work/tasks/a/STATUS.md")
    assert done.returncode == 75
    assert "work/tasks/a/STATUS.md" in git(world.host, "show", "--name-only", "--format=", "HEAD").stdout
    git(world.host, "remote", "set-url", "origin", str(world.origin))
    assert world.sync().returncode == 0
    assert world.on_origin("work/tasks/a/STATUS.md") == "two\n"


def test_a_real_conflict_aborts_and_keeps_the_commit_with_65(world):
    write(world.other / "work/tasks/a/STATUS.md", "laptop\n")
    git(world.other, "commit", "-qam", "laptop")
    git(world.other, "push", "-q", "origin", BRANCH)
    write(world.host / "work/tasks/a/STATUS.md", "host\n")
    done = world.sync("work/tasks/a/STATUS.md")
    assert done.returncode == 65
    assert not (world.host / ".git/rebase-merge").exists() and not (world.host / ".git/rebase-apply").exists()
    assert git(world.host, "show", "HEAD:work/tasks/a/STATUS.md").stdout == "host\n"


def test_unpushed_work_outside_the_list_is_not_shipped_along(world):
    write(world.host / "scripts/tool.py", "half done\n")
    git(world.host, "commit", "-qam", "unfinished")
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    done = world.sync("work/tasks/a/STATUS.md")
    assert done.returncode == 65
    assert world.on_origin("scripts/tool.py") == "x\n"


# ------------------------------------------------------------ the cockpit's side

sys.path.insert(0, str(SCRIPT.parent))
from lib.bridge_cockpit.work_sync import WorkSync  # noqa: E402


def queued(world: Clones, tmp_path: Path, run=None) -> WorkSync:
    def real(paths: list[str], person: str) -> int:
        return world.sync(*paths, actor=person).returncode
    return WorkSync(world.host, tmp_path / "state", run or real)


def test_only_what_the_action_changed_is_queued(world, tmp_path):
    sync = queued(world, tmp_path)
    write(world.host / "work/tasks/a/open.md", "left open by somebody\n")
    before = sync.snapshot()
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    write(world.host / "work/log.md", "# log\nrow\n")
    write(world.host / "work/board.md", "regenerated\n")
    assert sync.after(before, "pat") == ["work/log.md", "work/tasks/a/STATUS.md"]


def test_a_second_write_to_an_open_file_counts(world, tmp_path):
    sync = queued(world, tmp_path)
    write(world.host / "work/log.md", "# log\nfirst\n")
    before = sync.snapshot()
    import os
    write(world.host / "work/log.md", "# log\nfirst\nsecond\n")
    os.utime(world.host / "work/log.md", ns=(1, 1))
    assert sync.after(before, "pat") == ["work/log.md"]


def test_drain_pushes_and_empties_the_queue(world, tmp_path):
    sync = queued(world, tmp_path)
    before = sync.snapshot()
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    sync.after(before, "pat")
    assert sync.drain() is True and sync.pending() == []
    assert world.on_origin("work/tasks/a/STATUS.md") == "two\n"


def test_the_queue_survives_a_restart(world, tmp_path):
    first = queued(world, tmp_path, run=lambda p, a: 1)
    before = first.snapshot()
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    first.after(before, "pat")
    assert first.drain() is False
    second = queued(world, tmp_path)
    assert len(second.pending()) == 1 and second.drain() is True
    assert world.on_origin("work/tasks/a/STATUS.md") == "two\n"


def test_exit_75_is_safe_locally_and_leaves_the_queue(world, tmp_path):
    sync = queued(world, tmp_path, run=lambda p, a: 75)
    before = sync.snapshot()
    write(world.host / "work/tasks/a/STATUS.md", "two\n")
    sync.after(before, "pat")
    assert sync.drain() is True and sync.pending() == []


# ------------------------------------------------------------ the served cockpit

import dataclasses  # noqa: E402

bc = __import__("importlib").import_module("lib.bridge_cockpit.config")
srv = __import__("importlib").import_module("lib.bridge_cockpit.server")


def bare_config():
    fields = {f.name: None for f in dataclasses.fields(bc.WebConfig)
              if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING}
    return bc.WebConfig(**{**fields, "relay": True, "triage_daily": True, "snapshot_minutes": 60})


def test_served_turns_off_what_belongs_to_the_owner_machine():
    cfg = srv.served_config(bare_config())
    assert cfg.served is True and cfg.relay is False and cfg.triage_daily is False and cfg.snapshot_minutes == 0


def test_served_runner_has_no_model_and_no_terminal(tmp_path):
    runner = srv.served_runner(tmp_path, code=SCRIPT.parents[1])
    assert runner.claude is None and runner.codex is None and runner.cmux is None
    argv = [runner.python, runner.script("scripts/work-sync.py"), "--actor", "pat"]
    runner.check(argv)


def test_a_cockpit_on_the_owner_machine_syncs_nothing(tmp_path):
    from test_bridge_cockpit import World
    world = World(tmp_path)
    try:
        assert world.app.work_sync is None
    finally:
        world.close()


class Recorder:
    def __init__(self):
        self.calls = []

    def snapshot(self):
        self.calls.append("before")
        return {}

    def after(self, before, person):
        self.calls.append(("after", person))
        return []

    def stop(self):
        pass


def test_a_person_action_is_recorded_and_an_owner_action_is_not(tmp_path):
    from test_bridge_cockpit import World
    world = World(tmp_path)
    try:
        world.app.work_sync = Recorder()
        actions = world.app.actions
        actions.validate = lambda verb, args: {}
        actions.v_note = lambda ctx: None
        world.app.access.verb_ok = lambda verb: None
        world.app.access.check = lambda viewer, verb, clean: None
        actions.execute("note", {})
        assert world.app.work_sync.calls == []
        actions.execute("note", {}, viewer="pat")
        assert world.app.work_sync.calls == ["before", ("after", "pat")]
    finally:
        world.close()
