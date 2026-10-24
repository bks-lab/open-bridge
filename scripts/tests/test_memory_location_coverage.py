# SPDX-License-Identifier: MIT
"""Contract for `memory-location.py check`'s coverage pass (docs/memory.md § Coverage).

A fact file nothing reaches is invisible to every session: the index is the
only thing the harness loads, so a fact that MEMORY.md, MEMORY-ARCHIVE.md and
every reachable fact's `[[wikilink]]` all miss exists on disk and is never
recalled. The pass walks links transitively from the two index files and
names every fact it never reached.

    default   warning on stderr with the count and each unreachable file,
              exit code unchanged (0 when the index lint is clean)
    --strict  the same list, exit 1

Meta files with an all-uppercase stem (MEMORY.md, MEMORY-ARCHIVE.md, README.md,
PROVENANCE.md) are not facts. A `[[wikilink]]` resolves to a fact's `name:`
slug or its file stem, with `|alias` and `#section` stripped.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "memory-location.py"


def _load(path: Path, name: str) -> types.ModuleType:
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


ml = _load(SCRIPT, "memory_location_coverage_under_test")


def _repo_with_memory(tmp_path, monkeypatch) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(".claude/settings.local.json\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert ml.main(["--repo", str(repo), "enable"]) == 0
    memory = repo / "work" / "memory"
    memory.mkdir(parents=True)
    return repo, memory


def _fact(memory: Path, filename: str, name: str, body: str = "") -> None:
    (memory / filename).write_text(
        f"---\nname: {name}\ndescription: d\nmetadata:\n  type: feedback\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _index(memory: Path, *lines: str, archive: tuple[str, ...] = ()) -> None:
    (memory / "MEMORY.md").write_text("# Memory\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    if archive:
        (memory / "MEMORY-ARCHIVE.md").write_text(
            "# Archive\n\n" + "\n".join(archive) + "\n", encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# library: coverage_report
# ---------------------------------------------------------------------------


def test_every_fact_reached_by_index_archive_or_wikilink(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a", "see [[b]]")
    _fact(memory, "feedback_b.md", "b", "and [[c-slug|alias]] plus [[feedback_d#part]]")
    _fact(memory, "reference_c.md", "c-slug")
    _fact(memory, "feedback_d.md", "d")
    _fact(memory, "project_e.md", "e")
    _index(memory, "- [A](feedback_a.md) - hook", archive=("- [E](project_e.md) - hook",))

    facts, unreachable = ml.coverage_report(memory)
    assert facts == 5
    assert unreachable == []


def test_unreachable_facts_are_named(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    _fact(memory, "feedback_orphan.md", "orphan")
    _fact(memory, "reference_island.md", "island", "points at [[orphan]]")
    _index(memory, "- [A](feedback_a.md) - hook")

    facts, unreachable = ml.coverage_report(memory)
    assert facts == 3
    # a wikilink only counts from a REACHABLE file: island links orphan, nobody links island
    assert unreachable == ["feedback_orphan.md", "reference_island.md"]


def test_wikilink_cycle_terminates(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a", "[[b]]")
    _fact(memory, "feedback_b.md", "b", "[[a]]")
    _index(memory, "- [A](feedback_a.md) - hook")

    assert ml.coverage_report(memory) == (2, [])


def test_meta_files_are_not_facts(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    (memory / "PROVENANCE.md").write_text("# where facts came from\n", encoding="utf-8")
    (memory / "README.md").write_text("# readme\n", encoding="utf-8")
    (memory / "feedback_a.md.bak").write_text("old\n", encoding="utf-8")
    _index(memory, "- [A](feedback_a.md) - hook")

    assert ml.coverage_report(memory) == (1, [])


def test_no_index_at_all_leaves_every_fact_unreachable(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")

    assert ml.coverage_report(memory) == (1, ["feedback_a.md"])


def test_missing_directory_reports_nothing(tmp_path):
    assert ml.coverage_report(tmp_path / "absent") == (0, [])


# ---------------------------------------------------------------------------
# CLI: check, default warns, --strict fails
# ---------------------------------------------------------------------------


def test_check_default_warns_with_count_and_keeps_exit_zero(tmp_path, monkeypatch, capsys):
    repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    _fact(memory, "feedback_orphan.md", "orphan")
    _index(memory, "- [A](feedback_a.md) - hook")

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "check"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "1 of 2 fact file(s) unreachable" in err
    assert "feedback_orphan.md" in err


def test_check_strict_fails_on_an_unreachable_fact(tmp_path, monkeypatch, capsys):
    repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    _fact(memory, "feedback_orphan.md", "orphan")
    _index(memory, "- [A](feedback_a.md) - hook")

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "check", "--strict"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "feedback_orphan.md" in err


def test_check_strict_passes_full_coverage_silently(tmp_path, monkeypatch, capsys):
    repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    _index(memory, "- [A](feedback_a.md) - hook")

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "check", "--strict"])
    assert rc == 0
    assert capsys.readouterr().err == ""


def test_check_lint_failure_still_exits_one_without_strict(tmp_path, monkeypatch, capsys):
    repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_orphan.md", "orphan")
    _index(memory, "- [Ghost](feedback_ghost.md) - hook")

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "check"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "feedback_ghost.md" in err
    assert "feedback_orphan.md" in err
