"""Deck module `read` (reference/modules.md § Module: read): the reading view.

Key R (or a data-deck="read" button) lays the slides of the active track out as one
document with their notes under each slide; R or Esc returns to the exact slide and
step. data-read-default opens a deck in it (the send variant).
"""
from __future__ import annotations

from engine_testlib import (current, deck, module_deck, new_deck, open_deck, slide,
                            wait_current, wait_settled)


def notes(text: str) -> str:
    return '<aside class="notes"><p>%s</p></aside>' % text


def five(**kw):
    slides = [slide("One", ' id="a"', notes("Note A")), slide("Two", ' id="b"'),
              slide("Three", ' id="c"', notes("Note C")), slide("Four", ' id="d"'),
              slide("Five", ' id="e"', notes("Note E"))]
    return module_deck(["read"], slides, **kw)


def reading(page) -> bool:
    return page.evaluate("() => document.documentElement.classList.contains('deck-read')")


def wait_reading(page, on: bool = True):
    page.wait_for_function("(on) => document.documentElement.classList.contains('deck-read') === on", arg=on)


def inert_count(page) -> int:
    return page.evaluate("() => document.querySelectorAll('.slide[inert]').length")


def shown_notes(page) -> list[str]:
    return page.evaluate("""() => [...document.querySelectorAll('.deck-read-notes')]
      .filter(n => getComputedStyle(n).display !== 'none').map(n => n.innerText.trim())""")


def test_absent_until_asked(open_html):
    page = open_deck(open_html, five())
    assert page.evaluate("() => document.querySelectorAll('[class*=\"deck-read\"]').length") == 0, \
        "listed with --with, the module adds nothing before R"
    plain = open_deck(open_html, deck(3))
    plain.keyboard.press("r")
    assert not reading(plain), "a deck without the module ignores R"
    assert page.errors == []


def test_r_opens_a_document_with_notes_and_returns_to_the_slide(open_html):
    page = open_deck(open_html, five())
    page.evaluate("() => window.SlideDeck.goTo(2)")
    wait_settled(page, 2)
    page.keyboard.press("r")
    wait_reading(page)
    assert inert_count(page) == 0, "every slide is readable, none inert"
    assert [n.split("\n")[-1] for n in shown_notes(page)] == ["Note A", "Note C", "Note E"]
    geo = page.evaluate("""() => ({ snap: getComputedStyle(document.querySelector('.deck')).scrollSnapType,
      scrollable: (d => d.scrollHeight > d.clientHeight + 100)(document.querySelector('.deck')),
      top: document.querySelector('#c').getBoundingClientRect().top })""")
    assert geo["snap"] in ("none", ""), "no scroll snap while reading"
    assert geo["scrollable"], "the document scrolls freely"
    assert 0 <= geo["top"] < 200, "the view opens at the slide the deck was on"
    page.mouse.wheel(0, 2500)
    page.wait_for_timeout(400)
    assert current(page) == 2, "scrolling the document does not move the deck"
    page.keyboard.press("r")
    wait_reading(page, False)
    wait_settled(page, 2)
    assert inert_count(page) == 4, "back in the deck only the active slide is live"
    assert page.evaluate("() => location.hash") == "#c"
    assert page.evaluate("() => document.querySelectorAll('.deck-read-notes, .deck-read-head').length") == 0
    assert page.errors == []


def test_escape_returns_to_the_exact_step(open_html):
    page = open_deck(open_html, five())
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    page.evaluate("() => window.SlideDeck.setStep(2)")
    page.wait_for_function("() => location.hash === '#b.2'")
    page.keyboard.press("r")
    wait_reading(page)
    page.keyboard.press("End")
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    wait_reading(page, False)
    wait_settled(page, 1)
    page.wait_for_timeout(300)
    assert page.evaluate("() => [window.SlideDeck.current(), window.SlideDeck.step(), location.hash]") == [1, 2, "#b.2"]
    assert page.errors == []


def test_keys_scroll_the_page_instead_of_paging(open_html):
    page = open_deck(open_html, five())
    page.keyboard.press("r")
    wait_reading(page)
    page.keyboard.press("PageDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Space")
    page.wait_for_function("() => document.querySelector('.deck').scrollTop > 300")
    assert current(page) == 0, "the arrows, Space and Page keys scroll, they do not change slides"
    page.keyboard.press("Home")
    page.wait_for_function("() => document.querySelector('.deck').scrollTop === 0")
    page.keyboard.press("r")
    wait_reading(page, False)
    wait_settled(page, 0)
    assert page.errors == []


def test_escape_closes_the_help_before_the_view(open_html):
    page = open_deck(open_html, five())
    page.keyboard.press("r")
    wait_reading(page)
    page.keyboard.press("?")
    assert page.evaluate("() => !document.querySelector('.deck-help').hidden")
    assert "R" in page.locator(".deck-help__list").inner_text()
    page.keyboard.press("Escape")
    assert page.evaluate("() => document.querySelector('.deck-help').hidden")
    assert reading(page), "the first Escape closed only the help"
    page.keyboard.press("Escape")
    wait_reading(page, False)
    assert page.errors == []


def test_only_the_active_track_and_its_numbers(open_html):
    slides = [slide("One", ' id="a"'), slide("Long", ' id="b" data-track="long"'),
              slide("Three", ' id="c"', notes("Note C")), slide("Long too", ' id="d" data-track="long"')]
    page = open_deck(open_html, module_deck(["read"], slides, deck_attrs='data-tracks-default="short"'))
    page.keyboard.press("r")
    wait_reading(page)
    heads = page.evaluate("""() => [...document.querySelectorAll('.deck-read-head')]
      .filter(h => getComputedStyle(h).display !== 'none').map(h => h.querySelector('.deck-read-num').textContent)""")
    assert heads == ["1 / 2", "2 / 2"]
    assert page.evaluate("() => getComputedStyle(document.querySelector('#b')).display") == "none"
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.track() === 'all'")
    page.wait_for_function("""() => [...document.querySelectorAll('.deck-read-head .deck-read-num')]
      .map(n => n.textContent).join(',') === '1 / 4,2 / 4,3 / 4,4 / 4'""")
    assert reading(page) and inert_count(page) == 0
    assert page.errors == []


def test_theme_and_language_still_switch(open_html):
    pair = '<p class="pair"><span data-de>Hallo</span><span data-en>Hello</span></p>'
    slides = [slide("One", ' id="a"', pair + notes('<span data-de>Notiz</span><span data-en>Note</span>')),
              slide("Two", ' id="b"')]
    page = open_deck(open_html, module_deck(["read"], slides))
    page.keyboard.press("r")
    wait_reading(page)
    theme = page.evaluate("() => window.SlideDeck.state().theme")
    page.keyboard.press("t")
    assert page.evaluate("() => window.SlideDeck.state().theme") != theme
    lang = page.evaluate("() => window.SlideDeck.state().lang")
    page.keyboard.press("l")
    page.wait_for_function("(l) => window.SlideDeck.state().lang !== l", arg=lang)
    want = "Hallo" if lang == "en" else "Hello"
    assert page.locator("#a .pair").inner_text().strip() == want
    assert page.locator(".deck-read-notes").first.inner_text().strip().endswith("Notiz" if want == "Hallo" else "Note")
    assert page.locator(".deck-read-bar [data-deck='lang']").count() == 1, "a bilingual deck offers the switch"
    page.wait_for_timeout(100)
    assert reading(page) and inert_count(page) == 0, "a relabel does not make slides inert again"
    assert page.errors == []


def test_buttons_open_present_and_present_from_here(open_html):
    btn = '<button type="button" class="open-read" data-deck="read">Read</button>'
    slides = [slide("One", ' id="a"', btn), slide("Two", ' id="b"'), slide("Three", ' id="c"'),
              slide("Four", ' id="d"')]
    page = open_deck(open_html, module_deck(["read"], slides))
    page.click(".open-read")
    wait_reading(page)
    assert page.locator(".deck-read-bar [data-deck='lang']").count() == 0, "no language switch in a one-language deck"
    page.click(".deck-read-bar .deck-read-present")
    wait_reading(page, False)
    wait_settled(page, 0)
    page.keyboard.press("r")
    wait_reading(page)
    page.locator(".deck-read-head").nth(3).locator(".deck-read-go").click()
    wait_reading(page, False)
    wait_settled(page, 3)
    page.wait_for_function("() => location.hash === '#d'")
    assert page.errors == []


def test_a_number_jump_while_reading_picks_the_slide_to_return_to(open_html):
    page = open_deck(open_html, five())
    page.keyboard.press("r")
    wait_reading(page)
    page.keyboard.type("4")
    page.keyboard.press("Enter")
    wait_current(page, 3)
    page.wait_for_function("() => Math.abs(document.querySelector('#d').getBoundingClientRect().top) < 150")
    page.wait_for_timeout(800)
    page.keyboard.press("r")
    wait_reading(page, False)
    wait_settled(page, 3)
    assert page.errors == []


def test_read_default_opens_the_send_copy_in_the_view(open_html):
    page = open_deck(open_html, five(deck_attrs="data-read-default"))
    wait_reading(page)
    assert page.evaluate("() => document.querySelector('.deck').scrollTop") == 0
    page.keyboard.press("Escape")
    wait_reading(page, False)
    wait_settled(page, 0)
    page.goto(page.url.split("#")[0] + "#d")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() > 0")
    wait_reading(page)
    page.wait_for_function("() => Math.abs(document.querySelector('#d').getBoundingClientRect().top) < 200")
    off = open_deck(open_html, five(deck_attrs='data-read-default="off"'))
    assert not reading(off)
    assert page.errors == []


def test_hidden_steps_show_while_reading(open_html):
    extra = '<p class="frag" data-step style="visibility: hidden; opacity: 0">later</p>'
    page = open_deck(open_html, module_deck(["read"], [slide("One", ' id="a"', extra), slide("Two")]))
    page.keyboard.press("r")
    wait_reading(page)
    assert page.evaluate("""() => { const s = getComputedStyle(document.querySelector('.frag'));
      return s.visibility === 'visible' && s.opacity === '1'; }"""), "a document shows every step"
    page.keyboard.press("r")
    wait_reading(page, False)
    assert page.evaluate("() => getComputedStyle(document.querySelector('.frag')).visibility") == "hidden"


def test_print_shows_the_slides_not_the_reading_chrome(open_html, page):
    open_deck(open_html, five())
    page.keyboard.press("r")
    wait_reading(page)
    page.emulate_media(media="print")
    try:
        shown = page.evaluate("""() => [...document.querySelectorAll('.deck-read-head, .deck-read-notes, .deck-read-bar, .deck-read-progress')]
          .filter(e => getComputedStyle(e).display !== 'none').length""")
        assert shown == 0
        assert page.evaluate("() => getComputedStyle(document.querySelector('#a')).height").startswith("63")  # 167mm
    finally:
        page.emulate_media(media="null")


def test_progress_follows_the_scroll(open_html):
    page = open_deck(open_html, five())
    page.keyboard.press("r")
    wait_reading(page)
    page.keyboard.press("End")
    page.wait_for_function("""() => { const p = document.querySelector('.deck-read-progress');
      return p && parseFloat(p.style.width) > 95; }""")


def test_new_deck_ships_the_module():
    assert "read" in new_deck().available_modules()


def test_narrow_window_reads_without_sideways_scroll(open_html):
    page = open_deck(open_html, five(), viewport={"width": 500, "height": 800})
    page.keyboard.press("r")
    wait_reading(page)
    assert page.evaluate("() => { const d = document.querySelector('.deck'); return d.scrollWidth <= d.clientWidth + 1; }")
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-read-label')).display") == "none"
    assert page.errors == []
