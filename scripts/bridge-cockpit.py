#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The Bridge cockpit: a local web page that watches and steers the Bridge (the briefing, the work, agent
tabs and sessions, workers, machines, tokens).

    python3 scripts/bridge-cockpit.py serve [--port N] [--ignore-disabled]   # foreground
    python3 scripts/bridge-cockpit.py start [--port N] [--json]              # in the background, reused
    python3 scripts/bridge-cockpit.py open [--via auto|cmux|system|none] [--json]   # start, then open the page
    python3 scripts/bridge-cockpit.py url                                    # a login link, good once for a minute
    python3 scripts/bridge-cockpit.py status [--json]
    python3 scripts/bridge-cockpit.py stop
    python3 scripts/bridge-cockpit.py autostart on|off|status                # macOS: run from login on, always there
    python3 scripts/bridge-cockpit.py new-token                              # a new key on the next start

Global flags before the command: --root R (the Bridge, default this repo) and
--state-dir DIR (default R/.bridge/cockpit). The code that runs is the checkout this file lies in,
so a cockpit from a branch can be pointed at the live Bridge with --root. The server binds 127.0.0.1 only, keeps one
key per Bridge (R/.bridge/cockpit/token, 0600) that no command prints (links carry a one-time
login code made from it) and refuses to start until cockpit.enabled is true in
bridge-config.yaml. It runs the Bridge scripts (inbox.py, task.py, workplace.py) and collects with
--no-save. Exit codes: 0 ok, 1 not running, 2 disabled or invalid config (or a wrong call: argparse
prints a usage text on stderr), 3 port in use, 4 did not come up, 5 open failed. User doc: docs/bridge-cockpit.md.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import http.client
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# python3 may point at a new version that has no PyYAML yet; then the cockpit
# starts again under the newest Python that has it, so /cockpit keeps working through an update
PYTHONS = ("python3.14", "python3.13", "python3.12", "python3.11")


def _python_with_yaml() -> str | None:
    for name in PYTHONS:
        for exe in (shutil.which(name), f"/opt/homebrew/bin/{name}"):
            if exe and os.path.exists(exe) and os.path.realpath(exe) != os.path.realpath(sys.executable):
                ok = subprocess.run([exe, "-c", "import yaml"], capture_output=True).returncode == 0
                if ok:
                    return exe
    return None


try:
    import yaml  # noqa: F401  (the config reader needs it)
except ImportError:
    _exe = _python_with_yaml()
    if _exe is None:
        sys.exit("bridge-cockpit: needs PyYAML (python3 -m pip install pyyaml)")
    os.execv(_exe, [_exe, str(Path(__file__).resolve()), *sys.argv[1:]])

from lib import ai_services  # noqa: E402  (path set above)
from lib.bridge_cockpit import VERSION  # noqa: E402
from lib.bridge_cockpit.config import WebConfigError, load_web_config  # noqa: E402
from lib.bridge_cockpit.launch import can_launch  # noqa: E402  (also read by scripts/bridge-setup.py)
from lib.bridge_cockpit.server import default_state_dir  # noqa: E402
from lib.bridge_cockpit.store import read_json  # noqa: E402

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
START_WAIT_S = 10.0
STOP_WAIT_S = 5.0


def pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def health(port: int, timeout: float = 2.0) -> dict | None:
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", "/api/health", headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        if resp.status != 200:
            return None
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, http.client.HTTPException):
        return None


def server_file(state_dir: Path) -> Path:
    return state_dir / "server.json"


def running_info(root: Path, state_dir: Path) -> dict | None:
    """server.json when its pid lives and /api/health on its port names this root."""
    from lib.bridge_cockpit.server import instance_id
    info = read_json(server_file(state_dir))
    if not isinstance(info, dict) or not pid_alive(info.get("pid")) or not isinstance(info.get("port"), int):
        return None
    h = health(info["port"])
    if not h or h.get("instance") != instance_id(root):
        return None
    return info


class NoKey(Exception):
    """<state>/token is missing or damaged: the running server's key cannot be read."""


def read_key(state_dir: Path) -> str:
    """The key of the running server, from <state>/token (0600). Never made here: a new key would not
    match the server's, so a missing one is an error, not a reason to write one (stable_token does that
    at start)."""
    from lib.bridge_cockpit.server import TOKEN_RE
    try:
        value = (state_dir / "token").read_text(encoding="utf-8").strip()
    except OSError:
        raise NoKey from None
    if not TOKEN_RE.fullmatch(value):
        raise NoKey
    return value


def link(info: dict, state_dir: Path) -> str:
    """A login link: a code made from the key, good once and for a minute, never the key itself."""
    from lib.bridge_cockpit.server import login_code
    return f"http://127.0.0.1:{info['port']}/?code={login_code(read_key(state_dir), time.time() * 1000)}"


def plain(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def start_line(port: int) -> str:
    """The first line a serve prints, dated, so stdout.log says when each start happened"""
    return f"{time.strftime('%Y-%m-%dT%H:%M:%S')} bridge-cockpit {VERSION} on {plain(port)}"


ENABLE_HINT = "Set cockpit.enabled: true in bridge-config.yaml (docs/bridge-cockpit.md)."


def check_config(root: Path, ignore_disabled: bool) -> tuple[object | None, int]:
    try:
        cfg = load_web_config(root)
    except WebConfigError as error:
        print(f"bridge-cockpit: {error}", file=sys.stderr)
        return None, 2
    for line in cfg.config_warnings:
        # never a reason to refuse: the loader fell back, this says where (status prints them too)
        print(f"bridge-cockpit: warning: {line}", file=sys.stderr)
    if not cfg.enabled and not ignore_disabled:
        print(f"bridge-cockpit: off. {ENABLE_HINT}", file=sys.stderr)
        return None, 2
    return cfg, 0


# ---------------------------------------------------------------- commands

def cmd_serve(args, root: Path, state_dir: Path) -> int:
    cfg, code = check_config(root, args.ignore_disabled)
    if cfg is None:
        return code
    from lib.bridge_cockpit.server import make_server
    port = cfg.port if args.port is None else args.port
    try:
        server = make_server(root, port=port, state_dir=state_dir, cfg=cfg, background=False, code_root=DEFAULT_ROOT)
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, errno.EACCES):
            if running_info(root, state_dir):
                # this Bridge's cockpit already serves (started by hand before the login item): nothing to do,
                # and a clean exit, so launchd does not try again and again
                print(f"bridge-cockpit: already running on {plain(port)}", file=sys.stderr)
                return 0
            print(f"bridge-cockpit: port {port} is in use", file=sys.stderr)
            return 3
        raise
    app = server.app

    def stop(signum, frame):  # noqa: ARG001
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    app.start()
    print(start_line(app.port), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        app.stop()
        server.server_close()
        info = read_json(server_file(state_dir))
        if isinstance(info, dict) and info.get("pid") == os.getpid():
            try:
                server_file(state_dir).unlink()
            except OSError:
                pass
    return 0


def start(args, root: Path, state_dir: Path) -> tuple[int, dict | None]:
    info = running_info(root, state_dir)
    if info:
        return 0, {**info, "reused": True}
    cfg, code = check_config(root, getattr(args, "ignore_disabled", False))
    if cfg is None:
        return code, None
    try:
        server_file(state_dir).unlink()
    except OSError:
        pass
    state_dir.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(Path(__file__).resolve()), "--root", str(root), "--state-dir", str(state_dir), "serve"]
    if getattr(args, "port", None) is not None:
        argv += ["--port", str(args.port)]
    if getattr(args, "ignore_disabled", False):
        argv.append("--ignore-disabled")
    # what the process prints goes to stdout.log; server.log is written only through log_error, which rotates
    # it, and a second open handle on it would keep writing into the moved file (review C29)
    with open(state_dir / "stdout.log", "ab") as log:
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                                 cwd=str(root))
    deadline = time.monotonic() + START_WAIT_S
    while time.monotonic() < deadline:
        exit_code = child.poll()
        if exit_code is not None:
            # the child's own words went to stdout.log; say here what a terminal user has to change
            if exit_code == 3:
                port = cfg.port if getattr(args, "port", None) is None else args.port
                print(f"bridge-cockpit: port {port} is in use, set cockpit.port in bridge-config.yaml",
                      file=sys.stderr)
            elif exit_code == 2:
                print(f"bridge-cockpit: the server refused its config, see .bridge/cockpit/stdout.log. {ENABLE_HINT}",
                      file=sys.stderr)
            return (exit_code if exit_code in (2, 3) else 4), None
        info = read_json(server_file(state_dir))
        if isinstance(info, dict) and info.get("pid") == child.pid and isinstance(info.get("port"), int) \
                and health(info["port"], timeout=1.0):
            return 0, {**info, "reused": False}
        time.sleep(0.1)
    return 4, None


def cmd_start(args, root: Path, state_dir: Path) -> int:
    code, info = start(args, root, state_dir)
    if code:
        if code == 4:
            print("bridge-cockpit: the server did not come up, see .bridge/cockpit/stdout.log and server.log",
                  file=sys.stderr)
        return code
    if args.json:
        print(json.dumps({"url": link(info, state_dir), "port": info["port"], "pid": info["pid"], "reused": info["reused"]}))
    else:
        print(link(info, state_dir))
    return 0


def cmd_open(args, root: Path, state_dir: Path) -> int:
    args.port = None
    args.ignore_disabled = False
    code, info = start(args, root, state_dir)
    if code:
        return code
    cfg = load_web_config(root)
    via = args.via or cfg.open_in
    if via == "auto":
        via = "cmux" if os.environ.get("CMUX_SURFACE_ID") else "system"
    url = link(info, state_dir)
    ok = True
    if via == "cmux":
        opener = root / "skills" / "cmux" / "scripts" / "cmux-open.sh"
        argv = [str(opener), "browser", "--name", "Cockpit", url]
    elif via == "system":
        tool = "open" if sys.platform == "darwin" else "xdg-open"
        argv = [shutil.which(tool) or tool, url]
    else:
        argv = None
    if argv:
        try:
            ok = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=30, cwd=str(root)).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    if not ok:
        print(f"bridge-cockpit: could not open the page. {plain(info['port'])} "
              "(a login link: python3 scripts/bridge-cockpit.py url)", file=sys.stderr)
        if args.json:
            print(json.dumps({"opened": "none", "port": info["port"], "reused": info["reused"], "error": "open failed"}))
        return 5
    if args.json:
        print(json.dumps({"opened": via, "port": info["port"], "reused": info["reused"]}))
    elif via == "none":
        print(url)
    else:
        print(f"opened ({via}): {plain(info['port'])}")
    return 0


def cmd_url(args, root: Path, state_dir: Path) -> int:
    info = running_info(root, state_dir)
    if not info:
        print("bridge-cockpit: not running", file=sys.stderr)
        return 1
    print(link(info, state_dir))
    return 0


def cmd_status(args, root: Path, state_dir: Path) -> int:
    info = running_info(root, state_dir)
    out = {"running": bool(info), "pid": info.get("pid") if info else None, "port": info.get("port") if info else None,
           "started_ms": info.get("started_ms") if info else None, "version": info.get("version") if info else None,
           "clients": info.get("clients", 0) if info else 0, "relay_online": bool(info.get("relay_online")) if info else False}
    # what the check of the cockpit: block found, read from the file now (the running server may be older)
    try:
        warnings = list(load_web_config(root).config_warnings)
    except WebConfigError as error:
        warnings = [str(error)]
    out["config_warnings"] = warnings
    out["can_launch"] = can_launch(root)
    # a service whose workflow/ai-services file names a provider its code cannot run (docs/ai-services.md)
    out["provider_gaps"] = ai_services.gaps(root)
    if args.json:
        print(json.dumps(out))
    elif info:
        print(f"running: pid {out['pid']}, {plain(out['port'])}, {out['clients']} page(s) open, "
              f"relay {'online' if out['relay_online'] else 'offline'}")
    else:
        print("not running")
    if not args.json:
        for line in warnings:
            print(f"warning: {line}")
        if out["can_launch"] is False:
            print("warning: agent tabs cannot start: no terminal driver serves launch "
                  "(workplace.driver in bridge-config.yaml, docs/workplace.md)")
        for g in out["provider_gaps"]:
            print(f"warning: {g['service']} cannot run on {g['provider']}, only on {', '.join(g['supported'])}: "
                  "it stays off (docs/ai-services.md, A service your provider cannot run)")
    return 0 if info else 1


def is_our_server(pid: int) -> bool:
    """The process runs `bridge-cockpit.py serve`: a pid from a stale server.json may belong to anything now."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    command = out.stdout.strip()
    return out.returncode == 0 and "bridge-cockpit.py" in command and " serve" in command


def cmd_stop(args, root: Path, state_dir: Path) -> int:
    info = read_json(server_file(state_dir))
    pid = info.get("pid") if isinstance(info, dict) else None
    # Signal only this server: healthy and naming this root, or at least a bridge-cockpit.py serve process
    # (one that hangs). Anything else is a stale file whose pid the system gave to another process.
    if not pid_alive(pid) or (running_info(root, state_dir) is None and not is_our_server(pid)):
        try:
            server_file(state_dir).unlink()
        except OSError:
            pass
        print("bridge-cockpit: not running", file=sys.stderr)
        return 1
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline and pid_alive(pid):
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        time.sleep(0.1)
    if pid_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        server_file(state_dir).unlink()
    except OSError:
        pass
    print("stopped")
    return 0


# ---------------------------------------------------------------- autostart (macOS login item) and the key

LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"


def launch_agent(root: Path, state_dir: Path, python: str, path_env: str) -> tuple[str, dict]:
    """The login item of one Bridge: starts `serve` at login and again after a crash, never after `stop`
    (KeepAlive only on an unsuccessful exit). PATH is the one of the shell that switched it on, since the
    cockpit calls cmux, gh, git and claude, and launchd starts with almost none."""
    label = "ai.open-bridge.cockpit." + hashlib.sha256(str(Path(root)).encode("utf-8")).hexdigest()[:10]
    log = str(Path(state_dir) / "stdout.log")    # beside server.log, see start()
    return label, {
        "Label": label,
        "ProgramArguments": [python, str(Path(__file__).resolve()), "--root", str(root), "serve"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "EnvironmentVariables": {"PATH": path_env},
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def cmd_autostart(args, root: Path, state_dir: Path) -> int:
    if sys.platform != "darwin":
        print("bridge-cockpit: autostart is macOS only for now; elsewhere run `start` from your session's startup",
              file=sys.stderr)
        return 2
    label, plist = launch_agent(root, state_dir, sys.executable, os.environ.get("PATH", "/usr/bin:/bin"))
    path = LAUNCH_AGENTS / f"{label}.plist"
    domain = f"gui/{os.getuid()}"
    loaded = _launchctl("print", f"{domain}/{label}").returncode == 0
    if args.action == "status":
        print(f"autostart {'on' if path.exists() and loaded else 'off'} ({path})")
        return 0 if path.exists() and loaded else 1
    if args.action == "off":
        if loaded:
            _launchctl("bootout", f"{domain}/{label}")
        if path.exists():
            path.unlink()
        print("autostart off; the running server stays until `stop`")
        return 0
    cfg, code = check_config(root, False)
    if cfg is None:
        return code
    state_dir.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    if loaded:
        _launchctl("bootout", f"{domain}/{label}")
    with open(path, "wb") as fh:
        plistlib.dump(plist, fh)
    done = _launchctl("bootstrap", domain, str(path))
    if done.returncode != 0:
        print(f"bridge-cockpit: launchctl bootstrap failed: {done.stderr.strip()}", file=sys.stderr)
        return 4
    print(f"autostart on: the cockpit runs from login, {plain(cfg.port)}")
    return 0


def cmd_new_token(args, root: Path, state_dir: Path) -> int:
    from lib.bridge_cockpit.server import forget_token
    forget_token(state_dir)
    print("a new key on the next start: `stop`, `start`, then open a link from `url` in each browser")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bridge-cockpit.py", description="The briefing as a local web page.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="the Bridge root (default: this repo)")
    parser.add_argument("--state-dir", default=None, help="runtime files (default: <root>/.bridge/cockpit)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve", help="run the server in the foreground")
    p.add_argument("--port", type=int, default=None, help="port (0 = any free one; default cockpit.port)")
    p.add_argument("--ignore-disabled", action="store_true", help="start even when cockpit.enabled is not true")
    p = sub.add_parser("start", help="start in the background or reuse the running server")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--ignore-disabled", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("open", help="start, then open the page")
    p.add_argument("--via", choices=["auto", "cmux", "system", "none"], default=None)
    p.add_argument("--json", action="store_true")
    sub.add_parser("url", help="print a login link (a one-time code, good for a minute)")
    p = sub.add_parser("status", help="is it running")
    p.add_argument("--json", action="store_true")
    sub.add_parser("stop", help="stop the server")
    p = sub.add_parser("autostart", help="macOS: start the cockpit at login (a LaunchAgent)")
    p.add_argument("action", choices=["on", "off", "status"])
    sub.add_parser("new-token", help="make a new key on the next start (every browser opens `url` once more)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    state_dir = Path(args.state_dir).resolve() if args.state_dir else default_state_dir(root)
    commands = {"serve": cmd_serve, "start": cmd_start, "open": cmd_open, "url": cmd_url, "status": cmd_status,
                "stop": cmd_stop, "autostart": cmd_autostart, "new-token": cmd_new_token}
    try:
        return commands[args.command](args, root, state_dir)
    except NoKey:
        print(f"bridge-cockpit: cannot read the key in {state_dir / 'token'}; "
              "`stop` and `start` make a new one, then open a link from `url`", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
