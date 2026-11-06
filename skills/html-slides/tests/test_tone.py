"""The tone of a slide: `data-tone` replaces the inline chapter colour and glow.

A style preset renders a tone as a coloured label (and divider heading) plus a
soft glow behind the slide. The design preset renders it quietly: heading colour
and accent only, no glow. `.fx` on the root, the deck or one slide brings the
decoration back. Decks that still carry the old inline styles keep working.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import ASSETS, FIXTURES, SKILL, slide_type_snippets

NEW_DECK = SKILL / "scripts" / "new-deck.py"
DESIGN = FIXTURES / "tooling" / "DESIGN.md"

INLINE_ATTR = re.compile(r"\sstyle\s*=")

TONED = """
<section class="slide slide--title slide--with-grid" id="t-title"><h1 class="slide__display">T</h1></section>
<section class="slide slide--content" id="t-content" data-tone="green">
  <div class="slide__inner"><div><p class="slide__label">Label</p><h2 class="slide__heading">H</h2></div></div>
</section>
<section class="slide slide--divider" id="t-divider" data-tone="amber">
  <span class="slide__number">01</span><div><h2 class="slide__heading">D</h2></div>
</section>
<section class="slide slide--content fx" id="t-fx" data-tone="red">
  <div class="slide__inner"><div><p class="slide__label">Label</p><h2 class="slide__heading">H</h2></div></div>
</section>
<section class="slide slide--bleed" id="t-bleed"><div class="slide__bg slide__bg--gradient"></div>
  <div class="slide__content"><h2 class="slide__heading">B</h2></div></section>
<section class="slide slide--content" id="t-old" style="background-image:radial-gradient(ellipse at 20% 80%, var(--green-dim) 0%, transparent 45%);">
  <div class="slide__inner"><div><p class="slide__label" style="color:var(--green);">Old</p>
  <h2 class="slide__heading" style="color:var(--green);">Old heading</h2></div></div>
</section>
"""


def build(tmp_path: Path, *extra: str, design: bool) -> str:
    if design:
        shutil.copyfile(DESIGN, tmp_path / "DESIGN.md")
    frag = tmp_path / "tone.html"
    frag.write_text(TONED, encoding="utf-8")
    out = tmp_path / "deck.html"
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Tone", "--slides", str(frag), "--out", str(out),
                    "--force", *extra], check=True, capture_output=True)
    return out.read_text("utf-8")


@pytest.fixture
def design_deck(open_html, page, tmp_path):
    open_html(build(tmp_path, design=True))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


@pytest.fixture
def style_deck(open_html, page, tmp_path):
    out = tmp_path / "style"
    out.mkdir()
    open_html(build(out, "--preset", "bold-signal", design=False))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


def look(page, sel: str, pseudo: str | None = None) -> dict:
    return page.evaluate("""([s, p]) => { const e = document.querySelector(s); const cs = getComputedStyle(e, p);
      return {image: cs.backgroundImage, color: cs.color, shadow: cs.boxShadow, text: cs.textShadow}; }""", [sel, pseudo])


def resolve(page, name: str) -> str:
    return page.evaluate("""(n) => { const p = document.createElement('i'); p.style.color = 'var(--' + n + ')';
      document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; }""", name)


def test_slide_types_carry_no_inline_style():
    bad = [h for h, html in slide_type_snippets() if INLINE_ATTR.search(html)]
    assert bad == []


def test_showcase_carries_no_inline_style():
    text = (SKILL / "examples" / "showcase.slides.html").read_text("utf-8")
    assert not INLINE_ATTR.search(text)


def test_engine_css_has_no_raw_rgba():
    assert "rgba(" not in (ASSETS / "slide-engine.css").read_text("utf-8")


def test_style_preset_renders_a_tone_as_label_colour_and_glow(style_deck):
    assert look(style_deck, "#t-content .slide__label")["color"] == resolve(style_deck, "green")
    assert "radial-gradient" in look(style_deck, "#t-content")["image"]
    assert look(style_deck, "#t-divider .slide__heading")["color"] == resolve(style_deck, "amber")


def test_style_preset_keeps_title_glow_grid_and_gradient(style_deck):
    assert "radial-gradient" in look(style_deck, "#t-title")["image"]
    assert "radial-gradient" in look(style_deck, "#t-title", "::before")["image"]
    assert "linear-gradient" in look(style_deck, "#t-bleed .slide__bg")["image"]


def test_design_preset_renders_a_tone_quietly(design_deck):
    assert look(design_deck, "#t-content")["image"] == "none"
    assert look(design_deck, "#t-content .slide__label")["color"] == resolve(design_deck, "accent")
    assert look(design_deck, "#t-divider .slide__heading")["color"] != resolve(design_deck, "amber")
    assert look(design_deck, "#t-content .slide__heading")["color"] != resolve(design_deck, "green")


def test_design_preset_switches_off_title_glow_grid_and_gradient(design_deck):
    assert look(design_deck, "#t-title")["image"] == "none"
    assert look(design_deck, "#t-title", "::before")["image"] == "none"
    assert "gradient" not in look(design_deck, "#t-bleed .slide__bg")["image"]


def test_fx_on_a_slide_brings_the_glow_back(design_deck):
    assert "radial-gradient" in look(design_deck, "#t-fx")["image"]
    assert look(design_deck, "#t-fx .slide__label")["color"] == resolve(design_deck, "red")


@pytest.mark.parametrize("where", ["html", ".deck"])
def test_fx_on_root_or_deck_brings_decoration_back(design_deck, where):
    design_deck.evaluate("(w) => document.querySelector(w).classList.add('fx')", where)
    assert "radial-gradient" in look(design_deck, "#t-content")["image"]
    assert "radial-gradient" in look(design_deck, "#t-title")["image"]
    assert "radial-gradient" in look(design_deck, "#t-title", "::before")["image"]
    assert "linear-gradient" in look(design_deck, "#t-bleed .slide__bg")["image"]


def test_old_inline_styles_stay_neutralised_under_design(design_deck):
    assert look(design_deck, "#t-old")["image"] == "none"
    assert look(design_deck, "#t-old .slide__label")["color"] == resolve(design_deck, "accent")
    assert look(design_deck, "#t-old .slide__heading")["color"] != resolve(design_deck, "green")


def test_old_inline_styles_keep_their_look_under_a_style_preset(style_deck):
    assert "radial-gradient" in look(style_deck, "#t-old")["image"]
    assert look(style_deck, "#t-old .slide__heading")["color"] == resolve(style_deck, "green")


@pytest.mark.parametrize("fixture", ["design_deck", "style_deck"])
def test_help_card_and_chrome_cast_no_raw_shadow(request, fixture):
    page = request.getfixturevalue(fixture)
    page.evaluate("document.querySelector('.deck-help').hidden = false")
    card = look(page, ".deck-help__card")
    assert card["shadow"] == "none"
    if fixture == "design_deck":
        assert look(page, ".deck-counter")["text"] == "none"
    else:
        assert "rgba(0, 0, 0" not in look(page, ".deck-counter")["text"]


# --- images without inline styles -------------------------------------------------------

PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
IMAGES = """
<section class="slide slide--bleed" id="i-bleed">
  <img class="slide__bg" src="%(px)s" alt="">
  <div class="slide__scrim"></div>
  <div class="slide__content"><h2 class="slide__heading">B</h2></div>
</section>
<section class="slide slide--content" id="i-content">
  <div class="slide__inner"><div><h2 class="slide__heading">C</h2></div>
    <div class="slide__aside"><img class="slide__image" src="%(px)s" alt="A picture"></div></div>
</section>
""" % {"px": PIXEL}


@pytest.fixture
def image_deck(open_html, page, tmp_path):
    frag = tmp_path / "img.html"
    frag.write_text(IMAGES, encoding="utf-8")
    out = tmp_path / "img-deck.html"
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Img", "--slides", str(frag), "--out", str(out),
                    "--force", "--preset", "swiss-modern"], check=True, capture_output=True)
    open_html(out.read_text("utf-8"))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


def test_img_slide_bg_fills_the_bleed_slide_behind_the_scrim(image_deck):
    info = image_deck.evaluate("""() => { const i = document.querySelector('#i-bleed img.slide__bg');
      const s = document.querySelector('#i-bleed'); const c = getComputedStyle(i);
      const r = i.getBoundingClientRect(), sr = s.getBoundingClientRect();
      return {pos: c.position, fit: c.objectFit, z: +c.zIndex,
              scrim: +getComputedStyle(document.querySelector('#i-bleed .slide__scrim')).zIndex,
              w: Math.round(r.width) - Math.round(sr.width), h: Math.round(r.height) - Math.round(sr.height)}; }""")
    assert info["pos"] == "absolute" and info["fit"] == "cover"
    assert info["w"] == 0 and info["h"] == 0
    assert info["z"] < info["scrim"]


def test_slide_image_is_a_bordered_flat_picture_within_the_slide(image_deck):
    image_deck.evaluate("document.querySelector('#i-content').scrollIntoView()")
    info = image_deck.evaluate("""() => { const c = getComputedStyle(document.querySelector('#i-content .slide__image'));
      return {border: c.borderTopWidth, style: c.borderTopStyle, radius: c.borderTopLeftRadius, shadow: c.boxShadow,
              fit: c.objectFit, maxw: c.maxWidth}; }""")
    assert info["border"] == "1px" and info["style"] == "solid"
    assert info["radius"] != "0px" and info["shadow"] == "none"
    assert info["fit"] in ("cover", "contain") and info["maxw"] == "100%"
