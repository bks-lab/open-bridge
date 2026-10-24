"""Engine core features that are always on: cover, number jump, zoom, a11y,
reduced motion, the print handout and the runtime language switch.
"""
from __future__ import annotations

import re

from engine_testlib import (current, deck, open_deck, pdf_pages, slide, wait_current,
                            wait_settled)
from slides_testlib import ASSETS


# --- B / W cover ----------------------------------------------------------------------------

def cover(page):
    return page.evaluate("""() => { const c = document.querySelector('.deck-cover');
      return c && !c.hidden ? getComputedStyle(c).backgroundColor : null; }""")


def test_b_and_w_cover_the_screen_and_lift_again(open_html):
    page = open_deck(open_html, deck(4))
    assert cover(page) is None
    page.keyboard.press("b")
    assert cover(page) == "rgb(0, 0, 0)"
    page.keyboard.press("w")
    assert cover(page) == "rgb(255, 255, 255)", "W while black switches to white"
    page.keyboard.press("w")
    assert cover(page) is None
    page.keyboard.press("B")
    page.keyboard.press("ArrowRight")
    assert cover(page) is None, "any other key lifts the cover"
    page.wait_for_timeout(200)
    assert current(page) == 0, "and is consumed: nothing moves unseen"
    page.keyboard.press("b")
    page.keyboard.press("Escape")
    assert cover(page) is None
    assert page.errors == []


def test_cover_hidden_in_print(open_html, page):
    open_deck(open_html, deck(2))
    page.keyboard.press("b")
    page.emulate_media(media="print")
    try:
        assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-cover')).display") == "none"
    finally:
        page.emulate_media(media="null")


# --- digits + Enter -------------------------------------------------------------------------

def test_digits_and_enter_jump_to_slide_n_of_the_active_track(open_html):
    page = open_deck(open_html, deck(12))
    page.keyboard.type("11")
    assert "11" in page.locator(".deck-jump").inner_text()
    page.keyboard.press("Enter")
    wait_settled(page, 10)
    page.keyboard.type("99")
    page.keyboard.press("Enter")
    wait_settled(page, 11)
    page.keyboard.type("3")
    page.keyboard.press("Escape")
    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    assert current(page) == 11, "Esc drops the typed number"
    page.keyboard.type("4")
    page.keyboard.press("Backspace")
    page.keyboard.type("2")
    page.keyboard.press("Enter")
    wait_settled(page, 1)
    assert page.errors == []


def test_jump_counts_the_slides_of_the_track(open_html):
    slides = [slide("One"), slide("Long only", ' data-track="long"'), slide("Three"), slide("Four")]
    page = open_deck(open_html, deck(slides, deck_attrs='data-tracks-default="short" data-deck-id="jump"'))
    page.keyboard.type("3")
    page.keyboard.press("Enter")
    wait_settled(page, 2)
    assert page.evaluate("() => window.SlideDeck.state().id") == ""
    assert page.locator(".slide.is-active h2").inner_text() == "Four"


# --- Alt+click zoom -------------------------------------------------------------------------

def zoomed(page):
    return page.evaluate("() => document.documentElement.classList.contains('deck-zoomed')")


def test_alt_click_zooms_and_click_or_esc_resets(open_html):
    page = open_deck(open_html, deck(3))
    page.mouse.move(400, 300)
    page.keyboard.down("Alt")
    page.mouse.click(400, 300)
    page.keyboard.up("Alt")
    assert zoomed(page)
    tf = page.evaluate("() => getComputedStyle(document.querySelector('.slide.is-active > *')).transform")
    assert tf != "none"
    page.mouse.click(400, 300)
    assert not zoomed(page)
    assert page.evaluate("() => document.querySelector('.slide.is-active > *').style.transform") == ""
    page.keyboard.down("Alt")
    page.mouse.click(600, 200)
    page.keyboard.up("Alt")
    assert zoomed(page)
    page.keyboard.press("Escape")
    assert not zoomed(page)
    page.keyboard.down("Alt")
    page.mouse.click(600, 200)
    page.keyboard.up("Alt")
    page.evaluate("() => window.SlideDeck.goTo(1)")
    assert not zoomed(page), "a slide change resets the zoom"
    assert page.errors == []


def test_zoom_gives_back_the_inline_transform_it_found(open_html):
    page = open_deck(open_html, deck(3))
    inline = "() => { const c = document.querySelector('.slide.is-active > *');" \
             " return [c.style.transform, c.style.transformOrigin, c.style.transition]; }"
    page.evaluate("""() => { const c = document.querySelector('.slide.is-active > *');
      c.style.transform = 'translateX(10px)'; c.style.transformOrigin = '0px 0px'; c.style.transition = 'opacity 1s'; }""")
    for close in ("click", "Escape"):
        page.mouse.move(400, 300)
        page.keyboard.down("Alt")
        page.mouse.click(400, 300)
        page.keyboard.up("Alt")
        assert zoomed(page)
        assert "scale(2)" in page.evaluate(inline)[0]
        if close == "click":
            page.mouse.click(400, 300)
        else:
            page.keyboard.press("Escape")
        assert not zoomed(page)
        page.wait_for_timeout(450)
        assert page.evaluate(inline) == ["translateX(10px)", "0px 0px", "opacity 1s"], close
    assert page.errors == []


# --- a11y -----------------------------------------------------------------------------------

def test_slide_labels_count_n_of_total(open_html):
    page = open_deck(open_html, deck(4))
    labels = page.evaluate("() => [...document.querySelectorAll('.slide')].map(s => s.getAttribute('aria-label'))")
    assert labels == ["1 / 4", "2 / 4", "3 / 4", "4 / 4"]


def test_only_the_active_slide_is_interactive(open_html):
    page = open_deck(open_html, deck([slide("One", extra='<button id="b1">x</button>'),
                                      slide("Two", extra='<button id="b2">y</button>'), slide("Three")]))
    inert = page.evaluate("() => [...document.querySelectorAll('.slide')].map(s => s.inert)")
    assert inert == [False, True, True]
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    inert = page.evaluate("() => [...document.querySelectorAll('.slide')].map(s => s.inert)")
    assert inert == [True, False, True]
    page.click("#b2")
    page.emulate_media(media="print")
    try:
        assert page.evaluate("() => [...document.querySelectorAll('.slide')].every(s => getComputedStyle(s).display !== 'none')")
    finally:
        page.emulate_media(media="null")


def test_wheel_scroll_still_moves_the_deck_over_inert_slides(open_html):
    page = open_deck(open_html, deck(4))
    page.mouse.move(640, 360)
    page.mouse.wheel(0, 720)
    wait_current(page, 1, timeout=5000)


# --- reduced motion -------------------------------------------------------------------------

def test_reduced_motion_zeroes_every_engine_transition(open_html, page):
    page.emulate_media(reduced_motion="reduce")
    try:
        open_deck(open_html, deck(3))
        page.keyboard.press("b")
        durations = page.evaluate("""() => ['.deck-progress', '.deck-hints', '.deck-dot', '.theme-toggle',
            '.deck-cover', '.slide .reveal'].map(s => { const e = document.querySelector(s);
              return e ? getComputedStyle(e).transitionDuration : '0s'; })""")
        assert all(set(d.split(", ")) <= {"0s"} for d in durations), durations
        assert page.evaluate("() => document.querySelector('.deck').style.scrollBehavior || getComputedStyle(document.querySelector('.deck')).scrollBehavior") == "auto"
    finally:
        page.emulate_media(reduced_motion="no-preference")


def test_reduced_motion_rule_also_covers_modules():
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    block = re.search(r"/\* reduced motion: every animation \*/.*?@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.S)
    assert block, "one global reduced-motion block"
    assert "animation-duration" in block.group(1) and "transition-duration" in block.group(1)


# --- print handout --------------------------------------------------------------------------

NOTED = [slide("One", extra='<aside class="notes"><p>Note one.</p></aside>'), slide("Two"),
         slide("Three", extra='<aside class="notes"><p>Note three.</p></aside>')]


def test_print_handout_puts_notes_after_each_slide(open_html, page):
    open_deck(open_html, deck(NOTED, deck_attrs="data-print-notes"))
    page.emulate_media(media="print")
    try:
        order = page.evaluate("""() => [...document.querySelector('.deck').children]
          .filter(e => getComputedStyle(e).display !== 'none')
          .map(e => e.classList.contains('slide') ? 'S' : (e.textContent.includes('Note') ? 'N' : '?'))""")
        assert order == ["S", "N", "S", "S", "N"], order
        pdf = page.pdf(prefer_css_page_size=True, print_background=True)
        assert len(pdf_pages(pdf)) == 5
    finally:
        page.emulate_media(media="null")
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-print-notes')).display") == "none"


def test_no_handout_without_the_option(open_html, page):
    open_deck(open_html, deck(NOTED))
    assert page.locator(".deck-print-notes").count() == 0
    page.evaluate("() => { document.querySelector('.deck').setAttribute('data-print-notes', '');"
                  " window.dispatchEvent(new Event('beforeprint')); }")
    assert page.locator(".deck-print-notes").count() == 2, "set late (render-pdf --notes), built on beforeprint"


# --- language -------------------------------------------------------------------------------

BILINGUAL = [slide('<span data-de>Eins</span><span data-en>One</span>', ' id="a"'),
             slide('<span data-de>Zwei</span><span data-en>Two</span>', ' id="b"')]


def shown(page, sel):
    return page.evaluate("(s) => getComputedStyle(document.querySelector(s)).display !== 'none'", sel)


def test_l_switches_the_language_of_pairs_and_controls(open_html):
    page = open_deck(open_html, deck(BILINGUAL, deck_attrs='data-deck-id="lang-a"'))
    assert shown(page, ".slide [data-en]") and not shown(page, ".slide [data-de]")
    page.evaluate("() => { window.__l = []; window.SlideDeck.on('langchange', e => window.__l.push(e.lang)); }")
    page.keyboard.press("l")
    assert shown(page, ".slide [data-de]") and not shown(page, ".slide [data-en]")
    assert page.evaluate("() => [document.documentElement.lang, document.documentElement.getAttribute('data-lang')]") == ["de", "de"]
    assert page.locator(".theme-toggle").get_attribute("aria-label") != "Toggle light or dark theme"
    assert page.evaluate("() => window.SlideDeck.strings().status").endswith(" von {m}")
    assert page.evaluate("() => window.__l") == ["de"]
    page.keyboard.press("?")
    assert "Tastenkürzel" in page.locator(".deck-help").inner_text()
    page.keyboard.press("Escape")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 2")
    assert page.evaluate("() => window.SlideDeck.state().lang") == "de", "the choice is kept per deck id"
    page.click("body")
    page.evaluate("() => window.SlideDeck.setLang('en')")
    assert shown(page, ".slide [data-en]")
    assert page.errors == []


def test_lang_button_and_aria_pairs(open_html):
    extra = '<button id="lb" data-deck="lang" data-aria-de="Sprache" data-aria-en="Language">L</button>'
    slides = [slide('<span data-de>Eins</span><span data-en>One</span>', extra=extra)]
    page = open_deck(open_html, deck(slides, deck_attrs='data-deck-id="lang-b"'))
    assert page.get_attribute("#lb", "aria-label") == "Language"
    page.click("#lb")
    assert page.evaluate("() => window.SlideDeck.state().lang") == "de"
    assert page.get_attribute("#lb", "aria-label") == "Sprache"


def test_l_is_off_in_a_deck_without_pairs(open_html):
    page = open_deck(open_html, deck(3, deck_attrs='data-deck-id="lang-c"'))
    page.keyboard.press("l")
    assert page.evaluate("() => window.SlideDeck.state().lang") == "en"
    page.keyboard.press("?")
    kbds = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    assert "L" not in kbds
    page.keyboard.press("Escape")
    page.evaluate("() => window.SlideDeck.setLang('de')")
    assert page.evaluate("() => window.SlideDeck.strings().status").endswith(" von {m}"), "the API still relabels"


def test_pairs_follow_html_lang_before_any_script(open_html, page):
    html = deck(BILINGUAL, lang="de")
    html = re.sub(r"(<!-- slide-engine:js:start -->).*?(<!-- slide-engine:js:end -->)", r"\1\2", html, flags=re.S)
    open_html(html)
    assert shown(page, ".slide [data-de]") and not shown(page, ".slide [data-en]")


def test_help_lists_the_core_keys(open_html):
    page = open_deck(open_html, deck(BILINGUAL, deck_attrs='data-deck-id="lang-d"'))
    page.keyboard.press("?")
    kbds = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    for k in ("B", "W", "Enter", "L", "Alt+click"):
        assert k in kbds, (k, kbds)


def test_german_help_names_the_keys_in_german(open_html):
    page = open_deck(open_html, deck(BILINGUAL, lang="de", deck_attrs='data-deck-id="lang-k"'))
    page.keyboard.press("?")
    kbds = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    for k in ("Leertaste", "Bild↓", "Alt+Klick"):
        assert k in kbds, (k, kbds)
    for k in ("Space", "PgDn", "Alt+click"):
        assert k not in kbds, (k, kbds)


def test_help_with_every_module_fits_a_laptop_screen(open_html, page):
    from engine_testlib import SHIPPED_MODULES, module_deck
    page.set_viewport_size({"width": 1440, "height": 810})
    names = sorted(p.stem for p in SHIPPED_MODULES.glob("*.js"))
    slides = BILINGUAL + [slide("Tracked", ' data-track="b"', '<div data-buehne hidden></div>')]
    open_deck(open_html, module_deck(names, slides, lang="de", deck_attrs='data-deck-id="help-fit"'))
    rows = page.evaluate("() => document.querySelectorAll('.deck-help__list dt').length")
    page.keyboard.press("?")
    fit = page.evaluate("""() => { const c = document.querySelector('.deck-help__card');
      return [c.scrollHeight, c.clientHeight]; }""")
    assert fit[0] <= fit[1] + 1, "the help list needs a scroll at 1440 x 810: %s" % fit
    keys = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    assert "F" in keys and "V" in keys and rows >= 18, (rows, keys)
