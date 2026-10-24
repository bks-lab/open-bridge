"""Deck modules together: what one module promises another (reference/modules.md).

Each module is tested alone in its own file; this file holds the seams. read shows
every step of the real steps module, and the draw overlay stands aside while reading.
"""
from __future__ import annotations

from engine_testlib import module_deck, open_deck, slide, wait_settled

CODE = ('<div class="slide__code-block"><pre><code data-lines="1|2-3">'
        'first()\nsecond()\nthird()\n</code></pre></div>')


def wait_reading(page, on: bool = True):
    page.wait_for_function("(on) => document.documentElement.classList.contains('deck-read') === on", arg=on)


def full(page, sel: str) -> list[bool]:
    """Per element: fully visible (no hidden, no dimming, no offset)."""
    return page.evaluate("""(sel) => [...document.querySelectorAll(sel)].map(e => {
      const s = getComputedStyle(e);
      return s.visibility === 'visible' && s.opacity === '1' && (s.transform === 'none' || s.transform === '');
    })""", sel)


def steps_read_deck():
    frags = ('<p data-step class="f">One</p><p data-step data-step-effect="rise" class="f">Two</p>'
             '<ul data-steps data-step-effect="dim"><li>a</li><li>b</li></ul>')
    slides = [slide("One", ' id="a"'), slide("Two", ' id="b"', frags + CODE), slide("Three", ' id="c"')]
    return module_deck(["read", "steps"], slides)


def test_read_shows_every_step_and_every_code_line_of_the_steps_module(open_html):
    page = open_deck(open_html, steps_read_deck())
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    page.keyboard.press("ArrowRight")   # first step of slide b
    page.wait_for_function("() => window.SlideDeck.step() === 1")
    assert not all(full(page, "#b .f, #b [data-steps] > *")), "the slide view still hides later steps"
    page.keyboard.press("r")
    wait_reading(page)
    page.wait_for_timeout(450)   # the step transitions are 0.35s
    assert all(full(page, "#b .f, #b [data-steps] > *")), full(page, "#b .f, #b [data-steps] > *")
    lines = page.evaluate("""() => [...document.querySelectorAll('#b .code-line')].map(l => {
      const s = getComputedStyle(l); return [s.opacity, s.boxShadow]; })""")
    assert lines and all(o == "1" and sh == "none" for o, sh in lines), lines
    page.keyboard.press("r")
    wait_reading(page, False)
    page.wait_for_function("() => window.SlideDeck.step() === 1")
    page.wait_for_timeout(450)
    assert not all(full(page, "#b .f, #b [data-steps] > *")), "back in the slide view, the step state returns"
    assert page.errors == []


def draw_read_deck():
    return module_deck(["draw", "read"], [slide("One", ' id="a"'), slide("Two", ' id="b"')])


def test_draw_overlay_stands_aside_while_reading(open_html):
    page = open_deck(open_html, draw_read_deck())
    page.keyboard.press("d")
    page.mouse.move(300, 300)
    page.mouse.down()
    page.mouse.move(600, 320, steps=8)
    page.mouse.up()
    assert page.evaluate("() => window.SlideDeckDraw.strokes(0)") == 1
    page.keyboard.press("r")
    wait_reading(page)
    assert page.evaluate("() => window.SlideDeckDraw.mode()") == "off", "reading ends drawing mode"
    hidden = page.evaluate("""() => [...document.querySelectorAll('.deck-draw, .deck-laser, .deck-draw-badge')]
      .every(e => getComputedStyle(e).display === 'none')""")
    assert hidden, "the overlay is hidden under :root.deck-read"
    page.keyboard.press("d")
    page.keyboard.press("q")
    assert page.evaluate("() => window.SlideDeckDraw.mode()") == "off", "D and Q wait for the slide view"
    page.keyboard.press("r")
    wait_reading(page, False)
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-draw')).display") != "none", \
        "the ink is back with the slides"
    assert page.evaluate("() => window.SlideDeckDraw.strokes(0)") == 1
    assert page.errors == []


def test_the_seams_are_documented():
    from slides_testlib import SKILL
    out = (SKILL / "reference" / "output-formats.md").read_text("utf-8")
    assert "data-read-default" in out, "the send variant belongs on the send path"
    mods = (SKILL / "reference" / "modules.md").read_text("utf-8")
    assert ":root.deck-read" in mods.split("## Module: draw")[1].split("\n## ")[0], "draw says it stands aside"


def test_presenter_previews_of_a_read_default_copy_show_slides(browser, tmp_path):
    """A send copy opens in the reading view; the presenter's previews are copies of
    that deck and must still show slides, not a document."""
    from engine_testlib import DESKTOP
    html = module_deck(["presenter", "read"], [slide("One", ' id="a"'), slide("Two", ' id="b"')],
                       deck_attrs=' data-deck-id="combo" data-read-default=""')
    f = tmp_path / "index.html"
    f.write_text(html, encoding="utf-8")
    ctx = browser.new_context(viewport=DESKTOP)
    try:
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f.as_uri())
        wait_reading(pg)
        with pg.expect_popup() as info:
            pg.keyboard.press("p")
        pop = info.value
        pop.wait_for_function("""() => ['cur', 'next'].every(n => {
          const fr = document.querySelector('[data-pp=' + n + '] iframe');
          return fr && fr.contentWindow && fr.contentWindow.SlideDeck && fr.contentWindow.SlideDeck.count(); })""",
                              polling=100, timeout=6000)
        pop.wait_for_timeout(200)
        modes = pop.evaluate("""() => ['cur', 'next'].map(n => document.querySelector('[data-pp=' + n + '] iframe')
          .contentDocument.documentElement.classList.contains('deck-read'))""")
        assert modes == [False, False], modes
        assert errors == []
    finally:
        ctx.close()
