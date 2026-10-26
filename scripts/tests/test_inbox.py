# SPDX-License-Identifier: MIT
"""Contract for scripts/inbox.py: one place where everything that needs a person waits.

The properties that matter, in the order they bit before this file existed:

* an item knows when it is done (`closes_when`) and `check` closes it from the
  live source, so a solved thing never comes back in a briefing;
* two machines write the inbox through git and never conflict: an item is
  created once and every change is a NEW file, nothing is ever rewritten;
* state is derived from the events, never stored;
* a repeated finding (a watcher firing every five minutes) is one item, not fifty;
* `run` executes only what a person released, and never an `only-you` action.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inbox.py"

spec = importlib.util.spec_from_file_location("inbox", SCRIPT)
assert spec is not None and spec.loader is not None
inbox = importlib.util.module_from_spec(spec)
sys.modules["inbox"] = inbox      # dataclasses resolve the module by name while loading
sys.dont_write_bytecode = True
spec.loader.exec_module(inbox)

NOW = dt.datetime(2026, 10, 4, 18, 0)


@pytest.fixture()
def box(tmp_path):
    return inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=lambda: NOW)


def add(box, **kw):
    base = dict(source="homebox/issue-radar", kind="decision", summary="PR #70 is green and waits")
    base.update(kw)
    return box.add(**base)


# ---------------------------------------------------------------- creation

def test_add_creates_one_immutable_item_file(box):
    item_id = add(box)
    item_dir = box.root / item_id
    assert (item_dir / "item.yaml").is_file()
    assert box.get(item_id).state == "open"
    assert item_id.startswith("20261004-1800-")


def test_add_rejects_unknown_kind_gate_and_urgency(box):
    with pytest.raises(ValueError):
        add(box, kind="todo")
    with pytest.raises(ValueError):
        add(box, gate="maybe")
    with pytest.raises(ValueError):
        add(box, urgency="asap")


def test_an_idea_is_a_kind_and_ranks_after_everything_that_waits_on_someone(box):
    # An idea has no deadline and nobody is blocked by it: it must never push a decision down.
    idea = add(box, kind="idea", summary="try a new model", urgency="today")
    decision = add(box, kind="decision", summary="merge it", urgency="today")
    result = add(box, kind="result", summary="it ran", urgency="today")
    assert box.get(idea).kind == "idea"
    assert [i.id for i in box.open_items()] == [decision, result, idea]


def test_same_key_while_open_is_one_item(box):
    first = add(box, key="backup-stale")
    second = add(box, key="backup-stale", summary="still stale")
    assert first == second
    assert len(box.items()) == 1
    # the repeat is recorded, so the item shows it is still firing
    assert [e.verb for e in box.get(first).events] == ["seen"]


def test_same_key_after_close_opens_a_new_item(box):
    first = add(box, key="backup-stale")
    box.close(first, note="fixed")
    second = add(box, key="backup-stale")
    assert second != first


def test_ids_never_collide_within_one_minute(box):
    ids = {add(box, summary=f"thing {i}") for i in range(5)}
    assert len(ids) == 5


# ---------------------------------------------------------------- events, never rewrites

def test_every_change_is_a_new_file_and_item_yaml_never_changes(box):
    item_id = add(box)
    before = (box.root / item_id / "item.yaml").read_bytes()
    box.note(item_id, "looked at it")
    box.approve(item_id)
    box.close(item_id)
    assert (box.root / item_id / "item.yaml").read_bytes() == before
    assert len(list((box.root / item_id / "events").glob("*.yaml"))) == 3


def test_two_machines_writing_at_once_produce_disjoint_files(tmp_path):
    root = tmp_path / "work" / "inbox"
    laptop = inbox.Inbox(root, actor="laptop", clock=lambda: NOW)
    homebox = inbox.Inbox(root, actor="homebox", clock=lambda: NOW)
    item_id = laptop.add(source="laptop", kind="decision", summary="x")
    laptop.note(item_id, "a")
    homebox.note(item_id, "b")
    names = sorted(p.name for p in (root / item_id / "events").iterdir())
    assert len(names) == 2 and len(set(names)) == 2
    assert any("laptop" in n for n in names) and any("homebox" in n for n in names)


# ---------------------------------------------------------------- derived state

@pytest.mark.parametrize(
    "steps, state",
    [
        ([], "open"),
        ([("approve", {})], "approved"),
        ([("approve", {"when": {"after": "2099-01-01T00:00"}})], "waiting"),
        ([("defer", {"until": "2099-01-01"})], "deferred"),
        ([("defer", {"until": "2000-01-01"})], "open"),
        ([("reject", {})], "dropped"),
        ([("close", {})], "done"),
        ([("approve", {}), ("executed", {})], "done"),
        ([("approve", {}), ("failed", {})], "open"),
    ],
)
def test_state_is_derived_from_events(box, steps, state):
    item_id = add(box)
    for verb, kw in steps:
        box.event(item_id, verb, **kw)
    assert box.get(item_id).state == state


def test_open_list_hides_done_and_dropped_and_deferred(box):
    a = add(box, summary="a")
    b = add(box, summary="b")
    c = add(box, summary="c")
    add(box, summary="d")
    box.close(a)
    box.reject(b)
    box.event(c, "defer", until="2099-01-01")
    assert [i.summary for i in box.open_items()] == ["d"]


# ---------------------------------------------------------------- probes and check

def test_check_closes_an_item_whose_closes_when_holds(box, tmp_path):
    marker = tmp_path / "token-ok"
    item_id = add(box, closes_when={"path_exists": str(marker)})
    assert box.check() == []
    marker.write_text("ok")
    closed = box.check()
    assert closed == [item_id]
    item = box.get(item_id)
    assert item.state == "done"
    assert item.events[-1].by == "check"


def test_probe_command_and_after(box):
    assert inbox.probe({"command": ["true"]}) is True
    assert inbox.probe({"command": ["false"]}) is False
    assert inbox.probe({"after": "2000-01-01T00:00"}, now=NOW) is True
    assert inbox.probe({"after": "2099-01-01T00:00"}, now=NOW) is False


def test_unknown_or_broken_probe_is_unknown_never_true(box):
    assert inbox.probe({"no_such_probe": 1}) is None
    assert inbox.probe({"command": ["/definitely/not/here"]}) is None
    item_id = add(box, closes_when={"no_such_probe": 1})
    assert box.check() == []
    assert box.get(item_id).state == "open"


def test_gh_probe_reads_state_through_a_runner(box):
    calls = []

    def fake_gh(args):
        calls.append(args)
        return json.dumps({"state": "MERGED", "statusCheckRollup": []})

    assert inbox.probe({"gh_pr": "org/repo#70", "state": "merged"}, gh=fake_gh) is True
    assert calls and calls[0][:3] == ["pr", "view", "70"]


def test_gh_probe_green_needs_every_check_successful():
    def runner(rollup):
        return lambda args: json.dumps({"state": "OPEN", "statusCheckRollup": rollup})

    green = [{"conclusion": "SUCCESS"}, {"conclusion": "SKIPPED"}]
    red = [{"conclusion": "SUCCESS"}, {"conclusion": "FAILURE"}]
    pending = [{"conclusion": "", "status": "IN_PROGRESS"}]
    assert inbox.probe({"gh_pr": "o/r#1", "state": "green"}, gh=runner(green)) is True
    assert inbox.probe({"gh_pr": "o/r#1", "state": "green"}, gh=runner(red)) is False
    assert inbox.probe({"gh_pr": "o/r#1", "state": "green"}, gh=runner(pending)) is False
    assert inbox.probe({"gh_pr": "o/r#1", "state": "green"}, gh=runner([])) is False


# ---------------------------------------------------------------- run: only what a person released

def test_run_executes_an_approved_your_yes_action(box, tmp_path):
    out = tmp_path / "ran"
    item_id = add(box, gate="your-yes", action={"argv": ["touch", str(out)]})
    assert box.run() == []          # not approved yet
    box.approve(item_id)
    assert box.run() == [item_id]
    assert out.exists()
    assert box.get(item_id).state == "done"


def test_run_waits_for_the_condition_of_a_conditional_yes(box, tmp_path):
    out = tmp_path / "ran"
    cond = tmp_path / "green"
    item_id = add(box, gate="your-yes", action={"argv": ["touch", str(out)]})
    box.approve(item_id, when={"path_exists": str(cond)})
    assert box.run() == []
    assert box.get(item_id).state == "waiting"
    cond.write_text("")
    assert box.run() == [item_id]
    assert out.exists()


def test_run_never_executes_only_you_even_when_approved(box, tmp_path):
    out = tmp_path / "sent"
    item_id = add(box, gate="only-you", action={"argv": ["touch", str(out)]})
    with pytest.raises(PermissionError):
        box.approve(item_id, when={"after": "2000-01-01T00:00"})
    box.approve(item_id)            # a plain yes is recorded ...
    assert box.run() == []          # ... but run refuses to act on it
    assert not out.exists()


def test_run_executes_free_actions_without_approval(box, tmp_path):
    out = tmp_path / "regen"
    item_id = add(box, gate="free", action={"argv": ["touch", str(out)]})
    assert box.run() == [item_id]
    assert out.exists()


def test_failed_action_records_exit_code_and_stays_open(box):
    item_id = add(box, gate="free", action={"argv": ["false"]})
    assert box.run() == []
    item = box.get(item_id)
    assert item.state == "open"
    assert item.events[-1].verb == "failed"
    assert item.events[-1].data.get("exit") == 1


def test_action_must_be_an_argv_list_never_a_shell_string(box):
    with pytest.raises(ValueError):
        add(box, action={"argv": "rm -rf /"})
    with pytest.raises(ValueError):
        add(box, action={"shell": "echo hi"})


# ---------------------------------------------------------------- ordering and rendering

def test_first_thing_is_the_most_urgent_decision(box):
    add(box, summary="later finding", kind="finding", urgency="later")
    add(box, summary="today decision", kind="decision", urgency="today")
    add(box, summary="now finding", kind="finding", urgency="now")
    add(box, summary="today finding", kind="finding", urgency="today")
    order = [i.summary for i in box.open_items()]
    assert order == ["now finding", "today decision", "today finding", "later finding"]


def test_render_writes_a_generated_view(box):
    add(box, summary="PR #70 waits", task="a2a")
    text = box.render()
    assert "GENERATED" in text and "PR #70 waits" in text and "a2a" in text


def test_validate_reports_a_hand_edited_broken_item(box):
    item_id = add(box)
    (box.root / item_id / "item.yaml").write_text("kind: nonsense\n")
    problems = box.validate()
    assert problems and item_id in problems[0]


# ---------------------------------------------------------------- CLI

def run_cli(tmp_path, *args):
    env_root = tmp_path / "repo"
    (env_root / "work" / "inbox").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(env_root), "--by", "test", *args],
        capture_output=True, text=True,
    )


def test_cli_add_list_close_roundtrip(tmp_path):
    r = run_cli(tmp_path, "add", "--from", "cli", "--kind", "finding", "--summary", "disk 91 %")
    assert r.returncode == 0, r.stderr
    item_id = r.stdout.strip()
    r = run_cli(tmp_path, "list", "--json")
    assert json.loads(r.stdout)[0]["id"] == item_id
    r = run_cli(tmp_path, "close", item_id[:15], "--note", "cleaned")
    assert r.returncode == 0, r.stderr
    r = run_cli(tmp_path, "list", "--json")
    assert json.loads(r.stdout) == []


def test_cli_unknown_command_exits_2_without_writing(tmp_path):
    r = run_cli(tmp_path, "frobnicate")
    assert r.returncode == 2
    assert not any((tmp_path / "repo" / "work" / "inbox").iterdir())


def test_due_is_validated_and_orders_within_the_same_urgency(box):
    with pytest.raises(ValueError):
        add(box, due="next tuesday")
    add(box, summary="later due", due="2026-10-09")
    add(box, summary="sooner due", due="2026-10-06T15:00")
    assert [i.summary for i in box.open_items()] == ["sooner due", "later due"]


def test_approve_can_release_an_edited_text(box):
    item_id = add(box, kind="draft")
    box.approve(item_id, text="shorter answer")
    assert box.get(item_id).approved_text == "shorter answer"


# ---------------------------------------------------------------- review 2026-10-04: the hard cases

def test_ids_carry_a_random_suffix_so_two_machines_never_share_one(tmp_path):
    a = inbox.Inbox(tmp_path / "a" / "work" / "inbox", actor="laptop", clock=lambda: NOW)
    b = inbox.Inbox(tmp_path / "b" / "work" / "inbox", actor="homebox", clock=lambda: NOW)
    assert a.add(source="x", kind="finding", summary="same") != b.add(source="x", kind="finding", summary="same")


def test_events_are_stamped_in_utc_and_ordered_across_time_zones(tmp_path):
    root = tmp_path / "work" / "inbox"
    utc = dt.timezone.utc
    berlin = dt.timezone(dt.timedelta(hours=2))
    laptop = inbox.Inbox(root, actor="laptop", clock=lambda: dt.datetime(2026, 10, 4, 10, 0, tzinfo=berlin))
    arm = inbox.Inbox(root, actor="homebox", clock=lambda: dt.datetime(2026, 10, 4, 8, 5, tzinfo=utc))
    item_id = laptop.add(source="x", kind="decision", summary="merge", action={"argv": ["true"]})
    laptop.approve(item_id)                     # 08:00 UTC
    arm.event(item_id, "failed", exit=1)        # 08:05 UTC, later although its local clock reads earlier
    assert laptop.get(item_id).state == "open"
    assert laptop.get(item_id).events[0].at.endswith("+00:00")


def test_empty_composite_and_blank_path_are_unknown(box):
    assert inbox.probe({"all": []}) is None
    assert inbox.probe({"any": []}) is None
    assert inbox.probe({"all": "x"}) is None
    assert inbox.probe({"path_exists": ""}) is None
    assert inbox.probe({"path_exists": "   "}) is None


def test_only_you_items_never_run_a_command_probe(box, tmp_path):
    marker = tmp_path / "ran"
    item_id = add(box, gate="only-you", closes_when={"command": ["touch", str(marker)]})
    assert box.check() == []
    assert not marker.exists()
    assert box.get(item_id).state == "open"


def test_a_dropped_key_stays_quiet_a_closed_key_comes_back(box):
    first = add(box, key="advise:quiet:x")
    box.event(first, "drop", text="do not nag")
    assert add(box, key="advise:quiet:x") == first
    assert box.get(first).state == "dropped"
    second = add(box, key="other")
    box.close(second)
    assert add(box, key="other") != second


def test_a_repeat_refreshes_the_summary(box):
    item_id = add(box, key="k", summary="untouched for 7 days")
    add(box, key="k", summary="untouched for 9 days")
    assert box.get(item_id).summary == "untouched for 9 days"


def test_one_unreadable_file_does_not_take_the_inbox_down(box):
    good = add(box, summary="good")
    bad = add(box, summary="bad")
    (box.root / bad / "item.yaml").write_text("<<<<<<< HEAD\n: : :\n")
    (box.root / good / "events" / "20261004T180000-00-x-note.yaml").write_text("- a list, not a mapping\n")
    assert [i.id for i in box.items()] == [good]
    assert box.get(good).state == "open"


def test_run_reports_failures(box):
    ok = add(box, gate="free", action={"argv": ["true"]}, summary="ok")
    bad = add(box, gate="free", action={"argv": ["false"]}, summary="bad")
    result = box.run_report()
    assert result["ran"] == [ok] and result["failed"] == [(bad, 1)]


def test_only_the_designated_runner_executes(tmp_path):
    root = tmp_path / "work" / "inbox"
    laptop = inbox.Inbox(root, actor="laptop", clock=lambda: NOW, runner="homebox")
    arm = inbox.Inbox(root, actor="homebox", clock=lambda: NOW, runner="homebox")
    marker = tmp_path / "once"
    laptop.add(source="x", kind="finding", summary="s", gate="free", action={"argv": ["touch", str(marker)]})
    assert laptop.run() == []
    assert not marker.exists()
    assert len(arm.run()) == 1 and marker.exists()


def test_list_shows_the_command_a_yes_would_run(tmp_path):
    r = run_cli(tmp_path, "add", "--from", "cli", "--kind", "decision", "--summary", "merge it",
                "--action-json", '{"argv": ["gh", "pr", "merge", "70"]}')
    assert r.returncode == 0, r.stderr
    out = run_cli(tmp_path, "list").stdout
    assert "gh pr merge 70" in out


def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, env=env,
                          capture_output=True, text=True)


def test_sync_commits_only_the_inbox_and_works_without_a_rendered_view(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    (repo / "README.md").write_text("x\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "init"); git(repo, "push", "-q", "origin", "HEAD:main")
    (repo / "other.txt").write_text("not inbox\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    add_cli = subprocess.run([sys.executable, str(SCRIPT), "--root", str(repo), "--by", "t", "add", "--from", "x",
                              "--kind", "finding", "--summary", "disk full"], capture_output=True, text=True, env=env)
    assert add_cli.returncode == 0, add_cli.stderr
    done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(repo), "--by", "t", "sync"],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    shipped = git(origin, "ls-tree", "-r", "--name-only", "main").stdout.split()
    assert any(p.startswith("work/inbox/") for p in shipped)
    assert "other.txt" not in shipped


def test_sync_refuses_to_push_commits_outside_the_inbox(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    (repo / "README.md").write_text("x\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "init"); git(repo, "push", "-q", "origin", "HEAD:main")
    (repo / "other.txt").write_text("local work\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "local work")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(repo), "--by", "t", "sync"],
                          capture_output=True, text=True, env=env)
    assert done.returncode != 0 and "outside" in done.stderr
    assert "other.txt" not in git(origin, "ls-tree", "-r", "--name-only", "main").stdout


def test_sync_does_not_leave_the_index_unmerged_when_the_generated_view_diverged(tmp_path):
    """2026-10-07: the runner's local work/inbox.md (a view) met a changed upstream copy,
    the autostash pop conflicted and left unmerged index entries. Every later stash and
    rebase on that checkout then failed for hours until somebody ran `git reset`."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    (repo / "work").mkdir()
    (repo / "work" / "inbox.md").write_text("view v1\n")
    git(repo, "add", "-A"); git(repo, "commit", "-q", "-m", "init"); git(repo, "push", "-q", "origin", "HEAD:main")
    git(tmp_path, "clone", "-q", str(origin), str(other))
    (other / "work" / "inbox.md").write_text("view v2 from upstream\n")
    git(other, "commit", "-q", "-am", "view moved"); git(other, "push", "-q", "origin", "HEAD:main")
    (repo / "work" / "inbox.md").write_text("view v1 rendered locally\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run([sys.executable, str(SCRIPT), "--root", str(repo), "--by", "t", "add", "--from", "x",
                    "--kind", "finding", "--summary", "disk full"], capture_output=True, text=True, env=env)
    done = subprocess.run([sys.executable, str(SCRIPT), "--root", str(repo), "--by", "t", "sync"],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    assert git(repo, "ls-files", "-u").stdout.strip() == "", "index must not stay unmerged"
    assert git(repo, "stash", "list").stdout.strip() == "", "no autostash may be left behind"


def test_a_dry_run_elsewhere_lists_what_waits_for_the_runner(tmp_path):
    """The briefing on a machine that is not the runner shows "ready, waiting for <runner>"."""
    laptop = inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=lambda: NOW, runner="homebox")
    item_id = laptop.add(source="x", kind="finding", summary="s", gate="free", action={"argv": ["true"]})
    report = laptop.run_report(dry_run=True)
    assert report["ran"] == [item_id]
    assert "homebox" in report["skipped"]
    assert laptop.run_report()["ran"] == []


# ---------------------------------------------------------------- urgency verb

def test_urgency_event_changes_the_effective_urgency_and_the_order(box):
    a = add(box, summary="first", urgency="today")
    b = add(box, summary="second", urgency="later")
    box.event(b, "urgency", value="now")
    assert box.get(b).urgency == "now"
    assert [i.id for i in box.open_items()][0] == b
    assert box.get(a).urgency == "today"
    assert box.get(b).as_dict()["urgency"] == "now"


def test_cli_urgency_sets_value_accepts_prefix_and_renders(tmp_path):
    r = run_cli(tmp_path, "add", "--from", "cli", "--kind", "finding", "--summary", "disk 91 %")
    item_id = r.stdout.strip()
    r = run_cli(tmp_path, "urgency", item_id[:15], "now")
    assert r.returncode == 0, r.stderr
    assert json.loads(run_cli(tmp_path, "list", "--json").stdout)[0]["urgency"] == "now"
    assert "| now |" in (tmp_path / "repo" / "work" / "inbox.md").read_text(encoding="utf-8")
    assert (tmp_path / "repo" / "work" / "inbox" / item_id / "item.yaml").read_text().count("urgency: today") == 1


def test_cli_urgency_refuses_bad_value_closed_item_and_unknown_id(tmp_path):
    item_id = run_cli(tmp_path, "add", "--from", "cli", "--kind", "finding", "--summary", "x").stdout.strip()
    assert run_cli(tmp_path, "urgency", item_id, "soon").returncode == 2   # argparse choices
    run_cli(tmp_path, "close", item_id)
    r = run_cli(tmp_path, "urgency", item_id, "now")
    assert r.returncode == 1 and "closed" in r.stderr
    r = run_cli(tmp_path, "urgency", "nope", "now")
    assert r.returncode == 1 and "inbox:" in r.stderr


# ---------------------------------------------------------------- unseen_for
# A reporter that files the same key every run (a daily health report) says "still
# there" by firing again. When it stops firing, the condition is gone: nobody has to
# tell the inbox, and nobody has to clear a log so a check can turn green.

def _box_at(tmp_path, clock):
    return inbox.Inbox(tmp_path / "work" / "inbox", actor="homebox", clock=lambda: clock[0])


def test_unseen_for_closes_an_item_its_reporter_stopped_refiling(tmp_path):
    clock = [NOW]
    box = _box_at(tmp_path, clock)
    item_id = add(box, kind="finding", key="crash:x", closes_when={"unseen_for": {"hours": 36}})
    clock[0] = NOW + dt.timedelta(hours=35)
    assert box.check() == []
    clock[0] = NOW + dt.timedelta(hours=36)
    assert box.check() == [item_id]
    assert box.get(item_id).state == "done"


def test_a_refiled_key_restarts_the_unseen_clock(tmp_path):
    clock = [NOW]
    box = _box_at(tmp_path, clock)
    item_id = add(box, kind="finding", key="crash:x", closes_when={"unseen_for": {"hours": 36}})
    clock[0] = NOW + dt.timedelta(hours=30)
    add(box, kind="finding", key="crash:x")           # next day's report still lists it
    clock[0] = NOW + dt.timedelta(hours=60)           # 30 h after the last sighting
    assert box.check() == []
    clock[0] = NOW + dt.timedelta(hours=66)
    assert box.check() == [item_id]


def test_unseen_for_without_an_item_or_a_valid_span_is_unknown(box):
    assert inbox.probe({"unseen_for": {"hours": 36}}, now=NOW) is None      # no item to look at
    item_id = add(box, closes_when={"unseen_for": {"hours": "soon"}})
    assert box.check() == []
    assert box.get(item_id).state == "open"
    item_id = add(box, summary="zero", closes_when={"unseen_for": {"hours": 0}})
    assert box.check() == []                                               # 0 h would close at once


def test_a_malformed_unseen_for_is_unknown_and_the_rest_of_the_inbox_is_still_checked(box):
    # {unseen_for: 36} is an easy slip for {unseen_for: {hours: 36}}. It must not
    # raise out of probe() and abort check() for every other item.
    item = inbox.Item(id="x", data={"created": "2026-10-04T18:00"}, events=[], today=NOW.date())
    for bad in (36, [1], "36h"):
        assert inbox.probe({"unseen_for": bad}, now=NOW, item=item) is None
    broken = add(box, summary="broken", closes_when={"unseen_for": 36})
    gone = add(box, summary="gone", closes_when={"path_exists": "."})
    assert box.check() == [gone]
    assert box.get(broken).state == "open"


def _item_created(created):
    data = {} if created is None else {"created": created}
    return inbox.Item(id="x", data=data, events=[], today=NOW.date())


def test_unseen_for_reads_an_unquoted_yaml_timestamp_as_the_creation_time():
    # yaml.safe_load turns an unquoted `created: 2026-10-04T18:00:00+02:00` into a datetime.
    created = yaml.safe_load("created: 2026-10-04T17:00:00+00:00")["created"]
    assert isinstance(created, dt.datetime)
    spec = {"unseen_for": {"hours": 36}}
    now = dt.datetime(2026, 10, 4, 18, 0, tzinfo=dt.timezone.utc)
    assert inbox.probe(spec, now=now, item=_item_created(created)) is False
    assert inbox.probe(spec, now=now + dt.timedelta(hours=36), item=_item_created(created)) is True


def test_unseen_for_without_any_sighting_time_is_unknown():
    spec = {"unseen_for": {"hours": 36}}
    assert inbox.probe(spec, now=NOW, item=_item_created(None)) is None
    assert inbox.probe(spec, now=NOW, item=_item_created("not a time")) is None


def test_the_item_schema_declares_unseen_for_with_a_positive_span():
    path = ROOT / "work" / "templates" / "_schema.inbox-item.yaml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec = schema["$defs"]["probe"]["properties"]["unseen_for"]
    assert spec["required"] == ["hours"]
    assert spec["properties"]["hours"]["exclusiveMinimum"] == 0


# ---------------------------------------------------------------- closing by key, closer
# 2026-10-07: an alarm became an item, the alarm ended, the item stayed open for hours.
# The reporter that knows "it is over" knows the key, not the item id.

def test_close_by_key_closes_every_live_item_with_that_key(box):
    a = box.add(source="m/notify", kind="finding", summary="puller failed", key="notify:abc")
    b = box.add(source="m/x", kind="finding", summary="other", key="other")
    closed = box.close_by_key("notify:abc", note="recovered")
    assert closed == [a]
    assert box.get(a).state == "done"
    assert box.get(b).state == "open"


def test_close_by_key_leaves_a_dropped_item_dropped(box):
    a = box.add(source="m/notify", kind="finding", summary="noise", key="k")
    box.event(a, "drop", text="not interesting")
    assert box.close_by_key("k") == []
    assert box.get(a).state == "dropped"


def test_close_by_key_without_a_match_is_an_empty_answer(box):
    assert box.close_by_key("nothing") == []


def test_cli_close_with_key(tmp_path):
    r = run_cli(tmp_path, "add", "--from", "m", "--kind", "finding", "--summary", "s", "--key", "k1")
    assert r.returncode == 0, r.stderr
    done = run_cli(tmp_path, "close", "--key", "k1", "--note", "recovered")
    assert done.returncode == 0, done.stderr
    assert "closed" in done.stdout
    assert "Nothing waits." in run_cli(tmp_path, "list", "--short").stdout


def test_closer_is_stored_and_validated(box):
    a = box.add(source="m", kind="finding", summary="s", closer="person")
    assert box.get(a).closer == "person"
    with pytest.raises(ValueError):
        box.add(source="m", kind="finding", summary="s2", closer="somebody")


def test_a_finding_without_a_way_to_close_warns(box, capsys):
    box.add(source="m", kind="finding", summary="nobody will ever close me")
    assert "no way to close" in capsys.readouterr().err


def test_a_finding_with_a_probe_or_a_closer_does_not_warn(box, capsys):
    box.add(source="m", kind="finding", summary="a", closes_when={"after": "2026-10-09"})
    box.add(source="m", kind="finding", summary="b", closer="reporter")
    assert "no way to close" not in capsys.readouterr().err


# ---------------------------------------------------------------- reopen: a close by mistake

def test_reopen_brings_a_closed_or_dropped_item_back_as_a_new_event(box):
    for verb in ("close", "drop", "reject"):
        item_id = add(box, key=f"k-{verb}")
        box.event(item_id, verb, text="by mistake")
        assert box.get(item_id).state in ("done", "dropped")
        before = sorted(p.name for p in (box.root / item_id / "events").iterdir())
        box.reopen(item_id, note="still needed")
        after = sorted(p.name for p in (box.root / item_id / "events").iterdir())
        assert after[:len(before)] == before and len(after) == len(before) + 1   # nothing rewritten
        assert after[-1].endswith("-reopen.yaml")
        assert box.get(item_id).state == "open"
        assert item_id in [i.id for i in box.open_items()]


def test_runs_on_is_a_defer_that_names_what_it_waits_on(box):
    # runs on: quiet until the day to look again, with who or what it waits on
    item_id = add(box, key="k-runs")
    box.event(item_id, "defer", until="2099-01-01", waits_on="an answer from the vendor")
    item = box.get(item_id)
    # stored as waits_on, never a bare `on` key (a boolean to YAML 1.1 readers)
    stored = "\n".join(f.read_text(encoding="utf-8") for f in (box.root / item_id / "events").glob("*defer*"))
    assert "waits_on: an answer from the vendor" in stored and "'on'" not in stored
    assert item.state == "deferred" and item.deferral == {"until": "2099-01-01", "on": "an answer from the vendor"}
    assert item.as_dict()["waiting_on"] == "an answer from the vendor" and item.as_dict()["deferred_until"] == "2099-01-01"
    box.event(item_id, "defer", until="2099-02-01")            # a plain later: nothing it waits on
    assert box.get(item_id).deferral == {"until": "2099-02-01", "on": None}
    box.reopen(item_id)
    assert box.get(item_id).deferral is None and "waiting_on" not in box.get(item_id).as_dict()
    box.event(item_id, "defer", until="2099-03-01", on="an older event")   # the first events wrote `on`: still read
    assert box.get(item_id).deferral == {"until": "2099-03-01", "on": "an older event"}


def test_reopen_takes_back_a_defer(box):
    # "later" by mistake: the cockpit's undo reopens the deferred item at once
    item_id = add(box, key="k-later")
    box.event(item_id, "defer", until="2099-01-01")
    assert box.get(item_id).state == "deferred"
    box.reopen(item_id)
    assert box.get(item_id).state == "open"


def test_a_reopened_executed_item_is_never_run_again_without_a_new_yes(box):
    item_id = add(box, gate="your-yes", action={"argv": ["true"]})
    box.approve(item_id)
    box.event(item_id, "executed")
    box.reopen(item_id)
    item = box.get(item_id)
    assert item.state == "open" and item.approval is None
    assert item_id not in [i.id for i in box.runnable()]


def test_reopen_takes_back_a_yes_that_has_not_run(box):
    # a yes in the cockpit by mistake: undo before the runner's next pass, the item is open and never runs
    item_id = add(box, gate="your-yes", action={"argv": ["true"]})
    box.approve(item_id)
    assert box.get(item_id).state == "approved"
    box.reopen(item_id)
    assert box.get(item_id).state == "open" and item_id not in [i.id for i in box.runnable()]


def test_reopen_refuses_an_open_item_and_a_close_after_it_closes_again(box):
    item_id = add(box)
    with pytest.raises(ValueError):
        box.reopen(item_id)
    box.close(item_id)
    box.reopen(item_id)
    box.close(item_id, note="now really done")
    assert box.get(item_id).state == "done"


def test_cli_reopen_renders_the_inbox_view(tmp_path):
    def run(*args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--by", "web", *args],
                              capture_output=True, text=True)
    item_id = run("add", "--from", "x/y", "--kind", "decision", "--summary", "Tidy labels").stdout.strip()
    assert run("close", item_id).returncode == 0
    r = run("reopen", item_id, "--note", "closed by mistake")
    assert r.returncode == 0, r.stderr
    assert "Tidy labels" in (tmp_path / "work" / "inbox.md").read_text(encoding="utf-8")
    assert run("reopen", item_id).returncode == 1


# ---------------------------------------------------------------- quiet after a deliberate close
#
# An alarm was investigated and closed by a reader in the morning; a reminder hours later
# carried the IDENTICAL text and opened a new item plus a new phone message. A close by
# somebody who looked at it answers that exact text.

DETAIL = "WHERE: host\nWHAT TO DO: read the log\n[failure] job: ended with 143 at 2026-10-13T02:59:51+00:00"


def _closed(box, by="watcher", text="noted after investigation", detail=DETAIL):
    item_id = add(box, kind="finding", key="notify:k1", detail=detail, closer="bot")
    box.event(item_id, "close", by=by, text=text)
    return item_id


def test_recently_closed_finds_an_identical_finding_closed_by_a_reader(box):
    item_id = _closed(box)
    hit = box.recently_closed("notify:k1", DETAIL, hours=24)
    assert hit is not None and hit[0].id == item_id and hit[1].by == "watcher"


def test_recently_closed_ignores_a_close_older_than_the_window(tmp_path):
    clock = {"now": NOW}
    box = inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=lambda: clock["now"])
    _closed(box)
    clock["now"] = NOW + dt.timedelta(hours=25)
    assert box.recently_closed("notify:k1", DETAIL, hours=24) is None


def test_recently_closed_ignores_a_changed_finding(box):
    _closed(box)
    assert box.recently_closed("notify:k1", DETAIL.replace("143", "1"), hours=24) is None


def test_recently_closed_treats_a_moved_timestamp_as_the_same_finding(box):
    _closed(box)
    moved = DETAIL.replace("2026-10-13T02:59:51+00:00", "2026-10-14T03:00:02+00:00")
    assert box.recently_closed("notify:k1", moved, hours=24) is not None


def test_recently_closed_ignores_a_probe_close_the_trouble_came_back(box):
    _closed(box, by="check", text="closes_when holds")
    assert box.recently_closed("notify:k1", DETAIL, hours=24) is None


def test_recently_closed_ignores_an_all_clear_the_trouble_came_back(box):
    _closed(box, by="always-on", text="All clear from the run manager: healthy again")
    assert box.recently_closed("notify:k1", DETAIL, hours=24) is None


def test_recently_closed_knows_only_the_english_all_clear_by_default(box):
    _closed(box, by="always-on", text="Fin d'alerte: ok")
    assert box.recently_closed("notify:k1", DETAIL, hours=24) is not None


def test_recently_closed_takes_the_all_clear_words_of_the_fork(tmp_path):
    box = inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=lambda: NOW,
                      all_clear=("Fin d'alerte",))
    _closed(box, by="always-on", text="Fin d'alerte: ok")
    assert box.recently_closed("notify:k1", DETAIL, hours=24) is None


def test_cli_reads_the_all_clear_words_from_the_config(tmp_path, capsys):
    (tmp_path / "bridge-config.yaml").write_text("inbox:\n  all_clear: [\"Fin d'alerte\"]\n", encoding="utf-8")
    box = inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop")
    _closed(box, by="always-on", text="Fin d'alerte: ok")
    rc = inbox.main(["--root", str(tmp_path), "--by", "always-on", "add", "--from", "m/bridge-notify",
                     "--kind", "finding", "--summary", "orbit (m)", "--key", "notify:k1",
                     "--detail", DETAIL, "--closer", "bot", "--quiet-after-close-h", "24"])
    assert rc == 0
    assert not capsys.readouterr().out.strip().splitlines()[-1].startswith("quiet ")


def test_cli_add_quiet_after_close_records_seen_and_files_nothing(tmp_path, capsys):
    root = tmp_path
    box = inbox.Inbox(root / "work" / "inbox", actor="laptop")
    item_id = _closed(box)
    rc = inbox.main(["--root", str(root), "--by", "always-on", "add", "--from", "m/bridge-notify",
                     "--kind", "finding", "--summary", "orbit (m)", "--key", "notify:k1",
                     "--detail", DETAIL, "--closer", "bot", "--quiet-after-close-h", "24"])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    assert rc == 0
    assert out.startswith(f"quiet {item_id} watcher ")
    assert [p.name for p in (root / "work" / "inbox").iterdir() if p.is_dir()] == [item_id]
    assert box.get(item_id).events[-1].verb == "seen"
    assert box.get(item_id).state == "done"


def test_cli_add_without_the_flag_still_opens_a_new_item(tmp_path, capsys):
    box = inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop")
    item_id = _closed(box)
    inbox.main(["--root", str(tmp_path), "add", "--from", "m/bridge-notify", "--kind", "finding",
                "--summary", "orbit (m)", "--key", "notify:k1", "--detail", DETAIL, "--closer", "bot"])
    assert capsys.readouterr().out.strip().splitlines()[-1] != item_id


# ---------------------------------------------------------------- arts: what a person sees an item as

def test_every_kind_has_an_art_and_the_arts_are_three():
    assert {k: inbox.art_of_kind(k) for k in inbox.KINDS} == {
        "decision": "ask", "question": "ask", "draft": "ask",
        "finding": "report", "result": "report", "idea": "idea"}
    assert inbox.ARTS == ("ask", "report", "idea")


def test_an_unknown_kind_is_an_ask_so_a_person_sees_it():
    assert inbox.art_of_kind("verdict") == "ask"
    assert inbox.art_of_kind(None) == "ask"


def test_art_of_reads_the_item_and_stores_nothing(box):
    item_id = add(box, kind="idea", summary="maybe one day")
    assert inbox.art_of(box.get(item_id)) == "idea"
    assert inbox.art_of(box.get(item_id).as_dict()) == "idea"
    stored = yaml.safe_load((box.root / item_id / "item.yaml").read_text(encoding="utf-8"))
    assert "art" not in stored


def test_list_json_carries_the_art_and_list_art_filters(tmp_path):
    for kind, summary in (("decision", "merge it"), ("finding", "disk 91 %"), ("idea", "a dark mode")):
        r = run_cli(tmp_path, "add", "--from", "cli", "--kind", kind, "--summary", summary, "--closer", "person")
        assert r.returncode == 0, r.stderr
    rows = json.loads(run_cli(tmp_path, "list", "--json").stdout)
    assert {r["summary"]: r["art"] for r in rows} == {"merge it": "ask", "disk 91 %": "report", "a dark mode": "idea"}
    asks = json.loads(run_cli(tmp_path, "list", "--json", "--art", "ask").stdout)
    assert [r["summary"] for r in asks] == ["merge it"]
    short = run_cli(tmp_path, "list", "--short", "--art", "idea").stdout
    assert "a dark mode" in short and "merge it" not in short
    assert run_cli(tmp_path, "list", "--art", "task").returncode != 0      # only the three arts

