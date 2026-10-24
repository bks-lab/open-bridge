# SPDX-License-Identifier: MIT
"""Contract for skills/bridge-audit/scripts/run-checkers.py.

The audit used to re-derive by hand what the repository's own checkers
already measure, and never ran them: a dead edge that `check-edges.py` exits 1
on did not appear in the audit report. The runner calls every checker the tree
carries and turns each red one into an audit finding.

Run: python3 -m pytest skills/bridge-audit/tests -q
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

RUNNER = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run-checkers.py"


def _tree(tmp: pathlib.Path) -> pathlib.Path:
    s = tmp / "scripts"
    s.mkdir()
    (s / "check-green.py").write_text("print('all fine')\n")
    (s / "validate-red.py").write_text("import sys\nprint('noise')\nprint('2 entries lack scope')\nsys.exit(1)\n")
    (s / "measure-context.py").write_text("print('within budget')\n")
    (s / "helper.py").write_text("raise SystemExit(1)\n")            # not a checker
    (s / "check-slow.py").write_text("import time\ntime.sleep(30)\n")
    return tmp


def run(root, *args):
    p = subprocess.run([sys.executable, str(RUNNER), "--repo-root", str(root), *args],
                       capture_output=True, text=True, timeout=60)
    return p


def test_discovers_exactly_the_checker_families(tmp_path):
    root = _tree(tmp_path)
    p = run(root, "--json", "--skip", "check-slow.py")
    names = sorted(r["checker"] for r in json.loads(p.stdout)["results"])
    assert names == ["check-green.py", "measure-context.py", "validate-red.py"], names


def test_a_red_checker_becomes_a_finding_with_its_last_line(tmp_path):
    root = _tree(tmp_path)
    p = run(root, "--json", "--skip", "check-slow.py")
    data = json.loads(p.stdout)
    assert p.returncode == 1
    (f,) = data["findings"]
    assert f["check_name"] == "checker:validate-red.py"
    assert f["target_path"] == "scripts/validate-red.py"
    assert f["severity"] == "P1"                    # a validator guards a contract
    assert f["summary"] == "validate-red.py exited 1"
    assert f["detail"] == "2 entries lack scope"
    assert "python3 scripts/validate-red.py" in f["fix"]


def test_all_green_exits_zero_and_reports_the_count(tmp_path):
    root = _tree(tmp_path)
    (root / "scripts" / "validate-red.py").write_text("print('ok')\n")
    p = run(root, "--skip", "check-slow.py")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "3 checker(s) ran, 3 green" in p.stdout, p.stdout


def test_a_hanging_checker_is_a_finding_not_a_hang(tmp_path):
    root = _tree(tmp_path)
    p = run(root, "--json", "--timeout", "1")
    slow = [f for f in json.loads(p.stdout)["findings"] if f["check_name"] == "checker:check-slow.py"]
    assert slow and "did not finish" in slow[0]["summary"], p.stdout


def test_text_report_groups_by_severity(tmp_path):
    root = _tree(tmp_path)
    p = run(root, "--skip", "check-slow.py")
    assert "P1" in p.stdout and "validate-red.py" in p.stdout, p.stdout


def test_the_summary_is_stable_when_the_count_in_the_output_moves(tmp_path):
    # The history fingerprint hashes the summary. A checker whose last line
    # carries a count would get a new fingerprint every time the count moved,
    # and a persistently red checker would never count as recurring.
    root = _tree(tmp_path)
    first = json.loads(run(root, "--json", "--skip", "check-slow.py").stdout)["findings"][0]
    (root / "scripts" / "validate-red.py").write_text(
        "import sys\nprint('3 entries lack scope')\nsys.exit(1)\n")
    second = json.loads(run(root, "--json", "--skip", "check-slow.py").stdout)["findings"][0]
    assert first["summary"] == second["summary"]
    assert first["detail"] != second["detail"]


def test_text_report_shows_the_detail_line(tmp_path):
    root = _tree(tmp_path)
    p = run(root, "--skip", "check-slow.py")
    assert "2 entries lack scope" in p.stdout, p.stdout
