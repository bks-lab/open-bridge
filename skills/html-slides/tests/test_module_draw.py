"""Deck module `draw` (reference/modules.md § Module: draw): laser pointer and drawing overlay.

Every deck here is the engine probe deck with the shipped module spliced in through
engine_testlib.module_deck, exactly as new-deck.py --with draw would splice it.
"""
from __future__ import annotations

import re

from engine_testlib import SHIPPED_MODULES, current, deck, module_deck, new_deck, open_deck, slide, wait_settled

SLIDES = [slide("One", ' id="a"'), slide("Two", ' id="b"'), slide("Three", ' id="c"')]


def draw_deck(slides=None, **kw):
    return module_deck(["draw"], slides or SLIDES, **kw)


def ink(page, index=None) -> int:
    """Painted pixels on the canvas of slide `index` (default: the active one); 0 without a canvas."""
    return page.evaluate("""(i) => {
      const s = window.SlideDeck.slides()[i === null ? window.SlideDeck.current() : i];
      const c = s && s.querySelector(':scope > canvas.deck-draw');
      if (!c || !c.width || !c.height) return 0;
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for (let k = 3; k < d.length; k += 4) if (d[k] > 0) n++;
      return n;
    }""", index)


def stroke(page, x0=300, y0=300, x1=700, y1=380, steps=12):
    page.mouse.move(x0, y0)
    page.mouse.down()
    for k in range(1, steps + 1):
        page.mouse.move(x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps)
    page.mouse.up()
    page.wait_for_timeout(60)  # one animation frame for the render


def accent(page) -> list[int]:
    return page.evaluate("""() => {
      const p = document.createElement('span'); p.style.color = 'var(--accent)';
      document.body.appendChild(p);
      const m = getComputedStyle(p).color.match(/\\d+/g).slice(0, 3).map(Number);
      p.remove(); return m;
    }""")


def pixel(page, x, y) -> list[int]:
    """RGBA of the active slide's canvas at viewport point (x, y)."""
    return page.evaluate("""([x, y]) => {
      const s = window.SlideDeck.slides()[window.SlideDeck.current()];
      const c = s.querySelector(':scope > canvas.deck-draw'), r = c.getBoundingClientRect();
      const px = Math.round((x - r.left) / r.width * c.width), py = Math.round((y - r.top) / r.height * c.height);
      return [...c.getContext('2d').getImageData(px, py, 1, 1).data];
    }""", [x, y])


def mode(page) -> str:
    return page.evaluate("() => window.SlideDeckDraw.mode()")


# --- off means absent --------------------------------------------------------------------------

def test_listed_module_adds_nothing_until_asked(open_html):
    page = open_deck(open_html, draw_deck())
    assert page.evaluate("() => document.querySelectorAll('.deck-draw, .deck-laser, .deck-draw-badge').length") == 0
    assert mode(page) == "off"
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-drawing')")
    page.keyboard.press("c")
    page.keyboard.press("z")
    page.keyboard.press("h")
    assert mode(page) == "off", "C, Z and H only act while drawing"
    assert page.errors == []


def test_module_is_available_and_lists_its_keys_in_help(open_html):
    assert "draw" in new_deck().available_modules()
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("?")
    kbds = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    for k in ("D", "Q", "C", "Z", "H"):
        assert k in kbds, (k, kbds)


def test_d_does_nothing_in_a_deck_without_the_module(open_html):
    page = open_deck(open_html, deck(SLIDES))
    page.keyboard.press("d")
    assert page.evaluate("() => document.querySelectorAll('canvas').length") == 0


# --- drawing -----------------------------------------------------------------------------------

def test_d_draws_on_the_active_slide_in_the_accent_colour(open_html):
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    assert mode(page) == "draw"
    assert page.evaluate("() => document.documentElement.classList.contains('deck-drawing')")
    assert page.locator(".deck-draw-badge").is_visible()
    stroke(page, 300, 300, 700, 300)
    assert ink(page) > 200
    r, g, b, a = pixel(page, 500, 300)
    assert a > 200 and [r, g, b] == accent(page), "the pen is the accent token"
    assert page.evaluate("() => window.SlideDeckDraw.strokes(0)") == 1
    assert page.errors == []


def test_drawings_stay_with_their_slide_while_navigating(open_html):
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    stroke(page)
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert mode(page) == "draw", "arrows still move the deck while drawing"
    assert ink(page) == 0, "the next slide starts blank"
    stroke(page, 200, 500, 600, 520)
    page.keyboard.press("ArrowLeft")
    wait_settled(page, 0)
    assert ink(page, 0) > 0 and ink(page, 1) > 0
    assert page.evaluate("() => [0, 1, 2].map(i => window.SlideDeckDraw.strokes(i))") == [1, 1, 0]


def test_z_undoes_c_clears_the_slide_shift_c_clears_all(open_html):
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    stroke(page, 300, 300, 700, 300)
    stroke(page, 300, 450, 700, 450)
    assert page.evaluate("() => window.SlideDeckDraw.strokes(0)") == 2
    page.keyboard.press("z")
    assert page.evaluate("() => window.SlideDeckDraw.strokes(0)") == 1
    page.wait_for_timeout(60)
    assert pixel(page, 500, 450)[3] == 0, "the undone stroke is gone from the canvas"
    page.keyboard.press("c")
    page.wait_for_timeout(60)
    assert ink(page) == 0
    stroke(page)
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    stroke(page)
    page.keyboard.press("Shift+C")
    page.wait_for_timeout(60)
    assert page.evaluate("() => [0, 1].map(i => window.SlideDeckDraw.strokes(i))") == [0, 0]
    assert ink(page, 0) == 0 and ink(page, 1) == 0


def test_h_switches_to_a_wide_translucent_marker(open_html):
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    stroke(page, 300, 300, 700, 300)
    pen = ink(page)
    page.keyboard.press("c")
    page.keyboard.press("h")
    assert page.evaluate("() => window.SlideDeckDraw.tool()") == "marker"
    stroke(page, 300, 300, 700, 300)
    assert ink(page) > pen * 2, "the marker is wider than the pen"
    assert 0 < pixel(page, 500, 300)[3] < 200, "and translucent"
    page.keyboard.press("h")
    assert page.evaluate("() => window.SlideDeckDraw.tool()") == "pen"


def test_escape_leaves_drawing_and_the_ink_stays(open_html):
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    stroke(page)
    page.keyboard.press("Escape")
    assert mode(page) == "off"
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-drawing')")
    assert not page.locator(".deck-draw-badge").is_visible()
    assert ink(page) > 0, "annotations stay visible until cleared"
    assert page.evaluate("() => getComputedStyle(document.querySelector('canvas.deck-draw')).pointerEvents") == "none"
    page.keyboard.press("c")
    assert page.evaluate("() => window.SlideDeckDraw.strokes(0)") == 1, "C is free again outside drawing"
    page.keyboard.press("d")
    page.keyboard.press("d")
    assert mode(page) == "off", "D toggles"


def test_ink_follows_a_theme_switch_and_a_resize(open_html, page):
    open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    stroke(page, 300, 300, 700, 300)
    before = accent(page)
    page.keyboard.press("t")
    page.wait_for_timeout(80)
    after = accent(page)
    assert before != after
    assert pixel(page, 500, 300)[:3] == after, "the ink is re-coloured to the new accent"
    page.set_viewport_size({"width": 1000, "height": 600})
    page.wait_for_timeout(150)
    try:
        assert ink(page) > 100, "strokes are kept in slide coordinates and redrawn"
        assert pixel(page, 500 * 1000 / 1280, 300 * 600 / 720)[3] > 0
    finally:
        page.set_viewport_size({"width": 1280, "height": 720})


def test_data_deck_buttons_toggle_draw_and_laser(open_html):
    btns = '<button data-deck="draw" id="bd">draw</button><button data-deck="laser" id="bl">laser</button>'
    page = open_deck(open_html, draw_deck([slide("One", extra=btns), slide("Two")]))
    page.click("#bd")
    assert mode(page) == "draw"
    page.keyboard.press("Escape")
    page.click("#bl")
    assert mode(page) == "laser"
    assert page.errors == []


# --- laser -------------------------------------------------------------------------------------

def test_q_laser_follows_the_pointer_and_q_or_escape_ends_it(open_html):
    page = open_deck(open_html, draw_deck())
    page.mouse.move(100, 100)
    page.keyboard.press("q")
    assert mode(page) == "laser"
    page.mouse.move(640, 360)
    page.wait_for_timeout(40)
    box = page.locator(".deck-laser").bounding_box()
    assert box and abs(box["x"] + box["width"] / 2 - 640) < 3 and abs(box["y"] + box["height"] / 2 - 360) < 3
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck')).cursor") == "none"
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert mode(page) == "laser", "the laser stays on across slides"
    page.keyboard.press("q")
    assert mode(page) == "off" and not page.locator(".deck-laser").is_visible()
    page.keyboard.press("q")
    page.keyboard.press("Escape")
    assert mode(page) == "off"
    assert current(page) == 1


def test_draw_and_laser_exclude_each_other(open_html):
    page = open_deck(open_html, draw_deck())
    page.keyboard.press("q")
    page.keyboard.press("d")
    assert mode(page) == "draw" and not page.locator(".deck-laser").is_visible()
    page.keyboard.press("q")
    assert mode(page) == "laser"
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-drawing')")


def trail_shown(page) -> int:
    return page.evaluate("() => [...document.querySelectorAll('.deck-laser-trail')]"
                         ".filter(e => !e.hidden && getComputedStyle(e).display !== 'none').length")


def test_laser_leaves_a_short_trail_but_none_under_reduced_motion(open_html, page):
    open_deck(open_html, draw_deck())
    page.keyboard.press("q")
    for x in range(300, 700, 40):
        page.mouse.move(x, 300)
    assert trail_shown(page) > 0
    page.wait_for_timeout(600)
    assert trail_shown(page) == 0, "the trail fades out on its own"
    page.emulate_media(reduced_motion="reduce")
    try:
        for x in range(300, 700, 40):
            page.mouse.move(x, 400)
        assert trail_shown(page) == 0
        assert page.locator(".deck-laser").is_visible(), "the dot itself stays"
    finally:
        page.emulate_media(reduced_motion="no-preference")


# --- print, language, source rules -------------------------------------------------------------

def test_module_chrome_and_ink_are_off_in_print(open_html, page):
    open_deck(open_html, draw_deck())
    page.keyboard.press("d")
    stroke(page)
    page.keyboard.press("Escape")
    page.keyboard.press("q")
    page.mouse.move(500, 300)
    page.emulate_media(media="print")
    try:
        shown = page.evaluate("() => [...document.querySelectorAll('.deck-draw, .deck-laser, .deck-laser-trail, .deck-draw-badge')]"
                              ".filter(e => getComputedStyle(e).display !== 'none').length")
        assert shown == 0
    finally:
        page.emulate_media(media="null")


def test_badge_and_help_follow_the_deck_language(open_html):
    pairs = slide("Eins", extra='<p data-de="Hallo" data-en="Hello">Hello</p>')
    page = open_deck(open_html, draw_deck([pairs, slide("Zwei")], lang="de", deck_attrs='data-deck-id="draw-lang"'))
    page.keyboard.press("d")
    de = page.locator(".deck-draw-badge").inner_text()
    page.keyboard.press("l")
    page.wait_for_timeout(30)
    en = page.locator(".deck-draw-badge").inner_text()
    assert "Zeichnen" in de and "Drawing" in en, (de, en)


def test_module_css_uses_tokens_and_hides_in_print():
    css = (SHIPPED_MODULES / "draw.css").read_text("utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css), "colours come from the deck tokens"
    assert "@media print" in css and "var(--accent)" in css
    js = (SHIPPED_MODULES / "draw.js").read_text("utf-8")
    assert "</script" not in js.lower() and "reducedMotion" in js
