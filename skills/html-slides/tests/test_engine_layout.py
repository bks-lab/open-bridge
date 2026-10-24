"""Engine v2 print, beamer, narrow windows and polish (plan item S9)."""
from __future__ import annotations

import pytest

from engine_testlib import DESKTOP, deck, open_deck, pdf_pages, slide
from slides_testlib import build_probe_deck

ANIMATED = ('<style>@keyframes probe-in { from { opacity: 0; } to { opacity: 1; } }'
            '.probe-anim { animation: probe-in 4s 30s both; }</style>'
            '<div class="probe-anim" id="anim">animated</div>')

OPACITY_ZERO = """() => [...document.querySelectorAll('.slide, .slide *')]
  .filter(el => el.offsetParent !== null || el.classList.contains('slide'))
  .filter(el => getComputedStyle(el).display !== 'none' && parseFloat(getComputedStyle(el).opacity) < 0.99)
  .map(el => el.className || el.tagName)"""


def test_print_reset_every_slide_one_page_nothing_hidden(open_html, page):
    open_deck(open_html, deck([slide("One", extra=ANIMATED)] + [slide("S%d" % i) for i in range(2, 7)]))
    page.emulate_media(media="print")
    try:
        geom = page.evaluate("() => [...document.querySelectorAll('.slide')].map(s => {"
                             " const r = s.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })")
        assert geom == [[1123, 631]] * 6, "297 x 167 mm per slide"
        assert page.evaluate(OPACITY_ZERO) == [], "nothing may print invisible"
        assert page.evaluate("() => getComputedStyle(document.getElementById('anim')).opacity") == "1"
        chrome = page.evaluate("() => ['.deck-progress','.deck-dots','.deck-counter','.deck-hints','.theme-toggle',"
                               "'.deck-notes','.deck-help','.deck-live'].filter(s => { const e = document.querySelector(s);"
                               " return e && getComputedStyle(e).display !== 'none'; })")
        assert chrome == []
    finally:
        page.emulate_media(media="null")
    pages = pdf_pages(page.pdf(prefer_css_page_size=True))
    assert len(pages) == 6
    for w, h in pages:
        assert abs(w - 841.89) < 1.5 and abs(h - 473.39) < 1.5, (w, h)


def test_reveal_is_the_only_entrance_class(open_html):
    page = open_deck(open_html, deck(6))
    style = page.evaluate("() => { const s = document.querySelectorAll('.slide')[4]; const c = getComputedStyle(s);"
                          " return [c.opacity, c.transform, getComputedStyle(s.querySelector('.reveal')).opacity]; }")
    assert style[0] == "1" and style[1] == "none", "an unvisited slide itself is not faded"
    assert style[2] == "0", "its .reveal children wait for the entrance"


@pytest.mark.parametrize("viewport,zoom", [
    ({"width": 1280, "height": 720}, "1"),
    ({"width": 1600, "height": 900}, "1.2"),
    ({"width": 2400, "height": 1300}, "1.45"),
])
def test_beamer_zoom_steps(open_html, viewport, zoom):
    title = '<section class="slide slide--title"><h1 class="slide__display">T</h1></section>'
    page = open_deck(open_html, deck([title, slide("Content")]), viewport=viewport)
    got = page.evaluate("() => getComputedStyle(document.querySelector('.slide--content > .slide__inner')).zoom")
    assert got == zoom
    assert page.evaluate("() => getComputedStyle(document.querySelector('.slide--title > h1')).zoom") == "1"


TALL = slide("Tall", extra='<ul class="slide__bullets">%s</ul>' % "".join("<li>Point %d</li>" % i for i in range(30)))


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 600}, {"width": 500, "height": 900}],
                         ids=["short", "narrow"])
def test_tall_content_is_not_clipped(open_html, viewport):
    page = open_deck(open_html, deck([slide("A"), TALL, slide("C")]), viewport=viewport)
    clipped = page.evaluate("() => [...document.querySelectorAll('.slide')].filter(s => s.scrollHeight - s.clientHeight > 1).length")
    assert clipped == 0
    tall_h = page.evaluate("() => document.querySelectorAll('.slide')[1].getBoundingClientRect().height")
    assert tall_h > viewport["height"], "the slide grows with its content"


def test_probe_deck_not_clipped_at_500x900(open_html):
    page = open_deck(open_html, build_probe_deck(), viewport={"width": 500, "height": 900})
    clipped = page.evaluate("() => [...document.querySelectorAll('.slide')].filter(s => s.scrollHeight - s.clientHeight > 1)"
                            ".map(s => s.className)")
    assert clipped == []
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0


def test_dots_hidden_on_narrow_screens(open_html):
    page = open_deck(open_html, deck(4), viewport={"width": 500, "height": 900})
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-dots')).display") == "none"
    page = open_deck(open_html, deck(4), viewport=DESKTOP)
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-dots')).display") != "none"


def test_key_help_is_readable(open_html):
    page = open_deck(open_html, deck(3))
    page.keyboard.press("?")
    info = page.evaluate("""() => { const box = document.querySelector('.deck-help__card');
      const item = box.querySelector('dd');
      return [parseFloat(getComputedStyle(item).fontSize), getComputedStyle(box).backgroundColor]; }""")
    assert info[0] >= 16
    assert not info[1].startswith("rgba(") or info[1].endswith(", 1)"), "an opaque card, not a blurred veil"


def test_table_card_hugs_its_rows(open_html):
    page = open_deck(open_html, build_probe_deck(), viewport=DESKTOP)
    ratio = page.evaluate("() => { const w = document.querySelector('.slide--table .table-wrap');"
                          " return w.getBoundingClientRect().height / w.closest('.slide').getBoundingClientRect().height; }")
    assert ratio < 0.5, "a short table gets a short card"


def test_slides_and_reveals_show_without_intersection_observer(browser, tmp_path):
    """Moved from html-canvas with the deck engine: no observer must not mean a blank deck."""
    ctx = browser.new_context(viewport=DESKTOP)
    try:
        ctx.add_init_script("delete window.IntersectionObserver;")
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        f = tmp_path / "index.html"
        f.write_text(deck(3), encoding="utf-8")
        pg.goto(f.as_uri())
        pg.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 3")
        assert pg.evaluate("'IntersectionObserver' in window") is False
        pg.wait_for_timeout(900)
        visible = pg.evaluate("() => [...document.querySelectorAll('.slide')].map(s => s.classList.contains('visible'))")
        assert visible == [True, True, True]
        assert set(pg.evaluate("() => [...document.querySelectorAll('.slide .reveal')]"
                               ".map(e => getComputedStyle(e).opacity)")) == {"1"}
        assert errors == []
    finally:
        ctx.close()


def _type(name: str) -> str:
    from slides_testlib import slide_type_snippets
    return next(h for n, h in slide_type_snippets() if n == name).replace("{color}", "accent")


def test_pipeline_steps_hug_their_text(open_html):
    """Short steps must not stretch to the slide's height with the file chip pinned far below."""
    page = open_deck(open_html, deck([_type("Pipeline / Flow Diagram")]))
    h = page.evaluate("""() => [document.querySelector('.pipeline__step').getBoundingClientRect().height,
                                document.querySelector('.slide').getBoundingClientRect().height]""")
    assert h[0] < 0.5 * h[1], h


def test_aside_stays_below_the_text_on_narrow_screens(open_html):
    page = open_deck(open_html, deck([_type("Content (Text + Aside)")]), viewport={"width": 600, "height": 900})
    shown = page.evaluate("() => document.querySelector('.slide__aside').getClientRects().length")
    assert shown > 0, "content must not vanish below 768 px"


def _tall_pipeline() -> str:
    """A pipeline slide whose content fills the slide, so its label sits at the top padding."""
    html = _type("Pipeline / Flow Diagram")
    step = html[html.index('<div class="pipeline__step">'):html.index("<!-- repeat steps -->")]
    return html.replace("<!-- repeat steps -->", step * 4)


def test_back_link_never_covers_the_first_line_of_a_slide(open_html):
    """On a narrow screen the fixed back link sits over the slide's top padding; it must clear it."""
    page = open_deck(open_html, deck([_tall_pipeline(), slide("Two")], deck_attrs='data-back-href="index.html"'),
                     viewport={"width": 600, "height": 900})
    back_bottom, pad = page.evaluate("""() => [document.querySelector('.deck-back').getBoundingClientRect().bottom,
      parseFloat(getComputedStyle(document.querySelector('.slide')).paddingTop)]""")
    assert pad >= back_bottom + 8, (back_bottom, pad)
    page = open_deck(open_html, deck([_tall_pipeline(), slide("Two")]), viewport={"width": 600, "height": 900})
    assert page.evaluate("() => parseFloat(getComputedStyle(document.querySelector('.slide')).paddingTop)") < back_bottom, \
        "without a back link the slide keeps its own padding"


def test_key_hints_are_hidden_on_narrow_screens(open_html):
    page = open_deck(open_html, deck(3), viewport={"width": 600, "height": 900})
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-hints')).display") == "none"


def test_code_shows_cli_flags_without_ligatures():
    from slides_testlib import ASSETS
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    block = css[css.index(".slide__code-block {"):]
    assert "font-variant-ligatures: none" in block[:block.index("}")]


def test_print_draws_no_focus_ring(open_html, page):
    """A focused deck or control printed its focus ring as a thin frame round every page."""
    open_deck(open_html, deck(3))
    page.evaluate("""() => { const d = document.querySelector('.deck'); d.tabIndex = -1;
      d.style.outline = '2px solid rgb(0, 0, 255)'; d.focus(); }""")
    page.emulate_media(media="print")
    assert page.evaluate("() => getComputedStyle(document.activeElement).outlineStyle") == "none"


GAP = """([a, b]) => { const r1 = document.querySelector(a).getBoundingClientRect(),
  r2 = document.querySelector(b).getBoundingClientRect(); return r2.top - r1.bottom; }"""


def test_title_and_code_keep_their_distance_without_inline_margins(open_html, page):
    """The engine carries the spacing the snippets used to set inline: a tagline under the
    display line, a subtitle over it, a code block (and its filename badge) under a heading."""
    title = ('<section class="slide slide--title" id="t"><div class="reveal"><p class="slide__subtitle" id="sub">Eyebrow line</p></div>'
             '<h1 class="slide__display reveal" id="disp">Typography gap</h1>'
             '<div class="reveal" id="tagwrap"><p class="slide__subtitle" id="tag">Tagline under it</p></div></section>')
    code = ('<section class="slide slide--code" id="c"><h2 class="slide__heading reveal" id="ch">Code heading</h2>'
            '<div class="slide__code-block reveal" id="cb"><span class="slide__code-filename" id="cf">deck.py</span>'
            '<pre><code>print("x")</code></pre></div></section>')
    open_deck(open_html, deck([title, code]))
    assert page.evaluate(GAP, ["#disp", "#tagwrap"]) >= 12
    assert page.evaluate(GAP, ["#sub", "#disp"]) >= 12
    page.evaluate("() => window.SlideDeck.goTo(1)")
    page.wait_for_timeout(400)
    assert page.evaluate(GAP, ["#ch", "#cf"]) >= 4, "the filename badge touches the heading"
