# SPDX-License-Identifier: MIT
"""Contract for `task.py brief`: the nested brief block of a STATUS.md written or replaced as a whole, with
by, at, basis and edited, and every other byte of the file left as it was."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "task.py"
sys.path.insert(0, str(ROOT / "scripts"))
from lib.bridge_cockpit.card_fields import brief_basis, strip_brief, validate_brief  # noqa: E402

STATUS = (
    "# yaml-language-server: $schema=../../templates/_schema.status.yaml\n"
    "---\n"
    "slug: alpha   # keep me\n"
    "status: doing\n"
    "title: \"Quoted: title\"\n"
    "next: {what: \"Ship it\", who: me}\n"
    "last_updated: 2026-09-01\n"
    "---\n\n# Alpha\n\nbody status: doing\n\n- [ ] one\n"
)
BRIEF = {"goal": "Invoices reach the customer without a manual resend",
         "story": {"as": "an accountant", "want": "every invoice delivered once", "so_that": "nobody chases a resend"},
         "acceptance": ["A rejected invoice shows up in the inbox within an hour", "No invoice is delivered twice"],
         "by": "claude-haiku-5-5", "at": "2026-10-25"}


def run(root, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args], capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    for kind, slug in (("tasks", "alpha"), ("streams", "river")):
        d = tmp_path / "work" / kind / slug
        d.mkdir(parents=True)
        (d / "STATUS.md").write_text(STATUS.replace("alpha", slug), encoding="utf-8")
    return tmp_path


def path(repo, slug="alpha", kind="tasks"):
    return repo / "work" / kind / slug / "STATUS.md"


def front(text):
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_a_brief_is_written_as_one_block_and_nothing_else_changes(repo):
    old = path(repo).read_text(encoding="utf-8")
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF), "--json")
    assert r.returncode == 0, r.stderr
    new = path(repo).read_text(encoding="utf-8")
    # every byte but the block stays, comments, quoting and order included
    assert strip_brief(new) == strip_brief(old) == old
    fm = front(new.split("\n", 1)[1])
    brief = fm["brief"]
    assert brief["goal"] == BRIEF["goal"] and brief["acceptance"] == BRIEF["acceptance"]
    assert brief["story"] == BRIEF["story"] and brief["by"] == "claude-haiku-5-5"
    assert brief["edited"] is False and brief["basis"] == brief_basis(new) == brief_basis(old)
    assert validate_brief(brief) == ({**BRIEF, "basis": brief["basis"], "edited": False}, [])
    out = json.loads(r.stdout)
    assert out["slug"] == "alpha" and out["basis"] == brief["basis"]
    # last_updated stays: a brief is no activity on the task
    assert "last_updated: 2026-09-01\n" in new


def test_a_second_write_replaces_the_block_in_place(repo):
    run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF))
    first = path(repo).read_text(encoding="utf-8")
    other = {**BRIEF, "goal": "Every invoice is sent once", "acceptance": ["Nobody resends by hand"]}
    del other["story"]
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps(other))
    assert r.returncode == 0, r.stderr
    new = path(repo).read_text(encoding="utf-8")
    assert new.count("brief:") == 1 and strip_brief(new) == strip_brief(first)
    brief = front(new.split("\n", 1)[1])["brief"]
    assert brief["goal"] == "Every invoice is sent once" and "story" not in brief
    assert brief["acceptance"] == ["Nobody resends by hand"]


def test_a_hand_written_block_in_the_middle_is_replaced_where_it_stands(repo):
    text = STATUS.replace("next:", "brief:\n  goal: \"Old goal\"\n  acceptance:\n    - \"x\"\n\n  edited: false\nnext:")
    path(repo).write_text(text, encoding="utf-8")
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF))
    assert r.returncode == 0, r.stderr
    new = path(repo).read_text(encoding="utf-8")
    lines = new.splitlines()
    assert lines.index("brief:") < lines.index('next: {what: "Ship it", who: me}')
    assert "Old goal" not in new and strip_brief(new) == strip_brief(text)


def test_edited_marks_a_human_write(repo):
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF), "--edited")
    assert r.returncode == 0, r.stderr
    assert front(path(repo).read_text(encoding="utf-8").split("\n", 1)[1])["brief"]["edited"] is True


def test_mark_edited_turns_the_flag_and_keeps_the_text_as_it_is(repo):
    run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF))
    text = path(repo).read_text(encoding="utf-8").replace(BRIEF["goal"], "A goal a person wrote")
    path(repo).write_text(text, encoding="utf-8")
    r = run(repo, "brief", "alpha", "--mark-edited")
    assert r.returncode == 0, r.stderr
    new = path(repo).read_text(encoding="utf-8")
    assert new == text.replace("  edited: false\n", "  edited: true\n")


def test_mark_edited_adds_the_flag_when_the_block_has_none(repo):
    text = STATUS.replace("next:", "brief:\n  goal: \"Hand made\"\nnext:")
    path(repo).write_text(text, encoding="utf-8")
    assert run(repo, "brief", "alpha", "--mark-edited").returncode == 0
    new = path(repo).read_text(encoding="utf-8")
    assert new == text.replace("  goal: \"Hand made\"\n", "  goal: \"Hand made\"\n  edited: true\n")


def test_mark_edited_without_a_brief_is_refused(repo):
    r = run(repo, "brief", "alpha", "--mark-edited")
    assert r.returncode == 1 and "no brief" in r.stderr
    assert path(repo).read_text(encoding="utf-8") == STATUS


def test_a_basis_that_no_longer_matches_is_refused_without_writing(repo):
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF), "--basis", "0123456789abcdef")
    assert r.returncode == 1 and "changed" in r.stderr
    assert path(repo).read_text(encoding="utf-8") == STATUS
    ok = run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF), "--basis", brief_basis(STATUS))
    assert ok.returncode == 0, ok.stderr


@pytest.mark.parametrize("bad", [{**BRIEF, "goal": "x" * 141}, {**BRIEF, "goal": "Ship it \u2014 now"},
                                 {**BRIEF, "by": "haiku"}, {"acceptance": ["a"]}])
def test_a_brief_the_gate_refuses_is_not_written(repo, bad):
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps(bad))
    assert r.returncode == 1 and "brief:" in r.stderr
    assert path(repo).read_text(encoding="utf-8") == STATUS


def test_a_stream_gets_its_brief_too_and_crlf_stays_crlf(repo):
    p = path(repo, "river", "streams")
    p.write_bytes(STATUS.replace("alpha", "river").replace("\n", "\r\n").encode("utf-8"))
    stream = {k: v for k, v in BRIEF.items() if k != "acceptance"}
    r = run(repo, "brief", "river", "--brief-json", json.dumps({**stream, "acceptance": []}))
    assert r.returncode == 0, r.stderr
    raw = p.read_bytes().decode("utf-8")
    assert "\n" not in raw.replace("\r\n", "")
    assert "brief:\r\n" in raw and "acceptance: []\r\n" in raw


def test_a_basis_made_only_of_digits_stays_text(repo, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_brief_under_test", SCRIPT)
    task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task)
    block = task.brief_block({**BRIEF, "basis": "0123456789012345", "edited": False})
    assert yaml.safe_load(block)["brief"]["basis"] == "0123456789012345"


def test_brief_and_mark_edited_are_one_or_the_other(repo):
    assert run(repo, "brief", "alpha").returncode == 1
    assert run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF), "--mark-edited").returncode == 1
    assert run(repo, "brief", "nope", "--brief-json", json.dumps(BRIEF)).returncode == 1


# ---------------------------------------------------------------- the review reads the acceptance

class _Done:
    returncode, stdout, stderr = 0, "", ""


def _task_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("task_review_brief_under_test", SCRIPT)
    task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task)
    return task


def test_the_review_prompt_carries_the_acceptance_as_evidence_for_close(repo):
    task = _task_module()
    assert run(repo, "brief", "alpha", "--brief-json", json.dumps(BRIEF)).returncode == 0
    (repo / "work" / "log.md").write_text("# Log\n", encoding="utf-8")
    [t] = task.gather(repo, ["alpha"], lambda argv, **kw: _Done())
    assert t["evidence"]["acceptance"] == BRIEF["acceptance"]
    block = task._task_block(t)
    assert "acceptance: " + " | ".join(BRIEF["acceptance"]) in block
    assert "acceptance" in task.REVIEW_PROMPT and "close" in task.REVIEW_PROMPT.split("acceptance", 1)[1][:400]


def test_a_task_without_a_brief_has_no_acceptance_line(repo):
    task = _task_module()
    (repo / "work" / "log.md").write_text("# Log\n", encoding="utf-8")
    [t] = task.gather(repo, ["alpha"], lambda argv, **kw: _Done())
    assert t["evidence"]["acceptance"] is None and "acceptance:" not in task._task_block(t)


@pytest.mark.parametrize("char", ["\x81", "\x85", " "])
def test_a_brief_with_a_control_character_is_refused_and_the_file_untouched(repo, char):
    old = path(repo).read_bytes()
    r = run(repo, "brief", "alpha", "--brief-json", json.dumps({**BRIEF, "goal": f"a{char}b goal"}))
    assert r.returncode != 0 and "control or format character" in r.stderr
    assert path(repo).read_bytes() == old


def _task_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_task_brief_atomic", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_brief_write_and_the_edited_mark_replace_the_file_whole(repo, monkeypatch):
    # a reader never sees half a STATUS.md: the new text goes to a file beside it, which then takes its place
    task = _task_module()
    replaced = []
    real_replace = task.os.replace
    monkeypatch.setattr(task.os, "replace", lambda a, b: (replaced.append((Path(a), Path(b))), real_replace(a, b)))
    task.write_brief(repo, "alpha", dict(BRIEF), today="2026-10-25")
    task.mark_brief_edited(repo, "alpha")
    target = path(repo)
    assert [b for _, b in replaced] == [target, target]
    assert all(a.parent == target.parent and a != target and not a.exists() for a, _ in replaced)
    assert front(target.read_text(encoding="utf-8").split("\n", 1)[1])["brief"]["edited"] is True
    assert sorted(p.name for p in target.parent.iterdir()) == ["STATUS.md"]
