#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run every checker the tree carries and report the red ones as audit findings.

The repository already ships deterministic checkers (scripts/check-*.py,
scripts/validate-*.py, scripts/measure-context.py), each green in upstream CI.
An instance whose CI never runs meets them only when somebody types them, and
the audit, the one pass meant to find drift, re-derived parts of what they
measure by hand instead of running them. This runner is the audit's Check 16:
discover, run each bare (exactly as CI does), and turn a non-zero exit into a
finding. The summary is the stable "<checker> exited <rc>", and the
checker's own last line goes into `detail`: the history fingerprint hashes the
summary, and a last line that carries a count would give a persistently red
checker a new fingerprint on every run.

Discovery is a glob, never a list, so a checker added tomorrow is audited
tomorrow. A checker that does not finish within --timeout is a finding too.

Usage:
  python3 skills/bridge-audit/scripts/run-checkers.py            # text report
  python3 skills/bridge-audit/scripts/run-checkers.py --json     # for the history JSON
  ... --skip check-site-links.py --timeout 60

Exit 0 when every checker is green, 1 when there is a finding.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

PATTERNS = ("check-*.py", "validate-*.py", "measure-context.py")

# A validator guards a contract that other files are written against, and the
# budget guard a ceiling the harness enforces by dropping content silently: P1.
# Every other checker reports drift that misleads but breaks nothing yet: P2.
P1_PREFIXES = ("validate-", "measure-context", "check-secret-")


def severity(name: str) -> str:
    return "P1" if name.startswith(P1_PREFIXES) else "P2"


def discover(root: pathlib.Path, skip: set[str]) -> list[pathlib.Path]:
    found = {p for pat in PATTERNS for p in (root / "scripts").glob(pat) if p.is_file()}
    return sorted((p for p in found if p.name not in skip), key=lambda p: p.name)


def last_line(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def run_one(root: pathlib.Path, script: pathlib.Path, timeout: float) -> dict:
    t0 = time.monotonic()
    try:
        p = subprocess.run([sys.executable, str(script)], cwd=root, capture_output=True,
                           text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = None, ""
    return {"checker": script.name, "rc": rc, "seconds": round(time.monotonic() - t0, 2),
            "tail": last_line(out)}


def finding(r: dict, timeout: float) -> dict:
    name = r["checker"]
    if r["rc"] is None:
        summary = f"{name} did not finish within {timeout:g} s"
    else:
        summary = f"{name} exited {r['rc']}"
    return {"check_name": f"checker:{name}", "target_path": f"scripts/{name}",
            "severity": severity(name), "summary": summary, "detail": r["tail"],
            "fix": f"run `python3 scripts/{name}` and follow its output"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", type=pathlib.Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip", action="append", default=[], help="checker file name to leave out")
    ap.add_argument("--timeout", type=float, default=120.0, help="seconds per checker")
    a = ap.parse_args(argv)
    root = a.repo_root
    if root is None:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        root = pathlib.Path(top.stdout.strip() or ".")
    root = root.resolve()

    results = [run_one(root, s, a.timeout) for s in discover(root, set(a.skip))]
    findings = [finding(r, a.timeout) for r in results if r["rc"] != 0]

    if a.json:
        print(json.dumps({"results": results, "findings": findings}, indent=1, ensure_ascii=False))
    else:
        total = sum(r["seconds"] for r in results)
        green = len(results) - len(findings)
        print(f"Check 16 (checkers): {len(results)} checker(s) ran, {green} green, {total:.1f} s")
        for sev in ("P1", "P2"):
            hits = [f for f in findings if f["severity"] == sev]
            if hits:
                print(f"\n{sev}: checkers ({len(hits)} finding(s))")
                for f in hits:
                    print(f"  {f['summary']}")
                    if f["detail"]:
                        print(f"    {f['detail']}")
                    print(f"  → {f['fix']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
