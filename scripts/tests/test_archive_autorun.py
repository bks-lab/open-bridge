# SPDX-License-Identifier: MIT
"""Contract for scripts/archive-autorun.py — the scheduled, mechanical archive.

The properties worth pinning are about ORDER and REFUSAL, not about prose:

* every archive file exists before `log.md` is touched, because until then the log
  is the only place those rows exist;
* an existing archive is never overwritten;
* it refuses off a `user/*` branch, where the engine's own rules say not to write;
* "nothing closed" and "something went wrong" never print the same.

Run: python3 -m pytest scripts/tests/test_archive_autorun.py -q
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = "scripts/archive-autorun.py"

LOG = """# Week 27 — 2026-06-29 to 2026-07-05

## Mon 13.07

### TODO (rolling)
- [ ] something still open

| Timestamp | Glyph | Context | What |
|---|---|---|---|
| 2026-07-13 09:00 | 💻 | alpha | first |
| 2026-07-13 10:00 | 🔧 | beta | second |

## Wed 19.08

| Timestamp | Glyph | Context | What |
|---|---|---|---|
| 2026-08-19 09:00 | 💻 | alpha | third |
"""


@pytest.fixture
def repo(tmp_path):
    """A throwaway Bridge: the three scripts, a config, a log, on a user/* branch."""
    for rel in (SCRIPT, "scripts/archive-buckets.py", "scripts/inbox.py",
                "scripts/lib/inbox_verbs.py"):
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    (tmp_path / "bridge-config.yaml").write_text(
        "work:\n  enabled: true\n  archive_cadence: weekly\n", encoding="utf-8")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "log.md").write_text(LOG, encoding="utf-8")
    for args in (["init", "-q", "-b", "user/test"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "T"], ["add", "-A"],
                 ["commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True)
    return tmp_path


def run(repo, *extra):
    return subprocess.run(["python3", SCRIPT, "--today", "2026-09-24", *extra],
                          cwd=repo, capture_output=True, text=True)


def test_it_archives_every_closed_period_and_resets_once(repo):
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    weeks = repo / "work" / "archive" / "weeks"
    assert (weeks / "2026-W29.md").exists() and (weeks / "2026-W29-raw.md").exists()
    assert (weeks / "2026-W34.md").exists() and (weeks / "2026-W34-raw.md").exists()
    # the raw carries ONLY its own period
    assert "first" in (weeks / "2026-W29-raw.md").read_text()
    assert "third" not in (weeks / "2026-W29-raw.md").read_text()
    assert "third" in (weeks / "2026-W34-raw.md").read_text()


def _inbox_summaries(repo) -> list[str]:
    import yaml
    root = repo / "work" / "inbox"
    return [yaml.safe_load(p.read_text())["summary"] for p in sorted(root.glob("*/item.yaml"))]


def test_the_open_todo_and_the_obligation_go_to_the_inbox(repo):
    # Open items belong in the inbox (docs/inbox.md), where something closes
    # them. A rolling TODO block in the log is a sentence nothing ever closes.
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    summaries = _inbox_summaries(repo)
    assert any("something still open" in s for s in summaries), summaries
    assert any("distillation" in s for s in summaries), summaries


def test_the_reset_log_carries_no_todo_block(repo):
    run(repo)
    log = (repo / "work" / "log.md").read_text()
    assert "### TODO" not in log and "### Carried over" not in log
    assert "- [ ] " not in log


def test_a_rerun_files_no_second_item(repo):
    run(repo)
    first = len(_inbox_summaries(repo))
    assert first == 2, "the obligation and the one open item"
    (repo / "work" / "log.md").write_text(LOG, encoding="utf-8")
    shutil.rmtree(repo / "work" / "archive")
    run(repo)
    assert len(_inbox_summaries(repo)) == first


def test_distinct_todos_never_share_an_inbox_key(repo):
    # The key must tell apart every line the dedup tells apart: non-ASCII
    # text and a long shared prefix once collapsed to one key, and the
    # second item was absorbed by the first and lost.
    prefix = "x" * 70
    log = LOG.replace("- [ ] something still open\n",
                      "- [ ] something still open\n- [ ] 確認する\n- [ ] 送信する\n"
                      f"- [ ] {prefix} one\n- [ ] {prefix} two\n")
    (repo / "work" / "log.md").write_text(log, encoding="utf-8")
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    summaries = _inbox_summaries(repo)
    for text in ("確認する", "送信する", f"{prefix} one", f"{prefix} two"):
        assert text in summaries, (text, summaries)


def test_a_todo_in_the_open_period_stays_in_the_log_and_out_of_the_inbox(repo):
    # Only what is archived is filed. A TODO in a day-block that stays in the
    # log would otherwise be filed now and again when its period closes,
    # reopening an item the person may have closed in between.
    log = LOG + """
## Tue 22.09

- [ ] still this week

| Timestamp | Glyph | Context | What |
|---|---|---|---|
| 2026-09-22 09:00 | 💻 | alpha | fourth |
"""
    (repo / "work" / "log.md").write_text(log, encoding="utf-8")
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not any("still this week" in s for s in _inbox_summaries(repo))
    assert "- [ ] still this week" in (repo / "work" / "log.md").read_text()
    assert any("something still open" in s for s in _inbox_summaries(repo))


def test_without_an_inbox_the_open_items_stay_in_the_log(repo):
    # Never lose an unchecked item: no inbox, the log keeps carrying it.
    (repo / "scripts" / "inbox.py").unlink()
    r = run(repo)
    assert r.returncode == 0, r.stdout + r.stderr
    log = (repo / "work" / "log.md").read_text()
    assert "something still open" in log, "an unchecked item must survive the reset"
    assert "distillation" in log, "the owed judgement half must be recorded, not dropped"
    assert "inbox" in r.stdout


def test_no_rows_are_lost(repo):
    before = (repo / "work" / "log.md").read_text().count("| 2026-")
    run(repo)
    weeks = repo / "work" / "archive" / "weeks"
    after = sum(p.read_text().count("| 2026-") for p in weeks.glob("*-raw.md"))
    after += (repo / "work" / "log.md").read_text().count("| 2026-")
    assert after == before, f"{before} rows in, {after} accounted for"


def test_a_dry_run_writes_nothing(repo):
    before = (repo / "work" / "log.md").read_text()
    r = run(repo, "--dry-run")
    assert r.returncode == 0
    assert not (repo / "work" / "archive").exists()
    assert not (repo / "work" / "inbox").exists()
    assert (repo / "work" / "log.md").read_text() == before


def test_an_existing_archive_is_never_overwritten(repo):
    run(repo)
    first = (repo / "work" / "archive" / "weeks" / "2026-W29.md").read_text()
    # put the same periods back and run again
    (repo / "work" / "log.md").write_text(LOG, encoding="utf-8")
    r = run(repo)
    assert r.returncode == 3, "a collision wants a human, not a guess"
    assert "already exists" in r.stdout
    assert (repo / "work" / "archive" / "weeks" / "2026-W29.md").read_text() == first


def test_it_refuses_off_a_user_branch(repo):
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=repo, capture_output=True)
    r = run(repo)
    assert r.returncode == 3 and "user/*" in r.stdout


def test_nothing_closed_is_not_an_error_and_says_so(repo):
    run(repo)                      # drain everything first
    r = run(repo)                  # nothing closed remains... except the collision guard
    # after a drain the log holds no closed period, so re-running is the quiet path
    (repo / "work" / "log.md").write_text(
        "# Week 39\n\n## Thu 24.09\n\n| 2026-09-24 09:00 | 💻 | a | x |\n", encoding="utf-8")
    r = run(repo)
    assert r.returncode == 0 and "nothing closed" in r.stdout


def test_a_disabled_work_system_is_a_no_op(repo):
    (repo / "bridge-config.yaml").write_text("work:\n  enabled: false\n", encoding="utf-8")
    r = run(repo)
    assert r.returncode == 0 and "not true" in r.stdout
    assert not (repo / "work" / "archive").exists()
