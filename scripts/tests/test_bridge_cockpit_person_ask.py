# SPDX-License-Identifier: MIT
"""A person's question: off without a key of its own, read only, in a folder that holds their files and nothing else."""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit_access import MARK, get, post, world  # noqa: E402,F401
from lib.bridge_cockpit import config as cf  # noqa: E402
from lib.bridge_cockpit import person_ask as pa  # noqa: E402
from lib.bridge_cockpit import quick, server as srv  # noqa: E402
from lib import ai_services as ai  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused, RunResult  # noqa: E402

KEY = "sk-test-not-a-real-key"
ANSWER = json.dumps({"type": "result", "result": "The answer", "session_id": "11111111-2222-3333-4444-555555555555",
                     "total_cost_usd": 0.002, "modelUsage": {"haiku": {"costUSD": 0.002}}})


@pytest.fixture
def asked(world, monkeypatch):  # noqa: F811
    (world.root / "work" / "tasks" / "home-task" / "STATUS.md").write_text(
        "---\ntype: feature\nstatus: doing\narea: Home\nheadline: Home\n---\n\n# Home\n", encoding="utf-8")
    (world.root / "work" / "tasks" / "job-task" / "STATUS.md").write_text(
        f"---\ntype: feature\nstatus: doing\narea: Job\nheadline: {MARK}\n---\n\n# {MARK}\n", encoding="utf-8")
    path = world.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "boundary:\n  level: room\n", encoding="utf-8")
    monkeypatch.setenv("PERSON_ASK_TEST_KEY", KEY)
    world.app.cfg = dataclasses.replace(world.app.cfg, served_ask=pa.Settings(auth="key", key_env="PERSON_ASK_TEST_KEY", daily_questions=2))
    world.calls = []

    def run_person(argv, timeout, cwd, key=None, config_dir=None):
        world.calls.append({"argv": argv, "cwd": cwd, "key": key, "config_dir": config_dir})
        return RunResult(True, 0, ANSWER + "\n", "", 5)

    monkeypatch.setattr(world.runner, "run_person", run_person)
    return world


def question(w, text="What is open?", person="pat", **extra):
    return post(w, "/api/ask", {"kind": "free", "args": {"text": text}, "via": "quick", **extra}, person=person)


def status_of(res):
    return res[0]


def body_of(res):
    return json.loads(res[-1])


def settled(w, person="pat"):
    for _ in range(100):
        state = w.app.person_ask.state(person)
        if not any(c["running"] for c in state["convs"]):
            return state
        time.sleep(0.02)
    raise AssertionError("still running")


def test_without_a_key_a_question_stays_off(world):  # noqa: F811
    assert world.app.person_ask.state("pat")["available"] is False
    assert status_of(question(world)) == 403


def test_a_key_that_is_named_but_missing_stays_off(asked, monkeypatch):
    monkeypatch.delenv("PERSON_ASK_TEST_KEY")
    assert asked.app.person_ask.state("pat")["available"] is False
    assert status_of(question(asked)) == 403
    assert asked.calls == []


def test_the_answer_comes_back_in_their_own_folder_with_the_key(asked):
    res = question(asked)
    assert status_of(res) == 202
    conv = body_of(res)["conv"]
    state = settled(asked)
    assert state["convs"][0]["id"] == conv and state["convs"][0]["turns"][0]["a"] == "The answer"
    call = asked.calls[0]
    assert call["key"] == KEY and Path(call["cwd"]).name == "room" and "pat" in Path(call["cwd"]).parts
    argv = call["argv"]
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob" and argv[argv.index("--setting-sources") + 1] == ""


def test_the_folder_holds_their_files_only(asked):
    question(asked)
    settled(asked)
    room = Path(asked.calls[0]["cwd"])
    found = [p for p in room.rglob("*") if p.is_file()]
    assert any(p.parent.name == "home-task" for p in found)
    assert not any(MARK in p.read_text(encoding="utf-8") for p in found)
    assert not any(p.is_symlink() for p in room.rglob("*"))


def test_a_link_in_a_file_folder_is_not_followed(asked, tmp_path):
    secret = tmp_path / "outside.md"
    secret.write_text(MARK, encoding="utf-8")
    os.symlink(secret, asked.root / "work" / "tasks" / "home-task" / "link.md")
    question(asked)
    settled(asked)
    room = Path(asked.calls[0]["cwd"])
    assert not (room / "home-task" / "link.md").exists()


def test_the_folder_follows_the_source(asked):
    question(asked)
    settled(asked)
    room = Path(asked.calls[0]["cwd"])
    (asked.root / "work" / "tasks" / "home-task" / "notes.md").write_text("new", encoding="utf-8")
    question(asked)
    settled(asked)
    assert (room / "home-task" / "notes.md").read_text(encoding="utf-8") == "new"


def test_a_taken_name_takes_the_file_away(asked):
    question(asked)
    settled(asked)
    (asked.root / "work" / "tasks" / "home-task" / "STATUS.md").write_text(
        "---\ntype: feature\nstatus: doing\narea: Job\nheadline: moved\n---\n", encoding="utf-8")
    question(asked)
    settled(asked)
    assert not (Path(asked.calls[0]["cwd"]) / "home-task").exists()


def test_the_key_stays_out_of_what_a_page_gets(asked):
    question(asked)
    settled(asked)
    assert KEY not in json.dumps(asked.app.person_ask.state("pat"))
    assert KEY not in get(asked, "/api/state")[-1].decode("utf-8")
    assert "session" not in json.dumps(asked.app.person_ask.state("pat"))


@pytest.mark.parametrize("body", [
    {"kind": "free", "args": {"text": "x", "context": "y"}, "via": "quick"},
    {"kind": "free", "args": {"text": "x", "task": "job-task"}, "via": "quick"},
    {"kind": "free", "args": {"text": "x"}, "via": "control"},
    {"kind": "free", "args": {"text": "x"}, "via": "quick", "model": "codex"},
    {"kind": "free", "args": {"text": "x"}, "via": "quick", "place": "core"},
    {"kind": "overview", "args": {}, "via": "quick"},
    {"kind": "row", "args": {"key": "task:job-task"}, "via": "quick"},
    {"kind": "free", "args": {"text": ""}, "via": "quick"},
    {"kind": "free", "args": {"text": "x" * 5000}, "via": "quick"}])
def test_anything_but_a_plain_question_is_refused(asked, body):
    assert status_of(post(asked, "/api/ask", body)) == 400
    assert asked.calls == []


def test_a_day_has_its_limit(asked):
    assert status_of(question(asked)) == 202
    settled(asked)
    assert status_of(question(asked)) == 202
    settled(asked)
    assert status_of(question(asked)) == 429
    assert asked.app.person_ask.state("pat")["left"] == 0


def test_one_question_at_a_time(asked, monkeypatch):
    import threading
    gate = threading.Event()

    def wait(argv, timeout, cwd, key=None, config_dir=None):
        gate.wait(5)
        return RunResult(True, 0, ANSWER, "", 1)

    monkeypatch.setattr(asked.runner, "run_person", wait)
    assert status_of(question(asked)) == 202
    assert status_of(question(asked)) == 409
    gate.set()
    settled(asked)


def test_a_chat_goes_on_with_its_own_session_only(asked):
    conv = body_of(question(asked))["conv"]
    settled(asked)
    assert status_of(question(asked, conv=conv)) == 202
    settled(asked)
    argv = asked.calls[1]["argv"]
    assert argv[argv.index("--resume") + 1] == "11111111-2222-3333-4444-555555555555"


def test_a_chat_of_someone_else_is_gone(asked):
    conv = body_of(question(asked))["conv"]
    settled(asked)
    assert asked.app.person_ask.state("sam")["convs"] == []
    assert conv not in json.dumps(asked.app.person_ask.state("sam"))
    with pytest.raises(pa.ActionError):
        asked.app.person_ask.ask("sam", {"kind": "free", "args": {"text": "x"}, "via": "quick", "conv": conv})


def test_people_have_folders_of_their_own(asked):
    one = asked.app.person_ask.folder("pat")
    two = asked.app.person_ask.folder("sam")
    assert one != two and one.parent == two.parent


def test_the_answer_reaches_only_the_page_that_asked(asked):
    seen = []
    asked.app.hub.add("pat", lambda e, p: None).queue.put_nowait
    mine = asked.app.hub.add("pat", lambda e, p: None)
    other = asked.app.hub.add("sam", lambda e, p: {"x": 1})
    question(asked)
    settled(asked)
    while not mine.queue.empty():
        seen.append(mine.queue.get_nowait()[0])
    assert "person_ask" in seen
    assert not any(other.queue.get_nowait()[0] == "person_ask" for _ in range(other.queue.qsize()))


def test_a_failed_run_says_nothing_of_how(asked, monkeypatch):
    monkeypatch.setattr(asked.runner, "run_person",
                        lambda *a, **k: RunResult(False, 1, "", f"boom {asked.root}", 1))
    question(asked)
    state = settled(asked)
    assert str(asked.root) not in json.dumps(state) and state["convs"][0]["turns"][0]["error"]


def test_workspace_validation_refuses_a_dangerous_folder(tmp_path):
    import workspace as engine
    defs = {"a": {"id": "a", "sources": {"documents": ["~/Developer"]}}}
    assert any("documents" in p for p in engine.rule_problems(defs, "a"))
    defs = {"a": {"id": "a", "sources": {"documents": ["/srv/a"]}},
            "b": {"id": "b", "parent": "a", "sources": {"documents": ["/srv/b"]}}}
    assert any("documents" in p for p in engine.rule_problems(defs, "b"))
    defs["b"]["sources"]["documents"] = ["/srv/a/x"]
    assert not any("documents" in p for p in engine.rule_problems(defs, "b"))


def test_the_system_text_calls_files_data(asked):
    question(asked)
    settled(asked)
    argv = asked.calls[0]["argv"]
    system = argv[argv.index("--append-system-prompt") + 1]
    assert "instruction" in system.lower() and "read" in system.lower()


def test_the_run_takes_the_subscription_away(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "subscription")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "other")
    runner = Runner(tmp_path, cmux=None, claude="/fake/claude", codex=None, git="/fake/git")
    seen = {}

    def spawn(argv, timeout, on_line, cwd=None, env=None):
        seen.update(cwd=cwd, env=env)
        return RunResult(True, 0, "", "", 1)

    monkeypatch.setattr(runner, "_spawn_lines", spawn)
    argv = quick.build_argv("/fake/claude", "haiku", "q", "system")
    runner.run_person(argv, 5, tmp_path / "room", KEY, tmp_path / "cfg")
    env = seen["env"]
    assert env["ANTHROPIC_API_KEY"] == KEY and env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "cfg")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert seen["cwd"] == tmp_path / "room"


def test_a_served_runner_has_no_model_but_for_a_person_with_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "resolve_claude", lambda: "/fake/claude")
    off = srv.served_runner(tmp_path)
    on = srv.served_runner(tmp_path, ask=pa.Settings())
    named = srv.served_runner(tmp_path, ask=pa.Settings(claude="/opt/claude"))
    assert off.claude is None and off.person_claude is None
    assert on.claude is None and on.person_claude == "/fake/claude" and named.person_claude == "/opt/claude"


def test_login_runs_on_the_service_users_login(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "own")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stray")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    runner = Runner(tmp_path, cmux=None, claude="/fake/claude", codex=None, git="/fake/git")
    seen = {}
    monkeypatch.setattr(runner, "_spawn_lines", lambda argv, t, on, cwd=None, env=None: seen.update(env=env) or RunResult(True, 0, "", "", 1))
    runner.run_person(quick.build_argv("/fake/claude", "haiku", "q", "s"), 5, tmp_path)
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "own" and "ANTHROPIC_API_KEY" not in seen["env"]
    assert "CLAUDE_CONFIG_DIR" not in seen["env"]


def test_login_needs_no_key(asked):
    asked.app.cfg = dataclasses.replace(asked.app.cfg, served_ask=pa.Settings(people=["pat"]))
    assert status_of(question(asked)) == 202
    settled(asked)
    assert asked.calls[0]["key"] is None and asked.calls[0]["config_dir"] is None


@pytest.mark.parametrize("level", ["view", "wall"])
def test_only_a_room_opens_a_question(asked, level):
    path = asked.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("level: room", f"level: {level}"), encoding="utf-8")
    assert asked.app.person_ask.state("pat")["available"] is False
    assert status_of(question(asked)) == 403


def test_a_workspace_without_a_room_gives_no_folder(docs):
    path = docs.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("level: room", "level: view"), encoding="utf-8")
    assert docs.app.access.documents("pat") == []


def test_the_road_of_a_person_takes_only_a_question(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/claude", codex=None, git="/fake/git")
    with pytest.raises(RunnerRefused):
        runner.run_person(["/fake/claude", "-p", "--dangerously-skip-permissions", "x"], 5, tmp_path, KEY, tmp_path)


@pytest.mark.parametrize("block,word", [
    ({"auth": "key", "key_ref": "nonsense"}, "key_ref"), ({"auth": "key"}, "key"),
    ({"auth": "key", "key_env": "A", "key_ref": "keychain://a/b"}, "one"), ({"key_env": "A"}, "auth: key"),
    ({"model": "codex"}, "model"), ({"daily_questions": 0}, "daily_questions"), ({"other": 1}, "other"),
    ({"auth": "key", "key_env": "lower case"}, "key_env"), ({"auth": "other"}, "auth"), ({"claude": "claude"}, "claude")])
def test_a_wrong_block_stops_the_start(block, word):
    with pytest.raises(cf.WebConfigError, match=word):
        cf.served_ask_of({"ask": block})


def test_a_good_block_reads():
    got = cf.served_ask_of({"ask": {"auth": "key", "key_ref": "keychain://a/b", "model": "sonnet", "daily_questions": 5}})
    assert got.key_ref == "keychain://a/b" and got.model == "sonnet" and got.daily_questions == 5
    assert cf.served_ask_of({"ask": {"people": ["pat"]}}).auth == "login"
    assert cf.served_ask_of({}) is None and cf.served_ask_of(None) is None


# ------------------------------------------------------------ the documents of a workspace


def give_folder(w, *folders):
    listed = "".join(f"  - {f}\n" for f in folders)
    path = w.root / "workflow" / "workspaces" / "home.yaml"
    path.write_text(path.read_text(encoding="utf-8") + f"sources:\n  documents:\n{listed}", encoding="utf-8")


@pytest.fixture
def docs(asked, tmp_path, monkeypatch):
    from lib import document_paths as dp
    # a test's folder lies under /private or /var, which the rule refuses for real folders
    monkeypatch.setattr(dp, "SYSTEM", tuple(s for s in dp.SYSTEM if s not in ("/private", "/var", "/tmp")))
    shelf = tmp_path / "shelf"
    (shelf / "Family" / "school").mkdir(parents=True)
    (shelf / "Family-neighbour").mkdir()
    (shelf / "Family" / "school" / "letter.md").write_text("INSIDEWORD", encoding="utf-8")
    (shelf / "Family-neighbour" / "other.md").write_text(MARK, encoding="utf-8")
    (shelf / "Family" / "photo.heic").write_bytes(b"x")
    give_folder(asked, shelf / "Family")
    asked.shelf = shelf
    asked.app.cfg = dataclasses.replace(asked.app.cfg, served_ask=pa.Settings(auth="key", key_env="PERSON_ASK_TEST_KEY", daily_questions=20))
    return asked


def room_of(w):
    question(w)
    settled(w)
    w.app.person_ask.documents.wait()
    question(w)
    settled(w)
    return Path(w.calls[-1]["cwd"])


def test_a_workspace_folder_comes_along_and_its_neighbour_does_not(docs):
    room = room_of(docs)
    found = list((room / "documents").rglob("*.md"))
    assert [p.read_text(encoding="utf-8") for p in found] == ["INSIDEWORD"]
    assert not any(MARK in p.read_text(encoding="utf-8", errors="replace") for p in room.rglob("*") if p.is_file())
    assert not list(room.rglob("*.heic"))


def test_a_link_out_of_a_document_folder_stays_out(docs, tmp_path):
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "s.md").write_text(MARK, encoding="utf-8")
    os.symlink(secret, docs.shelf / "Family" / "out")
    os.symlink(secret / "s.md", docs.shelf / "Family" / "out.md")
    room = room_of(docs)
    assert not any(MARK in p.read_text(encoding="utf-8", errors="replace") for p in room.rglob("*") if p.is_file())
    assert not any(p.is_symlink() for p in room.rglob("*"))


def test_a_folder_that_is_a_link_to_home_is_refused(docs, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "t.md").write_text(MARK, encoding="utf-8")
    os.symlink(tmp_path / "home", docs.shelf / "sneak")
    give_folder(docs, docs.shelf / "sneak")
    assert docs.app.access.documents("pat") == [] or all("sneak" not in str(p) for p in docs.app.access.documents("pat"))


def test_someone_outside_the_workspace_gets_none_of_it(docs):
    assert docs.app.access.documents("sam") == []


def test_a_file_that_left_the_folder_leaves_the_room(docs):
    room = room_of(docs)
    assert list((room / "documents").rglob("letter.md"))
    (docs.shelf / "Family" / "school" / "letter.md").unlink()
    docs.app.person_ask.documents.last = {}
    room = room_of(docs)
    assert not list((room / "documents").rglob("letter.md"))


def test_a_pdf_comes_with_its_words_where_a_tool_can_read_them(docs, tmp_path, monkeypatch):
    (docs.shelf / "Family" / "bill.pdf").write_bytes(b"%PDF-1.4")
    tool = tmp_path / "bin" / "pdftotext"
    tool.parent.mkdir()
    tool.write_text('#!/bin/sh\nfor last; do :; done\nfor a; do [ "$a" = "$last" ] || src=$a; done\necho PDFWORDS > "$last"\n')
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tool.parent}:{os.environ['PATH']}")
    room = room_of(docs)
    assert list((room / "documents").rglob("bill.pdf"))
    assert list((room / "documents").rglob("bill.pdf.txt"))[0].read_text(encoding="utf-8").strip() == "PDFWORDS"


def test_a_question_does_not_wait_for_the_folders(docs, monkeypatch):
    monkeypatch.setattr(docs.app.person_ask.documents, "sync", lambda *a: time.sleep(3))
    began = time.monotonic()
    question(docs)
    settled(docs)
    assert time.monotonic() - began < 2


@pytest.mark.parametrize("path", [
    "/", "~", "~/", "~/Developer", "~/Developer/x", "~/Library/CloudStorage/OneDrive-x", "/Users", "/Volumes", "/Volumes/disk",
    "/etc", "/private/etc", "relative/path", "~/.ssh", "/data/../etc", "~/Library/Keychains"])
def test_a_dangerous_folder_is_refused(path):
    from lib import document_paths as dp
    assert dp.problem(path) is not None


@pytest.mark.parametrize("path", ["~/Documents/Family", "/Volumes/disk/shelf/Family", "/srv/shelf/family"])
def test_a_plain_folder_passes(path):
    from lib import document_paths as dp
    assert dp.problem(path) is None


# ------------------------------------------------------------ the documents of a file, and single files of the repo


def test_the_documents_of_a_file_come_along_with_a_pdf(asked):
    folder = asked.root / "work" / "tasks" / "home-task" / "deliverables"
    folder.mkdir()
    (folder / "plan.md").write_text("PLANWORD", encoding="utf-8")
    (folder / "policy.pdf").write_bytes(b"%PDF-1.4")
    (folder / "tool.py").write_text("code", encoding="utf-8")
    question(asked)
    settled(asked)
    room = Path(asked.calls[0]["cwd"]) / "home-task" / "deliverables"
    assert (room / "plan.md").read_text(encoding="utf-8") == "PLANWORD" and (room / "policy.pdf").exists()
    assert not (room / "tool.py").exists()


def test_a_pattern_opens_those_files_of_the_repo_and_nothing_beside_them(asked):
    folder = asked.root / "identity" / "contracts"
    folder.mkdir(parents=True)
    (folder / "one.yaml").write_text("provider: A\ncredential: keychain://a/b\n", encoding="utf-8")
    (folder / "two.md").write_text(MARK, encoding="utf-8")
    (asked.root / "identity" / "accounts").mkdir()
    (asked.root / "identity" / "accounts" / "one.yaml").write_text(MARK, encoding="utf-8")
    give_folder(asked, "identity/contracts/*.yaml")
    question(asked)
    settled(asked)
    room = Path(asked.calls[0]["cwd"]) / "documents"
    found = [p for p in room.rglob("*") if p.is_file()]
    assert [p.name for p in found] == ["one.yaml"] and "keychain://a/b" in found[0].read_text(encoding="utf-8")


def test_a_link_among_the_pattern_files_stays_out(asked, tmp_path):
    folder = asked.root / "identity" / "contracts"
    folder.mkdir(parents=True)
    secret = tmp_path / "s.yaml"
    secret.write_text(MARK, encoding="utf-8")
    os.symlink(secret, folder / "link.yaml")
    give_folder(asked, "identity/contracts/*.yaml")
    question(asked)
    settled(asked)
    assert not (Path(asked.calls[0]["cwd"]) / "documents").exists() or \
        not [p for p in (Path(asked.calls[0]["cwd"]) / "documents").rglob("*") if p.is_file()]


@pytest.mark.parametrize("path", [
    "*.yaml", "identity/*", "identity/**/*.yaml", "../x/*.yaml", ".git/config.yaml", "identity/.hidden/*.yaml",
    "bridge-config.yaml", "scripts/*.py", "identity/x.yaml/"])
def test_a_wide_pattern_is_refused(path):
    from lib import document_paths as dp
    assert dp.problem(path) is not None


@pytest.mark.parametrize("path", ["identity/contracts/*.yaml", "identity/contracts/one.yaml", "docs/family/a?.md"])
def test_a_narrow_pattern_passes(path):
    from lib import document_paths as dp
    assert dp.problem(path) is None


def test_only_the_named_people_may_ask(asked):
    asked.app.cfg = dataclasses.replace(asked.app.cfg, served_ask=dataclasses.replace(asked.app.cfg.served_ask, people=["sam"]))
    assert status_of(question(asked)) == 403
    asked.app.cfg = dataclasses.replace(asked.app.cfg, served_ask=dataclasses.replace(asked.app.cfg.served_ask, people=["pat"]))
    assert status_of(question(asked)) == 202


@pytest.mark.parametrize("block,word", [
    ({"auth": "login"}, "people"), ({"auth": "login", "people": []}, "people"), ({"people": "pat"}, "people"),
    ({"auth": "login", "people": ["pat", "sam"]}, "one")])
def test_a_login_belongs_to_one_named_person(block, word):
    problem = pa.settings_problem(block)
    assert problem and word in problem


def test_a_login_for_its_owner_is_fine():
    assert pa.settings_problem({"auth": "login", "people": ["pat"]}) is None


# ------------------------------------------------------------ Codex, one login a person

THREAD = "01a195e8-4b2d-7102-bdfa-34101f7287e1"
CODEX_ANSWER = "\n".join(json.dumps(x) for x in ({"type": "thread.started", "thread_id": THREAD},
                                                {"type": "item.completed", "item": {"type": "agent_message", "text": "From Codex"}},
                                                {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})) + "\n"


@pytest.fixture
def codex(asked, monkeypatch):
    path = asked.root / "workflow" / "workspaces" / "job.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "members: [sam]\n", encoding="utf-8")
    asked.app.cfg = dataclasses.replace(asked.app.cfg, served_ask=pa.Settings(
        people=["sam"], manager="sam", codex={"people": ["sam", "pat"]}, daily_questions=30))
    asked.runner.person_codex = "/opt/codex"
    asked.runner.person_claude = "/opt/claude"
    monkeypatch.setattr(pa, "CODEX_WALL_PROVED", True)
    asked.codex_calls = []

    def run_person_codex(argv, timeout, cwd, home):
        asked.codex_calls.append({"argv": argv, "cwd": cwd, "home": home})
        return RunResult(True, 0, CODEX_ANSWER, "", 5)

    monkeypatch.setattr(asked.runner, "run_person_codex", run_person_codex)
    home = asked.app.person_ask.codex_home("pat")
    home.mkdir(parents=True)
    (home / "auth.json").write_text("{}", encoding="utf-8")
    return asked


def choose(w, person, engine, who="sam"):
    return post(w, "/api/action", {"verb": "ask_engine", "args": {"person": person, "engine": engine}}, person=who)


def test_a_person_without_claude_runs_on_their_own_codex_login(codex):
    assert codex.app.person_ask.engine("pat") == "codex"
    assert status_of(question(codex)) == 202
    state = settled(codex)
    assert state["convs"][0]["turns"][0]["a"] == "From Codex" and state["engine"] == "codex"
    assert codex.calls == [] and codex.codex_calls[0]["home"] == codex.app.person_ask.codex_home("pat")
    assert codex.codex_calls[0]["cwd"] == codex.app.person_ask.folder("pat") / "room"


def test_codex_without_a_login_stays_off(codex):
    (codex.app.person_ask.codex_home("pat") / "auth.json").unlink()
    assert not codex.app.person_ask.available("pat")


def test_codex_stays_off_where_its_wall_was_not_proved(codex, monkeypatch):
    monkeypatch.setattr(pa, "CODEX_WALL_PROVED", False)
    assert not codex.app.person_ask.available("pat")


def test_a_claude_login_never_serves_someone_else(codex):
    assert codex.app.person_ask.options("pat") == ["codex"]
    assert status_of(choose(codex, "pat", "claude")) == 400
    assert codex.app.person_ask.engine("pat") == "codex"


def test_only_the_manager_switches(codex):
    assert status_of(choose(codex, "sam", "codex", who="pat")) == 403
    assert codex.app.person_ask.engine("sam") == "claude"
    assert status_of(choose(codex, "sam", "codex")) == 200
    assert codex.app.person_ask.engine("sam") == "codex"


def test_off_closes_the_chat_of_a_person(codex):
    assert status_of(choose(codex, "pat", "off")) == 200
    assert not codex.app.person_ask.available("pat")
    assert status_of(question(codex)) == 403


def test_only_the_manager_gets_the_list_and_it_names_no_path(codex):
    assert codex.app.person_ask.state("pat")["manage"] is None
    rows = codex.app.person_ask.state("sam")["manage"]
    assert rows == [{"person": "sam", "engine": "claude", "options": ["claude", "codex"], "signed_in": False},
                    {"person": "pat", "engine": "codex", "options": ["codex"], "signed_in": True}]


def test_a_switch_starts_a_new_session_in_the_same_chat(codex):
    question(codex)
    conv = settled(codex)["convs"][0]["id"]
    assert status_of(question(codex, conv=conv)) == 202
    settled(codex)
    assert THREAD in codex.codex_calls[1]["argv"]
    data = codex.app.person_ask.read("pat")
    data["convs"][0]["engine"] = "claude"
    codex.app.person_ask.write("pat", data)
    assert status_of(question(codex, conv=conv)) == 202
    settled(codex)
    assert THREAD not in codex.codex_calls[2]["argv"]


def test_the_codex_run_gets_a_clean_environment(tmp_path, monkeypatch):
    runner = Runner(tmp_path, cmux=None, claude=None, codex=None)
    runner.person_codex = "/opt/homebrew/bin/codex"
    seen = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setattr(runner, "_spawn_lines", lambda argv, timeout, on_line, cwd=None, env=None: seen.update(env=env, cwd=cwd))
    argv = ai.person_codex_argv(runner.person_codex, tmp_path, "Hello", "Answer")
    runner.run_person_codex(argv, 5, tmp_path, tmp_path / "codex")
    assert set(seen["env"]) == {"PATH", "HOME", "CODEX_HOME", "LANG"}
    assert seen["env"]["CODEX_HOME"] == str(tmp_path / "codex")
    with pytest.raises(RunnerRefused):
        runner.run_person_codex([*argv[:-2], "--dangerously-bypass-approvals-and-sandbox", *argv[-2:]], 5, tmp_path, tmp_path)


@pytest.mark.parametrize("block, word", [
    ({"people": ["a"], "codex": []}, "codex"),
    ({"people": ["a"], "codex": {"people": []}}, "codex"),
    ({"people": ["a"], "codex": {"people": ["b"], "other": 1}}, "codex"),
    ({"people": ["a"], "codex": {"people": ["b"], "path": "codex"}}, "absolute"),
    ({"people": ["a"], "codex": {"people": ["b"], "model": "a b"}}, "model"),
    ({"people": ["a"], "manager": "b"}, "manager"),
    ({"manager": "a"}, "people"),
])
def test_a_wrong_block_is_named(block, word):
    assert word in (pa.settings_problem(block) or "")


def test_codex_alone_needs_no_claude_login():
    assert pa.settings_problem({"codex": {"people": ["b"]}, "manager": "b"}) is None
