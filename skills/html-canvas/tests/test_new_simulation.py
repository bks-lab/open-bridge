"""new-simulation.py assembles one offline page and refuses to do it quietly wrong."""
from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from conftest import ASSETS, SCRIPTS, load_script, run_new_simulation

ARCHETYPES = ["flow", "worklist"]


@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_each_archetype_assembles_a_self_contained_page(archetype, tmp_path):
    out = tmp_path / "run.html"
    r = run_new_simulation(out, "--archetype", archetype, "--title", "Fixture run")
    assert r.returncode == 0, r.stderr
    text = out.read_text("utf-8")
    assert "global.Sim = {" in text and "new Sim.Clock(" in text
    assert "<!--@" not in text and "{{" not in text
    assert text.count("/* design-tokens:begin */") == 1
    assert '<html lang="en"' in text
    # single file, offline: no external script, stylesheet or font may be referenced
    assert "<script src=" not in text and "<link " not in text and "@import" not in text
    assert "wrote %s" % out in r.stdout


@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_lang_de_flips_the_default_language_everywhere(archetype, tmp_path):
    mod = load_script("new-simulation.py")
    out = tmp_path / "run.html"
    r = run_new_simulation(out, "--archetype", archetype, "--lang", "de",
                           "--title-de", "Lauf", "--title-en", "Run")
    assert r.returncode == 0, r.stderr
    text = out.read_text("utf-8")
    assert '<html lang="de"' in text and '<html lang="en"' not in text
    assert mod.LANG_BLOCK_DE in text and mod.LANG_BLOCK_EN not in text
    assert "|| 'de')" in text and "'data-lang', 'de')" in text
    assert "<title>Lauf</title>" in text


def test_list_names_both_archetypes(tmp_path):
    r = run_new_simulation(tmp_path / "unused.html", "--list")
    assert r.returncode == 0
    assert "flow" in r.stdout and "worklist" in r.stdout


def test_out_is_required():
    r = subprocess.run([sys.executable, str(SCRIPTS / "new-simulation.py"), "--archetype", "flow"],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "--out is required" in r.stderr


@pytest.fixture
def skill_copy(tmp_path):
    """A mutable copy of assets/ and scripts/, so a test can break one anchor."""
    root = tmp_path / "skillcopy"
    shutil.copytree(ASSETS, root / "assets")
    shutil.copytree(SCRIPTS, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    return root


@pytest.mark.parametrize("what,mutate", [
    ("head style close", lambda s: s.replace("\n</style>\n</head>", "\n</style>\n<!-- gone -->\n</head>")),
    ("body close", lambda s: s.replace("</body>", "</body></body>")),
    ("html lang", lambda s: s.replace('<html lang="en" class="">', '<html class="" lang="en">')),
])
def test_broken_shell_anchor_fails_loudly_and_writes_nothing(what, mutate, skill_copy, tmp_path):
    shell = skill_copy / "assets" / "shell.html"
    shell.write_text(mutate(shell.read_text("utf-8")), encoding="utf-8")
    out = tmp_path / "broken.html"
    r = run_new_simulation(out, "--archetype", "flow", "--lang", "de", scripts_dir=skill_copy / "scripts")
    assert r.returncode != 0
    assert "anchor" in r.stderr and what in r.stderr
    assert not out.exists()


def test_missing_fragment_marker_fails_loudly(skill_copy, tmp_path):
    frag = skill_copy / "assets" / "sim-flow.html"
    frag.write_text(frag.read_text("utf-8").replace("<!--@markup-->", ""), encoding="utf-8")
    out = tmp_path / "broken.html"
    r = run_new_simulation(out, "--archetype", "flow", scripts_dir=skill_copy / "scripts")
    assert r.returncode != 0 and "marker" in r.stderr
    assert not out.exists()


def test_existing_output_is_not_overwritten_without_force(tmp_path):
    out = tmp_path / "run.html"
    out.write_text("keep me", encoding="utf-8")
    r = run_new_simulation(out, "--archetype", "worklist")
    assert r.returncode != 0 and "--force" in r.stderr
    assert out.read_text("utf-8") == "keep me"
    r = run_new_simulation(out, "--archetype", "worklist", "--force")
    assert r.returncode == 0, r.stderr
    assert "global.Sim = {" in out.read_text("utf-8")
