# SPDX-License-Identifier: MIT
"""Contract for scripts/upstream-autoupdate.sh + scripts/upstream-resolve.py.

The defect these pin: the daily auto-update stopped at the first predicted
conflict, and since nothing ever resolved one, it stopped every morning after.
An instance sat 84 commits behind with 10 conflicting files, 3 of which were
fixes it had promoted itself and upstream had merely followed up on. A dirty
work/log.md, dirty for most of every working day, stopped it as well.

What a machine may decide, and what it must not:
  · promoted, then built on upstream  → take upstream, merge
  · promoted, then REVERTED upstream  → hold (the change may be live locally)
  · promoted, then built on LOCALLY   → keep local, merge
  · promoted, then REVERTED locally   → hold (upstream still carries it)
  · upstream only ADDED lines, and the local file already holds every added
    block as it stands                → keep local, merge
  · never promoted                    → hold
  · one held file holds the whole run, and the branch is left exactly as it was
  · a dirty file the merge does not touch is no reason to stop; one it touches is
  · a held file names only local commits upstream lacks (git cherry), and a
    path declared in promote.local_adaptations is labelled as such, still held
  · a skip that has kept upstream out for AUTOUPDATE_STALE_DAYS files one item

Every case runs the real script against throwaway repositories.

Run: python3 -m pytest scripts/tests/test_upstream_autoupdate.py -q
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ("upstream-autoupdate.sh", "upstream-resolve.py")
ENV = {**os.environ, "LC_ALL": "C", "MIRROR_CORE": "0",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
for k in ("SIGNAL_ACCOUNT", "SIGNAL_RECIPIENT", "AUTOUPDATE_NOTIFY_CMD",
          "MIRROR_REMOTE", "GIT_DIR", "GIT_WORK_TREE"):
    ENV.pop(k, None)


def run(cwd, *args, check=True):
    p = subprocess.run(args, cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and p.returncode:
        raise AssertionError(f"{args} → {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


class World:
    """`up` is the upstream (CORE) repo, `inst` the instance on user/me."""

    def __init__(self, tmp: pathlib.Path):
        self.up, self.inst = tmp / "up", tmp / "inst"
        self.up.mkdir()
        run(self.up, "git", "init", "-q", "-b", "main")
        self.write(self.up, "core.txt", "a\nb\nc\n")
        self.write(self.up, "other.txt", "x\n")
        self.commit(self.up, "init")
        run(tmp, "git", "clone", "-q", "-o", "upstream", str(self.up), str(self.inst))
        run(self.inst, "git", "config", "core.hooksPath", "/dev/null")
        run(self.inst, "git", "checkout", "-q", "-b", "user/me")
        (self.inst / "scripts").mkdir()
        for s in SCRIPTS:
            shutil.copy(REPO / "scripts" / s, self.inst / "scripts" / s)
        self.write(self.inst, "work/log.md", "# log\n")
        self.commit(self.inst, "instance scaffolding")

    @staticmethod
    def write(repo, path, text):
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    @staticmethod
    def commit(repo, msg):
        run(repo, "git", "add", "-A")
        run(repo, "git", "commit", "-q", "-m", msg)
        return run(repo, "git", "rev-parse", "HEAD").stdout.strip()

    def promote(self, path, text, msg):
        """Same content lands upstream under a different commit, as a promote PR does."""
        self.write(self.inst, path, text)
        self.commit(self.inst, msg)
        self.write(self.up, path, text)
        return self.commit(self.up, msg + " (#1)")

    def autoupdate(self):
        p = run(self.inst, "bash", "scripts/upstream-autoupdate.sh", check=False)
        status = (self.inst / "work" / "upstream-status.md").read_text()
        return p, status

    def head(self):
        return run(self.inst, "git", "rev-parse", "HEAD").stdout.strip()

    def show(self, rev, path):
        return run(self.inst, "git", "show", f"{rev}:{path}").stdout

    def plan(self):
        run(self.inst, "git", "fetch", "-q", "upstream")
        p = run(self.inst, "python3", "scripts/upstream-resolve.py", "--theirs", "upstream/main")
        return json.loads(p.stdout)


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def test_clean_merge_still_merges(w):
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = w.autoupdate()
    assert "merged 1 commit" in p.stdout, p.stdout + p.stderr
    assert w.show("HEAD", "other.txt") == "x\ny\n"


def test_promoted_then_followed_up_takes_upstream(w):
    w.promote("core.txt", "a\nB\nc\n", "fix b")
    w.write(w.up, "core.txt", "a\nB2\nc\n"); w.commit(w.up, "follow-up on b")
    assert [t["path"] for t in w.plan()["take_theirs"]] == ["core.txt"]
    p, status = w.autoupdate()
    assert "auto-updated" in status, status
    assert "auto-resolved to upstream: core.txt" in status
    assert w.show("HEAD", "core.txt") == "a\nB2\nc\n"
    assert run(w.inst, "git", "rev-list", "--count", "HEAD..upstream/main").stdout.strip() == "0"


def test_promoted_then_reverted_is_held(w):
    w.promote("core.txt", "a\nB\nc\n", "feature b")
    run(w.up, "git", "revert", "--no-edit", "HEAD")
    # A later upstream edit on the same line is what makes the revert collide;
    # without one, git keeps the local change on its own and merges cleanly.
    w.write(w.up, "core.txt", "a\nb2\nc\n"); w.commit(w.up, "later edit on that line")
    before = w.head()
    plan = w.plan()
    assert plan["take_theirs"] == []
    assert "reverted" in plan["unresolved"][0]["reason"]
    p, status = w.autoupdate()
    assert "SKIPPED" in status and "core.txt" in status and "reverted" in status, status
    assert w.head() == before
    assert w.show("HEAD", "core.txt") == "a\nB\nc\n"


def test_unpromoted_local_edit_is_held(w):
    w.write(w.inst, "core.txt", "a\nLOCAL\nc\n"); w.commit(w.inst, "local only")
    w.write(w.up, "core.txt", "a\nUP\nc\n"); w.commit(w.up, "upstream edit")
    before = w.head()
    p, status = w.autoupdate()
    assert "never reached upstream" in status, status
    assert w.head() == before


def test_one_held_file_holds_the_whole_run(w):
    w.promote("core.txt", "a\nB\nc\n", "fix b")
    w.write(w.up, "core.txt", "a\nB2\nc\n"); w.commit(w.up, "follow-up")
    w.write(w.inst, "other.txt", "LOCAL\n"); w.commit(w.inst, "local only")
    w.write(w.up, "other.txt", "UP\n"); w.commit(w.up, "upstream edit")
    before = w.head()
    plan = w.plan()
    assert [t["path"] for t in plan["take_theirs"]] == ["core.txt"]
    assert [u["path"] for u in plan["unresolved"]] == ["other.txt"]
    p, status = w.autoupdate()
    assert "SKIPPED" in status and "other.txt" in status, status
    assert w.head() == before
    assert not (w.inst / ".git" / "MERGE_HEAD").exists()


def test_dirty_log_does_not_block(w):
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    w.write(w.inst, "work/log.md", "# log\n| row in progress |\n")
    p, status = w.autoupdate()
    assert "auto-updated" in status, status
    assert (w.inst / "work/log.md").read_text().endswith("| row in progress |\n")


def test_dirty_file_the_merge_touches_blocks(w):
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    w.write(w.inst, "other.txt", "half-edited\n")
    before = w.head()
    p, status = w.autoupdate()
    assert "uncommitted changes in files the merge touches: other.txt" in status, status
    assert w.head() == before
    assert (w.inst / "other.txt").read_text() == "half-edited\n"


def test_promoted_then_deleted_upstream_takes_the_delete(w):
    w.promote("core.txt", "a\nB\nc\n", "fix b")
    run(w.up, "git", "rm", "-q", "core.txt"); w.commit(w.up, "retire core.txt")
    plan = w.plan()
    assert [t["path"] for t in plan["take_theirs"]] == ["core.txt"]
    assert plan["take_theirs"][0]["theirs_deleted"] is True
    p, status = w.autoupdate()
    assert "auto-updated" in status, status
    assert not (w.inst / "core.txt").exists()


# ------------------------------------------- the mirror case: local is newer
def test_promoted_then_built_on_locally_keeps_local(w):
    # The promote lands upstream byte for byte, and work goes on locally. Upstream's
    # file is one this instance already had: nothing upstream knows is lost.
    w.promote("core.txt", "a\nB\nc\n", "fix b")
    w.write(w.inst, "core.txt", "a\nB2\nc\n"); w.commit(w.inst, "local follow-up on b")
    plan = w.plan()
    assert plan["unresolved"] == [], plan
    assert [(t["path"], t["rule"]) for t in plan["take_ours"]] == [("core.txt", "seen_locally")]
    p, status = w.autoupdate()
    assert "auto-updated" in status, status
    assert "kept local: core.txt" in status
    assert w.show("HEAD", "core.txt") == "a\nB2\nc\n"
    assert run(w.inst, "git", "rev-list", "--count", "HEAD..upstream/main").stdout.strip() == "0"


def test_promoted_then_reverted_locally_is_held(w):
    w.promote("core.txt", "a\nB\nc\n", "feature b")
    run(w.inst, "git", "revert", "--no-edit", "HEAD")
    w.write(w.inst, "core.txt", "a\nb2\nc\n"); w.commit(w.inst, "later local edit on that line")
    before = w.head()
    plan = w.plan()
    assert plan["take_ours"] == [] and plan["take_theirs"] == []
    assert "reverted" in plan["unresolved"][0]["reason"]
    p, status = w.autoupdate()
    assert "SKIPPED" in status and "core.txt" in status, status
    assert w.head() == before


def test_upstream_additions_already_held_locally_keep_local(w):
    # The .gitignore case: upstream appends a block, the instance pulled the same
    # block earlier and has more lines of its own around it.
    w.write(w.inst, "core.txt", "a\nb\nc\nlocal-1\nX\nY\nlocal-2\n"); w.commit(w.inst, "local lines + pulled block")
    w.write(w.up, "core.txt", "a\nb\nc\nX\nY\n"); w.commit(w.up, "add X Y")
    plan = w.plan()
    assert [(t["path"], t["rule"]) for t in plan["take_ours"]] == [("core.txt", "contained")], plan
    p, status = w.autoupdate()
    assert "auto-updated" in status, status
    assert w.show("HEAD", "core.txt") == "a\nb\nc\nlocal-1\nX\nY\nlocal-2\n"


def test_upstream_addition_split_locally_is_held(w):
    w.write(w.inst, "core.txt", "a\nb\nc\nX\nlocal\nY\n"); w.commit(w.inst, "local")
    w.write(w.up, "core.txt", "a\nb\nc\nX\nY\n"); w.commit(w.up, "add X Y")
    plan = w.plan()
    assert plan["take_ours"] == [], plan
    assert [u["path"] for u in plan["unresolved"]] == ["core.txt"]


def test_upstream_that_also_changed_a_line_is_held(w):
    # Upstream did more than add: the contained rule must not hide its edit of a.
    w.write(w.inst, "core.txt", "a\nb\nc\nlocal\nX\nY\n"); w.commit(w.inst, "local")
    w.write(w.up, "core.txt", "A\nb\nc\nX\nY\n"); w.commit(w.up, "add X Y, edit a")
    plan = w.plan()
    assert plan["take_ours"] == [], plan
    assert [u["path"] for u in plan["unresolved"]] == ["core.txt"]


def test_mixed_plan_resolves_both_sides_in_one_merge(w):
    w.promote("core.txt", "a\nB\nc\n", "fix b")
    w.write(w.up, "core.txt", "a\nB-up\nc\n"); w.commit(w.up, "upstream follow-up")
    w.promote("other.txt", "x\nZ\n", "add z")
    w.write(w.inst, "other.txt", "x\nZ-local\n"); w.commit(w.inst, "local follow-up")
    plan = w.plan()
    assert [t["path"] for t in plan["take_theirs"]] == ["core.txt"]
    assert [t["path"] for t in plan["take_ours"]] == ["other.txt"]
    p, status = w.autoupdate()
    assert "auto-updated" in status, status
    assert w.show("HEAD", "core.txt") == "a\nB-up\nc\n"
    assert w.show("HEAD", "other.txt") == "x\nZ-local\n"
    msg = run(w.inst, "git", "log", "-1", "--format=%B").stdout
    assert "core.txt" in msg and "other.txt" in msg, msg


# ---------------------------------------------------------------- notifier
def _autoupdate_env(w, **extra):
    env = {**ENV, **extra}
    p = subprocess.run(["bash", "scripts/upstream-autoupdate.sh"], cwd=w.inst,
                       env=env, capture_output=True, text=True)
    return p, (w.inst / "work" / "upstream-status.md").read_text()


def test_generic_notifier_gets_the_message_on_stdin(w, tmp_path):
    out = tmp_path / "notified.txt"
    hook = tmp_path / "notify.sh"
    hook.write_text(f'#!/bin/sh\ncat > "{out}"\n')
    hook.chmod(0o755)
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, AUTOUPDATE_NOTIFY_CMD=str(hook))
    assert "auto-updated" in status, status
    assert "auto-updated" in out.read_text()


def test_a_failing_notifier_does_not_fail_the_run(w):
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, AUTOUPDATE_NOTIFY_CMD="false")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "auto-updated" in status, status


def test_notifier_argv_is_not_glob_expanded(w, tmp_path):
    out = tmp_path / "argv.txt"
    hook = tmp_path / "notify.sh"
    hook.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{out}"\ncat >/dev/null\n')
    hook.chmod(0o755)
    (tmp_path / "a.txt").write_text("x")
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, AUTOUPDATE_NOTIFY_CMD=f"{hook} {tmp_path}/*.txt")
    assert out.read_text().strip() == f"{tmp_path}/*.txt"


# ------------------------------------------------- mirror never hits user/*
def _mirror(w, tmp_path, *, with_main: bool):
    """A private mirror whose DEFAULT branch is the user branch.

    Both branches sit on an ancestor of upstream/main, so a push to either would
    be a clean fast-forward. That is the dangerous case: nothing but the name
    check stops CORE history from landing on the user's branch.
    """
    m = tmp_path / "mirror.git"
    run(tmp_path, "git", "init", "-q", "--bare", str(m))
    run(w.inst, "git", "remote", "add", "origin", str(m))
    run(w.inst, "git", "fetch", "-q", "upstream")
    run(w.inst, "git", "push", "-q", "origin", "upstream/main:refs/heads/user/me")
    if with_main:
        run(w.inst, "git", "push", "-q", "origin", "upstream/main:refs/heads/main")
    run(m, "git", "symbolic-ref", "HEAD", "refs/heads/user/me")
    run(w.inst, "git", "remote", "set-head", "origin", "-a")
    return m


def test_mirror_falls_back_to_core_branch_when_default_is_a_user_branch(w, tmp_path):
    m = _mirror(w, tmp_path, with_main=True)
    user_before = run(m, "git", "rev-parse", "refs/heads/user/me").stdout.strip()
    w.write(w.up, "other.txt", "x\ny\n"); up = w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, MIRROR_CORE="1")
    assert "auto-updated" in status, status
    assert run(m, "git", "rev-parse", "refs/heads/user/me").stdout.strip() == user_before
    assert run(m, "git", "rev-parse", "refs/heads/main").stdout.strip() == up
    assert "mirror: `origin/main` fast-forwarded" in status, status


def test_mirror_is_skipped_when_only_the_user_branch_exists(w, tmp_path):
    m = _mirror(w, tmp_path, with_main=False)
    user_before = run(m, "git", "rev-parse", "refs/heads/user/me").stdout.strip()
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, MIRROR_CORE="1")
    assert "auto-updated" in status, status
    assert run(m, "git", "rev-parse", "refs/heads/user/me").stdout.strip() == user_before
    assert "mirror: skipped" in status, status


# ------------------------------------------- the check net after the merge
# An instance whose CI is off (a billing stop, a fork with Actions disabled, a
# tree that never had a remote runner) meets no validator after this job merges:
# the merge runs with hooks off, and nothing checks the result. These pin the
# local check net: the merged tree runs the same fast checks a commit would, a
# merge that turns one red is rolled back and filed, and a check that was
# already red before the merge does not freeze the job.
FAKE_CHECK = (
    "import pathlib, sys\n"
    "sys.exit(1 if pathlib.Path('broken.txt').exists() else 0)\n"
)
FAKE_INBOX = (
    "import os, sys\n"
    "with open(os.environ['FAKE_INBOX_LOG'], 'a') as f:\n"
    "    f.write(' '.join(sys.argv[1:]) + '\\n')\n"
)


def _with_checks(w, tmp_path):
    """Instance carries one check (red iff broken.txt exists) and a recording inbox."""
    w.write(w.inst, "scripts/check-edges.py", FAKE_CHECK)
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX)
    w.commit(w.inst, "instance carries a check and an inbox")
    return tmp_path / "inbox.log"


def test_green_checks_after_the_merge_are_reported(w, tmp_path):
    log = _with_checks(w, tmp_path)
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "auto-updated" in status, status
    assert "checks: 1 passed" in status, status
    assert w.show("HEAD", "other.txt") == "x\ny\n"


def test_a_merge_that_turns_a_check_red_is_rolled_back_and_filed(w, tmp_path):
    log = _with_checks(w, tmp_path)
    w.write(w.inst, "work/log.md", "# log\nunsaved line\n")      # dirty, untouched by the merge
    before = w.head()
    w.write(w.up, "broken.txt", "x\n"); up = w.commit(w.up, "upstream breaks a check")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode != 0, p.stdout + p.stderr
    assert w.head() == before, "a merge that broke a check must not stay on the branch"
    assert not (w.inst / "broken.txt").exists()
    assert (w.inst / "work/log.md").read_text() == "# log\nunsaved line\n", "a dirty file was lost"
    assert "check-edges.py" in status and "rolled back" in status, status
    filed = log.read_text()
    assert filed.startswith("add ") and "--key upstream-autoupdate-checks" in filed, filed
    # The probe is pinned to the user branch, not to whatever HEAD the inbox
    # check runs in, and follows the moving upstream ref: a repeat add keeps
    # the first item's probe, so a fixed SHA would go stale.
    assert "refs/heads/user/me" in filed and "upstream/main" in filed, filed
    assert '"HEAD"' not in filed, filed
    assert "scripts/check-edges.py" in filed, "the probe must rerun the check it names"


def test_a_red_merge_does_not_reach_the_mirror(w, tmp_path):
    log = _with_checks(w, tmp_path)
    m = _mirror(w, tmp_path, with_main=True)
    main_before = run(m, "git", "rev-parse", "refs/heads/main").stdout.strip()
    w.write(w.up, "broken.txt", "x\n"); w.commit(w.up, "upstream breaks a check")
    p, status = _autoupdate_env(w, MIRROR_CORE="1", FAKE_INBOX_LOG=str(log))
    assert run(m, "git", "rev-parse", "refs/heads/main").stdout.strip() == main_before
    assert "fast-forwarded" not in status, status


def test_a_check_already_red_before_the_merge_does_not_block_it(w, tmp_path):
    log = _with_checks(w, tmp_path)
    w.write(w.inst, "broken.txt", "local\n"); w.commit(w.inst, "local tree already red")
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "auto-updated" in status, status
    assert "already red before the merge: check-edges.py" in status, status
    assert w.show("HEAD", "other.txt") == "x\ny\n"


def test_a_green_run_closes_the_filed_item(w, tmp_path):
    log = _with_checks(w, tmp_path)
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert "close --key upstream-autoupdate-checks" in log.read_text()


def test_checks_can_be_switched_off(w, tmp_path):
    log = _with_checks(w, tmp_path)
    w.write(w.up, "broken.txt", "x\n"); w.commit(w.up, "upstream breaks a check")
    p, status = _autoupdate_env(w, AUTOUPDATE_CHECKS="0", FAKE_INBOX_LOG=str(log))
    assert "auto-updated" in status, status
    assert "checks: skipped (AUTOUPDATE_CHECKS=0)" in status, status


# --------------------------------- the edges of the baseline comparison
LISTING_CHECK = (
    "import pathlib, sys\n"
    "hits = sorted(p.name for p in pathlib.Path('.').glob('broken*.txt'))\n"
    "for h in hits: print('dead edge:', h)\n"
    "print(len(hits), 'finding(s)')\n"
    "sys.exit(1 if hits else 0)\n"
)


def test_a_new_finding_in_a_check_already_red_rolls_back(w, tmp_path):
    # The check is red before the merge for a local reason; the merge adds a
    # second finding to the same check. Comparing exit codes alone would let
    # the merge through with an "already red" note.
    log = tmp_path / "inbox.log"
    w.write(w.inst, "scripts/check-edges.py", LISTING_CHECK)
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX)
    w.write(w.inst, "broken-local.txt", "x\n")
    w.commit(w.inst, "local tree already red")
    before = w.head()
    w.write(w.up, "broken-up.txt", "x\n"); w.commit(w.up, "upstream adds a dead edge")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode != 0, p.stdout + p.stderr
    assert w.head() == before, status
    assert "check-edges.py" in status and "rolled back" in status, status


def test_the_same_findings_in_a_check_already_red_do_not_block(w, tmp_path):
    log = tmp_path / "inbox.log"
    w.write(w.inst, "scripts/check-edges.py", LISTING_CHECK)
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX)
    w.write(w.inst, "broken-local.txt", "x\n")
    w.commit(w.inst, "local tree already red")
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "already red before the merge: check-edges.py" in status, status


def test_a_checker_new_with_the_merge_is_reported_not_rolled_back(w, tmp_path):
    # Upstream ships a checker the instance did not have, and it finds
    # something in instance content. Rolling back would repeat every morning
    # and freeze the job: the rule is new, the content is the instance's.
    log = tmp_path / "inbox.log"
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX); w.commit(w.inst, "inbox")
    w.write(w.up, "scripts/check-reachability.py", "import sys\nsys.exit(1)\n")
    w.commit(w.up, "upstream ships a new checker")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "auto-updated" in status, status
    assert "new or changed with the merge" in status and "check-reachability.py" in status, status
    assert (w.inst / "scripts/check-reachability.py").exists()
    filed = log.read_text()
    assert "--key upstream-autoupdate-rules" in filed, filed
    assert "scripts/check-reachability.py" in filed, "the probe must rerun the check"


def test_a_checker_made_stricter_by_the_merge_is_reported_not_rolled_back(w, tmp_path):
    log = tmp_path / "inbox.log"
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX); w.commit(w.inst, "inbox")
    w.promote("scripts/check-edges.py", FAKE_CHECK, "share the check")
    w.write(w.inst, "local.txt", "instance content\n"); w.commit(w.inst, "instance content")
    w.write(w.up, "scripts/check-edges.py",
            "import pathlib, sys\nsys.exit(1 if pathlib.Path('local.txt').exists() else 0)\n")
    w.commit(w.up, "stricter check")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "auto-updated" in status, status
    assert "new or changed with the merge" in status and "check-edges.py" in status, status


def test_the_budget_check_is_part_of_the_net(w, tmp_path):
    log = tmp_path / "inbox.log"
    w.write(w.inst, "scripts/measure-context.py", FAKE_CHECK)
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX)
    w.commit(w.inst, "instance carries the budget check")
    before = w.head()
    w.write(w.up, "broken.txt", "x\n"); w.commit(w.up, "upstream breaks the budget")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert w.head() == before, status
    assert "measure-context.py" in status, status


# ---- a held conflict names only what is really local ----
# Measured on a live instance: the held line listed commits that had long been
# promoted, so the reader went looking for work that was already upstream.

def test_a_promoted_commit_is_not_listed_as_never_reached(w):
    promoted = w.promote("core.txt", "a\nB\nc\n", "fix b")
    w.write(w.inst, "core.txt", "a\nB\nC\n"); local = w.commit(w.inst, "local only on c")
    w.write(w.up, "core.txt", "a\nB2\nc\n"); w.commit(w.up, "upstream edit on b")
    held = w.plan()["unresolved"]
    assert [u["path"] for u in held] == ["core.txt"], held
    shas = [c.split()[0] for c in held[0]["local_commits"]]
    assert local[:7] in shas, held
    assert not any(promoted[:7] == s or s.startswith(promoted[:7]) for s in shas), held
    inst_promoted = run(w.inst, "git", "log", "--format=%h", "--grep=^fix b$").stdout.split()
    assert inst_promoted and not set(inst_promoted) & set(shas), held
    p, status = w.autoupdate()
    assert local[:7] in status and inst_promoted[0] not in status, status


# ---- declared local adaptations ----

ADAPT = (
    "promote:\n"
    "  local_adaptations:\n"
    "    - path: core.txt\n"
    "      reason: this instance keeps its own wording\n"
)


def test_a_declared_local_adaptation_is_labelled_not_called_unpromoted(w):
    w.write(w.inst, "bridge-config.yaml", ADAPT); w.commit(w.inst, "declare adaptation")
    w.write(w.inst, "core.txt", "a\nLOCAL\nc\n"); w.commit(w.inst, "local wording")
    w.write(w.inst, "other.txt", "LOCAL\n"); w.commit(w.inst, "local only")
    w.write(w.up, "core.txt", "a\nUP\nc\n"); w.write(w.up, "other.txt", "UP\n")
    w.commit(w.up, "upstream edits")
    held = {u["path"]: u for u in w.plan()["unresolved"]}
    assert held["core.txt"]["local_adaptation"] == "this instance keeps its own wording"
    assert "declared local adaptation" in held["core.txt"]["reason"]
    assert "never reached upstream" not in held["core.txt"]["reason"]
    assert "local_adaptation" not in held["other.txt"]
    assert "never reached upstream" in held["other.txt"]["reason"]
    before = w.head()
    p, status = w.autoupdate()
    assert w.head() == before, "a declared adaptation is still a conflict a human merges"
    assert "declared local adaptation" in status, status


def test_local_adaptation_paths_may_be_globs(w):
    w.write(w.inst, "bridge-config.yaml", ADAPT.replace("path: core.txt", "path: '*.txt'"))
    w.commit(w.inst, "declare adaptation")
    w.write(w.inst, "core.txt", "a\nLOCAL\nc\n"); w.commit(w.inst, "local wording")
    w.write(w.up, "core.txt", "a\nUP\nc\n"); w.commit(w.up, "upstream edit")
    assert "local_adaptation" in w.plan()["unresolved"][0]


def test_a_malformed_adaptation_entry_is_reported_not_trusted(w):
    w.write(w.inst, "bridge-config.yaml", "promote:\n  local_adaptations:\n    - path: core.txt\n")
    w.commit(w.inst, "adaptation without a reason")
    w.write(w.inst, "core.txt", "a\nLOCAL\nc\n"); w.commit(w.inst, "local wording")
    w.write(w.up, "core.txt", "a\nUP\nc\n"); w.commit(w.up, "upstream edit")
    plan = w.plan()
    assert "local_adaptation" not in plan["unresolved"][0]
    assert plan.get("local_adaptations_invalid"), plan


# ---- a skip that lasts files one inbox item ----

STALE_KEY = "upstream-autoupdate-stale"


def _with_inbox(w, tmp_path):
    w.write(w.inst, "scripts/inbox.py", FAKE_INBOX)
    w.commit(w.inst, "instance carries an inbox")
    return tmp_path / "inbox.log"


def _old_upstream_conflict(w, days):
    w.write(w.inst, "core.txt", "a\nLOCAL\nc\n"); w.commit(w.inst, "local only")
    w.write(w.up, "core.txt", "a\nUP\nc\n")
    run(w.up, "git", "add", "-A")
    stamp = f"@{int(__import__('time').time()) - days * 86400} +0000"
    subprocess.run(["git", "commit", "-q", "-m", "upstream edit"], cwd=w.up, check=True,
                   env={**ENV, "GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp})


def _filed(log):
    return [l for l in (log.read_text().splitlines() if log.exists() else []) if l.startswith("add ")
            and f"--key {STALE_KEY}" in l]


def test_a_skip_older_than_the_threshold_files_one_item(w, tmp_path):
    log = _with_inbox(w, tmp_path)
    _old_upstream_conflict(w, days=5)
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert "SKIPPED" in status, status
    filed = _filed(log)
    assert len(filed) == 1, log.read_text()
    assert '"merge-base", "--is-ancestor"' in filed[0] and "upstream/main" in filed[0], filed
    assert "refs/heads/user/me" in filed[0] and '"HEAD"' not in filed[0], filed
    assert "5 day" in status, status
    # The repeat run files under the same key, so the inbox keeps one item.
    _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert {l.split("--key ")[1].split()[0] for l in _filed(log)} == {STALE_KEY}


def test_a_fresh_skip_files_nothing(w, tmp_path):
    log = _with_inbox(w, tmp_path)
    _old_upstream_conflict(w, days=0)
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert "SKIPPED" in status, status
    assert _filed(log) == []


def test_the_threshold_is_configurable(w, tmp_path):
    log = _with_inbox(w, tmp_path)
    _old_upstream_conflict(w, days=5)
    _autoupdate_env(w, FAKE_INBOX_LOG=str(log), AUTOUPDATE_STALE_DAYS="10")
    assert _filed(log) == []


def test_a_long_skip_on_a_staged_index_files_an_item(w, tmp_path):
    log = _with_inbox(w, tmp_path)
    w.write(w.up, "other.txt", "x\ny\n")
    run(w.up, "git", "add", "-A")
    stamp = f"@{int(__import__('time').time()) - 3 * 86400} +0000"
    subprocess.run(["git", "commit", "-q", "-m", "upstream change"], cwd=w.up, check=True,
                   env={**ENV, "GIT_COMMITTER_DATE": stamp})
    w.write(w.inst, "staged.txt", "s\n"); run(w.inst, "git", "add", "staged.txt")
    p, status = _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert "staged" in status, status
    assert len(_filed(log)) == 1, log.read_text() if log.exists() else ""


def test_a_merge_and_an_up_to_date_run_close_the_stale_item(w, tmp_path):
    log = _with_inbox(w, tmp_path)
    w.write(w.up, "other.txt", "x\ny\n"); w.commit(w.up, "upstream change")
    _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert f"close --key {STALE_KEY}" in log.read_text()
    log.unlink()
    _autoupdate_env(w, FAKE_INBOX_LOG=str(log))
    assert f"close --key {STALE_KEY}" in log.read_text()
