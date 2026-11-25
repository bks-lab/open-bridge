#!/usr/bin/env python3
"""Start a browser session on the configured target and check that a target works.

Every browser command after the start goes straight to `playwright-cli -s=<session> ...`.
This script owns only the two things that depend on the target:

  start   open a session: `chrome` launches Chrome with a persistent profile,
          `cdp` attaches to a running Chromium at a local CDP address
  check   run the common commands (fill, select, check, upload, click, wait, eval,
          console, screenshot) against a built-in page on 127.0.0.1 and report each

Target: --target, else $BRIDGE_BROWSER_TARGET, else chrome. The CDP address:
--cdp-url, else $BRIDGE_BROWSER_CDP_URL. The CLI: $BRIDGE_PLAYWRIGHT_CLI, else
`playwright-cli` on PATH.
"""
from __future__ import annotations

import argparse
import http.server
import ipaddress
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

TARGETS = ("chrome", "cdp")
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")


class BrowserError(Exception):
    pass


# ---------- snapshot parsing ----------

def find_ref(snapshot: str, role: str, name: str) -> str | None:
    """Ref of the first element with exactly this role and accessible name."""
    pat = re.compile(r'^\s*-\s+' + re.escape(role) + r'\s+"' + re.escape(name) + r'"[^\n]*?\[ref=([A-Za-z0-9]+)\]', re.M)
    m = pat.search(snapshot)
    return m.group(1) if m else None


def page_url(output: str) -> str | None:
    m = re.search(r"^- Page URL: (\S+)", output, re.M)
    return m.group(1) if m else None


# ---------- target ----------

def _is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def resolve_target(flag: str | None, cdp_flag: str | None, env) -> tuple[str, str | None]:
    target = flag or env.get("BRIDGE_BROWSER_TARGET") or "chrome"
    if target not in TARGETS:
        raise BrowserError(f"unknown target {target!r}, expected one of {', '.join(TARGETS)}")
    if target == "chrome":
        return "chrome", None
    url = cdp_flag or env.get("BRIDGE_BROWSER_CDP_URL")
    if not url:
        raise BrowserError("target cdp needs an address: --cdp-url or $BRIDGE_BROWSER_CDP_URL")
    # A CDP endpoint is full control over the browser and its logins: only ever a local one.
    if not _is_local(url):
        raise BrowserError(f"refusing a CDP address that is not local: {url}")
    return "cdp", url


# ---------- running the CLI ----------

def find_cli() -> str:
    cli = os.environ.get("BRIDGE_PLAYWRIGHT_CLI") or shutil.which("playwright-cli")
    if not cli:
        raise BrowserError("playwright-cli not found: install a pinned version, "
                           "npm install -g @playwright/cli@<version>, or set $BRIDGE_PLAYWRIGHT_CLI")
    return cli


def run_cli(argv: list[str]) -> tuple[int, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _call(runner, argv: list[str]) -> str:
    code, out = runner(argv)
    if code != 0 or "### Error" in out:
        detail = out.split("### Error", 1)[-1].strip().splitlines()
        raise BrowserError(f"{' '.join(argv[1:3])}: {detail[0] if detail else 'exit ' + str(code)}")
    return out


def start(session: str, url: str | None, target: tuple[str, str | None], *, headed: bool,
          runner=run_cli, cli: str | None = None) -> str:
    if not SESSION_RE.match(session or ""):
        raise BrowserError(f"session name {session!r}: letters, digits, - and _ only")
    cli = cli or find_cli()
    kind, cdp_url = target
    s = f"-s={session}"
    if kind == "chrome":
        argv = [cli, s, "open"] + ([url] if url else []) + ["--browser=chrome", "--persistent"]
        if headed:
            argv.append("--headed")
        return _call(runner, argv)
    out = _call(runner, [cli, s, "attach", f"--cdp={cdp_url}"])
    if url:
        out = _call(runner, [cli, s, "goto", url])
    return out


# ---------- check ----------

CHECK_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Browser check</title></head><body>
<h1>Browser check</h1>
<label>Name <input id="n"></label>
<select id="s" aria-label="Farbe"><option>rot</option><option>blau</option></select>
<label><input type="checkbox" id="c"> Zustimmen</label>
<input type="file" id="f" aria-label="Datei">
<button id="b">Senden</button>
<p id="out"></p>
<script>
document.getElementById('b').addEventListener('click', function () {
  setTimeout(function () {
    var f = document.getElementById('f').files[0];
    document.getElementById('out').textContent = 'OK ' + document.getElementById('n').value + ' ' +
      document.getElementById('s').value + ' ' + document.getElementById('c').checked + ' ' + (f ? f.name : '-');
    console.error('check-console');
  }, 600);
});
</script></body></html>
"""

CHECK_STEPS = [
    ("snapshot", "read the refs"),
    ("fill", "type into a text box"),
    ("select", "pick an option"),
    ("check", "tick a checkbox"),
    ("upload", "click the file input, then upload"),
    ("click", "press the button"),
    ("wait", "wait for text that appears later (run-code)"),
    ("eval", "evaluate JavaScript"),
    ("console", "read console errors"),
    ("screenshot", "save a screenshot"),
]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass


def _serve(folder: Path):
    handler = lambda *a, **k: _Quiet(*a, directory=str(folder), **k)  # noqa: E731
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def run_check(target: tuple[str, str | None], *, workdir: Path | None = None, session: str = "browser-check",
              headed: bool = False, runner=run_cli, cli: str | None = None) -> list[tuple[str, bool, str]]:
    cli = cli or find_cli()
    work = Path(workdir or tempfile.mkdtemp(prefix="browser-check-"))
    (work / "check.html").write_text(CHECK_PAGE, encoding="utf-8")
    upload = work / "upload.txt"
    upload.write_text("browser check\n", encoding="utf-8")
    srv = _serve(work)
    url = f"http://127.0.0.1:{srv.server_address[1]}/check.html"
    s = f"-s={session}"
    results: list[tuple[str, bool, str]] = []

    def step(name, fn):
        try:
            results.append((name, True, fn() or ""))
        except Exception as e:  # each step reports, the run goes on
            results.append((name, False, str(e)))

    try:
        start(session, url, target, headed=headed, runner=runner, cli=cli)
        snap = {}

        def refs():
            out = _call(runner, [cli, s, "snapshot"])
            for key, role, name in (("n", "textbox", "Name"), ("s", "combobox", "Farbe"),
                                    ("c", "checkbox", "Zustimmen"), ("f", "button", "Datei"),
                                    ("b", "button", "Senden")):
                ref = find_ref(out, role, name)
                if not ref:
                    raise BrowserError(f"no ref for {role} {name!r}")
                snap[key] = ref
            return ", ".join(f"{k}={v}" for k, v in snap.items())

        step("snapshot", refs)
        step("fill", lambda: _call(runner, [cli, s, "fill", snap["n"], "Check"]) and "")
        step("select", lambda: _call(runner, [cli, s, "select", snap["s"], "blau"]) and "")
        step("check", lambda: _call(runner, [cli, s, "check", snap["c"]]) and "")

        def do_upload():
            out = _call(runner, [cli, s, "click", snap["f"]])
            if "File chooser" not in out:
                raise BrowserError("clicking the file input opened no file chooser")
            _call(runner, [cli, s, "upload", str(upload)])

        step("upload", do_upload)
        step("click", lambda: _call(runner, [cli, s, "click", snap["b"]]) and "")

        def wait():
            code = ("async page => { await page.getByText('OK Check').waitFor({ timeout: 10000 }); "
                    "return await page.locator('#out').textContent(); }")
            out = _call(runner, [cli, s, "run-code", code])
            if "OK Check blau true upload.txt" not in out:
                raise BrowserError("result text differs: " + out.split("### Result", 1)[-1].strip()[:80])
            return "OK Check blau true upload.txt"

        step("wait", wait)

        def ev():
            out = _call(runner, [cli, s, "eval", "document.title"])
            if "Browser check" not in out:
                raise BrowserError("eval returned no title")

        step("eval", ev)

        def console():
            out = _call(runner, [cli, s, "console"])
            if "check-console" not in out:
                raise BrowserError("console error not reported")

        step("console", console)

        def shot():
            path = work / "check.png"
            _call(runner, [cli, s, "screenshot", f"--filename={path}"])
            if not path.exists() or path.stat().st_size == 0:
                raise BrowserError("no screenshot file")
            return str(path)

        step("screenshot", shot)
    except BrowserError as e:
        results.append(("start", False, str(e)))
    finally:
        try:
            if target[0] == "cdp":
                runner([cli, s, "detach"])
            else:
                runner([cli, s, "close"])
        finally:
            srv.shutdown()
    return results


# ---------- CLI ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "check"):
        p = sub.add_parser(name)
        p.add_argument("--target", choices=TARGETS)
        p.add_argument("--cdp-url")
        p.add_argument("--headless", action="store_true", help="start: no window (default for check)")
        p.add_argument("--headed", action="store_true", help="check: show the window")
        if name == "start":
            p.add_argument("session")
            p.add_argument("url", nargs="?")
    a = ap.parse_args(argv)
    try:
        target = resolve_target(a.target, a.cdp_url, os.environ)
        if a.cmd == "start":
            out = start(a.session, a.url, target, headed=not a.headless)
            print(out.strip())
            return 0
        results = run_check(target, headed=a.headed)
    except BrowserError as e:
        print(f"browser: {e}", file=sys.stderr)
        return 2
    width = max(len(r[0]) for r in results)
    for name, ok, detail in results:
        print(f"{'✓' if ok else '✗'} {name.ljust(width)}  {detail}".rstrip())
    failed = sum(1 for r in results if not r[1])
    print(f"target {target[0]}{' ' + target[1] if target[1] else ''}: "
          f"{len(results) - failed} of {len(results)} steps passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
