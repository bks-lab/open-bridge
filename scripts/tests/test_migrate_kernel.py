"""scripts/migrate-kernel.py: remove the keys kernel/manifest.yaml retires, once.

A retired key is a declaration nothing reads any more but a session still
carries: `work_system` in ecosystem.yaml named where the work log and the board
live, no script read it, and the registry card showed it to every session. The
manifest lists such keys under `retired:`, check-kernel.py names each one that is
still there, and this script removes them: dry run first, `--write` to change
the file, `--check` exits 1 while one is left.

Run: python3 -m pytest scripts/tests/test_migrate_kernel.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "migrate-kernel.py"


def _load():
    spec = importlib.util.spec_from_file_location("migrate_kernel", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_kernel"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mk():
    return _load()


MANIFEST = """schema_version: 1
entries: []
retired:
  - file: "ecosystem*.yaml"
    key: work_system
    reason: nothing reads it
    fix: python3 scripts/migrate-kernel.py --write
moved:
  - old: docs/families.md
    new: kernel/families.yaml
"""

REGISTRY = """# My registry.

org: acme
local_root: ~/code          # clones live here

# Work-system tracking. When enabled, AGENTS.md session-start + logging rules apply.
work_system:
  enabled: true
  path: work/
  files:
    current: work/log.md   # the log
    board: work/board.md

# ---------------------------------------------------------------------------
# base: repos every team member needs
# ---------------------------------------------------------------------------
base:
  one:
    description: "a repo"   # work_system: not this one
"""


@pytest.fixture
def fork(tmp_path):
    (tmp_path / "kernel").mkdir()
    (tmp_path / "kernel" / "manifest.yaml").write_text(MANIFEST, encoding="utf-8")
    (tmp_path / "ecosystem.yaml").write_text(REGISTRY, encoding="utf-8")
    return tmp_path


def test_the_dry_run_names_the_key_and_changes_nothing(mk, fork):
    plan = mk.plan(fork)
    assert [(r.file, r.key) for r in plan] == [("ecosystem.yaml", "work_system")]
    assert (fork / "ecosystem.yaml").read_text(encoding="utf-8") == REGISTRY


def test_write_removes_the_block_and_its_own_comment_and_nothing_else(mk, fork):
    mk.apply(fork, mk.plan(fork))
    text = (fork / "ecosystem.yaml").read_text(encoding="utf-8")
    assert "work_system:\n" not in text and "Work-system tracking" not in text
    assert "current: work/log.md" not in text
    # Everything around it stays, byte for byte, including other comments.
    assert text.startswith("# My registry.\n\norg: acme\nlocal_root: ~/code          # clones live here\n")
    assert "# base: repos every team member needs\n" in text
    assert 'description: "a repo"   # work_system: not this one' in text
    assert "\n\n\n" not in text


def test_a_second_write_changes_nothing(mk, fork):
    mk.apply(fork, mk.plan(fork))
    once = (fork / "ecosystem.yaml").read_bytes()
    assert mk.plan(fork) == []
    mk.apply(fork, mk.plan(fork))
    assert (fork / "ecosystem.yaml").read_bytes() == once


def test_a_missing_file_or_a_nested_key_is_not_a_hit(mk, fork):
    (fork / "ecosystem.yaml").write_text("org: x\nbase:\n  work_system: 1\n", encoding="utf-8")
    assert mk.plan(fork) == []
    (fork / "ecosystem.yaml").unlink()
    assert mk.plan(fork) == []


def test_the_result_is_still_yaml_with_the_same_other_keys(mk, fork):
    yaml = pytest.importorskip("yaml")
    before = yaml.safe_load(REGISTRY)
    mk.apply(fork, mk.plan(fork))
    after = yaml.safe_load((fork / "ecosystem.yaml").read_text(encoding="utf-8"))
    before.pop("work_system")
    assert after == before


def test_every_registry_the_glob_names_loses_the_key_but_the_template_stays(mk, fork):
    (fork / "ecosystem.acme.yaml").write_text("acme:\n  x: 1\nwork_system:\n  enabled: true\n", encoding="utf-8")
    (fork / "ecosystem.example.yaml").write_text("org: your-org\nwork_system:\n  enabled: true\n", encoding="utf-8")
    assert sorted(r.file for r in mk.plan(fork)) == ["ecosystem.acme.yaml", "ecosystem.yaml"]
    mk.apply(fork, mk.plan(fork))
    assert "work_system" not in (fork / "ecosystem.acme.yaml").read_text(encoding="utf-8")
    # The CORE template is upstream's file: a fork's migration never edits it.
    assert "work_system" in (fork / "ecosystem.example.yaml").read_text(encoding="utf-8")


USER_BUDGET = """schema_version: 1
items:
  ecosystem.yaml:
    source: phase1
    card:
      kind: index
      keep: [org, local_root, work_system]
  ecosystem.acme.yaml:
    card:
      keep:
        - acme
        - work_system
  work/board.md:
    source: phase1
"""


def test_the_instances_own_card_stops_keeping_the_retired_key(mk, fork):
    # Found by a fresh session on a real fork: its context-budget.user.yaml kept
    # work_system on the registry card, so context-index.py --check went red the
    # moment the key left ecosystem.yaml.
    (fork / "context-budget.user.yaml").write_text(USER_BUDGET, encoding="utf-8")
    (fork / "ecosystem.acme.yaml").write_text("acme:\n  x: 1\n", encoding="utf-8")
    plan = mk.plan(fork)
    assert "context-budget.user.yaml" in {r.file for r in plan}
    mk.apply(fork, plan)
    text = (fork / "context-budget.user.yaml").read_text(encoding="utf-8")
    assert "keep: [org, local_root]" in text
    assert "        - acme\n  work/board.md:" in text
    assert "work_system" not in text
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(text)["items"]["ecosystem.acme.yaml"]["card"]["keep"] == ["acme"]
    assert mk.plan(fork) == []


def _instance_files(root):
    (root / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    agent = root / "identity" / "agent"
    agent.mkdir(parents=True)
    (agent / "INSTANCE.md").write_text(
        "# Instance\n\nFamilies: `docs/families.md`, see [index](../../docs/families.md).\n",
        encoding="utf-8")
    (root / "work").mkdir()
    (root / "work" / "log.md").write_text("| 10:00 | read docs/families.md |\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("Old: `docs/families.md`.\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "own.py").write_text("P = 'docs/families.md'\n", encoding="utf-8")


def test_a_moved_kernel_file_is_followed_in_the_instances_own_files_only(mk, fork):
    _instance_files(fork)
    plan = mk.plan_moves(fork)
    assert plan.files == ["identity/agent/INSTANCE.md"], plan
    mk.apply_moves(fork, plan)
    text = (fork / "identity" / "agent" / "INSTANCE.md").read_text(encoding="utf-8")
    assert "`kernel/families.yaml`" in text and "(../../kernel/families.yaml)" in text
    # A record of the past, a CORE file (upstream brings its own) and code stay.
    assert "docs/families.md" in (fork / "work" / "log.md").read_text(encoding="utf-8")
    assert "docs/families.md" in (fork / "docs" / "guide.md").read_text(encoding="utf-8")
    assert "docs/families.md" in (fork / "scripts" / "own.py").read_text(encoding="utf-8")
    assert mk.plan_moves(fork).files == []


def test_check_is_red_while_an_own_file_names_a_moved_path(fork):
    _instance_files(fork)
    (fork / "ecosystem.yaml").unlink()
    assert _cli("--check", cwd=fork).returncode == 1
    assert _cli("--write", cwd=fork).returncode == 0
    assert _cli("--check", cwd=fork).returncode == 0


def _git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org",
                    "-c", "commit.gpgsign=false", *args], cwd=root, check=True, capture_output=True)


def test_check_kernel_is_green_after_the_migration_on_the_same_git_tree(mk, fork):
    """One file list and one matcher for the check and the fix: what check-kernel
    flags, migrate-kernel fixes, and an ignored folder flags nothing."""
    _instance_files(fork)
    (fork / ".gitignore").write_text(".claude/worktrees/\n", encoding="utf-8")
    stale = fork / ".claude" / "worktrees" / "old" / "rules"
    stale.mkdir(parents=True)
    (stale / "x.md").write_text("Index: `docs/families.md`.\n", encoding="utf-8")
    _git(fork, "init", "-q"); _git(fork, "add", "-A"); _git(fork, "commit", "-qm", "seed")
    ck = importlib.util.spec_from_file_location("check_kernel_for_mk", REPO / "scripts" / "check-kernel.py")
    ckm = importlib.util.module_from_spec(ck); sys.modules["check_kernel_for_mk"] = ckm; ck.loader.exec_module(ckm)
    hits = [rel for rel, _ in ckm._own_files_naming_moved(fork)]
    assert hits == ["identity/agent/INSTANCE.md"], hits
    mk.apply_moves(fork, mk.plan_moves(fork))
    assert ckm._own_files_naming_moved(fork) == []


def test_a_line_that_already_describes_the_move_is_left_alone(mk, fork):
    _instance_files(fork)
    note = fork / "work" / "memory" / "fact.md"
    note.parent.mkdir(parents=True)
    note.write_text("Step 2 moves `docs/families.md` to `kernel/families.yaml`.\n"
                    "The index: [index](../../docs/families.md).\n", encoding="utf-8")
    mk.apply_moves(fork, mk.plan_moves(fork))
    text = note.read_text(encoding="utf-8")
    assert "Step 2 moves `docs/families.md` to `kernel/families.yaml`." in text
    assert "[index](../../kernel/families.yaml)" in text


def test_deliverables_and_the_inbox_are_records_too(mk, fork):
    _instance_files(fork)
    for rel in ("work/tasks/t/deliverables/report.md", "work/streams/s/deliverables/r.md",
                "work/inbox/20261105-x/item.yaml"):
        path = fork / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("evidence: docs/families.md\n", encoding="utf-8")
    mk.apply_moves(fork, mk.plan_moves(fork))
    for rel in ("work/tasks/t/deliverables/report.md", "work/streams/s/deliverables/r.md",
                "work/inbox/20261105-x/item.yaml"):
        assert "docs/families.md" in (fork / rel).read_text(encoding="utf-8"), rel


def test_crlf_line_endings_survive_both_edits(mk, fork):
    crlf = REGISTRY.replace("\n", "\r\n").encode("utf-8")
    (fork / "ecosystem.yaml").write_bytes(crlf)
    mk.apply(fork, mk.plan(fork))
    out = (fork / "ecosystem.yaml").read_bytes()
    assert b"work_system:\r\n" not in out and b"current: work/log.md" not in out
    assert out.count(b"\r\n") == out.count(b"\n"), "every line keeps its CRLF"


def test_a_schema_header_is_not_taken_for_the_keys_comment(mk, fork):
    (fork / "ecosystem.yaml").write_text(
        "# yaml-language-server: $schema=./x.json\nwork_system:\n  enabled: true\norg: x\n", encoding="utf-8")
    mk.apply(fork, mk.plan(fork))
    assert (fork / "ecosystem.yaml").read_text(encoding="utf-8") == "# yaml-language-server: $schema=./x.json\norg: x\n"


def test_a_result_that_would_lose_other_keys_is_refused(mk, fork):
    # A column-0 comment inside the block would end it early and strand the rest.
    odd = "org: x\nwork_system:\n  enabled: true\n# note\n  path: work/\nbase: {}\n"
    (fork / "ecosystem.yaml").write_text(odd, encoding="utf-8")
    plan = mk.plan(fork)
    changed = mk.apply(fork, plan)
    assert changed == [] and (fork / "ecosystem.yaml").read_text(encoding="utf-8") == odd
    assert any("ecosystem.yaml" in r for r in mk.REFUSED)


def test_the_manifest_reader_takes_column_zero_lists_too(mk, tmp_path):
    (tmp_path / "kernel").mkdir()
    (tmp_path / "kernel" / "manifest.yaml").write_text(
        "retired:\n- file: ecosystem.yaml  # the base\n  key: work_system\n  reason: r\n  fix: f\n"
        "moved:\n- old: a.md\n  new: b.md\n", encoding="utf-8")
    (tmp_path / "ecosystem.yaml").write_text("work_system:\n  enabled: true\n", encoding="utf-8")
    assert [(r.file, r.key) for r in mk.plan(tmp_path)] == [("ecosystem.yaml", "work_system")]


def _cli(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(cwd), *args],
                          capture_output=True, text=True)


def test_the_cli_dry_run_then_write_then_check(fork):
    dry = _cli(cwd=fork)
    assert dry.returncode == 0 and "ecosystem.yaml: work_system" in dry.stdout, dry.stdout + dry.stderr
    assert _cli("--check", cwd=fork).returncode == 1
    assert _cli("--write", cwd=fork).returncode == 0
    assert _cli("--check", cwd=fork).returncode == 0


def test_the_live_manifest_retires_work_system_and_core_no_longer_ships_it():
    yaml = pytest.importorskip("yaml")
    manifest = yaml.safe_load((REPO / "kernel" / "manifest.yaml").read_text(encoding="utf-8"))
    retired = {(r["file"], r["key"]) for r in manifest.get("retired") or []}
    assert ("ecosystem*.yaml", "work_system") in retired
    moved = {(m["old"], m["new"]) for m in manifest.get("moved") or []}
    assert ("docs/families.md", "kernel/families.yaml") in moved
    for shipped in ("ecosystem.example.yaml", "examples/agency/ecosystem.yaml",
                    "examples/portfolio/ecosystem.yaml"):
        assert "work_system" not in (yaml.safe_load((REPO / shipped).read_text(encoding="utf-8")) or {}), shipped
