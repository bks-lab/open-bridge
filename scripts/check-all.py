#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One local command for every checker CI runs.

    python3 scripts/check-all.py            # fast tier: every checker, under a minute
    python3 scripts/check-all.py --full     # plus every test suite, several minutes
    python3 scripts/check-all.py --list     # what would run, nothing runs
    python3 scripts/check-all.py --only reach   # steps whose name contains "reach"

Run it after every upstream merge. Each step prints one line; a red step adds
the tail of its output; the last line sums up. Exit 0 when nothing is red.

The fast tier is the table CHECKS below; scripts/tests/test_check_all.py fails
when a scripts/check-*.py or scripts/validate-*.py is missing from it. The full
tier finds its suites by glob, so a new suite cannot be forgotten.

Every step runs with an empty, temporary global git config and a throwaway
identity. A local replay of CI once ran `git config --global` against the real
~/.gitconfig and overwrote the user's identity; that cannot happen here.

Steps run in parallel (--jobs, default 4), the longest first, so the run
takes about as long as its slowest step. With pytest-xdist installed the large
pytest suite also takes the cores the other steps leave; without it they run plain.
Inside every step `python3` is the interpreter that runs this script, because
the shell suites call bare `python3`.

On an instance (bridge-config.yaml present) no-scrub-leak.py reads only the
files the scope router ships as core. The instance holds its user's names on
purpose; the whole-repo scan read all of them, ran past its time limit, and
every hit would have been a false alarm.

A step whose tool is absent (node, uv) is skipped, not failed. Not covered: the
onboard-sim sandbox and the cockpit-relay TypeScript check, which need network.
pytest has to be importable by the interpreter that runs this script, or by
--python.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

REPO = pathlib.Path(__file__).resolve().parents[1]

# (name, argv) -- argv[0] is a path under scripts/, run with the chosen python.
CHECKS: list[tuple[str, list[str]]] = [
    ("validate-bridge.py", ["scripts/validate-bridge.py"]),
    ("validate-ecosystem.py", ["scripts/validate-ecosystem.py"]),
    ("validate-skill-scope.py --check", ["scripts/validate-skill-scope.py", "--check"]),
    ("validate-status.py", ["scripts/validate-status.py"]),
    ("check-commands-doc.py", ["scripts/check-commands-doc.py"]),
    ("check-doc-routes.py", ["scripts/check-doc-routes.py"]),
    ("check-edges.py", ["scripts/check-edges.py"]),
    ("check-figure-counts.py", ["scripts/check-figure-counts.py"]),
    ("check-generated-output.py", ["scripts/check-generated-output.py"]),
    ("check-inline-scripts.py", ["scripts/check-inline-scripts.py"]),
    ("check-kernel.py", ["scripts/check-kernel.py"]),
    ("check-object-grammar.py", ["scripts/check-object-grammar.py"]),
    ("check-reachability.py", ["scripts/check-reachability.py"]),
    ("check-reachability.py --surface subagent", ["scripts/check-reachability.py", "--surface", "subagent"]),
    ("check-secret-grammar.py", ["scripts/check-secret-grammar.py"]),
    ("check-secret-patterns.py", ["scripts/check-secret-patterns.py"]),
    ("check-site-basics.py", ["scripts/check-site-basics.py"]),
    ("check-site-links.py", ["scripts/check-site-links.py"]),
    ("check-skill-learnings.py", ["scripts/check-skill-learnings.py"]),
    ("check-where-things-live.py", ["scripts/check-where-things-live.py"]),
    ("standing-orders.py --check", ["scripts/standing-orders.py", "--check"]),
    ("context-index.py --check", ["scripts/context-index.py", "--check"]),
    ("data-model.py", ["scripts/data-model.py"]),
    ("measure-context.py", ["scripts/measure-context.py"]),
    ("briefing.py validate", ["scripts/briefing.py", "validate"]),
    ("briefing.py validate (examples/portfolio)",
     ["scripts/briefing.py", "--root", "examples/portfolio", "validate"]),
    ("no-scrub-leak.py", ["scripts/no-scrub-leak.py"]),
]

# Checkers that prove their own needles bite; slower, so full tier only.
MUTATE_CHECKS: list[tuple[str, list[str]]] = [
    (f"{name} --mutate", [script, "--mutate"])
    for name, script in [
        ("check-reachability.py", "scripts/check-reachability.py"),
        ("check-secret-grammar.py", "scripts/check-secret-grammar.py"),
        ("check-object-grammar.py", "scripts/check-object-grammar.py"),
        ("check-secret-patterns.py", "scripts/check-secret-patterns.py"),
        ("data-model.py", "scripts/data-model.py"),
    ]
]

CHECK_TIMEOUT = 300
SUITE_TIMEOUT = 1800
TAIL_LINES = 25
DEFAULT_JOBS = 4
# Measured on a laptop, sequential: these two are most of a full run. Started
# first, they overlap everything else instead of trailing behind it.
LONGEST_FIRST = ("pytest scripts/tests", "bash scripts/tests/test-overlay.sh")


@dataclass
class Step:
    name: str
    argv: list[str]
    cwd: str = "."
    needs: str | None = None          # a tool on PATH; absent -> skipped
    timeout: int = CHECK_TIMEOUT
    extra_env: dict = field(default_factory=dict)


def _rel(root: pathlib.Path, p: pathlib.Path) -> str:
    return p.relative_to(root).as_posix()


def _knows_mutate(path: pathlib.Path) -> bool:
    try:
        return "--mutate" in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _bash_steps(root: pathlib.Path, runner: pathlib.Path) -> list[Step]:
    rel = _rel(root, runner)
    steps = [Step(f"bash {rel}", ["bash", rel], needs="bash", timeout=SUITE_TIMEOUT)]
    if _knows_mutate(runner):
        steps.append(Step(f"bash {rel} --mutate", ["bash", rel, "--mutate"],
                          needs="bash", timeout=SUITE_TIMEOUT))
    return steps


def core_files(root: pathlib.Path) -> list[str] | None:
    """Tracked files the scope router classifies core, or None when this tree
    has no router to ask."""
    router = root / "scripts" / "categorize-commits.py"
    if not router.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_check_all_router", router)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True)
    if listed.returncode != 0:
        return None
    return [f for f in listed.stdout.split("\0")
            if f and (root / f).is_file() and not (root / f).is_symlink()
            and mod.classify_file(f) == "core"]


def plan(root: pathlib.Path, full: bool, python: str, xdist: bool = False,
         jobs: int = DEFAULT_JOBS) -> list[Step]:
    """Every step for this tree. Absent scripts drop out: a fork that has not
    taken a checker is not failing it."""
    root = pathlib.Path(root)
    # xdist gets the cores the other parallel steps leave; "auto" on top of
    # four busy steps doubled the slowest one (overlay 295 s -> 592 s).
    spread = ["-n", str(max(2, (os.cpu_count() or 4) - (jobs - 1)))] if xdist else []
    table = CHECKS + (MUTATE_CHECKS if full else [])
    steps = [Step(name, [python, *argv]) for name, argv in table if (root / argv[0]).is_file()]
    if (root / "bridge-config.yaml").is_file():
        core = core_files(root)
        for s in steps:
            if s.name == "no-scrub-leak.py" and core is not None:
                s.name = "no-scrub-leak.py (core files)"
                s.argv = [*s.argv, *core]
    if not full:
        return steps

    if any((root / "scripts/tests").glob("test_*.py")):
        steps.append(Step("pytest scripts/tests", [python, "-m", "pytest", "scripts/tests", "-q", "-rs", *spread],
                          timeout=SUITE_TIMEOUT))
    for sh in sorted((root / "scripts/tests").glob("test-*.sh")):
        steps += _bash_steps(root, sh)

    for skill in sorted(p for p in (root / "skills").glob("*") if p.is_dir() and not p.is_symlink()):
        runner = skill / "run-tests.sh"
        if runner.is_file():
            steps += _bash_steps(root, runner)
        elif any((skill / "tests").glob("test_*.py")):
            rel = _rel(root, skill / "tests")
            steps.append(Step(f"pytest {rel}", [python, "-m", "pytest", rel, "-q", "-rs"],
                              timeout=SUITE_TIMEOUT))
        if not runner.is_file():
            for sh in sorted((skill / "tests").glob("test-*.sh")):
                steps += _bash_steps(root, sh)

    for wrapper in ("identity", "infra", "workflow"):
        for runner in sorted((root / wrapper).glob("*/_tests/run.sh")):
            steps += _bash_steps(root, runner)

    mjs = sorted((root / "scripts/tests").glob("*.test.mjs"))
    if mjs:
        steps.append(Step("node scripts/tests/*.test.mjs",
                          ["node", "--max-old-space-size=512", "--test", "--test-timeout=30000",
                           *[_rel(root, m) for m in mjs]],
                          needs="node", timeout=SUITE_TIMEOUT))

    for sub, extra in (("agents", []), ("agents/_gateway", ["--with", "starlette"])):
        if (root / sub / "pyproject.toml").is_file() or (root / sub / "tests").is_dir():
            steps.append(Step(f"uv pytest {sub}",
                              ["uv", "run", "--with", "pytest", "--with", "pytest-asyncio", *extra, "pytest", "-q"],
                              cwd=sub, needs="uv", timeout=SUITE_TIMEOUT))
    return steps


def order(steps: list[Step]) -> list[Step]:
    """The longest known steps first, the rest in plan order."""
    rank = {name: i for i, name in enumerate(LONGEST_FIRST)}
    return sorted(steps, key=lambda s: rank.get(s.name, len(rank)))


def has_xdist(python: str) -> bool:
    if python == sys.executable:
        return importlib.util.find_spec("xdist") is not None
    return subprocess.run([python, "-c", "import xdist"], capture_output=True).returncode == 0


def isolated_env(tmpdir: pathlib.Path, python: str | None = None) -> dict:
    """The environment every step runs in: no global or system git config of
    the user's, and an identity that commits in fixture repos can use."""
    cfg = pathlib.Path(tmpdir) / "gitconfig"
    cfg.write_text("", encoding="utf-8")
    env = dict(os.environ)
    if python:
        shim = pathlib.Path(tmpdir) / "bin"
        shim.mkdir(exist_ok=True)
        # A wrapper, not a symlink to the resolved file: a virtualenv's python is
        # itself a symlink to the base interpreter, and only the path it is
        # started under finds the venv's pyvenv.cfg and so its packages.
        real = pathlib.Path(shutil.which(python) or python).absolute()
        for name in ("python3", "python"):
            wrapper = shim / name
            wrapper.write_text(f'#!/bin/sh\nexec "{real}" "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)
        env["PATH"] = f"{shim}{os.pathsep}{env.get('PATH', '')}"
    env.update({
        "GIT_CONFIG_GLOBAL": str(cfg),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "check-all",
        "GIT_AUTHOR_EMAIL": "check-all@example.invalid",
        "GIT_COMMITTER_NAME": "check-all",
        "GIT_COMMITTER_EMAIL": "check-all@example.invalid",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def _tail(text: str, n: int = TAIL_LINES) -> str:
    lines = [ln for ln in text.rstrip().splitlines() if ln.strip()]
    return "\n".join("      " + ln for ln in lines[-n:])


def _run_one(s: Step, root: pathlib.Path, env: dict) -> tuple[int, str, float]:
    t0 = time.monotonic()
    try:
        r = subprocess.run(s.argv, cwd=pathlib.Path(root) / s.cwd, env={**env, **s.extra_env},
                           stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=s.timeout)
        rc, output = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc = 124
        output = f"timed out after {s.timeout}s\n" + str(e.stdout or "") + str(e.stderr or "")
    except OSError as e:
        rc, output = 127, str(e)
    return rc, output, time.monotonic() - t0


def run_steps(steps: list[Step], root: pathlib.Path, out=sys.stdout, jobs: int = 1,
              python: str | None = None) -> int:
    green, red, skipped = [], [], []
    width = max((len(s.name) for s in steps), default=10)
    with tempfile.TemporaryDirectory(prefix="check-all-") as tmp:
        env = isolated_env(pathlib.Path(tmp), python=python or sys.executable)
        runnable = []
        for s in steps:
            if s.needs and shutil.which(s.needs, path=env["PATH"]) is None:
                skipped.append(s.name)
                print(f"  skip  {s.name:<{width}}  ({s.needs} not installed)", file=out, flush=True)
            else:
                runnable.append(s)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            futures = {pool.submit(_run_one, s, root, env): s for s in runnable}
            for fut in concurrent.futures.as_completed(futures):
                s = futures[fut]
                rc, output, dt = fut.result()
                if rc == 0:
                    green.append(s.name)
                    print(f"  ok    {s.name:<{width}}  {dt:6.1f}s", file=out, flush=True)
                else:
                    red.append(s.name)
                    print(f"  RED   {s.name:<{width}}  {dt:6.1f}s  exit {rc}", file=out, flush=True)
                    print(_tail(output), file=out, flush=True)
    summary = f"check-all: {len(green)} green, {len(red)} red, {len(skipped)} skipped"
    if red:
        summary += " · red: " + ", ".join(red)
    print(summary, file=out, flush=True)
    return 1 if red else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--full", action="store_true", help="also run every test suite")
    ap.add_argument("--list", action="store_true", help="print the steps, run nothing")
    ap.add_argument("--only", metavar="TEXT", help="only steps whose name contains TEXT")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="steps at once (default 4)")
    ap.add_argument("--python", default=sys.executable, help="interpreter for checkers and pytest")
    ap.add_argument("--root", default=str(REPO), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    root = pathlib.Path(args.root)
    xdist = args.full and has_xdist(args.python)
    steps = order(plan(root, full=args.full, python=args.python, xdist=xdist, jobs=args.jobs))
    if args.only:
        steps = [s for s in steps if args.only in s.name]
    if args.list:
        for s in steps:
            print(s.name + (f"  (needs {s.needs})" if s.needs else ""))
        return 0
    if args.full:
        probe = subprocess.run([args.python, "-c", "import pytest"], capture_output=True)
        if probe.returncode != 0:
            print(f"check-all: pytest is not importable by {args.python}; "
                  "install it or pass --python", file=sys.stderr)
            return 2
        if not xdist:
            print("check-all: pytest-xdist not installed, the large suites run on one core", flush=True)
    return run_steps(steps, root, jobs=args.jobs, python=args.python)


if __name__ == "__main__":
    sys.exit(main())
