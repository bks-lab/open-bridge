# SPDX-License-Identifier: MIT
"""Contract for scripts/check-all.py, the one local command for every checker.

The defect this pins: after an upstream merge, the checks CI runs had to be
started one by one, and the only list of them was the CI workflow. A local
replay of that workflow once ran a `git config --global` step against the
user's real ~/.gitconfig and overwrote their identity.

  · every scripts/check-*.py and scripts/validate-*.py is in the fast tier, so a
    new checker cannot be left out silently
  · a checker this tree does not have is skipped, not failed
  · the full tier finds test suites by glob: pytest per skill, a skill's own
    run-tests.sh instead of its pytest, --mutate where the runner knows it
  · a step that needs a missing tool (node, uv) is skipped, not failed
  · every step runs with an empty, temporary global git config
  · one red step makes the exit code 1, and the summary names it

Run: python3 -m pytest scripts/tests/test_check_all.py -q
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("check_all", REPO / "scripts" / "check-all.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_all"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ca():
    return _load()


def _touch(root: pathlib.Path, rel: str, text: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_every_checker_in_the_tree_is_in_the_fast_tier(ca):
    listed = {argv[0] for _, argv in ca.CHECKS}
    on_disk = {
        f"scripts/{p.name}"
        for pattern in ("check-*.py", "validate-*.py")
        for p in (REPO / "scripts").glob(pattern)
        if p.name != "check-all.py"
    }
    missing = sorted(on_disk - listed)
    assert not missing, f"checkers not in check-all.py CHECKS: {missing}"


def test_a_checker_this_tree_lacks_is_skipped(ca, tmp_path):
    _touch(tmp_path, "scripts/check-edges.py")
    names = [s.name for s in ca.plan(tmp_path, full=False, python="python3")]
    assert "check-edges.py" in names
    assert not any(n.startswith("validate-bridge.py") for n in names)


def test_full_tier_finds_suites_by_glob(ca, tmp_path):
    _touch(tmp_path, "scripts/tests/test_x.py")
    _touch(tmp_path, "scripts/tests/test-y.sh")
    _touch(tmp_path, "skills/alpha/tests/test_a.py")
    _touch(tmp_path, "skills/beta/tests/test_b.py")
    _touch(tmp_path, "skills/beta/run-tests.sh", "case $1 in --mutate) ;; esac\n")
    _touch(tmp_path, "skills/gamma/run-tests.sh", "echo plain\n")
    _touch(tmp_path, "infra/remotes/_tests/run.sh", "[ \"$1\" = --mutate ]\n")
    steps = ca.plan(tmp_path, full=True, python="python3")
    by_name = {s.name: s for s in steps}

    assert "pytest scripts/tests" in by_name
    assert "bash scripts/tests/test-y.sh" in by_name
    assert "pytest skills/alpha/tests" in by_name
    # a skill with its own runner is run by that runner, not a second time by pytest
    assert "pytest skills/beta/tests" not in by_name
    assert "bash skills/beta/run-tests.sh" in by_name
    assert "bash skills/beta/run-tests.sh --mutate" in by_name
    assert "bash skills/gamma/run-tests.sh" in by_name
    assert "bash skills/gamma/run-tests.sh --mutate" not in by_name
    assert "bash infra/remotes/_tests/run.sh --mutate" in by_name


def test_fast_tier_has_no_suites(ca, tmp_path):
    _touch(tmp_path, "scripts/tests/test_x.py")
    _touch(tmp_path, "skills/alpha/tests/test_a.py")
    names = [s.name for s in ca.plan(tmp_path, full=False, python="python3")]
    assert not any(n.startswith(("pytest", "bash", "node", "uv")) for n in names)


def test_every_step_gets_an_empty_global_git_config(ca, tmp_path):
    env = ca.isolated_env(tmp_path)
    cfg = pathlib.Path(env["GIT_CONFIG_GLOBAL"])
    assert cfg.parent == tmp_path
    assert cfg.read_text() == ""
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert pathlib.Path.home() not in cfg.parents


def _step(ca, name, code, needs=None):
    return ca.Step(name=name, argv=[sys.executable, "-c", code], needs=needs)


def test_one_red_step_fails_the_run_and_is_named(ca, tmp_path):
    out = io.StringIO()
    rc = ca.run_steps(
        [_step(ca, "green", "pass"), _step(ca, "red", "print('boom'); raise SystemExit(3)")],
        tmp_path, out=out,
    )
    text = out.getvalue()
    assert rc == 1
    assert "boom" in text
    assert "1 red" in text and "red" in text.splitlines()[-1]


def test_all_green_exits_zero(ca, tmp_path):
    out = io.StringIO()
    assert ca.run_steps([_step(ca, "a", "pass"), _step(ca, "b", "pass")], tmp_path, out=out) == 0


def test_a_step_whose_tool_is_missing_is_skipped(ca, tmp_path):
    out = io.StringIO()
    rc = ca.run_steps([_step(ca, "needs-tool", "raise SystemExit(1)", needs="no-such-tool-xyz")],
                      tmp_path, out=out)
    assert rc == 0
    assert "skip" in out.getvalue()


def test_a_step_runs_with_the_isolated_git_config(ca, tmp_path):
    out = io.StringIO()
    code = ("import os,sys; g=os.environ.get('GIT_CONFIG_GLOBAL',''); "
            "sys.exit(0 if g and not g.startswith(os.path.expanduser('~/.')) else 1)")
    assert ca.run_steps([_step(ca, "env", code)], tmp_path, out=out) == 0


def test_python3_inside_a_step_is_the_chosen_interpreter(ca, tmp_path):
    # Shell suites call bare `python3`; on a machine where that is another
    # interpreter without pytest, sixteen of them went red for no reason.
    env = ca.isolated_env(tmp_path, python=sys.executable)
    import shutil as _sh
    found = _sh.which("python3", path=env["PATH"])
    assert found and pathlib.Path(found).resolve() == pathlib.Path(sys.executable).resolve()


def test_steps_run_in_parallel(ca, tmp_path):
    import time as _t
    out = io.StringIO()
    steps = [_step(ca, f"s{i}", "import time; time.sleep(1)") for i in range(3)]
    t0 = _t.monotonic()
    assert ca.run_steps(steps, tmp_path, out=out, jobs=3) == 0
    assert _t.monotonic() - t0 < 2.5


def test_pytest_steps_use_xdist_only_when_installed(ca, tmp_path):
    _touch(tmp_path, "scripts/tests/test_x.py")
    with_x = {s.name: s for s in ca.plan(tmp_path, full=True, python="python3", xdist=True)}
    without = {s.name: s for s in ca.plan(tmp_path, full=True, python="python3", xdist=False)}
    assert "-n" in with_x["pytest scripts/tests"].argv
    assert "-n" not in without["pytest scripts/tests"].argv


def test_the_longest_steps_start_first(ca, tmp_path):
    _touch(tmp_path, "scripts/check-edges.py")
    _touch(tmp_path, "scripts/tests/test_x.py")
    _touch(tmp_path, "scripts/tests/test-overlay.sh")
    _touch(tmp_path, "scripts/tests/test-y.sh")
    names = [s.name for s in ca.order(ca.plan(tmp_path, full=True, python="python3"))]
    assert names[:2] == ["pytest scripts/tests", "bash scripts/tests/test-overlay.sh"]


def _instance(tmp_path, with_config=True):
    import subprocess as sp
    _touch(tmp_path, "scripts/no-scrub-leak.py")
    _touch(tmp_path, "scripts/categorize-commits.py",
           "def classify_file(path):\n    return 'core' if path.startswith(('docs/', 'scripts/')) else 'user'\n")
    _touch(tmp_path, "docs/guide.md", "x")
    _touch(tmp_path, "work/log.md", "x")
    if with_config:
        _touch(tmp_path, "bridge-config.yaml", "x: 1\n")
    sp.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    sp.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _leak_step(ca, root):
    return next(s for s in ca.plan(root, full=False, python="python3") if s.name.startswith("no-scrub-leak"))


def test_on_an_instance_the_leak_scan_reads_only_core_files(ca, tmp_path):
    # An instance holds its user's names and addresses on purpose. The whole-repo
    # scan read all of them: over 300 s, and every hit a false alarm. The question
    # that matters there is whether a CORE file carries one.
    step = _leak_step(ca, _instance(tmp_path))
    assert "docs/guide.md" in step.argv
    assert "work/log.md" not in step.argv
    assert "bridge-config.yaml" not in step.argv


def test_on_open_bridge_itself_the_leak_scan_reads_the_whole_repo(ca, tmp_path):
    step = _leak_step(ca, _instance(tmp_path, with_config=False))
    assert step.argv[-1].endswith("scripts/no-scrub-leak.py")
