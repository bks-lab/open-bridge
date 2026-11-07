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


# --- every text role, layout, numbers, bleed veil (second round) --------------------------

ROLES_SLIDES = """
<section class="slide slide--bleed" id="t">
  <div class="slide__scrim"></div>
  <div class="slide__content"><p class="slide__label">Label</p><h1 class="slide__display">Title</h1>
  <p class="slide__subtitle">Subtitle line</p></div>
</section>
<section class="slide slide--content" id="c">
  <p class="slide__label">Eyebrow</p>
  <h2 class="slide__heading">Heading</h2>
  <div class="slide__arc" aria-hidden="true"></div>
  <h3 class="probe-h3">Subhead</h3><h4 class="probe-h4">Small head</h4>
  <ul class="slide__bullets"><li>First point</li><li>Second point</li></ul>
  <ol class="slide__numbered"><li><strong>Item title</strong><span>Item text</span></li></ol>
  <div class="slide__stats"><div class="slide__stat"><span class="slide__stat-value">42</span>
  <span class="slide__stat-label">answers</span></div></div>
  <div class="slide__result"><p class="slide__result-label">Result</p><p class="slide__result-value">Value</p></div>
  <table class="data-table"><thead><tr><th>Head</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody></table>
</section>
"""

ROLES = """
components:
  slide-layout: {align: top, paddingTop: 8vh, paddingX: 5vw}
  slide-subtitle: {fontFamily: display, fontWeight: 500, fontSize: 2.08vw}
  slide-heading: {fontWeight: 600, fontSize: 3.54vw}
  slide-label: {fontWeight: 500, fontSize: 1.47vw, textColor: "{colors.on-surface-muted}"}
  slide-body: {fontWeight: 300, fontSize: 1.77vw, lineHeight: 1.4}
  slide-small: {fontWeight: 300, fontSize: 1.51vw}
  slide-item-title: {fontFamily: display, fontWeight: 500, fontSize: 1.98vw}
  slide-subhead: {fontFamily: display, fontWeight: 500, fontSize: 2.5vw}
  slide-result-value: {fontFamily: display, fontWeight: 500, fontSize: 2.5vw}
  slide-stat: {fontSize: "clamp(40px, 5.4vw, 120px)"}
  slide-table-head: {fontFamily: body, fontWeight: 600, fontSize: 1.51vw, textTransform: none}
  slide-number: {marker: plain, fontFamily: body, fontWeight: 600}
  slide-arc: {width: 2px, span: 100%, baseline: "{colors.border}"}
  slide-bleed: {veil: 55, dim: 0.36}
"""

LOOK2 = """() => { const g = (s, p) => getComputedStyle(document.querySelector(s), p || null);
  const W = innerWidth, px = v => +(parseFloat(v) / W * 100).toFixed(2);
  const c = document.querySelector('#c'), h = document.querySelector('#c .slide__heading');
  return {sub: [g('.slide__subtitle').fontFamily.split(',')[0], g('.slide__subtitle').fontWeight, px(g('.slide__subtitle').fontSize)],
    head: [g('#c .slide__heading').fontWeight, px(g('#c .slide__heading').fontSize)],
    label: [g('#c .slide__label').fontWeight, px(g('#c .slide__label').fontSize), g('#c .slide__label').color],
    li: [g('.slide__bullets li').fontWeight, px(g('.slide__bullets li').fontSize)],
    small: [g('.slide__stat-label').fontWeight, px(g('.slide__stat-label').fontSize), px(g('.slide__numbered > li > span').fontSize)],
    item: [g('.slide__numbered > li > strong').fontFamily.split(',')[0], g('.slide__numbered > li > strong').fontWeight, px(g('.slide__numbered > li > strong').fontSize)],
    result: [g('.slide__result-value').fontWeight, px(g('.slide__result-value').fontSize)],
    h3: [g('.probe-h3').fontWeight, px(g('.probe-h3').fontSize)], h4: [g('.probe-h4').fontWeight, px(g('.probe-h4').fontSize)],
    th: [g('.data-table th').fontFamily.split(',')[0], g('.data-table th').textTransform],
    num: [g('.slide__numbered > li', '::before').backgroundColor, g('.slide__numbered > li', '::before').borderTopWidth],
    left: h.getBoundingClientRect().left / W,
    top: (h.getBoundingClientRect().top - c.getBoundingClientRect().top) / c.getBoundingClientRect().height,
    arcW: document.querySelector('#c .slide__arc').getBoundingClientRect().width,
    colW: c.querySelector('.slide__heading').parentElement.getBoundingClientRect().width,
    base: g('#c .slide__arc', '::after').backgroundColor,
    veil: g('#t .slide__content', '::before').backgroundImage}; }"""


def build2(tmp: Path, components: str) -> str:
    d = design(tmp, components=components)
    frag = tmp / "roles.html"
    frag.write_text(ROLES_SLIDES, encoding="utf-8")
    out = tmp / "roles-deck.html"
    run("--title", "Roles", "--lang", "en", "--out", out, "--no-embed-fonts", "--slides", frag,
        "--design", d, "--theme-default", "light")
    return out.read_text("utf-8")


def open_slide(open_html, html: str, idx: int):
    pg = open_deck(open_html, html)
    pg.evaluate("i => window.SlideDeck.goTo(i)", idx)
    pg.wait_for_timeout(700)
    return pg


def test_every_text_role_follows_the_design(open_html, tmp_path):
    look = open_slide(open_html, build2(tmp_path / "r", ROLES), 1).evaluate(LOOK2)
    assert look["head"] == ["600", 3.54], look
    assert look["label"][:2] == ["500", 1.47], look
    assert look["li"] == ["300", 1.77], look
    assert look["small"] == ["300", 1.51, 1.51], look
    assert look["item"] == ["Fixture Display", "500", 1.98] or look["item"][1:] == ["500", 1.98], look
    assert look["result"] == ["500", 2.5], look
    assert look["h3"] == ["500", 2.5] and look["h4"] == ["500", 1.98], look
    assert look["th"][1] == "none", look


def test_the_label_takes_its_colour_role(open_html, tmp_path):
    look = open_slide(open_html, build2(tmp_path / "r", ROLES), 1).evaluate(LOOK2)
    muted = DESIGN.read_text("utf-8").split("on-surface-muted:")[1].split('"')[1]
    assert look["label"][2] == rgb(muted), look


def test_numbers_can_drop_their_box(open_html, tmp_path):
    look = open_slide(open_html, build2(tmp_path / "r", ROLES), 1).evaluate(LOOK2)
    assert look["num"] == ["rgba(0, 0, 0, 0)", "0px"], look


def test_top_alignment_full_arc_and_baseline(open_html, tmp_path):
    look = open_slide(open_html, build2(tmp_path / "r", ROLES), 1).evaluate(LOOK2)
    assert look["top"] < 0.2, look
    assert abs(look["left"] - 0.05) < 0.005, look
    assert look["arcW"] > 600, look
    assert look["base"] != "rgba(0, 0, 0, 0)", look


def test_the_bleed_veil_follows_the_design(open_html, tmp_path):
    look = open_slide(open_html, build2(tmp_path / "r", ROLES), 0).evaluate(LOOK2)
    assert "55%" in look["veil"] or "0.55" in look["veil"], look
    assert look["sub"][1:] == ["500", 2.08], look


def test_without_the_roles_the_preset_look_stays(open_html, tmp_path):
    look = open_slide(open_html, build2(tmp_path / "p", ""), 1).evaluate(LOOK2)
    assert look["head"][0] == "500" and look["arcW"] <= 521 and look["num"][1] == "1px", look
    assert look["base"] == "rgba(0, 0, 0, 0)", look


@pytest.mark.parametrize("bad", [
    "components:\n  slide-heading: {fontSize: big}\n",
    "components:\n  slide-label: {textColor: \"#ff00ff\"}\n",
    "components:\n  slide-layout: {align: sideways}\n",
    "components:\n  slide-number: {marker: star}\n",
    "components:\n  slide-heading: {fontFamily: comic}\n",
    "components:\n  slide-bleed: {veil: 140}\n",
])
def test_wrong_component_values_stop_the_build(tmp_path, bad):
    d = design(tmp_path / "b", components=bad)
    frag = tmp_path / "s.html"
    frag.write_text(ROLES_SLIDES, encoding="utf-8")
    r = run("--title", "X", "--out", tmp_path / "x.html", "--no-embed-fonts", "--slides", frag, "--design", d, check=False)
    assert r.returncode != 0 and "components.slide-" in r.stderr, r.stderr


def test_dark_mode_dims_the_photo_without_tint(open_html, tmp_path):
    d = design(tmp_path / "dim", components=ROLES)
    frag = tmp_path / "roles.html"
    frag.write_text(ROLES_SLIDES.replace('<div class="slide__scrim">', '<img class="slide__bg" src="" alt=""><div class="slide__scrim">'), encoding="utf-8")
    out = tmp_path / "dim.html"
    run("--title", "Dim", "--lang", "en", "--out", out, "--no-embed-fonts", "--slides", frag, "--design", d, "--theme-default", "dark")
    pg = open_deck(open_html, out.read_text("utf-8"))
    st = pg.evaluate("""() => ({bg: getComputedStyle(document.querySelector('#t .slide__bg')).filter,
        scrim: getComputedStyle(document.querySelector('#t .slide__scrim')).backgroundImage,
        veil: getComputedStyle(document.querySelector('#t .slide__content'), '::before').backgroundImage})""")
    assert st == {"bg": "brightness(0.36)", "scrim": "none", "veil": "none"}, st
