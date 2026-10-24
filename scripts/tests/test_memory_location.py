#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/memory-location.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. Claude Code's `autoMemoryDirectory` setting lets an instance
keep its auto memory (MEMORY.md index plus one fact file per markdown file)
inside the repo, at `work/memory/`, instead of at the harness's own default
outside it (`~/.claude/projects/<encoded-root>/memory`). The value has to be
an absolute path or start with `~/`; a relative value is silently ignored by
the harness, with no warning. `scripts/memory-location.py` is the ONE place
in CORE that resolves the live directory, so every reader (okf-export,
bridge-audit, bridge-curator) agrees on where memory lives, and it carries
the tooling to move an instance from the legacy path into the repo:

    resolve_memory_dir(start, home=None) -> (Path, source, warnings)
        Precedence: repo_root/.claude/settings.local.json ("setting:local"),
        repo_root/.claude/settings.json ("setting:project"),
        home/.claude/settings.json ("setting:user"). The FIRST of those that
        HOLDS the `autoMemoryDirectory` key decides, whether its value turns
        out usable or not; an unusable value (relative, empty, not a string)
        warns and falls through to the legacy hash path rather than trying
        the next file in the list. Never raises: a missing git binary, a
        missing settings file, or invalid JSON all degrade gracefully.

    repo_root_for(start)
        The git PROJECT root: `git rev-parse --git-common-dir`'s parent, so a
        linked worktree resolves to the SAME settings as the checkout it was
        made from (the harness scopes memory to the project, not the cwd).
        Falls back to `Path(start).resolve()` outside any git repo.

CLI subcommands, each covered below:

    status [--json]     where memory resolves to today, plus drift against
                         the legacy directory (files only there, files whose
                         legacy copy is newer and differs).
    enable [--path P]   writes {"autoMemoryDirectory": <abs>} into
                         repo_root/.claude/settings.local.json, preserving
                         every other key. Idempotent. Refuses (exit 2) on
                         invalid existing JSON, or when that settings file is
                         NOT git-ignored (an absolute local path must never
                         be committed).
    migrate             copies top-level regular files (directories and any
                         name containing ".bak" skipped) from the legacy
                         directory into the resolved one: new files are
                         copied, byte-identical files are skipped, files that
                         differ are a CONFLICT and left untouched unless
                         --prefer-newer and the legacy copy has the newer
                         mtime. Never deletes or modifies the legacy side.
                         Exit 1 while a conflict remains, exit 2 when nothing
                         is configured yet or the legacy directory is absent.
    stub-legacy --yes   replaces the legacy MEMORY.md with a short pointer
                         stub, keeping the old index as MEMORY.md.pre-move.
                         Refuses (exit 2) without --yes, when memory is still
                         the legacy directory, when a dry-run migrate would
                         still have something to copy or a conflict, or when
                         the legacy index is already a stub.
    check                lints the resolved MEMORY.md: over 200 lines, over
                         25 KB (25 * 1024 bytes), an index-line hook over 120
                         characters, or a linked `*.md` file that does not
                         exist. Exit 0 when the directory or MEMORY.md itself
                         is missing (nothing to lint yet). Also warns on fact
                         files no index or reachable wikilink reaches;
                         `--strict` makes that exit 1 (section at the end).

Tests build real git repos under `tmp_path` and pass an explicit, throwaway
`home` directory (never the real one) either directly to `resolve_memory_dir`
or via the `HOME` environment variable for CLI-level tests, since
`Path.home()` reads `$HOME` at call time.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "memory-location.py"


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


ml = _load(SCRIPT, "memory_location_under_test")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def git_repo(root: Path, *, gitignore: str = "") -> Path:
    """A real git checkout; `check-ignore` only needs the file present, not committed."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    if gitignore:
        (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    return root


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# resolve_memory_dir: precedence
# ---------------------------------------------------------------------------


def test_precedence_local_beats_project_and_user(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    local_target = str(tmp_path / "local-target")
    _write_json(repo / ".claude" / "settings.local.json", {"autoMemoryDirectory": local_target})
    _write_json(repo / ".claude" / "settings.json",
                {"autoMemoryDirectory": str(tmp_path / "project-target")})
    _write_json(home / ".claude" / "settings.json",
                {"autoMemoryDirectory": str(tmp_path / "user-target")})

    memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert memory_dir == Path(local_target)
    assert source == "setting:local"
    assert warnings == []


def test_precedence_project_beats_user_when_no_local(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    project_target = str(tmp_path / "project-target")
    _write_json(repo / ".claude" / "settings.json", {"autoMemoryDirectory": project_target})
    _write_json(home / ".claude" / "settings.json",
                {"autoMemoryDirectory": str(tmp_path / "user-target")})

    memory_dir, source, _warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert memory_dir == Path(project_target)
    assert source == "setting:project"


def test_precedence_user_when_nothing_repo_local(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    user_target = str(tmp_path / "user-target")
    _write_json(home / ".claude" / "settings.json", {"autoMemoryDirectory": user_target})

    memory_dir, source, _warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert memory_dir == Path(user_target)
    assert source == "setting:user"


def test_missing_key_falls_through_to_next_file(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    _write_json(repo / ".claude" / "settings.local.json", {"someOtherKey": "x"})
    project_target = str(tmp_path / "project-target")
    _write_json(repo / ".claude" / "settings.json", {"autoMemoryDirectory": project_target})

    memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert memory_dir == Path(project_target)
    assert source == "setting:project"
    assert warnings == []


# ---------------------------------------------------------------------------
# resolve_memory_dir: invalid values and legacy fallback
# ---------------------------------------------------------------------------


def test_relative_value_ignored_with_warning_falls_back_to_legacy(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    settings = repo / ".claude" / "settings.local.json"
    _write_json(settings, {"autoMemoryDirectory": "relative/path"})
    # A valid project-level value must NOT be consulted: the local file
    # HELD the key, so it alone decides, even though its value is unusable.
    _write_json(repo / ".claude" / "settings.json",
                {"autoMemoryDirectory": str(tmp_path / "project-target")})

    memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert source == "legacy"
    assert memory_dir == ml.legacy_memory_dir(ml.repo_root_for(str(repo)), home)
    assert len(warnings) == 1
    assert "not absolute" in warnings[0]
    assert str(settings) in warnings[0]


@pytest.mark.parametrize("value", ["", 42, None, ["not", "a", "string"]])
def test_non_string_or_empty_value_is_invalid(tmp_path, value):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    _write_json(repo / ".claude" / "settings.local.json", {"autoMemoryDirectory": value})

    _memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert source == "legacy"
    assert len(warnings) == 1


def test_tilde_expands_against_the_passed_home(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    _write_json(repo / ".claude" / "settings.local.json",
                {"autoMemoryDirectory": "~/my-memory"})

    memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert memory_dir == home / "my-memory"
    assert source == "setting:local"
    assert warnings == []


def test_bad_json_skipped_with_warning_and_next_file_still_consulted(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    local = repo / ".claude" / "settings.local.json"
    local.parent.mkdir(parents=True)
    local.write_text("{not json", encoding="utf-8")
    project_target = str(tmp_path / "project-target")
    _write_json(repo / ".claude" / "settings.json", {"autoMemoryDirectory": project_target})

    memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert source == "setting:project"
    assert memory_dir == Path(project_target)
    assert any("not valid JSON" in w for w in warnings)


def test_legacy_when_nothing_configured(tmp_path):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()

    memory_dir, source, warnings = ml.resolve_memory_dir(str(repo), home=home)
    assert source == "legacy"
    encoded = str(ml.repo_root_for(str(repo))).replace("/", "-")
    assert memory_dir == home / ".claude" / "projects" / encoded / "memory"
    assert warnings == []


def test_legacy_derivation_outside_any_git_repo(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    memory_dir, source, _warnings = ml.resolve_memory_dir(str(plain), home=home)
    assert source == "legacy"
    encoded = str(plain.resolve()).replace("/", "-")
    assert memory_dir == home / ".claude" / "projects" / encoded / "memory"


# ---------------------------------------------------------------------------
# repo_root_for: linked worktree resolves to the MAIN checkout
# ---------------------------------------------------------------------------


def test_linked_worktree_resolves_to_main_checkout_settings(tmp_path):
    main_repo = git_repo(tmp_path / "main")
    (main_repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=main_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=main_repo, check=True)
    subprocess.run(["git", "branch", "feature"], cwd=main_repo, check=True)
    worktree = tmp_path / "wt-feature"
    subprocess.run(["git", "worktree", "add", str(worktree), "feature", "-q"],
                    cwd=main_repo, check=True)

    home = tmp_path / "home"
    home.mkdir()
    target = str(tmp_path / "shared-target")
    _write_json(main_repo / ".claude" / "settings.local.json", {"autoMemoryDirectory": target})

    memory_dir, source, _warnings = ml.resolve_memory_dir(str(worktree), home=home)
    assert memory_dir == Path(target)
    assert source == "setting:local"
    assert ml.repo_root_for(str(worktree)) == ml.repo_root_for(str(main_repo))


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


def test_enable_writes_absolute_and_preserves_other_keys(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo", gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    settings = repo / ".claude" / "settings.local.json"
    _write_json(settings, {"someOtherKey": "keep-me"})

    rc = ml.main(["--repo", str(repo), "enable", "--path", "custom/mem"])
    assert rc == 0
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["someOtherKey"] == "keep-me"
    assert data["autoMemoryDirectory"] == str(repo / "custom" / "mem")
    assert settings.read_text(encoding="utf-8").endswith("\n")


def test_enable_default_path_is_work_memory(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo", gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(repo), "enable"])
    assert rc == 0
    data = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert data["autoMemoryDirectory"] == str(repo / "work" / "memory")


def test_enable_path_tilde_expands_against_home(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo", gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(repo), "enable", "--path", "~/private-memory"])
    assert rc == 0
    data = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    # must expand against home, exactly like resolve_memory_dir expands a
    # configured ~/-value, not get joined as a literal "~" path segment under
    # the repo.
    assert data["autoMemoryDirectory"] == str(home / "private-memory")


def test_enable_is_idempotent(tmp_path, monkeypatch, capsys):
    repo = git_repo(tmp_path / "repo", gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert ml.main(["--repo", str(repo), "enable"]) == 0
    settings = repo / ".claude" / "settings.local.json"
    before = settings.read_text(encoding="utf-8")

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "enable"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "unchanged" in out
    assert settings.read_text(encoding="utf-8") == before


def test_enable_dry_run_writes_nothing(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo", gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(repo), "enable", "--dry-run"])
    assert rc == 0
    assert not (repo / ".claude" / "settings.local.json").exists()


def test_enable_refuses_when_settings_file_not_gitignored(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")  # no .gitignore entry for the settings file
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(repo), "enable"])
    assert rc == 2
    assert not (repo / ".claude" / "settings.local.json").exists()


def test_enable_refuses_on_invalid_existing_json(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo", gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("[]", encoding="utf-8")  # valid JSON, but not an object

    rc = ml.main(["--repo", str(repo), "enable"])
    assert rc == 2
    assert settings.read_text(encoding="utf-8") == "[]"


def test_enable_outside_a_git_repo_is_not_blocked_by_the_ignore_check(tmp_path, monkeypatch):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(plain), "enable"])
    assert rc == 0
    assert (plain / ".claude" / "settings.local.json").is_file()


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


def _enabled_repo(tmp_path, monkeypatch, name="repo"):
    repo = git_repo(tmp_path / name, gitignore=".claude/settings.local.json\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert ml.main(["--repo", str(repo), "enable"]) == 0
    legacy = ml.legacy_memory_dir(ml.repo_root_for(str(repo)), home)
    target = repo / "work" / "memory"
    return repo, home, legacy, target


def test_migrate_copies_new_skips_identical_conflicts_on_differing(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    target.mkdir(parents=True)

    (legacy / "only_legacy.md").write_text("A", encoding="utf-8")
    (legacy / "same.md").write_text("same", encoding="utf-8")
    (target / "same.md").write_text("same", encoding="utf-8")
    (legacy / "differs.md").write_text("legacy-version", encoding="utf-8")
    (target / "differs.md").write_text("target-version", encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "migrate"])
    assert rc == 1  # a conflict remains

    assert (target / "only_legacy.md").read_text(encoding="utf-8") == "A"
    assert (target / "same.md").read_text(encoding="utf-8") == "same"
    # conflict: target left exactly as it was
    assert (target / "differs.md").read_text(encoding="utf-8") == "target-version"
    # legacy is NEVER touched
    assert (legacy / "differs.md").read_text(encoding="utf-8") == "legacy-version"
    assert (legacy / "same.md").exists()
    assert (legacy / "only_legacy.md").exists()


def test_migrate_prefer_newer_copies_the_newer_legacy_copy(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    target.mkdir(parents=True)

    (legacy / "differs.md").write_text("legacy-version", encoding="utf-8")
    (target / "differs.md").write_text("target-version", encoding="utf-8")
    import os
    import time
    now = time.time()
    os.utime(target / "differs.md", (now - 1000, now - 1000))
    os.utime(legacy / "differs.md", (now, now))

    rc = ml.main(["--repo", str(repo), "migrate", "--prefer-newer"])
    assert rc == 0
    assert (target / "differs.md").read_text(encoding="utf-8") == "legacy-version"
    # legacy still untouched
    assert (legacy / "differs.md").read_text(encoding="utf-8") == "legacy-version"


def test_migrate_conflict_older_legacy_stays_a_conflict_even_with_prefer_newer(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    target.mkdir(parents=True)
    (legacy / "differs.md").write_text("legacy-version", encoding="utf-8")
    (target / "differs.md").write_text("target-version", encoding="utf-8")
    import os
    import time
    now = time.time()
    os.utime(legacy / "differs.md", (now - 1000, now - 1000))
    os.utime(target / "differs.md", (now, now))

    rc = ml.main(["--repo", str(repo), "migrate", "--prefer-newer"])
    assert rc == 1
    assert (target / "differs.md").read_text(encoding="utf-8") == "target-version"


def test_migrate_skips_bak_names_and_directories(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "note.md.bak").write_text("backup", encoding="utf-8")
    (legacy / "subdir").mkdir()
    (legacy / "subdir" / "inner.md").write_text("nested", encoding="utf-8")
    (legacy / "real.md").write_text("real", encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "migrate"])
    assert rc == 0
    assert (target / "real.md").exists()
    assert not (target / "note.md.bak").exists()
    assert not (target / "subdir").exists()


def test_migrate_dry_run_makes_no_changes(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "fact.md").write_text("x", encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "migrate", "--dry-run"])
    assert rc == 0
    assert not target.exists() or not any(target.iterdir())
    assert (legacy / "fact.md").exists()


def test_migrate_refuses_when_nothing_configured(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(repo), "migrate"])
    assert rc == 2


def test_migrate_refuses_when_legacy_dir_missing(tmp_path, monkeypatch):
    repo, _home, legacy, _target = _enabled_repo(tmp_path, monkeypatch)
    assert not legacy.exists()

    rc = ml.main(["--repo", str(repo), "migrate"])
    assert rc == 2


# ---------------------------------------------------------------------------
# stub-legacy
# ---------------------------------------------------------------------------


def test_stub_legacy_refuses_without_yes(tmp_path, monkeypatch):
    repo, _home, legacy, _target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "stub-legacy"])
    assert rc == 2
    assert (legacy / "MEMORY.md").read_text(encoding="utf-8") == "# Memory Index\n"


def test_stub_legacy_refuses_when_source_is_legacy(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")  # never enabled: source stays "legacy"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    rc = ml.main(["--repo", str(repo), "stub-legacy", "--yes"])
    assert rc == 2


def test_stub_legacy_refuses_when_migrate_would_still_copy_or_conflict(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    (legacy / "not_yet_migrated.md").write_text("x", encoding="utf-8")
    # target dir does not even exist yet: nothing migrated

    rc = ml.main(["--repo", str(repo), "stub-legacy", "--yes"])
    assert rc == 2
    # refused before touching anything
    assert (legacy / "MEMORY.md").read_text(encoding="utf-8") == "# Memory Index\n"
    assert not (legacy / "MEMORY.md.pre-move").exists()


def test_stub_legacy_refuses_when_legacy_dir_absent(tmp_path, monkeypatch):
    repo, _home, legacy, _target = _enabled_repo(tmp_path, monkeypatch)
    assert not legacy.exists()

    rc = ml.main(["--repo", str(repo), "stub-legacy", "--yes"])
    assert rc == 2


def test_stub_legacy_success_keeps_pre_move_and_writes_stub(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    original = "# Memory Index\n\n- [A fact](fact.md) - a hook.\n"
    (legacy / "MEMORY.md").write_text(original, encoding="utf-8")
    (legacy / "fact.md").write_text("body", encoding="utf-8")

    assert ml.main(["--repo", str(repo), "migrate"]) == 0

    rc = ml.main(["--repo", str(repo), "stub-legacy", "--yes"])
    assert rc == 0

    stub = (legacy / "MEMORY.md").read_text(encoding="utf-8")
    assert stub.startswith(ml.STUB_MARKER)
    assert str(target) in stub

    pre_move = legacy / "MEMORY.md.pre-move"
    assert pre_move.is_file()
    assert pre_move.read_text(encoding="utf-8") == original

    # never modifies the migrated target
    assert (target / "MEMORY.md").read_text(encoding="utf-8") == original


def test_migrate_after_stub_legacy_never_overwrites_target_with_the_stub(tmp_path, monkeypatch):
    """Regression: stub-legacy leaves legacy/MEMORY.md holding the pointer text
    with the newest mtime of anything around (it was just written), so a later
    `migrate --prefer-newer` used to treat it like ordinary newer content and
    copy it over the target, clobbering the real, already-migrated index."""
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    original = "# Memory Index\n\n- [A fact](fact.md) - a hook.\n"
    (legacy / "MEMORY.md").write_text(original, encoding="utf-8")
    (legacy / "fact.md").write_text("body", encoding="utf-8")

    assert ml.main(["--repo", str(repo), "migrate"]) == 0
    assert ml.main(["--repo", str(repo), "stub-legacy", "--yes"]) == 0

    import os
    import time
    now = time.time()
    os.utime(legacy / "MEMORY.md", (now, now))  # the stub: newest of anything
    os.utime(target / "MEMORY.md", (now - 1000, now - 1000))

    rc = ml.main(["--repo", str(repo), "migrate", "--prefer-newer"])
    assert rc == 0
    assert (target / "MEMORY.md").read_text(encoding="utf-8") == original


def test_migrate_after_stub_legacy_does_not_copy_the_pre_move_index(tmp_path, monkeypatch):
    """stub-legacy keeps the old index as MEMORY.md.pre-move in the legacy
    directory. A later migrate must not carry that stale copy into the repo."""
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    (legacy / "fact.md").write_text("body", encoding="utf-8")

    assert ml.main(["--repo", str(repo), "migrate"]) == 0
    assert ml.main(["--repo", str(repo), "stub-legacy", "--yes"]) == 0
    assert (legacy / "MEMORY.md.pre-move").is_file()

    assert ml.main(["--repo", str(repo), "migrate"]) == 0
    assert not (target / "MEMORY.md.pre-move").exists()


def test_status_does_not_report_the_legacy_stub_as_drift(tmp_path, monkeypatch):
    """The stub is newer than the migrated index and differs from it by design;
    status must not present it as a fact a running session wrote after migrate."""
    repo, home, legacy, _target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")

    assert ml.main(["--repo", str(repo), "migrate"]) == 0
    assert ml.main(["--repo", str(repo), "stub-legacy", "--yes"]) == 0

    status = ml.build_status(str(repo), home)
    assert "MEMORY.md" not in status["newer_in_legacy"]
    assert "MEMORY.md" not in status["only_in_legacy"]


def test_stub_legacy_refuses_when_already_a_stub(tmp_path, monkeypatch):
    repo, _home, legacy, target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    assert ml.main(["--repo", str(repo), "migrate"]) == 0
    assert ml.main(["--repo", str(repo), "stub-legacy", "--yes"]) == 0

    rc = ml.main(["--repo", str(repo), "stub-legacy", "--yes"])
    assert rc == 2


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def _memory_dir_via_enable(tmp_path, monkeypatch):
    repo, _home, _legacy, target = _enabled_repo(tmp_path, monkeypatch)
    target.mkdir(parents=True)
    return repo, target


def test_check_passes_a_clean_index(tmp_path, monkeypatch):
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    (target / "fact.md").write_text("body", encoding="utf-8")
    (target / "MEMORY.md").write_text(
        "# Memory Index\n\n- [A fact](fact.md) - a short hook.\n", encoding="utf-8"
    )

    rc = ml.main(["--repo", str(repo), "check"])
    assert rc == 0


def test_check_exits_zero_when_directory_or_index_missing(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")  # never enabled, legacy dir does not exist either
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    assert ml.main(["--repo", str(repo), "check"]) == 0


def test_check_flags_too_many_lines(tmp_path, monkeypatch):
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    lines = "\n".join(f"line {i}" for i in range(ml.LOAD_LIMIT_LINES + 5))
    (target / "MEMORY.md").write_text(lines, encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "check"])
    assert rc == 1


def test_check_passes_exactly_at_the_line_limit_with_trailing_newline(tmp_path, monkeypatch):
    """Regression: every real file ends in a trailing newline, which used to
    add one phantom line via `str.split("\n")` and flag a file at exactly the
    documented 200-line limit as 201 lines, over the limit."""
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    lines = "\n".join(f"line {i}" for i in range(ml.LOAD_LIMIT_LINES)) + "\n"
    (target / "MEMORY.md").write_text(lines, encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "check"])
    assert rc == 0


def test_check_flags_too_many_bytes(tmp_path, monkeypatch):
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    (target / "MEMORY.md").write_text("a" * (ml.LOAD_LIMIT_BYTES + 100), encoding="utf-8")

    rc = ml.main(["--repo", str(repo), "check"])
    assert rc == 1


def test_check_flags_hook_over_120_chars(tmp_path, monkeypatch, capsys):
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    (target / "fact.md").write_text("body", encoding="utf-8")
    long_hook = "x" * 121
    (target / "MEMORY.md").write_text(
        f"# Memory Index\n\n- [A fact](fact.md) \u2014 {long_hook}\n", encoding="utf-8"
    )

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "check"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "120" in err


def test_check_flags_missing_linked_file(tmp_path, monkeypatch, capsys):
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    (target / "MEMORY.md").write_text(
        "# Memory Index\n\n- [Ghost](ghost.md) - never written.\n", encoding="utf-8"
    )

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "check"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "ghost.md" in err


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_json_has_the_documented_keys(tmp_path, monkeypatch, capsys):
    repo, _home, legacy, _target = _enabled_repo(tmp_path, monkeypatch)
    legacy.mkdir(parents=True)
    (legacy / "only_legacy.md").write_text("x", encoding="utf-8")

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "status", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert set(data) == {
        "memory_dir", "source", "legacy_dir", "memory_dir_exists", "legacy_exists",
        "memory_files", "legacy_files", "only_in_legacy", "newer_in_legacy",
        "index_lines", "index_bytes", "index_within_load_limit", "warnings",
    }
    assert data["source"] == "setting:local"
    assert data["only_in_legacy"] == ["only_legacy.md"]


def test_status_index_lines_matches_real_count_with_trailing_newline(tmp_path, monkeypatch):
    """Regression: `index_lines` used to be one higher than the real line
    count for any file ending in a trailing newline (virtually every real
    file), which also flipped `index_within_load_limit` to False at exactly
    the documented 200-line boundary."""
    repo, target = _memory_dir_via_enable(tmp_path, monkeypatch)
    lines = "\n".join(f"line {i}" for i in range(ml.LOAD_LIMIT_LINES)) + "\n"
    (target / "MEMORY.md").write_text(lines, encoding="utf-8")

    status = ml.build_status(str(repo))
    assert status["index_lines"] == ml.LOAD_LIMIT_LINES
    assert status["index_within_load_limit"] is True


def test_status_memory_dir_equals_legacy_dir_when_source_is_legacy(tmp_path, monkeypatch):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    status = ml.build_status(str(repo), home=home)
    assert status["source"] == "legacy"
    assert status["memory_dir"] == status["legacy_dir"]


# ---------------------------------------------------------------------------
# index / get: the harness-agnostic Phase 1 read (#209)
# ---------------------------------------------------------------------------


def _index_fixture(tmp_path, monkeypatch):
    repo, _home, _legacy, target = _enabled_repo(tmp_path, monkeypatch)
    target.mkdir(parents=True)
    (target / "feedback_use_trash.md").write_text(
        "---\nname: use-trash\ndescription: trash not rm\nmetadata:\n  type: feedback\n---\n\n"
        "Use trash, never rm.\n",
        encoding="utf-8",
    )
    (target / "MEMORY.md").write_text(
        "# Memory Index\n\n- [Use trash](feedback_use_trash.md) - deleting files\n",
        encoding="utf-8",
    )
    return repo, target


def test_index_prints_the_resolved_index_on_a_harness_without_auto_memory(
        tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDECODE", raising=False)

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "index"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[Use trash](feedback_use_trash.md)" in out


def test_index_skips_with_a_note_when_claude_code_already_loads_it(
        tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", raising=False)

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "index"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "feedback_use_trash.md" not in out
    assert "memory-location.py get <name>" in out


def test_index_prints_under_claude_code_when_auto_memory_is_disabled(
        tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    local = repo / ".claude" / "settings.local.json"
    data = json.loads(local.read_text(encoding="utf-8"))
    data["autoMemoryEnabled"] = False
    _write_json(local, data)

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "index"])
    assert rc == 0
    assert "[Use trash](feedback_use_trash.md)" in capsys.readouterr().out


def test_index_prints_nothing_and_exits_zero_without_an_index(tmp_path, monkeypatch, capsys):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDECODE", raising=False)

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "index"]) == 0
    assert capsys.readouterr().out == ""


def test_get_resolves_a_fact_by_name_slug_or_file_name(tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)

    for key in ("use-trash", "feedback_use_trash.md", "feedback_use_trash"):
        capsys.readouterr()
        assert ml.main(["--repo", str(repo), "get", key]) == 0
        assert "Use trash, never rm." in capsys.readouterr().out


def test_get_exits_one_on_an_unknown_fact(tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "get", "no-such-fact"]) == 1
    assert "no-such-fact" in capsys.readouterr().err


def test_get_refuses_a_path_outside_the_memory_directory(tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)
    (repo / "secret.md").write_text("outside", encoding="utf-8")

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "get", "../../secret.md"]) == 1
    assert "outside" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# links: session-link resolution against the harness's retention (#201)
# ---------------------------------------------------------------------------

LIVE_ID = "11111111-2222-3333-4444-555555555555"
GONE_ID = "99999999-8888-7777-6666-555555555555"


def _links_fixture(tmp_path, monkeypatch):
    repo, home, _legacy, target = _enabled_repo(tmp_path, monkeypatch)
    target.mkdir(parents=True)
    (target / "MEMORY.md").write_text("# Memory Index\n", encoding="utf-8")
    (target / "reference_live.md").write_text(
        f"---\nname: live\nmetadata:\n  type: reference\n  originSessionId: {LIVE_ID}\n---\nx\n",
        encoding="utf-8",
    )
    (target / "reference_gone.md").write_text(
        f"---\nname: gone\nmetadata:\n  type: reference\n---\nSeen in {GONE_ID}.jsonl\n",
        encoding="utf-8",
    )
    (target / "reference_plain.md").write_text(
        "---\nname: plain\nmetadata:\n  type: reference\n---\nno link\n", encoding="utf-8"
    )
    transcripts = home / ".claude" / "projects" / "-some-other-cwd"
    transcripts.mkdir(parents=True)
    (transcripts / f"{LIVE_ID}.jsonl").write_text("{}\n", encoding="utf-8")
    return repo, home, target


def test_links_counts_linked_and_unresolved_facts(tmp_path, monkeypatch, capsys):
    repo, _home, _target = _links_fixture(tmp_path, monkeypatch)

    capsys.readouterr()
    rc = ml.main(["--repo", str(repo), "links"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 of 3 memory files carry a session link, 1 of 2 unresolved" in out
    assert "reference_gone.md" in out
    assert "reference_live.md" not in out


def test_links_reports_zero_unresolved_when_every_transcript_exists(
        tmp_path, monkeypatch, capsys):
    repo, _home, target = _links_fixture(tmp_path, monkeypatch)
    (target / "reference_gone.md").unlink()

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links"]) == 0
    assert "1 of 2 memory files carry a session link, 0 of 1 unresolved" in capsys.readouterr().out


def test_links_json_carries_counts_and_the_harness_retention(tmp_path, monkeypatch, capsys):
    repo, home, _target = _links_fixture(tmp_path, monkeypatch)
    _write_json(home / ".claude" / "settings.json", {"cleanupPeriodDays": 90})

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"] == 2 + 1
    assert data["linked"] == 2
    assert data["unresolved"] == ["reference_gone.md"]
    assert data["retention_days"] == 90
    assert data["retention_source"] == "setting:user"


def test_links_defaults_retention_to_thirty_days(tmp_path, monkeypatch, capsys):
    repo, _home, _target = _links_fixture(tmp_path, monkeypatch)

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["retention_days"] == 30
    assert data["retention_source"] == "default"


def test_links_warns_when_the_declared_retention_disagrees_with_the_harness(
        tmp_path, monkeypatch, capsys):
    repo, _home, _target = _links_fixture(tmp_path, monkeypatch)
    (repo / "bridge-config.yaml").write_text(
        "work:\n  enabled: true\n  transcript_retention_days: 365\n", encoding="utf-8"
    )

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["declared_retention_days"] == 365
    assert any("365" in w and "30" in w for w in data["warnings"])


def test_links_exits_zero_without_a_memory_directory(tmp_path, monkeypatch, capsys):
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links"]) == 0
    assert "0 of 0 memory files carry a session link" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Review follow-ups: fresh clone, config dir, oversize, parsing, guards
# ---------------------------------------------------------------------------


def _fresh_clone_with_memory(tmp_path, monkeypatch):
    """No autoMemoryDirectory anywhere: the state of every fresh clone."""
    repo = git_repo(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    target = repo / "work" / "memory"
    target.mkdir(parents=True)
    (target / "reference_x.md").write_text("---\nname: x\n---\nfact x\n", encoding="utf-8")
    (target / "MEMORY.md").write_text("# Memory Index\n\n- [X](reference_x.md) - x\n",
                                      encoding="utf-8")
    return repo, home, target


def test_index_and_get_read_work_memory_on_a_fresh_clone(tmp_path, monkeypatch, capsys):
    repo, _home, _target = _fresh_clone_with_memory(tmp_path, monkeypatch)
    monkeypatch.delenv("CLAUDECODE", raising=False)

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "index"]) == 0
    assert "[X](reference_x.md)" in capsys.readouterr().out
    assert ml.main(["--repo", str(repo), "get", "x"]) == 0
    assert "fact x" in capsys.readouterr().out


def test_index_prints_work_memory_inside_claude_code_when_the_harness_reads_elsewhere(
        tmp_path, monkeypatch, capsys):
    """Without the setting Claude Code loads its legacy dir, not work/memory."""
    repo, _home, _target = _fresh_clone_with_memory(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "index"]) == 0
    assert "[X](reference_x.md)" in capsys.readouterr().out


def test_read_resolution_does_not_change_the_migration_resolver(tmp_path, monkeypatch):
    repo, home, _target = _fresh_clone_with_memory(tmp_path, monkeypatch)
    _dir, source, _w = ml.resolve_memory_dir(str(repo), home=home)
    assert source == "legacy"
    read_dir, read_source, _w = ml.resolve_read_dir(str(repo), home=home)
    assert read_source == "bridge"
    assert read_dir == repo / "work" / "memory"


def test_index_prints_an_oversized_index_even_under_claude_code(tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.delenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", raising=False)
    index = _target / "MEMORY.md"
    index.write_text(index.read_text(encoding="utf-8")
                     + "".join(f"- line {i}\n" for i in range(ml.LOAD_LIMIT_LINES)),
                     encoding="utf-8")

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "index"]) == 0
    assert "[Use trash](feedback_use_trash.md)" in capsys.readouterr().out


def test_index_prints_when_auto_memory_is_disabled_by_environment(
        tmp_path, monkeypatch, capsys):
    repo, _target = _index_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "index"]) == 0
    assert "[Use trash](feedback_use_trash.md)" in capsys.readouterr().out


def test_get_refuses_a_symlink_that_leaves_the_memory_directory(tmp_path, monkeypatch, capsys):
    repo, target = _index_fixture(tmp_path, monkeypatch)
    outside = tmp_path / "outside.md"
    outside.write_text("outside secret", encoding="utf-8")
    (target / "reference_link.md").symlink_to(outside)

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "get", "reference_link"]) == 1
    assert "outside secret" not in capsys.readouterr().out


def test_links_honours_claude_config_dir(tmp_path, monkeypatch, capsys):
    repo, home, _target = _links_fixture(tmp_path, monkeypatch)
    moved = tmp_path / "config"
    (home / ".claude").rename(moved)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(moved))
    _write_json(moved / "settings.json", {"cleanupPeriodDays": 60})

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["unresolved"] == ["reference_gone.md"]
    assert data["retention_days"] == 60


def test_links_counts_only_typed_fact_files(tmp_path, monkeypatch, capsys):
    repo, _home, target = _links_fixture(tmp_path, monkeypatch)
    (target / "README.md").write_text(f"see {GONE_ID}.jsonl\n", encoding="utf-8")
    (target / "PROVENANCE.md").write_text("notes\n", encoding="utf-8")

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"] == 3
    assert data["unresolved"] == ["reference_gone.md"]


def test_links_resolves_a_body_jsonl_link_and_a_top_level_origin_id(
        tmp_path, monkeypatch, capsys):
    repo, _home, target = _links_fixture(tmp_path, monkeypatch)
    (target / "reference_gone.md").write_text(f"body cites {LIVE_ID}.jsonl\n", encoding="utf-8")
    (target / "reference_plain.md").write_text(
        f"---\nname: plain\noriginSessionId: {LIVE_ID}\n---\nx\n", encoding="utf-8")

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["linked"] == 3
    assert data["unresolved"] == []


def test_links_reads_the_declared_retention_only_from_the_work_block(
        tmp_path, monkeypatch, capsys):
    repo, _home, _target = _links_fixture(tmp_path, monkeypatch)
    (repo / "bridge-config.yaml").write_text(
        "other:\n  transcript_retention_days: 999\n\nwork:\n  enabled: true\n"
        "  transcript_retention_days: \"30\"  # kept the harness default\n",
        encoding="utf-8",
    )

    capsys.readouterr()
    assert ml.main(["--repo", str(repo), "links", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["declared_retention_days"] == 30
    assert data["warnings"] == []

# ---------------------------------------------------------------------------
# check: coverage (docs/memory.md § Coverage)
#
# A fact file nothing reaches is invisible to every session: the index is the
# only thing the harness loads, so a fact that MEMORY.md, MEMORY-ARCHIVE.md and
# every reachable fact's `[[wikilink]]` all miss exists on disk and is never
# recalled. The pass walks links transitively from the two index files and
# names every fact it never reached.
#
#     default   warning on stderr with the count and each unreachable file,
#               exit code unchanged (0 when the index lint is clean)
#     --strict  the same list, exit 1
#
# Meta files with an all-uppercase stem that has letters (MEMORY.md,
# MEMORY-ARCHIVE.md, README.md, PROVENANCE.md) are not facts. A markdown link
# reaches its target with or without a `#section` or `"title"`. A `[[wikilink]]`
# resolves to a fact's file stem first, then its `name:` slug, with `|alias` and
# `#section` stripped, the same way on every run.
# ---------------------------------------------------------------------------


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


def test_markdown_link_with_section_or_title_still_reaches(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    _fact(memory, "feedback_b.md", "b")
    _fact(memory, "feedback_c.md", "c")
    _index(
        memory,
        "- [A](feedback_a.md#detail) - hook",
        '- [B](feedback_b.md "title") - hook',
        '- [C](./feedback_c.md#part "title") - hook',
    )

    assert ml.coverage_report(memory) == (3, [])


def test_a_stem_without_letters_is_a_fact_not_a_meta_file(tmp_path, monkeypatch):
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_a.md", "a")
    (memory / "2026-10.md").write_text("a fact named by date\n", encoding="utf-8")
    _index(memory, "- [A](feedback_a.md) - hook")

    assert ml.coverage_report(memory) == (2, ["2026-10.md"])


def test_wikilink_prefers_a_file_stem_over_another_facts_slug(tmp_path, monkeypatch):
    # feedback_b's slug equals feedback_a's stem: [[feedback_a]] must resolve to
    # the file feedback_a.md on every run, never to whichever the set yields first.
    _repo, memory = _repo_with_memory(tmp_path, monkeypatch)
    _fact(memory, "feedback_hub.md", "hub", "[[feedback_a]]")
    _fact(memory, "feedback_a.md", "a")
    _fact(memory, "feedback_b.md", "feedback_a")
    _index(memory, "- [H](feedback_hub.md) - hook")

    assert ml.coverage_report(memory) == (3, ["feedback_b.md"])
    # set order follows the string hash seed, so prove it across processes
    probe = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('ml', {str(SCRIPT)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"print(m.coverage_report(__import__('pathlib').Path({str(memory)!r}))[1])\n"
    )
    for seed in range(8):
        out = subprocess.run(
            [sys.executable, "-B", "-c", probe],
            env={"PYTHONHASHSEED": str(seed), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert out == "['feedback_b.md']", f"seed {seed}: {out}"


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
