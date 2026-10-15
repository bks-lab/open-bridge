# SPDX-License-Identifier: MIT
"""The cockpit demo on the website (docs/cockpit-demo/) is a generated copy of scripts/web.

scripts/build-cockpit-demo.py writes it; these tests hold the committed copy to the source, prove
that --check catches a changed byte or a stale file, that colors.css is the generator's output from
DESIGN.md, and that the demo's index.html turns mock mode on by itself.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build-cockpit-demo.py"
sys.dont_write_bytecode = True
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))

_spec = importlib.util.spec_from_file_location("build_cockpit_demo", SCRIPT)
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

from bridge_cockpit.design import stylesheet  # noqa: E402


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal repo: the cockpit's web folder and DESIGN.md, with the demo written once."""
    shutil.copytree(ROOT / "scripts" / "web", tmp_path / "scripts" / "web")
    shutil.copy(ROOT / "DESIGN.md", tmp_path / "DESIGN.md")
    demo.write(tmp_path)
    return tmp_path


def test_check_passes_on_the_committed_tree():
    result = subprocess.run([sys.executable, str(SCRIPT), "--check"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_changed_byte_in_a_copied_file_is_detected(tree: Path):
    assert demo.drift(tree) == []
    target = tree / "docs" / "cockpit-demo" / "logic.js"
    data = bytearray(target.read_bytes())
    data[-2] = ord("x") if data[-2] != ord("x") else ord("y")
    target.write_bytes(bytes(data))
    assert [path for path, _ in demo.drift(tree)] == ["logic.js"]
    assert demo.main(["--check", "--root", str(tree)]) == 1


def test_check_message_names_the_file_and_the_fix(tree: Path, capsys):
    (tree / "docs" / "cockpit-demo" / "jev" / "page.js").write_text("changed\n")
    assert demo.main(["--check", "--root", str(tree)]) == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert "jev/page.js" in text
    assert "python3 scripts/build-cockpit-demo.py --write" in text


def test_a_stale_file_is_drift_and_write_removes_it(tree: Path):
    stale = tree / "docs" / "cockpit-demo" / "old.js"
    stale.write_text("// gone from scripts/web\n")
    assert ("old.js", "stale") in demo.drift(tree)
    demo.write(tree)
    assert not stale.exists()
    assert demo.drift(tree) == []


def test_a_missing_file_is_drift(tree: Path):
    (tree / "docs" / "cockpit-demo" / "mock.js").unlink()
    assert ("mock.js", "missing") in demo.drift(tree)


def test_vendor_readme_is_not_copied(tree: Path):
    assert not (tree / "docs" / "cockpit-demo" / "vendor" / "README.md").exists()
    assert (tree / "docs" / "cockpit-demo" / "vendor" / "htm-preact-3.1.1.module.js").exists()


def test_colors_css_is_the_generator_output():
    if (ROOT / "bridge-config.yaml").is_file():
        pytest.skip("a configured instance keeps open-bridge's demo colours, its own DESIGN.md does not apply")
    committed = (ROOT / "docs" / "cockpit-demo" / "colors.css").read_text(encoding="utf-8")
    assert committed == stylesheet(ROOT)
    assert "--accent" in committed


def test_index_html_turns_mock_mode_on_first_thing():
    page = (ROOT / "docs" / "cockpit-demo" / "index.html").read_text(encoding="utf-8")
    head = page.split("<head>", 1)[1].lstrip()
    assert head.startswith("<script>"), "the mock bootstrap is the first thing in <head>"
    boot = head.split("</script>", 1)[0]
    assert "replaceState" in boot and "'mock'" in boot and "'1'" in boot
    assert '<meta name="robots" content="noindex">' in page
    assert "<title>Bridge Cockpit demo</title>" in page
    assert '<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">' in page
    assert (ROOT / "docs" / "assets" / "favicon.svg").is_file()
    assert '<script type="module" src="app.js"></script>' in page
    assert page.index("replaceState") < page.index('src="app.js"')


def test_the_bootstrap_parses_as_javascript(tmp_path: Path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    page = (ROOT / "docs" / "cockpit-demo" / "index.html").read_text(encoding="utf-8")
    boot = page.split("<head>", 1)[1].split("<script>", 1)[1].split("</script>", 1)[0]
    js = tmp_path / "boot.js"
    js.write_text(boot)
    result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_other_file_is_a_byte_copy():
    out = ROOT / "docs" / "cockpit-demo"
    for rel, data in demo.expected(ROOT).items():
        if rel in ("index.html", "colors.css"):
            continue
        assert (ROOT / "scripts" / "web" / rel).read_bytes() == data, rel
        assert (out / rel).read_bytes() == data, rel


# ---------------------------------------------------------------- a configured instance
#
# The demo shows open-bridge in open-bridge's colours. An instance with a DESIGN.md of its own
# would get a different colors.css from the generator; --check must not call that drift, and
# --write must not bake the instance's colours into a file that ships upstream.

def _instance(tree: Path) -> Path:
    (tree / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    design = tree / "DESIGN.md"
    text = design.read_text(encoding="utf-8")
    # a colour of its own: every hex colour the file uses becomes another one, whatever the Bridge's palette
    text = re.sub(r"#[0-9A-Fa-f]{6}\b", lambda m: "#123456" if m.group(0).upper() != "#123456" else "#654321", text)
    design.write_text(text, encoding="utf-8")
    assert stylesheet(tree) != (tree / "docs" / "cockpit-demo" / "colors.css").read_text(encoding="utf-8")
    return tree


def test_an_instance_with_its_own_design_is_not_drift(tree: Path):
    assert demo.drift(_instance(tree)) == []
    assert demo.main(["--check", "--root", str(tree)]) == 0


def test_write_in_an_instance_keeps_the_demo_colours(tree: Path):
    before = (tree / "docs" / "cockpit-demo" / "colors.css").read_bytes()
    demo.write(_instance(tree))
    assert (tree / "docs" / "cockpit-demo" / "colors.css").read_bytes() == before


def test_an_instance_still_catches_a_changed_copied_file(tree: Path):
    _instance(tree)
    (tree / "scripts" / "web" / "app.js").write_text("// changed\n", encoding="utf-8")
    assert ("app.js", "changed") in demo.drift(tree)
