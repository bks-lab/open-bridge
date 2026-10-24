#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/worklog.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. Phase 1 says to read `work/log.md` for "last activity, current
week". Nothing enforced the second half, and reading a file reads the file: on a
live instance the log measured 405,076 bytes, roughly 155,800 tokens, four times
everything else in the always-on budget put together. The instruction was prose,
and prose does not truncate a file.

This is the same shape as the config slice: name what the session needs, and emit
exactly that.

    parse_blocks(text) -> (header, blocks)
        `header` is everything before the first `## ` heading: the week line and
        the rolling TODO, which are session context in their own right. `blocks`
        is one entry per day heading.

    recent_blocks(blocks, count) -> list
        The `count` most recent, by the `DD.MM` in the heading. Order in the file
        is NOT assumed: an instance that appends day blocks at the end must get
        the same answer as one that prepends them. An unparseable heading falls
        back to file order rather than being dropped, because losing a day is
        worse than including one too many.

    render(header, blocks) -> str
        Deterministic.

    main(argv) -> int
        `--recent N` (default 3). A missing log is not an error: Phase 1 creates
        it from a template and continues.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "worklog.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("worklog", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["worklog"] = mod
    spec.loader.exec_module(mod)
    return mod


wl = _load_module()

HEADER = "# KW 35 (24.08 - 30.08.2026)\n\n**Focus:** something\n\n- [ ] a rolling todo\n\n"
D28 = "## Friday 28.08\n\n| 2026-08-28 19:43 | ok | ctx | twenty-eighth |\n\n"
D27 = "## Thursday 27.08\n\n| 2026-08-27 10:00 | ok | ctx | twenty-seventh |\n\n"
D26 = "## Wednesday 26.08\n\n| 2026-08-26 10:00 | ok | ctx | twenty-sixth |\n\n"
D24 = "## Monday 24.08\n\n| 2026-08-24 10:00 | ok | ctx | twenty-fourth |\n"

NEWEST_FIRST = HEADER + D28 + D27 + D26 + D24
OLDEST_FIRST = HEADER + D24 + D26 + D27 + D28


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "log.md").write_text(NEWEST_FIRST, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------- the parsing --

def test_the_header_is_everything_before_the_first_day():
    header, _ = wl.parse_blocks(NEWEST_FIRST)
    assert "KW 35" in header and "rolling todo" in header
    assert "28.08" not in header


def test_every_day_block_is_found():
    _, blocks = wl.parse_blocks(NEWEST_FIRST)
    assert len(blocks) == 4


def test_a_log_with_no_day_blocks_yields_only_a_header():
    header, blocks = wl.parse_blocks("# KW 1\n\nnothing yet\n")
    assert "KW 1" in header
    assert blocks == []


# ------------------------------------------------------------ the selection --

def test_the_most_recent_days_are_selected():
    _, blocks = wl.parse_blocks(NEWEST_FIRST)
    got = wl.recent_blocks(blocks, 2)
    assert "twenty-eighth" in "".join(got)
    assert "twenty-seventh" in "".join(got)
    assert "twenty-fourth" not in "".join(got)


def test_file_order_is_not_assumed():
    """An instance that appends day blocks must get the same answer as one that
    prepends them. Assuming an order is how a silently wrong week happens."""
    _, newest_first = wl.parse_blocks(NEWEST_FIRST)
    _, oldest_first = wl.parse_blocks(OLDEST_FIRST)
    a = set(wl.recent_blocks(newest_first, 2))
    b = set(wl.recent_blocks(oldest_first, 2))
    assert a == b


def test_asking_for_more_days_than_exist_returns_all():
    _, blocks = wl.parse_blocks(NEWEST_FIRST)
    assert len(wl.recent_blocks(blocks, 99)) == 4


def test_an_unparseable_heading_is_kept_rather_than_dropped():
    """Losing a day is worse than including one too many."""
    text = HEADER + "## Someday\n\nrow\n\n" + D28
    _, blocks = wl.parse_blocks(text)
    assert len(wl.recent_blocks(blocks, 99)) == 2


# -------------------------------------------------------------- the render --

def test_the_render_is_byte_identical_across_runs(tree):
    a = wl.main(["--repo-root", str(tree), "--recent", "2", "--to-string"])
    b = wl.main(["--repo-root", str(tree), "--recent", "2", "--to-string"])
    assert a == b


def test_the_render_is_smaller_than_the_file(tree):
    whole = (tree / "work" / "log.md").read_text(encoding="utf-8")
    out = wl.main(["--repo-root", str(tree), "--recent", "1", "--to-string"])
    assert len(out) < len(whole)


def test_the_render_keeps_the_header_because_it_is_session_context(tree):
    out = wl.main(["--repo-root", str(tree), "--recent", "1", "--to-string"])
    assert "rolling todo" in out


# ---------------------------------------------------------------- the main --

def test_main_exits_zero_and_prints(tree, capsys):
    assert wl.main(["--repo-root", str(tree), "--recent", "2"]) == 0
    assert "twenty-eighth" in capsys.readouterr().out


def test_a_missing_log_is_not_an_error(tmp_path, capsys):
    """Phase 1 creates it from a template and continues; it must not die here."""
    assert wl.main(["--repo-root", str(tmp_path), "--recent", "2"]) == 0
    assert capsys.readouterr().out.strip() == ""


# --------------------------------------------- the kept-heading contract --
#
# The module docstring: "A heading whose date will not parse is kept rather
# than dropped, because losing a day is worse than including one too many."
# `_sort_key` returned (0, 0, -index) for it against (1, ...) for a dated one,
# with reverse=True and then `ordered[:count]` — so it sorted LAST and was the
# FIRST thing cut. The contract was exactly inverted.
#
# The guarding test could not see it: it called recent_blocks(blocks, 99) on a
# two-block fixture and asserted len == 2, which is true of any implementation
# that does not delete blocks, and never exercised the production value 3.


def _blocks(*headings):
    return [f"## {h}\n| a | b |\n" for h in headings]


def test_an_unparseable_heading_survives_the_production_slice():
    blocks = _blocks("WICHTIG offene Punkte", "Samstag 30.08", "Freitag 29.08", "Donnerstag 28.08")
    kept = wl.recent_blocks(blocks, 3)
    assert any("WICHTIG offene Punkte" in b for b in kept)


def test_it_does_not_consume_one_of_the_dated_slots():
    # "including one too many" — the pinned section is extra, not a substitute
    # for a day. Otherwise adding one silently shortens the working memory.
    blocks = _blocks("WICHTIG offene Punkte", "Samstag 30.08", "Freitag 29.08", "Donnerstag 28.08")
    kept = wl.recent_blocks(blocks, 3)
    dated = [b for b in kept if "WICHTIG" not in b]
    assert len(dated) == 3


def test_several_unparseable_headings_are_all_kept():
    blocks = _blocks("Pinned A", "Pinned B", "Samstag 30.08", "Freitag 29.08")
    kept = wl.recent_blocks(blocks, 1)
    assert sum("Pinned" in b for b in kept) == 2


def test_unparseable_headings_keep_file_order():
    blocks = _blocks("Pinned A", "Pinned B", "Samstag 30.08")
    kept = wl.recent_blocks(blocks, 1)
    assert kept.index(blocks[0]) < kept.index(blocks[1])


def test_dated_blocks_are_still_newest_first(tmp_path):
    blocks = _blocks("Freitag 29.08", "Samstag 30.08", "Donnerstag 28.08")
    kept = wl.recent_blocks(blocks, 2)
    assert kept[0].startswith("## Samstag 30.08")
    assert kept[1].startswith("## Freitag 29.08")


def test_a_log_of_only_dated_blocks_is_unchanged(tmp_path):
    blocks = _blocks("Samstag 30.08", "Freitag 29.08", "Donnerstag 28.08")
    assert len(wl.recent_blocks(blocks, 2)) == 2


# ------------------------------------------------- the archive rollover --
#
# `/archive` runs on request, and the reminder that asks for it lived in prose:
# once nobody said the word, the log kept growing. On one instance it held three
# closed weeks and 595 KB before anyone noticed. The session start already runs
# `worklog.py --recent`, so that is where an unarchived closed period is named,
# every time, with its size. Nothing here archives: `/archive` distils memory
# and wants a human to confirm, so detection is the whole job.

def _day(weekday: str, iso: str, *whats: str) -> str:
    dd, mm = iso[8:10], iso[5:7]
    rows = "".join(f"| {iso} 10:0{i} | ok | ctx | {w} |\n" for i, w in enumerate(whats))
    return f"## {weekday} {dd}.{mm}\n\n{rows}\n"


ROLL_LOG = (
    "# Week 41 - 2026-10-05 to 2026-10-11\n\n"
    + _day("Mon", "2026-10-05", "w41 a", "w41 b")
    + _day("Mon", "2026-10-12", "w42 a")
    + _day("Mon", "2026-10-19", "w43 a")
)


def _roll_tree(tmp_path: Path, log: str = ROLL_LOG, config: str | None = None) -> Path:
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "work" / "log.md").write_text(log, encoding="utf-8")
    if config is not None:
        (tmp_path / "bridge-config.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def test_closed_periods_are_counted_with_rows_and_bytes():
    import datetime as dt
    status = wl.archive_status(ROLL_LOG, "weekly", dt.date(2026, 10, 21))
    assert status["cadence"] == "weekly"
    assert [p["label"] for p in status["periods"]] == ["Week 41", "Week 42"]
    assert status["rows"] == 3
    assert status["bytes"] > 0
    # the bytes are those of the closed blocks only, never the open week
    assert status["bytes"] < len(ROLL_LOG.encode("utf-8"))


def test_the_open_period_alone_is_nothing_to_report():
    import datetime as dt
    status = wl.archive_status(_day("Mon", "2026-10-19", "only"), "weekly", dt.date(2026, 10, 21))
    assert status["periods"] == []


def test_the_cadence_comes_from_the_config(tmp_path, capsys):
    root = _roll_tree(tmp_path, config="work:\n  archive_cadence: monthly\n")
    assert wl.main(["--repo-root", str(root), "--check", "--today", "2026-10-21"]) == 0


def test_the_recent_slice_names_the_unarchived_periods(tmp_path, capsys):
    root = _roll_tree(tmp_path)
    assert wl.main(["--repo-root", str(root), "--recent", "1", "--today", "2026-10-21"]) == 0
    out = capsys.readouterr().out
    assert "2 closed weekly period(s)" in out
    assert "Week 41" in out and "Week 42" in out
    assert "/archive" in out
    # the notice leads, so a truncated read still shows it
    assert out.lstrip().startswith(">")


def test_no_notice_when_everything_closed_is_archived(tmp_path, capsys):
    root = _roll_tree(tmp_path, log=_day("Mon", "2026-10-19", "only"))
    assert wl.main(["--repo-root", str(root), "--recent", "1", "--today", "2026-10-21"]) == 0
    assert "/archive" not in capsys.readouterr().out


def test_to_string_stays_the_bare_slice(tmp_path):
    """The meter and the suite read the slice itself; the notice is for a reader."""
    root = _roll_tree(tmp_path)
    out = wl.main(["--repo-root", str(root), "--recent", "1", "--today", "2026-10-21", "--to-string"])
    assert "/archive" not in out


def test_check_fails_while_a_closed_period_is_unarchived(tmp_path, capsys):
    root = _roll_tree(tmp_path)
    assert wl.main(["--repo-root", str(root), "--check", "--today", "2026-10-21"]) == 1
    assert "Week 41" in capsys.readouterr().out


def test_check_passes_on_a_clean_log(tmp_path, capsys):
    root = _roll_tree(tmp_path, log=_day("Mon", "2026-10-19", "only"))
    assert wl.main(["--repo-root", str(root), "--check", "--today", "2026-10-21"]) == 0


def test_check_passes_without_a_log(tmp_path):
    assert wl.main(["--repo-root", str(tmp_path), "--check"]) == 0


# ------------------------------------------------- rows under the wrong day --
#
# Rows written by hand were appended under the last block there was, so two
# working days sat under a Monday. Every row self-dates, so this is detectable.

MISFILED = (
    "## Mon 12.10\n\n"
    "| 2026-10-12 10:00 | ok | ctx | monday |\n"
    "| 2026-10-13 09:00 | ok | ctx | tuesday, under monday |\n"
    "| 2026-10-14 09:00 | ok | ctx | wednesday, under monday |\n"
)


def test_rows_under_another_days_block_are_found():
    found = wl.misfiled_rows(MISFILED)
    assert found == {"12.10": {"2026-10-13": 1, "2026-10-14": 1}}


def test_check_names_misfiled_rows(tmp_path, capsys):
    root = _roll_tree(tmp_path, log=MISFILED)
    assert wl.main(["--repo-root", str(root), "--check", "--today", "2026-10-14"]) == 1
    out = capsys.readouterr().out
    assert "2 row(s)" in out and "12.10" in out


# --------------------------------------------------------- the append path --
#
# One way to write a row that also opens the day block a row's date needs.

def test_append_opens_the_missing_day_block(tmp_path):
    root = _roll_tree(tmp_path, log=_day("Mon", "2026-10-12", "monday"))
    assert wl.main(["--repo-root", str(root), "--append", "--context", "bridge",
                    "--what", "tuesday row", "--at", "2026-10-13 09:15"]) == 0
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    assert "| 2026-10-13 09:15 | " in text
    assert wl.misfiled_rows(text) == {}
    header, blocks = wl.parse_blocks(text)
    tuesday = [b for b in blocks if b.split("\n", 1)[0].endswith("13.10")]
    assert len(tuesday) == 1 and "tuesday row" in tuesday[0]


def test_append_uses_the_existing_block(tmp_path):
    root = _roll_tree(tmp_path, log=_day("Mon", "2026-10-12", "monday"))
    assert wl.main(["--repo-root", str(root), "--append", "--context", "bridge",
                    "--what", "second", "--glyph", "💻", "--at", "2026-10-12 11:00"]) == 0
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    assert text.count("## ") == 1
    assert "| 2026-10-12 11:00 | 💻 | bridge | second |" in text


def test_append_neutralises_a_pipe(tmp_path):
    root = _roll_tree(tmp_path, log=_day("Mon", "2026-10-12", "monday"))
    wl.main(["--repo-root", str(root), "--append", "--context", "bridge",
             "--what", "a | b", "--at", "2026-10-12 11:00"])
    assert "| a / b |" in (root / "work" / "log.md").read_text(encoding="utf-8")


def test_append_needs_context_and_what(tmp_path):
    root = _roll_tree(tmp_path, log=_day("Mon", "2026-10-12", "monday"))
    with pytest.raises(SystemExit):
        wl.main(["--repo-root", str(root), "--append", "--what", "no context"])


def test_append_creates_a_missing_log(tmp_path):
    (tmp_path / "work").mkdir()
    assert wl.main(["--repo-root", str(tmp_path), "--append", "--context", "bridge",
                    "--what", "first", "--at", "2026-10-12 11:00"]) == 0
    text = (tmp_path / "work" / "log.md").read_text(encoding="utf-8")
    assert "12.10" in text and "| first |" in text
