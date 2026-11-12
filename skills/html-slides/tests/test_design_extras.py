"""Design-driven parts of a deck beyond the text roles (reference/deck-build.md).

Each is opt-in: a design that names none of them gets exactly the CSS it got before
(pinned byte for byte), and the engine's new custom properties fall back to the old
literal values. A design may ask for: font smoothing, a top slot and photo text colour
on a full-bleed slide, a photo share, the arc's height, fade and glow, a four-stop or
named number gradient and a minimum width for big numbers, numbers painted by the
gradient with a rule under them, bullets, spacing, a quote bar, the result plate, the
deck view toolbar and its Present button, and the mode a deck opens in.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine_testlib import deck, open_deck, slide
from slides_testlib import ASSETS, FIXTURES, SKILL, load_script

NEW_DECK = SKILL / "scripts" / "new-deck.py"
DESIGN = FIXTURES / "tooling" / "DESIGN.md"
OLD_KEYS = FIXTURES / "tooling" / "design-old-keys.yaml"
OLD_CSS = FIXTURES / "tooling" / "design-old-keys.css"
ND = load_script("new-deck.py")

EXTRA_LIGHT = {"highlight": "#7A2A68", "glow": "#3F37C9", "gradient-from": "#94306A",
               "gradient-via": "#7036A0", "gradient-via-2": "#5440B0", "gradient-to": "#3450A8",
               "on-photo": "#FFFFFF", "ink": "#101024"}
EXTRA_DARK = {"highlight": "#C060E0", "glow": "#5068F0", "gradient-from": "#F08AB0",
              "gradient-via": "#C060E0", "gradient-via-2": "#8078E8", "gradient-to": "#6090F0",
              "on-photo": "#FFFFFF", "ink": "#101024"}

EXTRAS = """
defaultMode: dark
gradients:
  metric: "linear-gradient(100deg, {colors.gradient-from} 0%, {colors.gradient-via} 35%, {colors.gradient-via-2} 70%, {colors.gradient-to} 100%)"
  accent: "linear-gradient(120deg, {colors.highlight} 0%, {colors.glow} 100%)"
shadows:
  plate: "0 10px 30px color-mix(in srgb, {colors.ink} 55%, transparent)"
# ---- components ----
components:
  slide-text: {smoothing: antialiased}
  slide-media: {share: 4/15, gap: 64px}
  slide-arc: {width: 2px, height: 18px, fade: 12%, glow: 5px 13px}
  slide-bleed: {padding: 64px, textColor: "{colors.on-photo}"}
  slide-stat: {gradient: "{gradients.metric}", minWidth: 10em}
  slide-number: {marker: plain, paint: gradient, rule: "{colors.highlight}", ruleWidth: 2px}
  slide-bullet: {style: disc, marker: "{colors.on-surface-muted}", indent: 1.2em, gap: 6px}
  slide-spacing: {afterHeading: 22px, labelToHeading: 9px, betweenBlocks: 20px, beforeHeading: 38px}
  slide-quote: {bar: "{gradients.accent}", barWidth: 3px, maxWidth: 60ch}
  plate:
    background: "color-mix(in srgb, {colors.highlight} 20%, transparent)"
    border: "1px solid color-mix(in srgb, {colors.on-surface} 14%, transparent)"
    shadow: "{shadows.plate}"
    backdropFilter: "blur(12px)"
    rounded: 16px
  toolbar: {backgroundColor: "{colors.ink}", textColor: "{colors.on-surface}", padding: 10px 24px}
  button-present: {background: "{gradients.accent}", textColor: "{colors.on-primary}", fontWeight: 500, rounded: 9999px}
  deck-view: {backgroundColor: "{colors.ink}", gap: 32px, slideShadow: "0 12px 40px rgb(0 0 0 / 0.4)"}
"""

SLIDES = """
<section class="slide slide--bleed" id="cover">
  <div class="slide__bg slide__bg--gradient"></div>
  <div class="slide__top"><p class="slide__label">Eyebrow</p></div>
  <div class="slide__content"><h1 class="slide__display">Title</h1><p class="slide__body">A line</p></div>
</section>
<section class="slide" id="body">
  <p class="slide__label">Label</p>
  <h2 class="slide__heading">Heading</h2>
  <p class="slide__body">Body</p>
  <div class="slide__arc slide__arc--half" aria-hidden="true"></div>
  <ul class="slide__bullets"><li>One</li><li>Two</li></ul>
  <p class="slide__body slide__body--sm">Small print</p>
  <blockquote class="slide__quote"><p>A quote</p></blockquote>
</section>
<section class="slide slide--media" id="media">
  <div class="slide__media" role="img" aria-label="photo"></div>
  <div class="slide__content">
    <div class="slide__stats"><div class="slide__stat"><span class="slide__stat-value">42</span>
    <span class="slide__stat-label">answers</span></div></div>
    <ol class="slide__numbered slide__numbered--3col slide__numbered--stacked">
      <li><strong>First</strong><span>a</span></li><li><strong>Second</strong><span>b</span></li>
      <li><strong>Third</strong><span>c</span></li></ol>
  </div>
</section>
<section class="slide" id="decision"><div class="slide__result"><p class="slide__result-label">Result</p>
  <p class="slide__result-value">Yes</p></div></section>
"""


def design(tmp: Path, extras: str = EXTRAS) -> Path:
    text = DESIGN.read_text("utf-8")
    text = text.replace("colors:\n", "colors:\n" + "".join('  %s: "%s"\n' % kv for kv in EXTRA_LIGHT.items()), 1)
    text = text.replace("colorsDark:\n", "colorsDark:\n" + "".join('  %s: "%s"\n' % kv for kv in EXTRA_DARK.items()), 1)
    head, sep, body = text.partition("\n---\n")
    out = tmp / "brand" / "DESIGN.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(head + "\n" + extras.strip() + sep + body, encoding="utf-8")
    return out


def build(tmp: Path, design_md: Path, *extra) -> str:
    frag = tmp / "slides.html"
    frag.write_text(SLIDES, encoding="utf-8")
    out = tmp / "deck.html"
    r = subprocess.run([sys.executable, str(NEW_DECK), "--title", "Extras", "--out", str(out), "--force",
                        "--no-embed-fonts", "--no-verify", "--slides", str(frag), "--design", str(design_md),
                        "--deck-attr", "data-view=deck", *map(str, extra)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return out.read_text("utf-8")


def rules(extras: str) -> str:
    return ND.component_rules(yaml.safe_load(extras))


# --- unchanged without the new keys ---------------------------------------------------------

def test_old_keys_give_the_css_they_gave_before():
    data = yaml.safe_load(OLD_KEYS.read_text("utf-8"))
    assert ND.component_rules(data) == OLD_CSS.read_text("utf-8")


def test_engine_fallbacks_are_the_old_values():
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    for old in ("var(--arc-height, clamp(14px, 2.4vh, 24px))", "var(--arc-glow-inner, 3px)",
                "var(--arc-glow-outer, 10px)", "var(--accent) var(--arc-fade, 28%)",
                "calc(100% - var(--arc-fade, 28%))"):
        assert old in css, old


def test_a_deck_without_a_design_mode_has_no_theme_default(tmp_path):
    html = build(tmp_path, design(tmp_path, ""))
    assert "data-theme-default" not in html.split(">", 2)[1]
    assert "design-components" not in html


# --- the new keys -----------------------------------------------------------------------------

def test_every_key_turns_into_css(tmp_path):
    html = build(tmp_path, design(tmp_path))
    assert '<html lang="en" data-theme-default="dark">' in html, "defaultMode opens the deck dark"
    css = html[html.index("design-components"):html.index("<!-- deck-tokens:end -->")]
    for want in ("-webkit-font-smoothing: antialiased", "--media-share: 26.667%", "--media-gap: 64px",
                 "--arc-height: 18px", "--arc-fade: 12%", "--arc-glow-inner: 5px; --arc-glow-outer: 13px",
                 "--stat-gradient: linear-gradient(100deg, var(--cmp-c-gradient-from) 0%",
                 "min-width: min(100%, 10em)", "--number-rule: var(--cmp-c-highlight)", "list-style: disc outside",
                 "--space-after-heading: 22px", "backdrop-filter: blur(12px)", "--deck-view-gap: 32px",
                 "box-shadow: 0 10px 30px color-mix(in srgb, var(--cmp-c-ink) 55%, transparent)"):
        assert want in css, want
    assert "  --cmp-c-highlight: #C060E0;" in css and "  --cmp-c-highlight: #7A2A68;" in css, "per mode"


def test_a_comment_line_of_dashes_keeps_the_components(tmp_path):
    spec_path = SKILL.parent / "html-canvas" / "scripts" / "design-to-css.py"
    spec = importlib.util.spec_from_file_location("d2c_probe", spec_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = mod.frontmatter(design(tmp_path))
    assert "slide-text" in data["components"], "the '# ---- components ----' comment does not end the front matter"


def test_the_four_stop_gradient_from_colour_roles(tmp_path):
    html = build(tmp_path, design(tmp_path, "components: {slide-heading: {fontWeight: 600}}"))
    assert "var(--gradient-via) 38%, var(--gradient-via-2) 67%" in html


@pytest.mark.parametrize("extras, word", [
    ("components: {slide-text: {smoothing: crisp}}", "smoothing"),
    ("components: {slide-media: {share: 3/7}}", "share"),
    ("components: {slide-arc: {fade: 70%}}", "fade"),
    ("components: {slide-arc: {glow: 4px}}", "glow"),
    ("components: {slide-number: {paint: rainbow}}", "paint"),
    ("components: {slide-bullet: {style: square}}", "style"),
    ("components: {slide-quote: {bar: '{gradients.none}'}}", "names nothing"),
    ("components: {plate: {background: 'url(x.png)'}}", "not a CSS value"),
    ("components: {plate: {background: 'red; color: blue'}}", "not a CSS value"),
    ("components: {toolbar: [red]}", "toolbar takes"),
    ("components: {slide-bleed: {padding: 1px 2px 3px 4px}}", "padding"),
])
def test_wrong_values_stop_the_build(extras, word):
    with pytest.raises(ValueError, match=word):
        rules(extras)


def test_shared_components_leave_other_generators_keys_alone():
    css = rules("components: {toolbar: {position: sticky, padding: 10px 24px}, deck-view: {counter: right}}")
    assert "padding: 10px 24px" in css and "sticky" not in css and "counter" not in css


def test_wrong_default_mode_stops_the_build(tmp_path):
    d = design(tmp_path, "defaultMode: dusk")
    frag = tmp_path / "s.html"
    frag.write_text(SLIDES, encoding="utf-8")
    r = subprocess.run([sys.executable, str(NEW_DECK), "--title", "x", "--out", str(tmp_path / "d.html"),
                        "--no-verify", "--no-embed-fonts", "--slides", str(frag), "--design", str(d)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "defaultMode" in r.stderr


def test_theme_default_flag_wins_over_the_design(tmp_path):
    html = build(tmp_path, design(tmp_path), "--theme-default", "light")
    assert 'data-theme-default="light"' in html


# --- in the browser ---------------------------------------------------------------------------

LOOK = """() => {
  const q = s => document.querySelector(s), cs = (s, p) => getComputedStyle(q(s), p || null);
  const slideBox = id => document.getElementById(id).getBoundingClientRect();
  const cover = slideBox('cover'), top = q('#cover .slide__top .slide__label').getBoundingClientRect();
  const media = slideBox('media'), photo = q('#media .slide__media').getBoundingClientRect();
  const arc = q('#body .slide__arc').getBoundingClientRect(), col = q('#body').getBoundingClientRect();
  const num = cs('#media .slide__numbered > li', '::before');
  return {
    smooth: cs('body').webkitFontSmoothing,
    topGap: top.top - cover.top, eyebrow: cs('#cover .slide__label').color, title: cs('#cover .slide__display').color,
    share: photo.width / media.width, arcH: arc.height, arcShare: arc.width,
    numPaint: num.backgroundImage, numRule: num.borderBottomWidth, numClip: num.webkitBackgroundClip,
    cols: cs('#media .slide__numbered').gridTemplateColumns.split(' ').length,
    small: parseFloat(cs('#body .slide__body--sm').fontSize), body: parseFloat(cs('#body .slide__body').fontSize),
    bullets: cs('#body .slide__bullets').listStyleType, dot: cs('#body .slide__bullets li', '::before').content,
    statMin: cs('.slide__stat-value').minWidth,
    labelGap: q('#body .slide__heading').getBoundingClientRect().top - q('#body .slide__label').getBoundingClientRect().bottom,
    quoteBar: cs('#body .slide__quote', '::before').backgroundImage,
    plate: cs('.slide__result').backdropFilter, radius: cs('.slide__result').borderTopLeftRadius,
    bar: cs('.deck-view-bar').backgroundColor, present: cs('.deck-view-present').backgroundImage,
    page: cs('body').backgroundColor };
}"""


def test_the_deck_wears_the_extras(open_html, tmp_path):
    page = open_deck(open_html, build(tmp_path, design(tmp_path)))
    page.evaluate("() => window.SlideDeck.setView('present')")
    look = page.evaluate(LOOK)
    assert look["smooth"] == "antialiased"
    assert abs(look["topGap"] - 64) < 1, "the eyebrow sits in the top slot at the design padding"
    assert look["eyebrow"] == look["title"] == "rgb(255, 255, 255)", "text on the photo in on-photo"
    assert abs(look["share"] - 4 / 15) < 0.01
    assert abs(look["arcH"] - 18) < 1
    assert "linear-gradient" in look["numPaint"] and look["numClip"] == "text" and look["numRule"] == "2px"
    assert look["cols"] == 3
    assert look["small"] < look["body"]
    assert look["bullets"] == "disc" and look["dot"] in ("none", "normal")
    assert look["statMin"].startswith("min(")
    assert abs(look["labelGap"] - 9) < 1.5, look["labelGap"]
    assert "linear-gradient" in look["quoteBar"]
    assert look["plate"] == "blur(12px)" and look["radius"] == "16px"
    page.evaluate("() => window.SlideDeck.setView('deck')")
    look = page.evaluate(LOOK)
    assert look["bar"] == look["page"] == "rgb(16, 16, 36)", "toolbar and page in ink"
    assert "linear-gradient" in look["present"]
    assert page.errors == []


def test_arc_modifiers_and_the_four_fifteenths_share_in_any_deck(open_html):
    s = ('<section class="slide slide--media" data-media-size="4/15" id="m"><div class="slide__media"></div>'
         '<div class="slide__content"><div class="slide__arc slide__arc--quarter"></div></div></section>')
    page = open_deck(open_html, deck([s, slide("Two")]))
    geo = page.evaluate("""() => { const m = document.getElementById('m').getBoundingClientRect(),
      p = document.querySelector('#m .slide__media').getBoundingClientRect(),
      a = document.querySelector('#m .slide__arc').getBoundingClientRect(),
      c = document.querySelector('#m .slide__content').getBoundingClientRect();
      return {share: p.width / m.width, arc: a.width / c.width}; }""")
    assert abs(geo["share"] - 4 / 15) < 0.01 and abs(geo["arc"] - 0.25) < 0.01
