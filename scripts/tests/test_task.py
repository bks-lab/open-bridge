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


def test_next_sets_the_next_step_as_a_mapping_with_a_dated_note_and_clear_takes_it_away(repo):
    import datetime
    import yaml
    today = datetime.date.today().isoformat()
    p = repo / "work/tasks/alpha/STATUS.md"
    # an older next step written as a block mapping goes whole, its indented lines too
    p.write_text(STATUS.replace("status: doing\n", "status: doing\nnext:\n  what: Old step\n  who: me\n", 1), encoding="utf-8")
    r = run(repo, "next", "alpha", "--", 'Call the vendor: "422" again')
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["next"] == {"what": 'Call the vendor: "422" again'} and front["last_updated"].isoformat() == today
    assert "Old step" not in text and "who: me" not in text and text.count("next:") == 1
    assert f"- {today}: Next step: Call the vendor" in text           # the date the step was taken over
    assert "slug: alpha   # keep me" in text and "body status: doing" in text
    assert run(repo, "next", "river", "--", "Watch it").returncode == 0     # a stream too
    assert run(repo, "next", "alpha", "--clear").returncode == 0
    text = p.read_text(encoding="utf-8")
    assert "next:" not in text and "Next step cleared" in text
    for bad in (("next", "alpha", "--", "   "), ("next", "alpha", "--", "a\nb"), ("next", "missing", "--", "x"),
                ("next", "alpha")):
        assert run(repo, *bad).returncode == 1, bad


def test_close_names_the_files_that_still_link_to_the_old_place(repo):
    other = repo / "work" / "tasks" / "beta"
    other.mkdir(parents=True)
    (other / "STATUS.md").write_text(
        STATUS.replace("alpha", "beta") + "\nSee [alpha](../alpha/STATUS.md).\n", encoding="utf-8")
    r = run(repo, "close", "alpha", "--json")
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    assert out["stale_links"] == ["work/tasks/beta/STATUS.md"]
    assert any("check-edges.py --fix" in w for w in out["warnings"])


# ---------------------------------------------------------------- shelve: park a finite task as an idea

def _inbox(repo):
    import importlib.util
    spec = importlib.util.spec_from_file_location("inbox_mod_shelve", ROOT / "scripts" / "inbox.py")
    ib = importlib.util.module_from_spec(spec)
    sys.modules["inbox_mod_shelve"] = ib
    spec.loader.exec_module(ib)
    return ib.Inbox(repo / "work" / "inbox", actor="test")


def _headlined(repo):
    p = repo / "work/tasks/alpha/STATUS.md"
    p.write_text(p.read_text(encoding="utf-8").replace("status: doing\n", 'status: doing\nheadline: "Sort the shelf"\n', 1),
                 encoding="utf-8")


def test_shelve_files_an_idea_defers_it_and_closes_the_task_as_declined(repo):
    import datetime
    import json as _json
    _log_with_today(repo)
    _headlined(repo)
    r = run(repo, "shelve", "alpha", "--reason", "no time this quarter", "--json")
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    today = datetime.date.today()
    month = f"{today:%Y-%m}"
    assert out["moved_to"] == f"work/done/{month}/alpha" and out["until"] == (today + datetime.timedelta(days=90)).isoformat()
    assert not (repo / "work/tasks/alpha").exists()
    text = (repo / f"work/done/{month}/alpha/STATUS.md").read_text(encoding="utf-8")
    assert "outcome: declined" in text and "shelved: no time this quarter" in text
    item = _inbox(repo).get(out["inbox"])
    assert item.key == "shelve:alpha" and item.kind == "idea" and item.gate == "only-you" and item.urgency == "later"
    assert item.summary == "Sort the shelf"
    assert f"work/done/{month}/alpha/STATUS.md" in item.detail and "task.py reopen alpha" in item.detail
    assert item.state == "deferred" and item.deferral["until"] == out["until"]
    assert (repo / "work" / "inbox.md").is_file()


def test_shelve_until_and_without_headline_or_reason(repo):
    import json as _json
    r = run(repo, "shelve", "alpha", "--until", "2099-03-01", "--json")
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    item = _inbox(repo).get(out["inbox"])
    assert out["until"] == "2099-03-01" and item.deferral["until"] == "2099-03-01"
    assert item.summary == "Quoted: title"               # no headline: the title, then the first heading
    month_dirs = list((repo / "work" / "done").glob("*/alpha/STATUS.md"))
    assert "Declined: shelved" in month_dirs[0].read_text(encoding="utf-8")


def test_shelve_refuses_a_stream_a_bad_day_and_an_unknown_or_closed_task_without_filing_anything(repo):
    assert run(repo, "shelve", "river").returncode == 1
    assert "stream" in run(repo, "shelve", "river").stderr
    assert run(repo, "shelve", "alpha", "--until", "someday").returncode == 1
    assert run(repo, "shelve", "ghost").returncode == 1
    assert _inbox(repo).items() == []
    assert (repo / "work/tasks/alpha/STATUS.md").is_file() and (repo / "work/streams/river/STATUS.md").is_file()
    assert run(repo, "shelve", "alpha").returncode == 0
    assert run(repo, "shelve", "alpha").returncode == 1           # already closed
    assert len(_inbox(repo).items()) == 1


def test_a_failed_close_leaves_no_half_state_the_idea_closes_again(repo, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_shelve_fail", ROOT / "scripts" / "task.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(m, "close_task", boom)
    with pytest.raises(OSError):
        m.shelve_task(repo, "alpha")
    assert (repo / "work/tasks/alpha/STATUS.md").is_file()
    items = _inbox(repo).items()
    assert len(items) == 1 and items[0].state == "done"          # task still open, no live idea about it


def test_reopen_closes_the_shelve_idea_open_or_deferred(repo):
    import json as _json
    out = _json.loads(run(repo, "shelve", "alpha", "--json").stdout)
    box = _inbox(repo)
    assert box.get(out["inbox"]).state == "deferred"
    r = run(repo, "reopen", "alpha", "--json")
    assert r.returncode == 0, r.stderr
    item = _inbox(repo).get(out["inbox"])
    assert item.state == "done" and any("reopened" in (e.data.get("text") or "") for e in item.events)
    assert (repo / "work/tasks/alpha/STATUS.md").is_file()
    # shelving again files a fresh idea (a closed key may come back)
    again = _json.loads(run(repo, "shelve", "alpha", "--json").stdout)
    assert again["inbox"] != out["inbox"]
    # an idea whose deferral ran out is open, and reopen closes it as well
    box = _inbox(repo)
    box.event(again["inbox"], "defer", until="2000-01-01")
    assert _inbox(repo).get(again["inbox"]).state == "open"
    assert run(repo, "reopen", "alpha").returncode == 0
    assert _inbox(repo).get(again["inbox"]).state == "done"


def test_reopen_without_a_shelve_idea_or_inbox_is_unchanged(repo):
    assert run(repo, "close", "alpha").returncode == 0
    r = run(repo, "reopen", "alpha")
    assert r.returncode == 0, r.stderr
    assert not (repo / "work" / "inbox").exists()


@pytest.mark.parametrize("verb", ["drop", "reject"])
def test_shelving_again_after_a_person_ended_the_idea_brings_the_idea_back(repo, verb):
    import json as _json
    first = _json.loads(run(repo, "shelve", "alpha", "--json").stdout)
    getattr(_inbox(repo), verb)(first["inbox"], note="not now")
    assert run(repo, "reopen", "alpha").returncode == 0
    r = run(repo, "shelve", "alpha", "--until", "2099-03-01", "--json")
    assert r.returncode == 0, r.stderr
    item = _inbox(repo).get(_json.loads(r.stdout)["inbox"])
    assert item.state == "deferred" and item.deferral["until"] == "2099-03-01"   # never shelved without a live idea


def test_a_mute_rule_on_shelve_ideas_is_kept_and_said(repo):
    import json as _json
    first = _json.loads(run(repo, "shelve", "alpha", "--json").stdout)
    _inbox(repo).drop(first["inbox"], note="never tell me", reason="family")
    assert run(repo, "reopen", "alpha").returncode == 0
    r = run(repo, "shelve", "alpha", "--json")
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    assert _inbox(repo).get(out["inbox"]).state == "dropped"
    assert any("mute" in w for w in out["warnings"])


# ---------------------------------------------------------------- merge: two tasks about the same thing become one

KEEP = (
    "---\n"
    "slug: keeper\n"
    "type: feature\n"
    "status: doing\n"
    "priority: P1\n"
    "created: 2026-09-01\n"
    "last_updated: 2026-09-01\n"
    "headline: Keep this one\n"
    "sync:\n"
    "  bridge_only: true\n"
    "---\n\n# Keep this one\n\n## Situation\n\nThe kept task.\n\n## Notes\n\n- 2026-09-02: first note of the keeper\n"
)
GONE = (
    "---\n"
    "slug: merged-one\n"
    "type: feature\n"
    "status: review\n"
    "priority: P2\n"
    "created: 2026-09-03\n"
    "last_updated: 2026-09-04\n"
    "headline: The other one\n"
    "brief:\n"
    "  goal: The same thing from another side\n"
    "---\n\n# The other one\n\n## Next Steps\n\n- [x] a ticked step\n- [ ] an open step\n  - [ ] a nested open step\n\n"
    "## Notes\n\n- 2026-09-03: started it\n- 2026-09-04: asked the vendor\n"
)


def _two(repo, keep=KEEP, gone=GONE, docs=("a.md", "b.pdf")):
    for slug, text in (("keeper", keep), ("merged-one", gone)):
        d = repo / "work" / "tasks" / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "STATUS.md").write_text(text, encoding="utf-8")
    deliv = repo / "work" / "tasks" / "merged-one" / "deliverables"
    deliv.mkdir(exist_ok=True)
    for name in docs:
        (deliv / name).write_text("doc\n", encoding="utf-8")
    (deliv / ".hidden").write_text("x\n", encoding="utf-8")
    _log_with_today(repo)
    return repo / "work" / "tasks" / "keeper" / "STATUS.md"


def test_close_merged_into_sets_the_outcome_and_the_task_it_went_into(repo):
    r = run(repo, "close", "alpha", "--merged-into", "keeper", "--json")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    text = (repo / "work" / "done" / f"{today:%Y-%m}" / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert "status: done\n" in text and "outcome: merged\n" in text and "merged_into: keeper\n" in text
    assert text.index("closed:") < text.index("outcome: merged") < text.index("merged_into: keeper")
    assert f"- {today.isoformat()}: Merged into keeper" in text
    out = _json.loads(r.stdout)
    assert out["outcome"] == "merged" and out["merged_into"] == "keeper"
    rows = [ln for ln in (repo / "work" / "log.md").read_text(encoding="utf-8").splitlines() if "| alpha |" in ln]
    assert rows and rows[-1].endswith("merged into keeper |")


def test_close_merged_into_refuses_declined_and_a_bad_slug(repo):
    assert run(repo, "close", "alpha", "--merged-into", "keeper", "--declined").returncode in (1, 2)
    assert run(repo, "close", "alpha", "--merged-into", "Bad Slug").returncode in (1, 2)
    assert (repo / "work" / "tasks" / "alpha" / "STATUS.md").is_file()


def test_merge_copies_goal_notes_and_open_steps_links_the_documents_and_closes_the_other(repo):
    keep = _two(repo)
    r = run(repo, "merge", "keeper", "--from", "merged-one", "--json")
    assert r.returncode == 0, r.stderr
    today = _dt.date.today()
    month = f"{today:%Y-%m}"
    done = repo / "work" / "done" / month / "merged-one"
    assert not (repo / "work" / "tasks" / "merged-one").exists() and (done / "STATUS.md").is_file()
    gone = (done / "STATUS.md").read_text(encoding="utf-8")
    assert "outcome: merged\n" in gone and "merged_into: keeper\n" in gone
    assert (done / "deliverables" / "a.md").is_file()                     # the documents move with the folder
    text = keep.read_text(encoding="utf-8")
    block = text[text.index("<!-- merged-from: merged-one -->"):text.index("<!-- /merged-from: merged-one -->")]
    assert "## Merged from merged-one\n" in block
    assert "The other one\n" in block and "The same thing from another side\n" in block
    assert "- 2026-09-03: started it\n" in block and "- 2026-09-04: asked the vendor\n" in block
    assert "- [ ] an open step\n" in block and "  - [ ] a nested open step\n" in block and "a ticked step" not in block
    assert f"- work/done/{month}/merged-one/STATUS.md\n" in block
    assert f"- work/done/{month}/merged-one/deliverables/a.md\n" in block
    assert f"- work/done/{month}/merged-one/deliverables/b.pdf\n" in block and ".hidden" not in block
    assert text.index("<!-- /merged-from: merged-one -->") < text.index("## Notes")   # before the notes
    assert f"related:\n  - work/done/{month}/merged-one/STATUS.md  # merged-from: merged-one\n" in text
    assert f"  - work/done/{month}/merged-one/deliverables/b.pdf  # merged-from: merged-one\n" in text
    assert f"- {today.isoformat()}: Merged in merged-one: The other one" in text
    assert f"last_updated: {today.isoformat()}" in text
    out = _json.loads(r.stdout)
    assert out == {"keep": "keeper", "slug": "merged-one", "moved_to": f"work/done/{month}/merged-one",
                   "notes": 2, "steps": 2, "docs": 2, "related": 3, "warnings": []}
    rows = (repo / "work" / "log.md").read_text(encoding="utf-8").splitlines()
    assert any("| merged-one |" in ln and ln.endswith("merged into keeper |") for ln in rows)
    assert any("| keeper |" in ln and ln.endswith("merged in merged-one |") for ln in rows)
    assert "keeper" in (repo / "work" / "board.md").read_text(encoding="utf-8")


def test_merge_takes_a_heading_of_its_own_and_puts_the_block_at_the_end_without_notes(repo):
    keep = _two(repo, keep=KEEP.split("## Notes")[0].rstrip("\n") + "\n", docs=())
    r = run(repo, "merge", "keeper", "--from", "merged-one", "--heading", "Taken over from {slug}", "--json")
    assert r.returncode == 0, r.stderr
    text = keep.read_text(encoding="utf-8")
    assert "## Taken over from merged-one\n" in text
    assert text.index("<!-- /merged-from: merged-one -->") < text.index("## Notes")   # the note made the section after it
    out = _json.loads(r.stdout)
    assert out["docs"] == 0 and out["related"] == 1


def test_merge_appends_to_a_block_list_of_related_and_leaves_a_flow_list_alone(repo):
    keep = _two(repo, keep=KEEP.replace("sync:\n", "related:\n  - docs/x.md\n  - docs/y.md\nsync:\n"), docs=())
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    month = f"{_dt.date.today():%Y-%m}"
    assert (f"related:\n  - docs/x.md\n  - docs/y.md\n  - work/done/{month}/merged-one/STATUS.md  # merged-from: merged-one\n"
            "sync:\n") in keep.read_text(encoding="utf-8")
    third = repo / "work" / "tasks" / "third-one"
    third.mkdir(parents=True)
    (third / "STATUS.md").write_text(GONE.replace("merged-one", "third-one"), encoding="utf-8")
    text = keep.read_text(encoding="utf-8")
    start = text.index("related:\n")
    keep.write_text(text[:start] + "related: [docs/x.md]\n" + text[text.index("sync:\n"):], encoding="utf-8")
    r = run(repo, "merge", "keeper", "--from", "third-one", "--json")
    assert r.returncode == 0, r.stderr
    out = _json.loads(r.stdout)
    assert out["related"] == 0 and out["warnings"] and "related" in out["warnings"][0]
    assert "related: [docs/x.md]\n" in keep.read_text(encoding="utf-8")


def test_merge_refuses_without_writing(repo):
    keep = _two(repo)
    before = keep.read_bytes()
    for args in (("keeper", "--from", "keeper"), ("keeper", "--from", "ghost"), ("ghost", "--from", "merged-one"),
                 ("keeper", "--from", "river"), ("river", "--from", "merged-one")):
        r = run(repo, "merge", *args)
        assert r.returncode == 1, (args, r.stderr)
    month = repo / "work" / "done" / f"{_dt.date.today():%Y-%m}" / "merged-one"
    month.mkdir(parents=True)
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 1        # its place in done is taken
    month.rmdir()
    keep.write_text(keep.read_text(encoding="utf-8") + "\n<!-- merged-from: merged-one -->\n", encoding="utf-8")
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 1        # a block for it is there already
    keep.write_bytes(before)
    assert keep.read_bytes() == before and (repo / "work" / "tasks" / "merged-one" / "STATUS.md").is_file()


def test_a_failed_close_takes_the_block_and_the_related_lines_out_again(repo, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    keep = _two(repo)
    before = keep.read_bytes()

    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(mod, "close_task", boom)
    with pytest.raises(OSError):
        mod.merge_task(repo, "keeper", "merged-one")
    assert keep.read_bytes() == before
    assert (repo / "work" / "tasks" / "merged-one" / "STATUS.md").is_file()


def test_unmerge_takes_the_merge_back(repo):
    keep = _two(repo)
    before = keep.read_bytes()
    gone_before = (repo / "work" / "tasks" / "merged-one" / "STATUS.md").read_bytes()
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    assert (repo / ".bridge" / "task-merges.json").is_file()        # what the undo restores, kept beside the run
    r = run(repo, "unmerge", "keeper", "--from", "merged-one", "--as", "review", "--json")
    assert r.returncode == 0, r.stderr
    back = repo / "work" / "tasks" / "merged-one" / "STATUS.md"
    assert back.is_file() and (repo / "work" / "tasks" / "merged-one" / "deliverables" / "a.md").is_file()
    # both files as they were before the merge, byte for byte: no note, no new last_updated, the status before
    assert back.read_bytes() == gone_before and keep.read_bytes() == before
    assert "status: review\n" in back.read_text(encoding="utf-8")
    out = _json.loads(r.stdout)
    assert out["keep"] == "keeper" and out["slug"] == "merged-one" and out["status"] == "review" and out["restored"] is True
    assert out["moved_to"] == "work/tasks/merged-one" and out["removed"] == {"block": True, "related": 3}
    assert "keeper<merged-one" not in _json.loads((repo / ".bridge" / "task-merges.json").read_text(encoding="utf-8"))
    rows = (repo / "work" / "log.md").read_text(encoding="utf-8").splitlines()
    assert any("| keeper |" in ln and ln.endswith("merge of merged-one taken back |") for ln in rows)


def test_unmerge_restores_the_kept_task_when_only_its_brief_was_written_meanwhile(repo):
    keep = _two(repo)
    before = keep.read_bytes()
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    text = keep.read_text(encoding="utf-8")
    # the describe pass wrote a new brief for the merged text: no change of what the task says
    keep.write_text(text.replace("sync:\n", "brief:\n  goal: Both sides of the same thing\nsync:\n", 1), encoding="utf-8")
    r = run(repo, "unmerge", "keeper", "--from", "merged-one", "--json")
    assert r.returncode == 0, r.stderr
    assert keep.read_bytes() == before


def test_unmerge_after_a_change_by_hand_takes_out_what_the_merge_added_and_writes_no_note(repo):
    keep = _two(repo)
    gone_before = (repo / "work" / "tasks" / "merged-one" / "STATUS.md").read_bytes()
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    today = _dt.date.today().isoformat()
    text = keep.read_text(encoding="utf-8")
    keep.write_text(text.replace("## Situation\n\nThe kept task.\n", "## Situation\n\nThe kept task, changed by hand.\n"),
                    encoding="utf-8")
    r = run(repo, "unmerge", "keeper", "--from", "merged-one", "--json")
    assert r.returncode == 0, r.stderr
    text = keep.read_text(encoding="utf-8")
    assert "The kept task, changed by hand." in text                       # the change by hand stays
    assert "merged-from" not in text and "related:" not in text
    assert "Merged in merged-one" not in text and "taken back" not in text     # the merge's note goes, the undo writes none
    assert "- 2026-09-02: first note of the keeper\n" in text
    # the merged task was not touched while closed: it comes back as it was
    assert (repo / "work" / "tasks" / "merged-one" / "STATUS.md").read_bytes() == gone_before
    assert _json.loads(r.stdout)["restored"] is False
    assert f"- {today}:" not in text


def test_unmerge_of_a_merged_task_changed_while_closed_writes_no_note_and_keeps_its_blocker(repo):
    blocked = GONE.replace("headline: The other one\n", "headline: The other one\nblocked_by: waits on the vendor\n"
                           "blocked_since: 2026-09-01\n")
    _two(repo, gone=blocked)
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    done = next((repo / "work" / "done").glob("*/merged-one/STATUS.md"))
    done.write_text(done.read_text(encoding="utf-8") + "\nA line written while it was closed.\n", encoding="utf-8")
    r = run(repo, "unmerge", "keeper", "--from", "merged-one", "--as", "review")
    assert r.returncode == 0, r.stderr
    back = (repo / "work" / "tasks" / "merged-one" / "STATUS.md").read_text(encoding="utf-8")
    assert "blocked_by: waits on the vendor\n" in back and "blocked_since: 2026-09-01\n" in back
    assert "status: review\n" in back and "outcome:" not in back and "merged_into" not in back and "closed:" not in back
    assert "Merged into keeper" not in back and "Reopened" not in back
    assert "A line written while it was closed." in back


def test_a_merged_task_keeps_its_blocker_while_closed_and_after_the_undo(repo):
    blocked = GONE.replace("headline: The other one\n", "headline: The other one\nblocked_by: waits on the vendor\n"
                           "blocked_since: 2026-09-01\n")
    _two(repo, gone=blocked)
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    done = next((repo / "work" / "done").glob("*/merged-one/STATUS.md")).read_text(encoding="utf-8")
    assert "blocked_by: waits on the vendor\n" in done and "blocked_since: 2026-09-01\n" in done
    assert run(repo, "unmerge", "keeper", "--from", "merged-one").returncode == 0
    back = (repo / "work" / "tasks" / "merged-one" / "STATUS.md").read_text(encoding="utf-8")
    assert back == blocked
    # a plain close still drops the blocker
    assert run(repo, "close", "merged-one").returncode == 0
    assert "blocked_by" not in next((repo / "work" / "done").glob("*/merged-one/STATUS.md")).read_text(encoding="utf-8")


def test_merge_leaves_the_bookkeeping_of_earlier_merges_out_of_the_section(repo):
    noisy = GONE.replace("- 2026-09-04: asked the vendor\n", "- 2026-09-04: asked the vendor\n- 2026-09-05: Merged into other-task\n"
                         "- 2026-09-05: Reopened: merge into other-task taken back\n- 2026-09-06: Merged in third-one: A third\n"
                         "- 2026-09-06: Merge of third-one taken back\n- 2026-09-07: Reopened\n")
    keep = _two(repo, gone=noisy)
    r = run(repo, "merge", "keeper", "--from", "merged-one", "--json")
    assert r.returncode == 0, r.stderr
    text = keep.read_text(encoding="utf-8")
    block = text[text.index("<!-- merged-from: merged-one -->"):text.index("<!-- /merged-from: merged-one -->")]
    assert "- 2026-09-03: started it\n" in block and "- 2026-09-04: asked the vendor\n" in block
    assert "- 2026-09-07: Reopened\n" in block                               # a reopen of its own is no merge bookkeeping
    assert "other-task" not in block and "third-one" not in block
    assert _json.loads(r.stdout)["notes"] == 3


@pytest.mark.parametrize("related", [
    "related:\n- docs/x.md\n- docs/y.md\n",                                    # indentless, as PyYAML writes it
    "related:\n  - docs/x.md\n  - \"docs/a long\n    name.md\"\n",                # an item that goes on in a second line
    "related:\n- docs/x.md\n- \"docs/a long\n  name.md\"\n",
])
def test_merge_and_unmerge_keep_a_related_list_of_any_block_style_readable(repo, related):
    yaml = pytest.importorskip("yaml")
    keep = _two(repo, keep=KEEP.replace("sync:\n", related + "sync:\n"), docs=())
    old = yaml.safe_load(keep.read_text(encoding="utf-8").split("---", 2)[1])["related"]
    r = run(repo, "merge", "keeper", "--from", "merged-one", "--json")
    assert r.returncode == 0, r.stderr
    month = f"{_dt.date.today():%Y-%m}"
    front = yaml.safe_load(keep.read_text(encoding="utf-8").split("---", 2)[1])
    assert front["related"] == old + [f"work/done/{month}/merged-one/STATUS.md"]
    assert front["sync"] == {"bridge_only": True}
    text = keep.read_text(encoding="utf-8")
    keep.write_text(text.replace("## Situation\n\nThe kept task.\n", "## Situation\n\nChanged by hand.\n"), encoding="utf-8")
    assert run(repo, "unmerge", "keeper", "--from", "merged-one").returncode == 0     # the edit path, not the restore
    front = yaml.safe_load(keep.read_text(encoding="utf-8").split("---", 2)[1])
    assert front["related"] == old and front["sync"] == {"bridge_only": True}


def test_merge_leaves_a_related_list_it_cannot_extend_safely_alone_and_says_so(repo, monkeypatch):
    yaml = pytest.importorskip("yaml")
    mod = _task_module()
    # an edit that would not read back as the old items plus the new ones is not written
    monkeypatch.setattr(mod, "_yaml_item", lambda path: "[broken")
    keep = _two(repo, keep=KEEP.replace("sync:\n", "related:\n  - docs/x.md\nsync:\n"), docs=())
    out = mod.merge_task(repo, "keeper", "merged-one")
    front = yaml.safe_load(keep.read_text(encoding="utf-8").split("---", 2)[1])
    assert front["related"] == ["docs/x.md"] and out["related"] == 0
    assert out["warnings"] and "related" in out["warnings"][0]


def _task_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_under_test_r4", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_unmerge_keeps_other_related_items_and_refuses_what_no_merge_made(repo):
    keep = _two(repo, keep=KEEP.replace("sync:\n", "related:\n  - docs/x.md\nsync:\n"), docs=())
    r = run(repo, "unmerge", "keeper", "--from", "merged-one")
    assert r.returncode == 1                                                  # nothing merged yet
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    assert run(repo, "unmerge", "merged-one", "--from", "keeper").returncode == 1   # the other way round
    text = keep.read_text(encoding="utf-8")
    cut = text.replace("<!-- merged-from: merged-one -->\n", "")
    keep.write_text(cut, encoding="utf-8")
    assert run(repo, "unmerge", "keeper", "--from", "merged-one").returncode == 1   # the block was changed by hand
    keep.write_text(text, encoding="utf-8")
    assert run(repo, "unmerge", "keeper", "--from", "merged-one").returncode == 0
    assert "related:\n  - docs/x.md\nsync:\n" in keep.read_text(encoding="utf-8")


def test_reopen_drops_merged_into(repo):
    assert run(repo, "close", "alpha", "--merged-into", "keeper").returncode == 0
    assert run(repo, "reopen", "alpha").returncode == 0
    text = (repo / "work" / "tasks" / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert "merged_into" not in text and "outcome:" not in text


def test_a_task_closed_as_merged_fits_the_status_schema(repo):
    yaml = pytest.importorskip("yaml")
    jsonschema = pytest.importorskip("jsonschema")
    _two(repo)
    assert run(repo, "merge", "keeper", "--from", "merged-one").returncode == 0
    text = next((repo / "work" / "done").glob("*/merged-one/STATUS.md")).read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---", 2)[1])
    front = _json.loads(_json.dumps(front, default=str))      # dates as the schema reads them: strings
    schema = yaml.safe_load((ROOT / "work" / "templates" / "_schema.status.yaml").read_text(encoding="utf-8"))
    schema.pop("required", None)                              # the fixture carries no sync block of its own
    jsonschema.validate(front, schema)
    assert front["outcome"] == "merged" and front["merged_into"] == "keeper"
    bad = {**front, "merged_into": "Not A Slug"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
