"""scripts/migrate-docs-tier.py: the one-time correction for a fork.

A fork that kept its own docs in `docs/` with a `scope:` line meets the folder
rule on its next upstream merge: `validate-bridge.py` turns red and names this
script. The script moves each such doc into the tier folder its line declares
(`docs/user/`, `docs/org/`, `docs/personal/`) and rewrites every link that
pointed at the old path, so nothing else has to be edited by hand. A dry run is
the default; `--write` changes files; `--check` exits 1 while a move is pending.

Run: python3 -m pytest scripts/tests/test_migrate_docs_tier.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "migrate-docs-tier.py"


def _load():
    spec = importlib.util.spec_from_file_location("migrate_docs_tier", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_docs_tier"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mdt():
    return _load()


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _read(root: pathlib.Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


MINE = """---
scope: user
summary: "an instance doc"
related:
  - ../ecosystem.yaml
  - guide.md
---

# Mine

See [the guide](guide.md), [a section](guide.md#setup), the
[registry](../ecosystem.yaml), [upstream](https://example.org/docs/guide.md)
and [this page](#mine).
"""


@pytest.fixture
def fork(tmp_path):
    _write(tmp_path, "docs/mine.md", MINE)
    _write(tmp_path, "docs/guide.md", "---\nsummary: g\n---\n# Guide\n\nRead [mine](mine.md#top).\n")
    _write(tmp_path, "AGENTS.md", "# Manual\n\nThe tiers: `docs/mine.md`.\n")
    _write(tmp_path, "identity/agent/IDENTITY.md",
           "# Identity\n\nLore in [mine](../../docs/mine.md).\n")
    _write(tmp_path, "ecosystem.yaml", "docs:\n  - docs/mine.md\n")
    _write(tmp_path, "scripts/tool.py", "PATH = 'docs/mine.md'\n")
    return tmp_path


def test_the_dry_run_plans_and_changes_nothing(mdt, fork):
    plan = mdt.plan(fork)
    assert [(m.source, m.target) for m in plan.moves] == [("docs/mine.md", "docs/user/mine.md")]
    assert (fork / "docs" / "mine.md").is_file()
    assert not (fork / "docs" / "user").exists()


def test_write_moves_the_doc_and_rewrites_every_link(mdt, fork):
    mdt.apply(fork, mdt.plan(fork))
    assert not (fork / "docs" / "mine.md").exists()
    moved = _read(fork, "docs/user/mine.md")
    # Its own relative links gain one level; absolute links and anchors stay.
    assert "[the guide](../guide.md)" in moved
    assert "[a section](../guide.md#setup)" in moved
    assert "[registry](../../ecosystem.yaml)" in moved
    assert "(https://example.org/docs/guide.md)" in moved
    assert "[this page](#mine)" in moved
    # Its frontmatter `related:` list is relative to the file as well.
    assert "  - ../../ecosystem.yaml\n" in moved
    assert "  - ../guide.md\n" in moved
    # Inbound links, in each form a tree uses.
    assert "Read [mine](user/mine.md#top)." in _read(fork, "docs/guide.md")
    assert "`docs/user/mine.md`" in _read(fork, "AGENTS.md")
    assert "[mine](../../docs/user/mine.md)" in _read(fork, "identity/agent/IDENTITY.md")
    assert "- docs/user/mine.md" in _read(fork, "ecosystem.yaml")


def test_related_entries_keep_their_own_convention(mdt, tmp_path):
    # The tree writes `related:` both ways: relative to the file (`../x`) and
    # from the repo root (`docs/x.md`, `AGENTS.md`). Each stays right.
    _write(tmp_path, "AGENTS.md", "# Manual\n")
    _write(tmp_path, "docs/guide.md", "# Guide\n")
    _write(tmp_path, "docs/mine.md", (
        "---\nscope: user\ntags:\n  - CI/CD\n  - v1.2\nrelated:\n  - guide.md\n"
        "  - docs/guide.md\n  - AGENTS.md\n  - ../AGENTS.md\n  - missing/thing.md\n"
        "aliases: [a.b, c/d]\n---\n# Mine\n"))
    plan = mdt.plan(tmp_path)
    mdt.apply(tmp_path, plan)
    moved = _read(tmp_path, "docs/user/mine.md")
    assert "  - ../guide.md\n" in moved          # file-relative, re-based
    assert "  - docs/guide.md\n" in moved        # repo-relative, unchanged
    assert "  - AGENTS.md\n" in moved            # repo-relative, unchanged
    assert "  - ../../AGENTS.md\n" in moved      # file-relative, re-based
    assert "  - missing/thing.md\n" in moved     # resolves nowhere: left alone ...
    assert "missing/thing.md" in " ".join(plan.unresolved)   # ... and reported
    assert "  - CI/CD\n  - v1.2\n" in moved      # not under related: untouched
    assert "aliases: [a.b, c/d]" in moved


def test_a_flow_style_related_list_is_rewritten_too(mdt, tmp_path):
    _write(tmp_path, "docs/guide.md", "# Guide\n")
    _write(tmp_path, "docs/mine.md", "---\nscope: user\nrelated: [guide.md, docs/guide.md]\n---\n")
    mdt.apply(tmp_path, mdt.plan(tmp_path))
    assert "related: [../guide.md, docs/guide.md]" in _read(tmp_path, "docs/user/mine.md")


def test_a_link_to_itself_and_other_link_forms_follow_the_move(mdt, tmp_path):
    _write(tmp_path, "docs/guide.md", "# Guide\n")
    _write(tmp_path, "docs/mine.md", (
        "---\nscope: user\n---\n# Mine\n\n[top](mine.md#mine), [titled](guide.md \"Guide\"),\n"
        "[ref][g]\n\n[g]: guide.md\n"))
    _write(tmp_path, "README.md", "See [mine](/docs/mine.md) and [again](docs/mine.md).\n")
    mdt.apply(tmp_path, mdt.plan(tmp_path))
    moved = _read(tmp_path, "docs/user/mine.md")
    assert "[top](mine.md#mine)" in moved
    assert '[titled](../guide.md "Guide")' in moved
    assert "[g]: ../guide.md" in moved
    readme = _read(tmp_path, "README.md")
    assert "(/docs/user/mine.md)" in readme and "(docs/user/mine.md)" in readme


def test_footnotes_fenced_lines_and_non_paths_are_left_alone(mdt, tmp_path):
    _write(tmp_path, "docs/guide.md", "# Guide\n")
    body = ("---\nscope: user\nrelated:\n  - mine.md\n  - docs/mine.md\n---\n# Mine\n\n"
            "[^1]: See the 2026 audit.\n[TODO]: check this\n[g]: guide.md\n\n"
            "```markdown\n[x](guide.md)\n[g]: guide.md\n```\n")
    _write(tmp_path, "docs/mine.md", body)
    plan = mdt.plan(tmp_path)
    mdt.apply(tmp_path, plan)
    moved = _read(tmp_path, "docs/user/mine.md")
    assert "[^1]: See the 2026 audit." in moved
    assert "[TODO]: check this" in moved
    assert "[g]: ../guide.md\n\n" in moved                       # a real definition moves
    assert "```markdown\n[x](guide.md)\n[g]: guide.md\n```" in moved  # a fenced example does not
    # A related entry that names the doc itself follows it, in its own convention.
    assert "  - mine.md\n" in moved and "  - docs/user/mine.md\n" in moved
    assert plan.unresolved == []


def test_the_dry_run_already_reports_unresolved_related_entries(mdt, tmp_path):
    _write(tmp_path, "docs/mine.md", "---\nscope: user\nrelated:\n  - missing/thing.md\n---\n")
    plan = mdt.plan(tmp_path)
    assert any("missing/thing.md" in n for n in plan.unresolved)
    assert (tmp_path / "docs" / "mine.md").is_file()


def test_records_of_the_past_are_left_as_written(mdt, fork):
    # The work log, closed tasks and archives say what was true when they were
    # written. Rewriting a path in them would make an old row claim something
    # that never happened.
    _write(fork, "work/log.md", "| 2026-11-04 10:00 | x | docs | read `docs/mine.md` |\n")
    _write(fork, "work/done/2026-10/task/STATUS.md", "See [mine](../../../../docs/mine.md).\n")
    _write(fork, "work/archive/2026-10.md", "Moved `docs/mine.md`.\n")
    _write(fork, "work/memory/fact.md", "Lore: `docs/mine.md`.\n")
    plan = mdt.plan(fork)
    mdt.apply(fork, plan)
    assert "`docs/mine.md`" in _read(fork, "work/log.md")
    assert "../../../../docs/mine.md" in _read(fork, "work/done/2026-10/task/STATUS.md")
    assert "`docs/mine.md`" in _read(fork, "work/archive/2026-10.md")
    assert set(plan.history_left) == {"work/log.md", "work/done/2026-10/task/STATUS.md",
                                      "work/archive/2026-10.md"}
    # Live knowledge is not history: it follows the move.
    assert "`docs/user/mine.md`" in _read(fork, "work/memory/fact.md")


def test_a_path_that_ends_a_sentence_is_rewritten(mdt, fork):
    # Found by a fresh session on a real fork: a registry description ended in
    # "Detail: docs/mine.md." and the full stop hid the path from the rewrite.
    _write(fork, "ecosystem.yaml", 'repo:\n  description: "Hub. Detail: docs/mine.md."\n'
                                   "  # Background: docs/mine.md.\n  other: docs/mine.md.bak\n")
    mdt.apply(fork, mdt.plan(fork))
    text = _read(fork, "ecosystem.yaml")
    assert 'Detail: docs/user/mine.md."' in text
    assert "# Background: docs/user/mine.md.\n" in text
    assert "other: docs/mine.md.bak" in text   # another file, not the moved one


def test_code_is_never_rewritten_only_named(mdt, fork):
    plan = mdt.plan(fork)
    mdt.apply(fork, plan)
    assert _read(fork, "scripts/tool.py") == "PATH = 'docs/mine.md'\n"
    assert "scripts/tool.py" in plan.mentions_left


def test_an_org_doc_moves_to_docs_org(mdt, tmp_path):
    _write(tmp_path, "docs/shared.md", "---\nscope: org\n---\n# Shared\n")
    plan = mdt.plan(tmp_path)
    assert [(m.source, m.target) for m in plan.moves] == [("docs/shared.md", "docs/org/shared.md")]


def test_the_legacy_user_doc_moves_without_a_scope_line(mdt, tmp_path):
    _write(tmp_path, "docs/applications.md", "# Applications\n")
    plan = mdt.plan(tmp_path)
    assert [(m.source, m.target) for m in plan.moves] == [
        ("docs/applications.md", "docs/user/applications.md")]


def test_an_unknown_scope_is_reported_and_never_moved(mdt, tmp_path):
    _write(tmp_path, "docs/odd.md", "---\nscope: usr\n---\n# Odd\n")
    plan = mdt.plan(tmp_path)
    assert plan.moves == []
    assert [rel for rel, _ in plan.unplaceable] == ["docs/odd.md"]
    mdt.apply(tmp_path, plan)
    assert (tmp_path / "docs" / "odd.md").is_file()


def test_a_taken_target_is_refused(mdt, fork):
    _write(fork, "docs/user/mine.md", "# Already here\n")
    plan = mdt.plan(fork)
    assert plan.moves == []
    assert [rel for rel, _ in plan.unplaceable] == ["docs/mine.md"]


def test_core_and_already_placed_docs_are_left_alone(mdt, tmp_path):
    _write(tmp_path, "docs/guide.md", "---\nscope: core\n---\n# Guide\n")
    _write(tmp_path, "docs/plain.md", "# Plain\n")
    _write(tmp_path, "docs/user/mine.md", "---\nscope: user\n---\n# Mine\n")
    plan = mdt.plan(tmp_path)
    assert plan.moves == [] and plan.unplaceable == []


def test_a_second_write_changes_nothing(mdt, fork):
    mdt.apply(fork, mdt.plan(fork))
    before = {p: p.read_bytes() for p in fork.rglob("*") if p.is_file()}
    second = mdt.plan(fork)
    assert second.moves == []
    mdt.apply(fork, second)
    assert {p: p.read_bytes() for p in fork.rglob("*") if p.is_file()} == before


def test_in_a_git_tree_the_move_is_a_git_mv(mdt, fork):
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q"], cwd=fork, check=True)
    subprocess.run([*git, "add", "-A"], cwd=fork, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], cwd=fork, check=True)
    mdt.apply(fork, mdt.plan(fork))
    status = subprocess.run(["git", "status", "--porcelain"], cwd=fork,
                            capture_output=True, text=True, check=True).stdout
    # Staged as a move: git shows R when the content stayed similar enough, and
    # D plus A for a small file whose links all changed. Both are in the index.
    assert ("R  docs/mine.md -> docs/user/mine.md" in status
            or ("D  docs/mine.md" in status and "A  docs/user/mine.md" in status)), status


def _cli(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(cwd), *args],
                          capture_output=True, text=True)


def test_the_cli_dry_run_then_write_then_check(fork):
    dry = _cli(cwd=fork)
    assert dry.returncode == 0, dry.stderr
    assert "docs/mine.md -> docs/user/mine.md" in dry.stdout
    assert (fork / "docs" / "mine.md").is_file()
    assert _cli("--check", cwd=fork).returncode == 1
    done = _cli("--write", cwd=fork)
    assert done.returncode == 0, done.stderr
    assert (fork / "docs" / "user" / "mine.md").is_file()
    assert _cli("--check", cwd=fork).returncode == 0


def test_check_is_red_for_an_unplaceable_doc_too(tmp_path):
    _write(tmp_path, "docs/odd.md", "---\nscope: usr\n---\n# Odd\n")
    assert _cli("--check", cwd=tmp_path).returncode == 1
