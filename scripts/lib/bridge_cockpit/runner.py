# SPDX-License-Identifier: MIT
"""Subprocess runner of the cockpit: one program allowlist, timeouts, a clean env.

Every script call of the server goes through `Runner.run`. Before a process starts,
`check` refuses any argv that is not one of the seven Bridge scripts of SCRIPT_PATHS (run
with this interpreter) or one of the exact shapes below it lets through: an A2A ask, a quick
question, codex read-only, the Haiku judge, organize, and ps for one pid. The cmux CLI is
never called directly; tabs go through workplace.py and its terminal driver. Tests inject a
fake runner that overrides `_spawn` and so still passes through the same check.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import agents
from . import organize
from ..model_route import haiku_argv_ok
from .quick import argv_ok, resolve_claude
from ..ai_services import codex_argv_ok, resolve, select, CLAUDE_MODELS

CMUX_APP = "/Applications/cmux.app/Contents/Resources/bin/cmux"
SCRIPT_PATHS = ("scripts/briefing.py", "scripts/inbox.py", "scripts/workplace.py", "scripts/task.py",
                "scripts/bridge-resources.py", "scripts/triage.py", "skills/cmux/scripts/cmux_layout.py")


class RunnerRefused(Exception):
    """The argv names a program outside the allowlist."""


@dataclass
class RunResult:
    ok: bool
    code: int
    out: str
    err: str
    took_ms: int


def resolve_cmux(env: dict | None = None) -> str | None:
    env = os.environ if env is None else env
    bundled = env.get("CMUX_BUNDLED_CLI_PATH")
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    found = shutil.which("cmux", path=env.get("PATH"))
    if found:
        return found
    if os.path.isfile(CMUX_APP) and os.access(CMUX_APP, os.X_OK):
        return CMUX_APP
    return None


class Runner:
    def __init__(self, root: Path | str, cmux: str | None = "auto", claude: str | None = "auto", codex: str | None = "auto",
                 code: Path | str | None = None):
        self.root = Path(root).resolve()
        # where the helper scripts come from: the checkout this cockpit runs from, which is the Bridge itself
        # unless a cockpit from another checkout (a branch beside it) is pointed at the live data with --root
        self.code = Path(code).resolve() if code else self.root
        self.python = sys.executable
        self.cmux = resolve_cmux() if cmux == "auto" else cmux
        self.claude = resolve_claude() if claude == "auto" else claude
        self.codex = resolve("codex") if codex == "auto" else codex
        self.scripts = frozenset(str(self.code / p) for p in SCRIPT_PATHS)

    def script(self, rel: str) -> str:
        return str(self.code / rel)

    def check(self, argv: list[str]) -> None:
        if not isinstance(argv, list) or len(argv) < 2 or not all(isinstance(a, str) for a in argv):
            raise RunnerRefused("argv must be a list of at least two strings")
        if any("\x00" in a for a in argv):
            raise RunnerRefused("NUL in argv")
        if argv[0] == self.python and argv[1] in self.scripts:
            return
        # a quick question: claude -p with a known model and the three read tools only (quick.py)
        # a message to an A2A agent: a2a.py ask or get in exactly their shapes (agents.py)
        if agents.argv_ok(argv, self.python, self.script(agents.SCRIPT)):
            return
        if self.claude and argv[0] == self.claude:
            chat_model = select(self.root, "briefing-chat", provider="claude").model
            if argv_ok(argv, self.claude, {*CLAUDE_MODELS.values(), chat_model}):
                return
        if codex_argv_ok(argv, self.codex):
            return
        # the judge of how complex an item is: Haiku without tools, settings or session (model_route.py)
        if haiku_argv_ok(argv, self.claude):
            return
        # organize with AI: one call with the snapshot of this Bridge's workspaces, no tools (organize.py)
        if organize.argv_ok(argv, self.claude):
            return
        # the Sessions page reads one variable of a Claude process's environment (sessions.py)
        if len(argv) == 6 and argv[:5] == ["/bin/ps", "eww", "-o", "command=", "-p"] and argv[5].isdigit():
            return
        raise RunnerRefused(f"program not allowed: {os.path.basename(argv[0])} {os.path.basename(argv[1])}")

    def env(self) -> dict:
        env = dict(os.environ)
        env.pop("BRIDGE_TAB_SLUG", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["BRIDGE_ACTOR"] = "web"
        return env

    def run(self, argv: list[str], timeout_s: float, on_line: Callable[[str], None] | None = None) -> RunResult:
        """With `on_line`, every line of stdout goes to it as it comes (a streamed answer); `out` still
        holds all of it at the end."""
        self.check(argv)
        if on_line is not None:
            return self._spawn_lines(list(argv), timeout_s, on_line)
        return self._spawn(list(argv), timeout_s)

    def _spawn_lines(self, argv: list[str], timeout_s: float, on_line: Callable[[str], None]) -> RunResult:
        start = time.monotonic()
        try:
            proc = subprocess.Popen(argv, cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=self.env(), start_new_session=True, shell=False)
        except OSError as error:
            return RunResult(False, -1, "", str(error), int((time.monotonic() - start) * 1000))
        expired = threading.Event()

        def kill() -> None:
            expired.set()
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()

        timer = threading.Timer(timeout_s, kill)
        timer.daemon = True
        timer.start()
        err_parts: list[bytes] = []
        reader = threading.Thread(target=lambda: err_parts.append(proc.stderr.read()), daemon=True)
        reader.start()
        out_lines: list[str] = []
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace")
                out_lines.append(line)
                try:
                    on_line(line.rstrip("\n"))
                except Exception:  # noqa: BLE001 - a listener never breaks the read
                    pass
            proc.wait()
        finally:
            timer.cancel()
            reader.join(timeout=2)
        took = int((time.monotonic() - start) * 1000)
        if expired.is_set():
            return RunResult(False, -1, "".join(out_lines), "timeout", took)
        text_err = b"".join(err_parts).decode("utf-8", errors="replace")
        return RunResult(proc.returncode == 0, proc.returncode, "".join(out_lines), text_err, took)

    def _spawn(self, argv: list[str], timeout_s: float) -> RunResult:
        start = time.monotonic()
        try:
            proc = subprocess.Popen(argv, cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, env=self.env(), start_new_session=True, shell=False)
        except OSError as error:
            return RunResult(False, -1, "", str(error), int((time.monotonic() - start) * 1000))
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            proc.communicate()
            return RunResult(False, -1, "", "timeout", int((time.monotonic() - start) * 1000))
        took = int((time.monotonic() - start) * 1000)
        text_out = out.decode("utf-8", errors="replace")
        text_err = err.decode("utf-8", errors="replace")
        return RunResult(proc.returncode == 0, proc.returncode, text_out, text_err, took)
