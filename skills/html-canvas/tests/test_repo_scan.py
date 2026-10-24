"""repo-scan.py counts and parses; it must do so deterministically on a known tree."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from conftest import FIXTURES, SCRIPTS


def scan(path, *flags):
    return subprocess.run([sys.executable, str(SCRIPTS / "repo-scan.py"), str(path), *flags],
                          capture_output=True, text=True)


@pytest.fixture
def tree(tmp_path):
    """The fixture repo plus directories the scanner must skip, built at test time."""
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "repo", root)
    for skipped in ("node_modules/dep", "target", ".git", "dist"):
        (root / skipped).mkdir(parents=True)
        (root / skipped / "main.py").write_text("x = 1\n" * 50, encoding="utf-8")
    return root


def test_json_inventory_of_the_fixture_tree(tree):
    r = scan(tree, "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["repo"] == "repo"
    assert data["languages"]["Python"]["files"] == 2
    assert data["languages"]["TypeScript"]["loc"] == 2
    assert data["entry_points"] == ["src/__main__.py", "src/main.py", "web/index.ts"]
    manifests = {m["file"]: m for m in data["manifests"]}
    assert manifests["pyproject.toml"]["name"] == "widget-service"
    assert manifests["pyproject.toml"]["deps"] == ["click", "pyyaml", "requests"]
    assert manifests["package.json"]["name"] == "widget-web"
    assert manifests["package.json"]["deps"] == ["react", "vite"]
    assert {d["path"] for d in data["docs"]} == {"docs/architecture.md", "README.md"}


def test_vendored_and_build_directories_are_skipped(tree):
    data = json.loads(scan(tree, "--json").stdout)
    assert data["languages"]["Python"]["files"] == 2          # the 4 planted main.py files are not counted
    assert not any(("node_modules" in e or "target" in e or "dist" in e) for e in data["entry_points"])
    assert not {"node_modules", "target", "dist", ".git"} & set(data["top_level"])


def test_text_report_has_every_section(tree):
    r = scan(tree)
    assert r.returncode == 0
    for heading in ("## Languages (by LOC)", "## Entry-point candidates", "## Dependency manifests",
                    "## Top-level structure", "## Documentation"):
        assert heading in r.stdout
    assert "src/main.py" in r.stdout


def test_output_is_deterministic(tree):
    assert scan(tree, "--json").stdout.replace(str(tree), "") == scan(tree, "--json").stdout.replace(str(tree), "")


def test_entry_points_under_a_fixtures_dir_are_ignored(tmp_path):
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    assert json.loads(scan(tmp_path, "--json").stdout)["entry_points"] == ["app.py"]


def test_a_path_that_is_not_a_directory_fails_with_a_message(tmp_path):
    r = scan(tmp_path / "missing")
    assert r.returncode != 0 and "not a directory" in r.stderr
