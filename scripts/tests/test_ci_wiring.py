"""Every test file in the tree is run by some CI job.

A suite that no workflow runs reports nothing, and nothing looks like a pass.
Measured the day this was written: several hundred tests, a whole skill's
suite among them, were green on a laptop and ran in no job at all.

The check reads `.github/workflows/*.yml` and follows what the `run:` steps
invoke, one script into the next, collecting every test path, test glob and
test directory a pytest or unittest line names. A `test_*.py` none of them
reaches is reported by path. It is deliberately a reading of the text and not
a dry run of the jobs, so it needs no runner, no dependency and no network,
and it errs on the side of reporting: a file it cannot prove is reached counts
as unreached.

Two layers, as elsewhere in this directory. The live test walks the real tree.
The fixture tests build small fake repos, one per way a suite is actually
wired here, and assert the reading finds it, so a green live run is not the
only evidence the reader works.
"""

from __future__ import annotations

import glob
import os
import re
import textwrap
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

# A line that runs tests. Only on such a line does a bare directory count as
# "the tests under here", so `cd skills` cannot claim a whole tree.
RUNNER = re.compile(r"\b(pytest|unittest|discover)\b")
# Shell prefixes that stand for "the directory this script lives in".
PREFIX = re.compile(r"\$\{?\w+\}?/|\$\([^)]*\)+[\"']?/")
# Installing pytest is not running it: `pip install pytest` and
# `uv run --with pytest` name the word and run nothing.
INSTALL = re.compile(r"\b(pip3?|pipx|uv pip)\s+install\b[^;&|]*|--with\s+\S+")
TOKEN = re.compile(r"[A-Za-z0-9_.*\-][A-Za-z0-9_./*\-]*")


def _follow(rel: str) -> bool:
    """A script worth reading for the tests it runs.

    Every shell script, since wrappers are how most suites here are entered.
    A Python file only when it lives in a tests directory (a runner or a
    mutation driver): the tools a step validates mention paths for their own
    reasons, and reading them would count those as test runs.
    """
    if rel.endswith(".sh"):
        return True
    return rel.endswith(".py") and "tests" in Path(rel).parts[:-1]


def _is_test(path: str) -> bool:
    return re.fullmatch(r"test_[^/]*\.py", os.path.basename(path)) is not None


def _test_files(repo: Path) -> set[str]:
    out = set()
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in {"node_modules", "__pycache__"}]
        for name in files:
            if _is_test(name):
                out.add((Path(root) / name).relative_to(repo).as_posix())
    return out


def _logical_lines(text: str, shell: bool) -> list[str]:
    text = re.sub(r"\\\n", " ", text)
    lines = []
    for line in text.splitlines():
        if shell and line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return lines


def _testpaths(repo: Path, wd: Path) -> list[Path]:
    pp = repo / wd / "pyproject.toml"
    if pp.is_file():
        try:
            data = tomllib.loads(pp.read_text())
        except (tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        paths = data.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("testpaths")
        if paths:
            return [wd / p for p in paths]
    return [wd]


def _bases(repo: Path, wd: Path, here: Path | None) -> list[Path]:
    """Directories a relative token may be relative to, as repo-relative paths."""
    bases = [Path("."), wd]
    if here is not None:
        cur = here
        while True:
            bases.append(cur)
            if cur == Path("."):
                break
            cur = cur.parent
    seen, out = set(), []
    for b in bases:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def _scan(repo: Path, text: str, wd: Path, here: Path | None, shell: bool,
          covered_files: set[str], covered_dirs: set[str], visited: set[str]) -> None:
    for line in _logical_lines(text, shell):
        line = INSTALL.sub(" ", line)
        runs_tests = RUNNER.search(line) is not None
        # In Python only a line that runs tests counts: the rest is prose and
        # variable names, and a docstring that names a path runs nothing.
        if not shell and not runs_tests:
            continue
        named = False
        for raw in TOKEN.findall(PREFIX.sub("", line)):
            tok = raw.strip("./") if raw.startswith("./") else raw.lstrip("/")
            if not tok or tok in {".", ".."}:
                continue
            for base in _bases(repo, wd, here):
                cand = (base / tok).as_posix()
                # A glob counts when it is a test glob: a bare `*` in a case
                # pattern would otherwise claim the directory it sits in.
                if "*" in cand:
                    if not (tok.endswith(".py") or runs_tests) or not tok.replace("*", "").strip("/"):
                        continue
                    for hit in glob.glob(str(repo / cand)):
                        rel = Path(hit).relative_to(repo).as_posix()
                        if _is_test(rel):
                            covered_files.add(rel)
                            named = True
                    continue
                path = repo / cand
                if path.is_file():
                    rel = path.relative_to(repo).as_posix()
                    if _is_test(rel):
                        covered_files.add(rel)
                        named = True
                    elif _follow(rel) and rel not in visited:
                        visited.add(rel)
                        child = Path(rel)
                        _scan(repo, path.read_text(errors="replace"), wd, child.parent,
                              rel.endswith(".sh"), covered_files, covered_dirs, visited)
                    break
                # Every base that holds such a directory counts: a runner that
                # cds first is read from all the places it might have gone.
                if (path.is_dir() and runs_tests and cand not in {".", ""}
                        and any("test" in part for part in Path(cand).parts)):
                    covered_dirs.add(Path(cand).as_posix())
                    named = True
        if runs_tests and not named and re.search(r"(^|\s)(python3? -m )?pytest(\s*$|\s+-)", line):
            for p in _testpaths(repo, wd):
                covered_dirs.add(p.as_posix())


def wiring(repo: Path) -> tuple[set[str], set[str]]:
    """Return (test files every CI job reaches, test files none reaches)."""
    covered_files: set[str] = set()
    covered_dirs: set[str] = set()
    visited: set[str] = set()
    for wf in sorted((repo / ".github" / "workflows").glob("*.y*ml")):
        doc = yaml.safe_load(wf.read_text()) or {}
        for job in (doc.get("jobs") or {}).values():
            job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory", ".")
            for step in job.get("steps") or []:
                run = step.get("run")
                if not run:
                    continue
                wd = Path(step.get("working-directory", job_wd))
                _scan(repo, run, wd, None, True, covered_files, covered_dirs, visited)
    tests = _test_files(repo)
    reached = set()
    for t in tests:
        if t in covered_files or any(
                d in {".", ""} or t.startswith(d.rstrip("/") + "/") for d in covered_dirs):
            reached.add(t)
    return reached, tests - reached


# ---------------------------------------------------------------- live tree


def test_every_test_file_is_run_by_a_ci_job():
    _, unreached = wiring(REPO)
    assert not unreached, (
        "These test files are run by no CI job. Wire each into a job in "
        ".github/workflows/ (a path, a glob or its directory on a pytest line):\n  "
        + "\n  ".join(sorted(unreached)))


# ---------------------------------------------------------------- fixtures


def _repo(tmp_path: Path, workflow: str, files: dict[str, str]) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(textwrap.dedent(workflow))
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return tmp_path


def test_an_explicit_path_is_reached_and_its_neighbour_is_not(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: python3 -m pytest scripts/tests/test_one.py -q
        """, {"scripts/tests/test_one.py": "", "scripts/tests/test_two.py": ""})
    reached, unreached = wiring(repo)
    assert reached == {"scripts/tests/test_one.py"}
    assert unreached == {"scripts/tests/test_two.py"}


def test_a_directory_on_a_pytest_line_reaches_everything_under_it(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: python3 -m pytest -q skills/x/tests
        """, {"skills/x/tests/test_a.py": "", "skills/x/tests/sub/test_b.py": "",
              "skills/y/tests/test_c.py": ""})
    _, unreached = wiring(repo)
    assert unreached == {"skills/y/tests/test_c.py"}


def test_a_directory_on_a_line_that_runs_no_tests_reaches_nothing(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: cd skills && ls skills/x/tests
        """, {"skills/x/tests/test_a.py": ""})
    _, unreached = wiring(repo)
    assert unreached == {"skills/x/tests/test_a.py"}


def test_a_glob_reaches_what_it_matches(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: python3 -m pytest scripts/tests/test_cockpit*.py
        """, {"scripts/tests/test_cockpit_a.py": "", "scripts/tests/test_cockpit_b.py": "",
              "scripts/tests/test_other.py": ""})
    _, unreached = wiring(repo)
    assert unreached == {"scripts/tests/test_other.py"}


def test_a_folded_multi_line_run_is_read_whole(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: >-
                  python3 -m pytest -q
                  scripts/tests/test_one.py
                  scripts/tests/test_two.py
        """, {"scripts/tests/test_one.py": "", "scripts/tests/test_two.py": ""})
    _, unreached = wiring(repo)
    assert unreached == set()


def test_a_wrapper_script_is_followed_with_continuation_lines(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: bash scripts/tests/test-suite.sh
        """, {
            "scripts/tests/test-suite.sh": """\
                #!/bin/bash
                # test_ignored.py in a comment proves nothing
                cd "$(dirname "$0")/../.."
                exec python3 -m pytest -q scripts/tests/test_one.py \\
                    scripts/tests/test_two.py
                """,
            "scripts/tests/test_one.py": "", "scripts/tests/test_two.py": "",
            "scripts/tests/test_ignored.py": ""})
    _, unreached = wiring(repo)
    assert unreached == {"scripts/tests/test_ignored.py"}


def test_a_skill_runner_chain_with_unittest_discover_is_followed(tmp_path):
    # skills/<s>/run-tests.sh -> scripts/tests/run.sh -> runner.py -> discover("tests")
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - run: bash skills/s/run-tests.sh
        """, {
            "skills/s/run-tests.sh": 'exec "$(cd "$(dirname "$0")" && pwd)/scripts/tests/run.sh" "$@"\n',
            "skills/s/scripts/tests/run.sh": 'DIR="$(cd "$(dirname "$0")" && pwd)"\npython3 "$DIR/runner.py"\n',
            "skills/s/scripts/tests/runner.py": 'suite = loader.discover("tests", top_level_dir=".")\n',
            "skills/s/tests/test_a.py": "", "skills/t/tests/test_b.py": ""})
    _, unreached = wiring(repo)
    assert unreached == {"skills/t/tests/test_b.py"}


def test_bare_pytest_in_a_working_directory_honours_its_testpaths(tmp_path):
    repo = _repo(tmp_path, """
        jobs:
          a:
            steps:
              - working-directory: agents
                run: uv run --with pytest pytest
        """, {
            "agents/pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            "agents/tests/test_a.py": "", "agents/_gateway/tests/test_b.py": ""})
    _, unreached = wiring(repo)
    assert unreached == {"agents/_gateway/tests/test_b.py"}


# ---------------------------------------------------------------- the gate


def _workflow(name: str) -> dict:
    return yaml.safe_load((REPO / ".github" / "workflows" / name).read_text())


def test_all_green_waits_for_every_validate_job():
    """`all-green` is the one check branch protection needs to require.

    That only holds while it depends on every other job. A job added later and
    left out of `needs:` would be a check that can be red on a mergeable PR.
    """
    jobs = _workflow("validate.yml")["jobs"]
    assert "all-green" in jobs, "validate.yml needs an all-green collector job"
    gate = jobs["all-green"]
    needs = gate.get("needs") or []
    assert set(needs) == set(jobs) - {"all-green"}, (
        "all-green must need every other job; missing: "
        + ", ".join(sorted(set(jobs) - {"all-green"} - set(needs))))
    # A needed job that fails skips its dependants, and a skipped required
    # check counts as passing. The collector has to run anyway and fail.
    assert "always()" in str(gate.get("if", ""))
    steps = " ".join(s.get("run", "") for s in gate.get("steps") or [])
    assert "failure" in steps and "cancelled" in steps


def test_a_release_cannot_be_cut_before_validation_passes():
    wf = _workflow("release.yml")
    # PyYAML reads the bare key `on` as True.
    triggers = wf.get("on", wf.get(True))
    assert "workflow_call" in (_workflow("validate.yml").get("on")
                               or _workflow("validate.yml").get(True))
    jobs = wf["jobs"]
    callers = [k for k, j in jobs.items() if j.get("uses") == "./.github/workflows/validate.yml"]
    assert callers, "release.yml must call validate.yml as a job"
    release = jobs["release"]
    needs = release.get("needs") or []
    needs = [needs] if isinstance(needs, str) else needs
    assert set(callers) <= set(needs), "the release job must need the validation job"
    assert "push" in triggers and triggers["push"]["branches"] == ["main"], (
        "the release path itself stays: push to main")
