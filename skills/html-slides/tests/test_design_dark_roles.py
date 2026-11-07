"""A text role a DESIGN.md never declared for dark mode must not reach the dark deck as its light colour.

The legacy shape (`dark-<role>` keys inside `colors:`) often has a dark ground and dark ink but
no dark caption colour. The map used to repeat the light value in the `.theme-dark` group, so
`--text-dim` and `--accent` stayed gray-500 on a gray-900 ground (3.7:1) and verify-page failed
the deck on contrast. presets/design.map.yaml now names what those roles derive from when the
dark palette lacks them (`dark-fallback`); a DESIGN.md that declares them is read as before.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from slides_testlib import FIXTURES, PRESETS, SKILL, filled, slide_type_snippets

CANVAS = SKILL.parent / "html-canvas" / "scripts"
NEW_DECK = SKILL / "scripts" / "new-deck.py"
MAP = PRESETS / "design.map.yaml"
REPO_DESIGN = SKILL.parents[1] / "DESIGN.md"
LEGACY = FIXTURES / "tooling" / "DESIGN-legacy.md"
CURRENT = FIXTURES / "tooling" / "DESIGN.md"

# What a deck of prose looks like: title, subtitle, label, heading, body, bullets.
PROSE = """\
<section class="slide slide--title" id="title">
  <div class="slide__content">
    <h1 class="slide__display">Dark roles</h1>
    <p class="slide__subtitle">A subtitle in the caption colour.</p>
  </div>
</section>
<section class="slide slide--content" id="one">
  <div class="slide__inner">
    <div>
      <p class="slide__label">Label</p>
      <h2 class="slide__heading">One</h2>
      <p class="slide__body">Body text on the slide.</p>
      <ul class="slide__bullets">
        <li>First point</li>
        <li>Second point</li>
      </ul>
    </div>
  </div>
</section>
"""


def map_css(design: Path) -> dict[str, dict[str, str]]:
    """The map output as {selector: {variable: value}}."""
    out = subprocess.run([sys.executable, str(CANVAS / "design-to-css.py"), str(design), "--map", str(MAP)],
                         check=True, capture_output=True, text=True).stdout
    body = re.sub(r"/\*.*?\*/", "", out, flags=re.S)
    return {sel.strip(): dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", decls))
            for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", body)}


def build(tmp_path: Path, design: Path, slides: str) -> Path:
    shutil.copyfile(design, tmp_path / "DESIGN.md")
    (tmp_path / "slides.html").write_text(slides, encoding="utf-8")
    out = tmp_path / "deck.html"
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Dark roles", "--slides", str(tmp_path / "slides.html"),
                    "--out", str(out), "--force", "--no-embed-fonts"], check=True, capture_output=True)
    return out


def contrast_findings(path: Path, *flags: str) -> list[dict]:
    proc = subprocess.run([sys.executable, str(CANVAS / "verify-page.py"), str(path), "--design",
                           str(path.parent / "DESIGN.md"), "--json", *flags], capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    found = json.loads(proc.stdout)["pages"][0].get("findings", [])
    skipped = [f for f in found if f.get("rule") == "browser-skipped"]
    if skipped:
        pytest.skip(skipped[0]["message"])
    return [f for f in found if f.get("rule") == "contrast"]


def all_types() -> str:
    return "\n".join(filled(h.replace("{color}", "accent")) for _, h in slide_type_snippets())


# --- the map ---------------------------------------------------------------------------------

def test_map_names_a_dark_fallback_for_its_neutral_text_roles():
    vars_ = yaml.safe_load(MAP.read_text("utf-8"))["vars"]
    for name in ("text-dim", "accent"):
        fallback = vars_[name]["dark-fallback"]
        assert fallback["role"] == "on-surface" and fallback.get("with") == "surface", (name, fallback)
        assert 0 < fallback["mix"] < 100, "a derived colour, never the plain ink: it stays a caption"
    for name in ("text", "bg", "border"):
        spec = vars_[name]
        assert isinstance(spec, str) or "dark-fallback" not in spec, "%s has a dark value of its own" % name


def test_a_dark_palette_without_dark_captions_does_not_repeat_the_light_ones():
    groups = map_css(LEGACY)
    light, dark = groups[":root, .theme-light"], groups[".theme-dark"]
    assert light["text-dim"] == "#666666" and light["accent"] == "#666666"
    assert dark["bg"] == "#111111" and dark["text"] == "#DDDDDD"
    for name in ("text-dim", "accent"):
        assert dark[name] != light[name], "%s: the light value reached the dark group" % name
        assert dark[name] == "color-mix(in srgb, #DDDDDD 72%, #111111)", (name, dark[name])


def test_a_dark_value_the_design_declares_is_used_as_written():
    groups = map_css(CURRENT)
    dark = groups[".theme-dark"]
    assert dark["text-dim"] == "#ABA79E" and dark["accent"] == "#8DB4E2", dark


# --- the deck, in a browser ------------------------------------------------------------------

def test_legacy_dark_deck_reads_at_contrast_in_both_themes(tmp_path):
    pytest.importorskip("playwright.sync_api")
    deck = build(tmp_path, LEGACY, all_types())
    assert contrast_findings(deck, "--browser") == []


def test_repo_design_deck_reads_at_contrast_in_both_themes(tmp_path):
    """The Bridge's own DESIGN.md, built into a deck, passes the deck gate: the exact case that
    failed with `dark: 3.67:1 under 4.5:1 for <p>`."""
    pytest.importorskip("playwright.sync_api")
    deck = build(tmp_path, REPO_DESIGN, PROSE)
    assert contrast_findings(deck, "--deck") == []
