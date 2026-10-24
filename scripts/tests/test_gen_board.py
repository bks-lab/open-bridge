#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/gen-board.py (the work/board.md generator).

CONTRACT, this file is the authoritative spec for the generator's surface.

    parse_status(md: Path) -> dict
        Reads a STATUS.md and returns the row data the board renders:
            slug        the parent directory's name
            desc        frontmatter `headline:`, else the first `# ` H1 in the
                        body, else the slug
            type        frontmatter `type:`,    else the em-dash placeholder
            context     frontmatter `context:`, else the placeholder
            since       frontmatter `created:`, else `last_updated:`, else the
                        placeholder
            status      frontmatter `status:`,  else "?"
            blocked_by  frontmatter `blocked_by:`, else ""

        Frontmatter parsing is DELEGATED, never hand-rolled here. The repo's
        reference implementation is scripts/okf-export.py's parse_frontmatter,
        which is covered by scripts/tests/test_okf_export.py and agrees with
        PyYAML on well-formed input. A second hand-rolled parser in this file
        is the defect this suite exists to prevent: it drifted for months and
        lost content that a real YAML parser keeps.

    collect(folder: Path) -> tuple[list[dict], list[str]]
        Every immediate subdirectory holding a STATUS.md becomes a row, sorted
        by directory name. Subdirectories without one are reported separately
        by name, never silently dropped.

    main() -> int
        No arguments      regenerate work/board.md and print a summary line.
        --check           print the same summary and write NOTHING.
        anything else     usage on stderr, exit 2, and write NOTHING. An
                          unrecognised flag must never fall through to the
                          write path: `gen-board.py --help` regenerating the
                          board is how this was found.

        Streams are collected and counted but never contribute to WIP, which
        is doing + review over work/tasks/ only.

NOT covered on purpose: the exact markdown layout of board.md. It is a view
and its wording changes; the tests assert the data that reaches it.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tokenize
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GEN_BOARD = REPO_ROOT / "scripts" / "gen-board.py"
OKF_EXPORT = REPO_ROOT / "scripts" / "okf-export.py"


def _load(path: Path, name: str) -> types.ModuleType:
    """Import a hyphenated script by path without leaving a __pycache__ entry."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


gb = _load(GEN_BOARD, "gen_board_under_test")
okf = _load(OKF_EXPORT, "okf_export_for_reference")


def _executable_source(path: Path) -> str:
    """The script's source with comments and string literals removed.

    A plain substring scan over the raw file matches the prose that DESCRIBES
    the removed parser as readily as the parser itself, so the guard below
    would fire on its own documentation. Tokenising is the only way to ask
    about code and not about text that merely looks like it.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return "\n".join(kept)


def write_status(tmp_path: Path, slug: str, frontmatter: str, body: str = "") -> Path:
    """Create <tmp_path>/<slug>/STATUS.md with the given frontmatter block."""
    d = tmp_path / slug
    d.mkdir(parents=True, exist_ok=True)
    md = d / "STATUS.md"
    md.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
    return md


# ---------------------------------------------------------------------------
# The four defects. Each of these failed before the parser was delegated.
# ---------------------------------------------------------------------------


def test_hash_inside_a_quoted_headline_is_literal(tmp_path):
    """A `#` inside a quoted scalar is content, not a comment opener.

    The old parser stripped the inline comment BEFORE resolving quotes, so a
    headline naming an issue lost the issue number, which is the load-bearing
    half of the sentence.
    """
    md = write_status(
        tmp_path,
        "cart-a11y-pass",
        'headline: "cart a11y fixes in review as PR #214"',
    )
    assert gb.parse_status(md)["desc"] == "cart a11y fixes in review as PR #214"


def test_unquoted_headline_keeps_a_trailing_quote_character(tmp_path):
    """`.strip('"').strip("'")` ate a quote the value legitimately ends on."""
    md = write_status(
        tmp_path, "session-gate", 'headline: the gate runs before "hi" or "status"'
    )
    assert gb.parse_status(md)["desc"] == 'the gate runs before "hi" or "status"'


def test_unquoted_headline_keeps_a_trailing_apostrophe(tmp_path):
    md = write_status(tmp_path, "quoting", "headline: it is 'fine'")
    assert gb.parse_status(md)["desc"] == "it is 'fine'"


def test_a_fence_lookalike_inside_a_value_does_not_end_the_frontmatter(tmp_path):
    """`text.split("---")` ended the block at the first `---` anywhere.

    Every key after it was lost and fell back to its placeholder, so one
    headline could blank out a row's type, context and status at once.
    """
    md = write_status(
        tmp_path,
        "dashes",
        'headline: "a --- b"\ntype: ops\ncontext: bridge\nstatus: doing',
    )
    row = gb.parse_status(md)
    assert row["desc"] == "a --- b"
    assert (row["type"], row["context"], row["status"]) == ("ops", "bridge", "doing")


def test_block_scalar_headline_is_folded_not_taken_literally(tmp_path):
    """A `headline: |` block reached the board as the literal indicator `|`."""
    md = write_status(
        tmp_path, "block", "headline: |\n  Heading\n  Trailer\nstatus: doing"
    )
    row = gb.parse_status(md)
    assert row["desc"] == "Heading\nTrailer"
    assert row["status"] == "doing"


def test_indented_fence_inside_a_block_scalar_does_not_close_the_block(tmp_path):
    md = write_status(
        tmp_path,
        "indented",
        "headline: |\n  Heading\n  ---\n  Trailer\nstatus: review",
    )
    assert gb.parse_status(md)["status"] == "review"


# ---------------------------------------------------------------------------
# Agreement with a real YAML parser, which is what "correct" means here.
# ---------------------------------------------------------------------------

WELL_FORMED_HEADLINES = [
    "plain text",
    '"double quoted"',
    "'single quoted'",
    '"with a # hash inside"',
    "'with a # hash inside'",
    "text with a trailing comment   # note",
    '"quoted then a comment"   # note',
    '"value: with a colon inside"',
    '"a --- b"',
    "'it is fine'",
    '"trailing backslash pair \\\\"',
    "Grüße, Größe, Straße",
    '"tab\\tseparated"',
    "  leading and trailing spaces are trimmed  ",
    '""',
    "''",
]


@pytest.mark.parametrize("headline", WELL_FORMED_HEADLINES)
def test_headline_matches_pyyaml_on_well_formed_input(tmp_path, headline):
    """Every value PyYAML accepts must reach the board as PyYAML reads it.

    An EMPTY headline is the one case where the two legitimately differ: the
    board's documented fallback chain then reaches for the H1 and finally the
    slug, so that is what the row must carry.
    """
    yaml = pytest.importorskip("yaml")
    block = f"slug: x\nheadline: {headline}\nstatus: doing"
    md = write_status(tmp_path, "probe", block)
    expected = str(yaml.safe_load(block)["headline"]).strip()
    assert gb.parse_status(md)["desc"] == (expected or "probe")


def test_every_status_file_in_this_repo_matches_pyyaml(tmp_path):
    """Differential over the repo's own corpus, so a regression shows up on
    real data and not only on the fixtures this file happens to imagine."""
    yaml = pytest.importorskip("yaml")
    corpus = sorted(REPO_ROOT.glob("examples/**/STATUS.md"))
    if not corpus:
        pytest.skip("no STATUS.md files ship in this repo")
    mismatches = []
    for md in corpus:
        text = md.read_text(encoding="utf-8")
        lines = text.split("\n")
        fences = [i for i, line in enumerate(lines) if line == "---"]
        if len(fences) < 2:
            continue
        try:
            reference = yaml.safe_load("\n".join(lines[fences[0] + 1 : fences[1]])) or {}
        except yaml.YAMLError:
            continue
        row = gb.parse_status(md)
        for key, cell in (("type", "type"), ("context", "context"), ("status", "status")):
            if key in reference and str(reference[key]).strip() != row[cell]:
                mismatches.append(f"{md}: {key} {reference[key]!r} != {row[cell]!r}")
        if "headline" in reference and str(reference["headline"]).strip() != row["desc"]:
            mismatches.append(f"{md}: headline {reference['headline']!r} != {row['desc']!r}")
    assert not mismatches, "\n".join(mismatches)


# ---------------------------------------------------------------------------
# The anti-drift guard: one parser, not two.
# ---------------------------------------------------------------------------


def test_gen_board_delegates_frontmatter_parsing(tmp_path):
    """parse_status must produce exactly what the reference parser produces.

    Guards the plausible wrong fix, which is to patch the hand-rolled parser
    in place. Two implementations of one job drift, and this one drifted
    silently because nothing compared them.
    """
    frontmatter = (
        'headline: "cart a11y fixes in review as PR #214"\n'
        "type: ops\n"
        "context: bridge\n"
        "status: doing\n"
        "created: 2026-08-22"
    )
    md = write_status(tmp_path, "delegated", frontmatter)
    reference, _ = okf.parse_frontmatter(md.read_text(encoding="utf-8"))
    row = gb.parse_status(md)
    assert row["desc"] == reference["headline"]
    assert row["type"] == reference["type"]
    assert row["context"] == reference["context"]
    assert row["status"] == reference["status"]
    assert row["since"] == reference["created"]


def test_gen_board_source_hand_rolls_no_frontmatter_parsing():
    """The three constructs that caused all four defects must not come back.

    A textual guard rather than a behavioural one on purpose: re-inlining the
    parser would pass every test above on the day it is written and drift
    afterwards, which is exactly the history this file records.
    """
    code = _executable_source(GEN_BOARD)
    forbidden = {
        'split("---")': "splitting the file on every --- rather than on fences",
        "strip('\"')": "stripping quote characters off both ends of a value",
        "\\s+#.*$": "stripping an inline comment before quoting is resolved",
    }
    found = [f"{needle}: {why}" for needle, why in forbidden.items() if needle in code]
    assert not found, "gen-board.py is parsing frontmatter itself again:\n" + "\n".join(found)


def test_the_source_guard_would_actually_fire():
    """A guard nobody has seen fail is not a guard.

    Feeds the guard the exact line the old parser used and asserts it trips,
    so a future refactor of _executable_source cannot quietly neuter it.
    """
    old_line = "val = re.sub(r'\\s+#.*$', '', val).strip().strip('\"')"
    assert "strip('\"')" in old_line and "\\s+#.*$" in old_line


# ---------------------------------------------------------------------------
# The rest of the documented contract, previously untested in full.
# ---------------------------------------------------------------------------


def test_description_falls_back_to_the_first_h1_then_to_the_slug(tmp_path):
    with_h1 = write_status(tmp_path, "has-h1", "status: doing", "\n# The heading\n\ntext\n")
    assert gb.parse_status(with_h1)["desc"] == "The heading"

    bare = write_status(tmp_path, "bare-slug", "status: doing", "\nno heading here\n")
    assert gb.parse_status(bare)["desc"] == "bare-slug"


def test_an_h1_after_a_fence_lookalike_in_the_body_is_still_found(tmp_path):
    """The body must be everything after the CLOSING fence, horizontal rules
    included. The old split reassembled it from fragments."""
    md = write_status(tmp_path, "hr", "status: doing", "\n---\n\n# Real heading\n")
    assert gb.parse_status(md)["desc"] == "Real heading"


def test_a_comment_rule_in_the_frontmatter_does_not_become_the_description(tmp_path):
    """The shape that was live on a real board, and the reason this fix is not
    cosmetic.

    A STATUS.md with no `headline:` falls back to the first `# ` heading in
    the BODY. Splitting the file on every `---` made the body start inside the
    frontmatter whenever a YAML comment used a `# -----` rule, so the fallback
    picked up a comment line. Two streams rendered a paragraph of internal
    commentary where their title belonged, with no error anywhere.
    """
    md = write_status(
        tmp_path,
        "partner-sync",
        "slug: partner-sync\n"
        "type: ops\n"
        "status: doing\n"
        "\n"
        "# ---------------------------------------------------------------\n"
        "# Sync block, deliberately local. Long internal commentary that has\n"
        "# no business being a board description.\n"
        "# ---------------------------------------------------------------\n"
        "sync:\n"
        "  bridge_only: true",
        "\n# Alice Example, coordination hub\n\nbody text\n",
    )
    row = gb.parse_status(md)
    assert row["desc"] == "Alice Example, coordination hub"
    assert "Sync block" not in row["desc"]
    assert row["status"] == "doing"


def test_since_prefers_created_over_last_updated(tmp_path):
    both = write_status(
        tmp_path, "both", "status: doing\ncreated: 2026-01-01\nlast_updated: 2026-08-22"
    )
    assert gb.parse_status(both)["since"] == "2026-01-01"

    only_updated = write_status(tmp_path, "updated", "status: doing\nlast_updated: 2026-08-22")
    assert gb.parse_status(only_updated)["since"] == "2026-08-22"


def test_missing_fields_get_their_documented_placeholders(tmp_path):
    md = write_status(tmp_path, "sparse", "slug: sparse")
    row = gb.parse_status(md)
    assert row["status"] == "?"
    assert row["blocked_by"] == ""
    assert row["type"] == row["context"] == row["since"]
    assert row["type"] not in ("", None)


def test_a_file_without_frontmatter_still_yields_a_row(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    md = d / "STATUS.md"
    md.write_text("# Just a heading\n\nbody\n", encoding="utf-8")
    row = gb.parse_status(md)
    assert row["slug"] == "plain"
    assert row["desc"] == "Just a heading"
    assert row["status"] == "?"


def test_blocked_by_is_a_flag_on_top_of_a_status_not_a_status(tmp_path):
    md = write_status(tmp_path, "blocked", "status: doing\nblocked_by: waiting on legal")
    row = gb.parse_status(md)
    assert row["status"] == "doing"
    assert row["blocked_by"] == "waiting on legal"
    assert "blocked" in gb.status_cell(row) and "doing" in gb.status_cell(row)


def test_collect_sorts_by_directory_and_reports_dirs_without_status(tmp_path):
    write_status(tmp_path, "zulu", "status: doing")
    write_status(tmp_path, "alpha", "status: doing")
    (tmp_path / "orphan").mkdir()
    rows, nostatus = gb.collect(tmp_path)
    assert [r["slug"] for r in rows] == ["alpha", "zulu"]
    assert nostatus == ["orphan"]


def test_collect_on_a_missing_folder_is_empty_not_an_error(tmp_path):
    assert gb.collect(tmp_path / "nope") == ([], [])


# ---------------------------------------------------------------------------
# CLI. --check must not write, and neither must an unknown flag.
# ---------------------------------------------------------------------------


@pytest.fixture
def board_tree(tmp_path, monkeypatch):
    """Point the generator at a throwaway tree instead of the real repo."""
    root = tmp_path / "instance"
    (root / "work").mkdir(parents=True)
    monkeypatch.setattr(gb, "ROOT", root)
    monkeypatch.setattr(gb, "TASKS", root / "work" / "tasks")
    monkeypatch.setattr(gb, "STREAMS", root / "work" / "streams")
    monkeypatch.setattr(gb, "DONE", root / "work" / "done")
    return root


def test_no_arguments_writes_the_board(board_tree, monkeypatch, capsys):
    write_status(board_tree / "work" / "tasks", "one", "status: doing\nheadline: first")
    monkeypatch.setattr(sys, "argv", ["gen-board.py"])
    assert gb.main() == 0
    board = (board_tree / "work" / "board.md").read_text(encoding="utf-8")
    assert "first" in board
    assert "board.md regenerated" in capsys.readouterr().out


def test_check_prints_the_summary_and_writes_nothing(board_tree, monkeypatch, capsys):
    write_status(board_tree / "work" / "tasks", "one", "status: doing")
    monkeypatch.setattr(sys, "argv", ["gen-board.py", "--check"])
    assert gb.main() == 0
    assert not (board_tree / "work" / "board.md").exists()
    assert "Doing 1" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--help", "-h", "--dry-run", "--chekc", "extra"])
def test_an_unrecognised_argument_never_falls_through_to_the_write_path(
    board_tree, monkeypatch, capsys, flag
):
    """Found by running `gen-board.py --help`, which regenerated the board."""
    write_status(board_tree / "work" / "tasks", "one", "status: doing")
    monkeypatch.setattr(sys, "argv", ["gen-board.py", flag])
    exit_code = gb.main()
    assert exit_code != 0, f"{flag!r} was accepted"
    assert not (board_tree / "work" / "board.md").exists(), f"{flag!r} wrote the board"
    captured = capsys.readouterr()
    assert "--check" in (captured.err + captured.out)


def test_streams_are_counted_but_never_count_against_wip(board_tree, monkeypatch, capsys):
    for slug in ("a", "b"):
        write_status(board_tree / "work" / "tasks", slug, "status: doing")
    for slug in ("long-runner-1", "long-runner-2", "long-runner-3"):
        write_status(board_tree / "work" / "streams", slug, "status: doing")
    monkeypatch.setattr(sys, "argv", ["gen-board.py", "--check"])
    assert gb.main() == 0
    out = capsys.readouterr().out
    assert "Doing 2" in out
    assert "Streams 3" in out
    assert f"WIP 2/{gb.WIP_WARN}" in out                   # no work.max_active: the default cap


def test_the_wip_cap_comes_from_the_config_and_zero_switches_it_off(board_tree, monkeypatch, capsys):
    for slug in ("a", "b", "c"):
        write_status(board_tree / "work" / "tasks", slug, "status: doing")
    (board_tree / "bridge-config.yaml").write_text("work:\n  max_active: 2\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["gen-board.py"])
    assert gb.main() == 0
    board = (board_tree / "work" / "board.md").read_text(encoding="utf-8")
    assert "| WIP (doing+review) | 3 / 2 · ⚠️ WIP 3 > 2 |" in board
    (board_tree / "bridge-config.yaml").write_text("work:\n  enabled: true\n", encoding="utf-8")
    assert gb.main() == 0                                   # not set: the default of 10
    assert f"| WIP (doing+review) | 3 / {gb.WIP_WARN} |" in (board_tree / "work" / "board.md").read_text(encoding="utf-8")
    (board_tree / "bridge-config.yaml").write_text("work:\n  max_active: 0\n", encoding="utf-8")
    assert gb.main() == 0                                   # 0: no cap at all
    assert "| WIP (doing+review) | 3 |" in (board_tree / "work" / "board.md").read_text(encoding="utf-8")


def test_a_multi_line_headline_stays_one_table_row(board_tree, monkeypatch):
    """Block scalars only started parsing correctly with this fix, so a
    headline can now legitimately carry newlines. A newline inside a cell ends
    the row and turns the remainder into loose text under the table.
    """
    write_status(
        board_tree / "work" / "tasks",
        "multiline",
        "status: doing\nheadline: |\n  First line\n  Second line\n  Third line",
    )
    monkeypatch.setattr(sys, "argv", ["gen-board.py"])
    assert gb.main() == 0
    board = (board_tree / "work" / "board.md").read_text(encoding="utf-8")
    matching = [line for line in board.splitlines() if "First line" in line]
    assert len(matching) == 1, f"headline spread over {len(matching)} lines"
    assert matching[0].startswith("| multiline |")
    assert "Second line" in matching[0] and "Third line" in matching[0]
    assert re.sub(r"\\.", "", matching[0]).count("|") == 7


def test_a_task_whose_headline_carries_a_pipe_does_not_break_the_table(board_tree, monkeypatch):
    """The board is a markdown table; a raw `|` in a cell splits the row."""
    write_status(
        board_tree / "work" / "tasks", "piped", 'status: doing\nheadline: "a | b"'
    )
    monkeypatch.setattr(sys, "argv", ["gen-board.py"])
    assert gb.main() == 0
    board = (board_tree / "work" / "board.md").read_text(encoding="utf-8")
    data_row = next(line for line in board.splitlines() if line.startswith("| piped |"))
    # count DELIMITERS, so an escaped pipe inside a cell does not read as one
    delimiters = re.sub(r"\\.", "", data_row).count("|")
    assert delimiters == 7, f"cell count broken by an unescaped pipe: {data_row}"
    assert "a \\| b" in data_row


# --------------------------------------------------- one WIP default --
#
# The template shipped `max_active: 5`, the generator defaulted to 10, and the
# operations rule warned at `>=` while every script warned at `>`. Three
# answers to one question. The number lives in gen-board.py as WIP_WARN; every
# other place that states it must agree, and the comparison is "exceeds".

def test_the_template_ships_the_generators_default():
    import yaml
    tmpl = yaml.safe_load((REPO_ROOT / "bridge-config.yaml.template").read_text(encoding="utf-8"))
    assert tmpl["work"]["max_active"] == gb.WIP_WARN


def test_the_pre_commit_hook_falls_back_to_the_same_default():
    hook = (REPO_ROOT / "scripts" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert f"max=${{max:-{gb.WIP_WARN}}}" in hook


def test_the_docs_state_the_default_and_the_comparison():
    doc = (REPO_ROOT / "docs" / "work-system.md").read_text(encoding="utf-8")
    assert f"default {gb.WIP_WARN}" in doc
    rule = (REPO_ROOT / "rules" / "operations.md").read_text(encoding="utf-8")
    assert ">= max_active" not in rule
