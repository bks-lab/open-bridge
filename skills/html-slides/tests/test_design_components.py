"""A DESIGN.md can ask the `design` preset for more than colours and families, each
part opt-in, so a design without it builds the deck it built before:

  colour roles  highlight / glow  the arc under a heading and its glow
                gradient-via      a middle stop for the gradient numbers
  components    slide-display, slide-heading, slide-body, slide-label: weight,
                letter spacing and line height, from a typography role or given directly
                slide-arc: the arc's line width
                knowledge-term: how a knowledge term looks (html-canvas design-to-css)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from engine_testlib import open_deck
from slides_testlib import FIXTURES
from test_new_deck import run  # noqa: F401

DESIGN = FIXTURES / "tooling" / "DESIGN.md"
PACK = Path(__file__).resolve().parents[2] / "html-canvas" / "scripts" / "knowledge-pack.py"
KFIX = Path(__file__).resolve().parents[2] / "html-canvas" / "tests" / "fixtures" / "knowledge"

SLIDES = """
<section class="slide slide--content" id="one">
  <p class="slide__label">Label</p>
  <h1 class="slide__display">Display</h1>
  <h2 class="slide__heading">A heading</h2>
  <div class="slide__arc" aria-hidden="true"></div>
  <p class="slide__body">Body copy with a <button class="kp-term" data-know="latency" type="button">latency</button>.</p>
  <div class="slide__stats"><div class="slide__stat"><span class="slide__stat-value">42</span>
  <span class="slide__stat-label">answers</span></div></div>
</section>
"""

EXTRA_LIGHT = {"highlight": "#A3249E", "glow": "#3F37C9", "gradient-from": "#B8327F",
               "gradient-via": "#9A2FD0", "gradient-to": "#4A47D6"}
EXTRA_DARK = {"highlight": "#D84CFF", "glow": "#6157FF", "gradient-from": "#FF76C8",
              "gradient-via": "#D84CFF", "gradient-to": "#6F7BFF"}

COMPONENTS = """
components:
  slide-display:
    typography: "{typography.display}"
    letterSpacing: -0.035em
  slide-heading:
    fontWeight: 600
    letterSpacing: -0.025em
    lineHeight: 1.06
  slide-body:
    fontWeight: 300
    lineHeight: 1.4
  slide-label:
    fontWeight: 500
    letterSpacing: 0.08em
  slide-arc:
    width: 2px
  knowledge-term:
    underline: solid
    underlineColor: "{colors.highlight}"
    icon: bulb
"""


def design(tmp: Path, colours: bool = True, components: str = "") -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    text = DESIGN.read_text("utf-8")
    if colours:
        text = text.replace("colors:\n", "colors:\n" + "".join('  %s: "%s"\n' % kv for kv in EXTRA_LIGHT.items()), 1)
        text = text.replace("colorsDark:\n", "colorsDark:\n" + "".join('  %s: "%s"\n' % kv for kv in EXTRA_DARK.items()), 1)
    head, sep, body = text.partition("\n---\n")
    out = tmp / "brand" / "DESIGN.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(head + ("\n" + components.strip() if components else "") + sep + body, encoding="utf-8")
    return out


def build(tmp: Path, design_md: Path, name: str = "deck.html", theme: str = "light") -> str:
    tmp = design_md.parent.parent
    frag = tmp / "slides.html"
    frag.write_text(SLIDES, encoding="utf-8")
    out = tmp / name
    run("--title", "Components", "--lang", "en", "--out", out, "--no-embed-fonts", "--slides", frag,
        "--design", design_md, "--theme-default", theme, "--blocks", "knowledge")
    pack = tmp / "pack.json"
    for args in (("build", "--terms", KFIX / "terms.yaml", "--corpus", KFIX / "corpus", "--out", pack),
                 ("embed", out, "--pack", pack)):
        r = subprocess.run([sys.executable, str(PACK), *map(str, args)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    return out.read_text("utf-8")


LOOK = """() => { const q = s => document.querySelector(s), cs = (s, p) => getComputedStyle(q(s), p || null);
  const h = cs('.slide__heading'), d = cs('.slide__display'), b = cs('.slide__body'), l = cs('.slide__label'),
        a = cs('.slide__arc'), v = cs('.slide__stat-value'), t = cs('.kp-term'), ta = cs('.kp-term', '::after');
  return {hw: h.fontWeight, hls: h.letterSpacing, hlh: h.lineHeight, hfs: parseFloat(h.fontSize),
          dw: d.fontWeight, dls: d.letterSpacing, bw: b.fontWeight, blh: b.lineHeight, bfs: parseFloat(b.fontSize),
          lw: l.fontWeight, lls: l.letterSpacing, lfs: parseFloat(l.fontSize),
          arc: a.borderTopColor, arcw: a.borderTopWidth, glow: a.filter, num: v.backgroundImage,
          kp: t.textDecorationStyle, kpc: t.textDecorationColor, kpa: ta.display}; }"""


def rgb(hexv: str) -> str:
    h = hexv.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@pytest.fixture
def plain(open_html, tmp_path):
    return open_deck(open_html, build(tmp_path, design(tmp_path / "plain", colours=False))).evaluate(LOOK)


@pytest.fixture
def full(open_html, tmp_path):
    return open_deck(open_html, build(tmp_path, design(tmp_path / "full", components=COMPONENTS))).evaluate(LOOK)


def test_without_them_the_deck_is_built_as_before(tmp_path):
    html = build(tmp_path, design(tmp_path, colours=False))
    assert "--arc:" not in html and "--stat-gradient:" not in html and "--kp-line" not in html.split("/* @block")[0]
    assert "design-components" not in html


def test_without_them_the_preset_look_stays(plain):
    assert plain["hw"] == "500" and plain["dw"] == "500", plain
    assert plain["arcw"] == "1px" and plain["kp"] == "dashed" and plain["kpa"] == "none", plain


def test_typography_comes_from_the_design(full, plain):
    assert full["hw"] == "600" and full["dw"] == "500", full   # display: weight of the role
    assert abs(float(full["hls"][:-2]) - (-0.025 * full["hfs"])) < 0.05, full
    assert abs(float(full["hlh"][:-2]) - 1.06 * full["hfs"]) < 0.5, full
    assert full["bw"] == "300" and abs(float(full["blh"][:-2]) - 1.4 * full["bfs"]) < 0.5, full
    assert full["lw"] == "500" and abs(float(full["lls"][:-2]) - 0.08 * full["lfs"]) < 0.05, full
    assert full["hfs"] == plain["hfs"], "sizes stay with the engine"


def test_the_arc_takes_highlight_glow_and_width(full, plain):
    assert full["arc"] == rgb(EXTRA_LIGHT["highlight"]) and full["arcw"] == "2px", full
    assert rgb(EXTRA_LIGHT["glow"]) in full["glow"], full
    assert plain["arc"] != full["arc"]


def test_the_numbers_run_through_the_middle_stop(full, plain):
    assert rgb(EXTRA_LIGHT["gradient-via"]) in full["num"], full
    assert rgb(EXTRA_LIGHT["gradient-via"]) not in plain["num"]


def test_the_knowledge_term_follows_the_design(full):
    assert full["kp"] == "solid" and full["kpc"] == rgb(EXTRA_LIGHT["highlight"]) and full["kpa"] == "inline-block", full


def test_a_component_with_a_wrong_reference_stops_the_build(tmp_path):
    bad = design(tmp_path, components='components:\n  slide-heading:\n    typography: "{typography.nope}"\n')
    frag = tmp_path / "slides.html"
    frag.write_text(SLIDES, encoding="utf-8")
    r = run("--title", "X", "--out", tmp_path / "d.html", "--no-embed-fonts", "--slides", frag,
            "--design", bad, check=False)
    assert r.returncode != 0 and "slide-heading" in r.stderr, r.stderr


def test_dark_mode_takes_the_dark_roles(open_html, tmp_path):
    html = build(tmp_path, design(tmp_path / "dark", components=COMPONENTS), theme="dark")
    look = open_deck(open_html, html).evaluate(LOOK)
    assert look["arc"] == rgb(EXTRA_DARK["highlight"]) and rgb(EXTRA_DARK["glow"]) in look["glow"], look
    assert look["kpc"] == rgb(EXTRA_DARK["highlight"]) and rgb(EXTRA_DARK["gradient-via"]) in look["num"], look


def test_usual_type_values_pass(tmp_path):
    ok = design(tmp_path / "usual", components="components:\n  slide-heading: {fontWeight: 450, letterSpacing: normal, lineHeight: 120%}\n")
    build(tmp_path, ok)   # raises on a refused value
