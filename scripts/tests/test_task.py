# SPDX-License-Identifier: MIT
"""Contract for scripts/task.py: set a task's priority or add a note without touching any other byte."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "task.py"

STATUS = (
    "---\n"
    "slug: alpha   # keep me\n"
    "status: doing\n"
    "title: \"Quoted: title\"\n"
    "last_updated: 2026-09-01\n"
    "---\n\n# Alpha\n\nbody status: doing\n"
)


def run(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    for kind, slug in (("tasks", "alpha"), ("streams", "river")):
        d = tmp_path / "work" / kind / slug
        d.mkdir(parents=True)
        (d / "STATUS.md").write_text(STATUS.replace("alpha", slug), encoding="utf-8")
    return tmp_path


def test_adds_priority_after_status_and_preserves_everything_else(repo):
    r = run(repo, "priority", "alpha", "P1")
    assert r.returncode == 0, r.stderr
    text = (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    import datetime
    expected = STATUS.replace("status: doing\n", "status: doing\npriority: P1\n", 1) \
        .replace("last_updated: 2026-09-01", f"last_updated: {datetime.date.today().isoformat()}")
    assert text == expected


def test_rewrites_an_existing_priority_line_only(repo):
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(STATUS.replace("status: doing\n", "status: doing\npriority: P3  # old\n", 1), encoding="utf-8")
    assert run(repo, "priority", "alpha", "P0").returncode == 0
    text = p.read_text(encoding="utf-8")
    assert "priority: P0\n" in text and "P3" not in text and text.count("priority:") == 1


def test_streams_work_too_and_the_board_is_regenerated(repo):
    r = run(repo, "priority", "river", "P2")
    assert r.returncode == 0, r.stderr
    assert "priority: P2" in (repo / "work/streams/river/STATUS.md").read_text(encoding="utf-8")
    assert (repo / "work" / "board.md").is_file()
    assert "alpha" in (repo / "work" / "board.md").read_text(encoding="utf-8")


def test_refuses_unknown_slug_and_bad_value_without_writing(repo):
    before = (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    r = run(repo, "priority", "ghost", "P1")
    assert r.returncode == 1 and "ghost" in r.stderr
    r = run(repo, "priority", "alpha", "P9")
    assert r.returncode in (1, 2)
    assert (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8") == before
    assert not (repo / "work" / "board.md").exists()


# ---------------------------------------------------------------- note

def test_note_appends_a_dated_line_under_a_new_notes_section(repo):
    import datetime
    assert run(repo, "note", "alpha", "Customer wants it by Friday").returncode == 0
    text = (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    today = datetime.date.today().isoformat()
    assert text.endswith(f"\n## Notes\n\n- {today}: Customer wants it by Friday\n")
    assert f"last_updated: {today}" in text and "body status: doing" in text


def test_note_goes_into_an_existing_notes_section_before_the_next_heading(repo):
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(STATUS + "\n## Notes\n\n- 2026-09-01: old\n\n## Later\n\nx\n", encoding="utf-8")
    assert run(repo, "note", "alpha", "new").returncode == 0
    text = p.read_text(encoding="utf-8")
    assert text.index("- 2026-09-01: old") < text.index(": new") < text.index("## Later")
    assert text.count("## Notes") == 1


def test_only_the_english_notes_heading_is_the_notes_section(repo):
    # CORE parses one heading, "## Notes"; any other heading is left alone and
    # a new "## Notes" section is opened at the end.
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(STATUS + "\n## Remarks\n\n- 2026-09-01: old\n", encoding="utf-8")
    assert run(repo, "note", "alpha", "new").returncode == 0
    text = p.read_text(encoding="utf-8")
    assert text.count("## Notes") == 1
    assert text.index("## Remarks") < text.index("## Notes") < text.index(": new")


def _from_template(repo):
    """A STATUS.md made from the shipped template, comment line above the fence included."""
    tpl = (ROOT / "work" / "templates" / "STATUS.md").read_text(encoding="utf-8")
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(tpl.replace("<slug>", "alpha"), encoding="utf-8")
    return tpl.replace("<slug>", "alpha"), p


def test_priority_works_on_a_status_made_from_the_template(repo):
    before, p = _from_template(repo)
    assert before.startswith("# yaml-language-server:")
    r = run(repo, "priority", "alpha", "P0")
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    assert text.splitlines()[0] == before.splitlines()[0]
    assert "\npriority: P0\n" in text and text.count("\npriority:") == 1


def test_note_works_on_a_status_made_from_the_template(repo):
    before, p = _from_template(repo)
    r = run(repo, "note", "alpha", "first note")
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    assert text.startswith(before.splitlines(keepends=True)[0])
    assert ": first note" in text and "last_updated: YYYY-MM-DD" not in text


def test_note_refuses_empty_text_and_unknown_slug(repo):
    before = (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    assert run(repo, "note", "alpha", "   ").returncode == 1
    assert run(repo, "note", "ghost", "x").returncode == 1
    assert (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8") == before


def test_note_at_the_end_of_a_file_without_final_newline_gets_its_own_line(repo):
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(STATUS + "\n## Notes\n\n- 2026-09-01: old", encoding="utf-8")
    assert run(repo, "note", "alpha", "new").returncode == 0
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[-2] == "- 2026-09-01: old" and lines[-1].endswith(": new")


def test_note_keeps_crlf_line_endings(repo):
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_bytes(STATUS.replace("\n", "\r\n").encode("utf-8"))
    assert run(repo, "note", "alpha", "new").returncode == 0
    data = p.read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")


# ---------------------------------------------------------------- close: the scripted 3-step close

import datetime as _dt
import json as _json

BLOCKED = (
    "---\n"
    "slug: alpha\n"
    "status: doing\n"
    "priority: P1\n"
    "blocked_by: >-\n"
    "  waiting on F: review of example-org/x#49\n"
    "blocked_since: 2026-09-20\n"
    "created: 2026-09-01\n"
    "last_updated: 2026-09-01\n"
    "---\n\n# Alpha\n\nbody\n"
)


def _log_with_today(repo):
    today = _dt.date.today()
    log = repo / "work" / "log.md"
    log.write_text(
        "# Week\n\n"
        f"## Mon {today:%d.%m}\n\n"
        "| Timestamp | Glyph | Context | What |\n|---|---|---|---|\n"
        f"| {today:%Y-%m-%d} 07:00 | 💻 | other | earlier row |\n", encoding="utf-8")
    return log


def test_close_moves_the_task_sets_the_fields_regenerates_the_board_and_logs_a_row(repo):
    (repo / "work/tasks/alpha/STATUS.md").write_text(BLOCKED, encoding="utf-8")
    log = _log_with_today(repo)
    r = run(repo, "close", "alpha", "--reason", "example-org/x#49 closed as completed", "--json")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    dest = repo / "work" / "done" / f"{today:%Y-%m}" / "alpha"
    assert not (repo / "work/tasks/alpha").exists()
    text = (dest / "STATUS.md").read_text(encoding="utf-8")
    assert "status: done\n" in text and f'closed: "{today.isoformat()}"\n' in text
    assert "blocked_by" not in text and "waiting on F" not in text and "blocked_since" not in text
    assert "outcome:" not in text
    assert f"- {today.isoformat()}: Closed: example-org/x#49 closed as completed" in text
    board = (repo / "work" / "board.md").read_text(encoding="utf-8")
    assert "alpha" in board
    rows = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.startswith(f"| {today:%Y-%m-%d}")]
    assert len(rows) == 2 and rows[0].endswith("earlier row |")
    assert "| alpha |" in rows[1] and "closed" in rows[1] and "x#49" in rows[1]
    out = _json.loads(r.stdout)
    assert out["slug"] == "alpha" and out["moved_to"] == f"work/done/{today:%Y-%m}/alpha"
    assert out["outcome"] is None


def test_close_declined_sets_the_outcome(repo):
    _log_with_today(repo)
    r = run(repo, "close", "alpha", "--declined", "--reason", "moot")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    text = (repo / "work" / "done" / f"{today:%Y-%m}" / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert "status: done\n" in text and "outcome: declined\n" in text
    assert "Declined: moot" in text


def test_a_normal_close_drops_an_old_declined_outcome(repo):
    _log_with_today(repo)
    path = repo / "work" / "tasks" / "alpha" / "STATUS.md"
    path.write_text(path.read_text(encoding="utf-8").replace("status: doing\n", "status: doing\noutcome: declined\n", 1),
                    encoding="utf-8")
    assert "outcome: declined" in path.read_text(encoding="utf-8")
    r = run(repo, "close", "alpha", "--reason", "shipped after all")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    text = (repo / "work" / "done" / f"{today:%Y-%m}" / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert "status: done\n" in text and "outcome:" not in text


def test_close_without_a_log_creates_one_with_todays_block(repo):
    r = run(repo, "close", "alpha")
    assert r.returncode == 0, r.stderr
    text = (repo / "work" / "log.md").read_text(encoding="utf-8")
    today = _dt.date.today()
    assert f"{today:%d.%m}" in text and f"| {today:%Y-%m-%d}" in text and "| alpha |" in text


def test_close_refuses_streams_unknown_and_already_closed_tasks_without_writing(repo):
    before = (repo / "work/streams/river/STATUS.md").read_text(encoding="utf-8")
    r = run(repo, "close", "river")
    assert r.returncode == 1 and "stream" in r.stderr
    assert (repo / "work/streams/river/STATUS.md").read_text(encoding="utf-8") == before
    r = run(repo, "close", "ghost")
    assert r.returncode == 1 and "ghost" in r.stderr
    done = repo / "work" / "done" / "2026-09" / "old"
    done.mkdir(parents=True)
    (done / "STATUS.md").write_text(STATUS.replace("alpha", "old").replace("doing", "done"), encoding="utf-8")
    r = run(repo, "close", "old")
    assert r.returncode == 1 and "already" in r.stderr
    assert not (repo / "work" / "board.md").exists() and not (repo / "work" / "log.md").exists()


def test_a_failed_move_leaves_the_task_byte_identical_and_a_retry_closes_it_once(repo):
    import os
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(BLOCKED, encoding="utf-8")
    before = p.read_bytes()
    month = repo / "work" / "done" / f"{_dt.date.today():%Y-%m}"
    month.mkdir(parents=True)
    os.chmod(month, 0o555)
    try:
        r = run(repo, "close", "alpha", "--reason", "done")
        assert r.returncode == 1 and "Traceback" not in r.stderr
        assert p.read_bytes() == before
    finally:
        os.chmod(month, 0o755)
    r = run(repo, "close", "alpha", "--reason", "done")
    assert r.returncode == 0, r.stderr
    text = (month / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert text.count("Closed: done") == 1


def test_a_failing_log_step_is_a_warning_after_the_move(repo):
    (repo / "work" / "log.md").mkdir(parents=True)     # a directory: the row cannot be written
    r = run(repo, "close", "alpha", "--json")
    assert r.returncode == 0 and "Traceback" not in r.stderr
    out = _json.loads(r.stdout)
    assert out["warnings"] and "log" in out["warnings"][0]
    assert (repo / "work" / "done" / f"{_dt.date.today():%Y-%m}" / "alpha" / "STATUS.md").is_file()


# ---------------------------------------------------------------- reopen: the inverse of close

def test_reopen_brings_a_closed_task_back_with_its_status_and_a_note(repo):
    (repo / "work/tasks/alpha/STATUS.md").write_text(BLOCKED, encoding="utf-8")
    log = _log_with_today(repo)
    assert run(repo, "close", "alpha", "--declined", "--reason", "by mistake").returncode == 0
    r = run(repo, "reopen", "alpha", "--json")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    path = repo / "work" / "tasks" / "alpha" / "STATUS.md"
    assert path.is_file() and not (repo / "work" / "done" / f"{today:%Y-%m}" / "alpha").exists()
    text = path.read_text(encoding="utf-8")
    assert "status: doing\n" in text and "closed:" not in text and "outcome:" not in text
    assert "priority: P1\n" in text                                    # everything else stays
    assert f"- {today.isoformat()}: Reopened" in text and "Declined: by mistake" in text   # history kept
    out = _json.loads(r.stdout)
    assert out["slug"] == "alpha" and out["status"] == "doing" and out["moved_from"].startswith("work/done/")
    rows = [ln for ln in log.read_text(encoding="utf-8").splitlines() if "| alpha |" in ln]
    assert rows[-1].endswith("reopened |")
    assert "alpha" in (repo / "work" / "board.md").read_text(encoding="utf-8")


def test_reopen_as_backlog_with_a_note_says_it_should_still_be_done(repo):
    _log_with_today(repo)
    assert run(repo, "close", "alpha").returncode == 0
    r = run(repo, "reopen", "alpha", "--as", "backlog", "--note", "still to be done")
    assert r.returncode == 0, r.stderr
    text = (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    assert "status: backlog\n" in text and "Reopened: still to be done" in text


def test_reopen_refuses_an_open_task_an_unknown_one_and_a_bad_status(repo):
    r = run(repo, "reopen", "alpha")
    assert r.returncode == 1 and "open" in r.stderr
    r = run(repo, "reopen", "ghost")
    assert r.returncode == 1 and "ghost" in r.stderr
    assert run(repo, "reopen", "alpha", "--as", "done").returncode == 2
    assert not (repo / "work" / "log.md").exists()


def test_reopen_takes_the_latest_close_when_a_slug_was_closed_twice(repo):
    for month in ("2026-08", "2026-09"):
        d = repo / "work" / "done" / month / "old"
        d.mkdir(parents=True)
        (d / "STATUS.md").write_text(STATUS.replace("alpha", "old").replace("doing", "done").replace(
            "last_updated: 2026-09-01", f"last_updated: {month}-15"), encoding="utf-8")
    r = run(repo, "reopen", "old", "--json")
    assert r.returncode == 0, r.stderr
    assert _json.loads(r.stdout)["moved_from"] == "work/done/2026-09/old"
    assert (repo / "work" / "done" / "2026-08" / "old").is_dir()


# ---------------------------------------------------------------- runs on, and a task from an inbox item

def test_wait_marks_a_task_as_running_on_until_a_day_and_clear_takes_it_back(repo):
    import datetime
    today = datetime.date.today().isoformat()
    p = repo / "work/tasks/alpha/STATUS.md"
    r = run(repo, "wait", "alpha", "--until", "2099-01-05", "--on", "an answer from the vendor")
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    assert 'blocked_by: "an answer from the vendor"' in text and "quiet_until: 2099-01-05" in text
    assert f"blocked_since: {today}" in text and "status: doing" in text
    assert "Runs on until 2099-01-05: an answer from the vendor" in text            # a dated note says so
    assert run(repo, "wait", "alpha", "--until", "2099-02-01").returncode == 0   # no new reason: the old one stays
    text = p.read_text(encoding="utf-8")
    assert 'blocked_by: "an answer from the vendor"' in text and "quiet_until: 2099-02-01" in text and text.count("blocked_by:") == 1
    assert run(repo, "wait", "alpha", "--clear").returncode == 0
    assert run(repo, "wait", "alpha", "--until", "2099-02-01").returncode == 0   # no reason at all: it simply runs
    assert 'blocked_by: "runs on"' in p.read_text(encoding="utf-8")
    assert run(repo, "wait", "alpha", "--clear").returncode == 0
    text = p.read_text(encoding="utf-8")
    assert "blocked_by" not in text and "quiet_until" not in text and "blocked_since" not in text
    assert run(repo, "wait", "alpha", "--until", "gestern").returncode == 1        # a day, nothing else


def test_new_task_from_an_inbox_item_starts_in_backlog_and_closes_the_item(repo):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("inbox_mod", ROOT / "scripts" / "inbox.py")
    ib = importlib.util.module_from_spec(spec)
    sys.modules["inbox_mod"] = ib                      # dataclasses look their module up
    spec.loader.exec_module(ib)
    box = ib.Inbox(repo / "work" / "inbox", actor="test")
    item = box.add(source="session", kind="decision", summary="Make the channel known: a few short videos",
                   detail="three short videos", closer="person")
    r = run(repo, "new", "--from-inbox", item, "--json")
    assert r.returncode == 0, r.stderr
    import json as _json
    out = _json.loads(r.stdout)
    slug = out["slug"]
    assert slug.startswith("make-the-channel-known")
    text = (repo / "work/tasks" / slug / "STATUS.md").read_text(encoding="utf-8")
    assert "status: backlog" in text and f"slug: {slug}" in text
    assert 'headline: "Make the channel known: a few short videos"' in text
    assert f"inbox {item}" in text and "three short videos" in text
    closed = box.get(item)
    assert closed.state == "done" and any(slug in (e.data.get("text") or "") for e in closed.events)
    assert run(repo, "new", "--from-inbox", item).returncode == 1       # a closed item becomes no second task
    assert run(repo, "new", "alpha", "--headline", "x").returncode == 1  # a slug that exists is refused
    r = run(repo, "new", "beta", "--headline", "Etwas Neues", "--status", "doing")
    assert r.returncode == 0, r.stderr
    assert "status: doing" in (repo / "work/tasks/beta/STATUS.md").read_text(encoding="utf-8")


def test_a_new_slug_is_the_head_of_the_summary_cut_between_words():
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_slug", ROOT / "scripts" / "task.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    assert m._new_slug("Chatbot on a new model: grant access in the cloud account") == "chatbot-on-a-new-model"
    slug = m._new_slug("Move the build machine carefully over to Python 3.15 (with PyYAML)")
    assert slug == "move-the-build-machine-carefully-over-to" and len(slug) <= 40
    assert m._new_slug("Größe prüfen") == "groesse-pruefen" and m._new_slug("!!!") == "task"


def test_reopen_as_review_restores_a_task_closed_while_in_review(repo):
    _log_with_today(repo)
    assert run(repo, "close", "alpha").returncode == 0
    r = run(repo, "reopen", "alpha", "--as", "review", "--json")
    assert r.returncode == 0, r.stderr
    assert "status: review\n" in (repo / "work/tasks/alpha/STATUS.md").read_text(encoding="utf-8")
    assert _json.loads(r.stdout)["status"] == "review"


def test_close_stream_ends_a_stream_and_reopen_brings_it_back_as_a_stream(repo):
    _log_with_today(repo)
    r = run(repo, "close", "river", "--stream", "--declined", "--reason", "customer left", "--json")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    dest = repo / "work" / "done" / f"{today:%Y-%m}" / "river"
    assert not (repo / "work/streams/river").exists() and not (repo / "work/tasks/river").exists()
    text = (dest / "STATUS.md").read_text(encoding="utf-8")
    assert "status: done\n" in text and "outcome: declined\n" in text and "was_stream: true\n" in text
    assert "Stream ended, declined: customer left" in text
    out = _json.loads(r.stdout)
    assert out["moved_to"] == f"work/done/{today:%Y-%m}/river" and out["stream"] is True
    # the undo puts a stream back where it lived, not into work/tasks/
    r = run(repo, "reopen", "river", "--json")
    assert r.returncode == 0, r.stderr
    back = (repo / "work/streams/river/STATUS.md").read_text(encoding="utf-8")
    assert not (repo / "work/tasks/river").exists()
    assert "was_stream" not in back and "status: doing\n" in back and "outcome:" not in back
    assert _json.loads(r.stdout)["moved_to"] == "work/streams/river"


def test_close_stream_on_a_task_closes_it_as_usual_and_reopen_stays_a_task(repo):
    _log_with_today(repo)
    assert run(repo, "close", "alpha", "--stream").returncode == 0
    today = _dt.date.today()
    assert "was_stream" not in (repo / "work" / "done" / f"{today:%Y-%m}" / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert run(repo, "reopen", "alpha").returncode == 0
    assert (repo / "work/tasks/alpha/STATUS.md").is_file()


def test_log_writes_one_row_into_todays_block_for_a_row_without_a_task(repo):
    log = _log_with_today(repo)
    r = run(repo, "log", "--", "repo", "Fix the example issue (example/repo#12) · Will not be done: dup of #3")
    assert r.returncode == 0, r.stderr
    rows = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.startswith(f"| {_dt.date.today():%Y-%m-%d}")]
    assert rows[0].endswith("| other | earlier row |")
    assert rows[-1].endswith("| repo | Fix the example issue (example/repo#12) · Will not be done: dup of #3 |")


def test_log_refuses_an_empty_row_and_keeps_a_pipe_from_breaking_the_table(repo):
    assert run(repo, "log", "--", "repo", "   ").returncode == 1
    assert not (repo / "work" / "log.md").exists()
    assert run(repo, "log", "--", "repo", "a | b").returncode == 0
    assert "| repo | a / b |" in (repo / "work" / "log.md").read_text(encoding="utf-8")
