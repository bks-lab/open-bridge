"""Engine v2 track filter (plan item S7).

fixtures/engine/tracks-7.html holds seven slides: one without a track, four on
"run", two on "prep", with data-tracks-default="run". Expected, as measured on
the deck engine this feature was lifted from: 5 slides at start, 7 after F,
5 after F again, dots, counter and progress following along.
"""
from __future__ import annotations

from engine_testlib import (counter, deck, fixture, open_deck, pdf_pages, shown_slides, slide,
                            wait_settled)


def state(page) -> tuple[int, int, str, float]:
    dots = page.locator(".deck-dot").count()
    width = page.evaluate("() => parseFloat(document.querySelector('.deck-progress').style.width)")
    return shown_slides(page), dots, counter(page), round(width)


def test_five_seven_five(open_html):
    page = open_deck(open_html, fixture("tracks-7.html"))
    assert state(page) == (5, 5, "1 / 5", 20)
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.count() === 7")
    assert state(page)[:3] == (7, 7, "1 / 7")
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.count() === 5")
    assert state(page) == (5, 5, "1 / 5", 20)
    assert page.errors == []


def test_track_persists_per_deck(open_html, page):
    open_deck(open_html, fixture("tracks-7.html"))
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.count() === 7")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 7")
    # A second deck (another path) keeps its own choice.
    open_deck(open_html, fixture("tracks-7.html"))
    assert page.evaluate("() => window.SlideDeck.count()") == 5


def test_unknown_or_empty_track_falls_back_to_all(open_html):
    page = open_deck(open_html, fixture("tracks-7.html"))
    page.evaluate("() => window.SlideDeck.setTrack('nothing-carries-this')")
    page.wait_for_function("() => window.SlideDeck.count() === 7")
    only_tracked = [slide("A%d" % i, attrs=' data-track="prep"') for i in range(3)]
    page = open_deck(open_html, deck(only_tracked, html_attrs='data-tracks-default="run"'))
    assert page.evaluate("() => window.SlideDeck.count()") == 3, "an empty filter shows every slide"


def test_set_track_and_track_button(open_html):
    btn = '<button id="to-prep" data-deck="track:prep">prep</button>'
    html = fixture("tracks-7.html").replace("<p class=\"slide__body reveal\">Neutral sample text.</p>",
                                            "<p class=\"slide__body reveal\">Neutral sample text.</p>" + btn, 1)
    page = open_deck(open_html, html)
    page.click("#to-prep")
    page.wait_for_function("() => window.SlideDeck.count() === 3")
    titles = page.evaluate("() => [...document.querySelectorAll('.slide')].filter(s => getComputedStyle(s).display !== 'none')"
                           ".map(s => s.querySelector('h2').textContent)")
    assert titles == ["Frame", "Prep 1", "Prep 2"]
    page.evaluate("() => window.SlideDeck.setTrack('all')")
    page.wait_for_function("() => window.SlideDeck.count() === 7")


def test_position_follows_the_slide_across_a_switch(open_html):
    page = open_deck(open_html, fixture("tracks-7.html"))
    page.evaluate("() => window.SlideDeck.goTo(2)")  # Run 2 in the run track
    wait_settled(page, 2)
    page.keyboard.press("f")
    wait_settled(page, 3)  # Run 2 is the fourth of all seven
    assert counter(page) == "4 / 7"


def test_print_shows_every_slide(open_html, page):
    open_deck(open_html, fixture("tracks-7.html"))
    assert shown_slides(page) == 5
    page.emulate_media(media="print")
    try:
        assert shown_slides(page) == 7
    finally:
        page.emulate_media(media="null")
    pages = pdf_pages(page.pdf(prefer_css_page_size=True))
    assert len(pages) == 7


def test_track_is_announced_in_the_deck_chrome(open_html):
    page = open_deck(open_html, fixture("tracks-7.html"))
    assert page.evaluate("() => document.documentElement.getAttribute('data-track-active')") == "run"
    page.keyboard.press("f")
    page.wait_for_function("() => document.documentElement.getAttribute('data-track-active') === 'all'")
    hints = page.locator(".deck-hints").inner_text()
    assert "F" in hints


def test_a_default_track_no_slide_names_still_exists(open_html):
    """Untagged slides belong to every track, so a track named only by the deck is real."""
    slides = [slide("Core %d" % i) for i in range(4)] + [slide("Extra %d" % i, attrs=' data-track="long"') for i in range(2)]
    page = open_deck(open_html, deck(slides, html_attrs='data-tracks-default="short"'))
    assert page.evaluate("() => window.SlideDeck.count()") == 4
    assert page.evaluate("() => window.SlideDeck.track()") == "short"
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.count() === 6")


def test_a_cycle_track_no_slide_names_still_exists(open_html):
    slides = [slide("Core %d" % i) for i in range(3)] + [slide("Extra", attrs=' data-track="full"')]
    page = open_deck(open_html, deck(slides, html_attrs='data-tracks-cycle="short full"'))
    page.evaluate("() => window.SlideDeck.setTrack('short')")
    page.wait_for_function("() => window.SlideDeck.count() === 3")
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.count() === 4")


def test_deep_link_uses_the_slide_id_so_it_holds_in_every_track(open_html, page):
    slides = [slide("One"), slide("Two", attrs=' data-track="full"'), slide("Three", attrs=' id="s-three"'), slide("Four")]
    open_deck(open_html, deck(slides, html_attrs='data-tracks-default="short"'))
    page.evaluate("() => window.SlideDeck.goTo(1)")
    page.wait_for_function("() => location.hash === '#s-three'", timeout=3000)
    page.evaluate("() => window.SlideDeck.goTo(2)")
    page.wait_for_function("() => location.hash === '#3'", timeout=3000)
    page.evaluate("() => window.SlideDeck.setTrack('full')")
    page.goto(page.url.split("#")[0] + "#s-three")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 4")
    page.wait_for_function("() => window.SlideDeck.current() === 2")
    page.wait_for_timeout(300)
    assert page.evaluate("() => location.hash") == "#s-three", "a copied #id link keeps its id form"


def test_track_labels_change_what_is_read_not_the_name(open_html, page):
    """data-tracks-labels gives a track a display name; data-track, storage and API keep the name."""
    slides = [slide("Core"), slide("Extra", attrs=' data-track="full"')]
    open_deck(open_html, deck(slides, deck_attrs='data-tracks-cycle="short full" data-tracks-default="full"'
                                                  ' data-tracks-labels="short=kurz full=lang"'))
    assert page.locator(".deck-track").inner_text() == "Track: lang"
    assert page.evaluate("() => [window.SlideDeck.track(), window.SlideDeck.trackLabel()]") == ["full", "lang"]
    page.evaluate("""() => { window.got = null;
      document.addEventListener('slidedeck:trackchange', e => { window.got = e.detail; }); }""")
    page.keyboard.press("f")
    page.wait_for_function("() => window.got !== null")
    assert page.evaluate("() => [window.got.track, window.got.label]") == ["short", "kurz"]
    assert page.locator(".deck-track").inner_text() == "Track: kurz"


def test_track_buttons_carry_aria_pressed(open_html, page):
    btns = '<button id="b-run" data-deck="track:run">run</button><button id="b-prep" data-deck="track:prep">prep</button>'
    html = fixture("tracks-7.html").replace("<p class=\"slide__body reveal\">Neutral sample text.</p>",
                                            "<p class=\"slide__body reveal\">Neutral sample text.</p>" + btns, 1)
    open_deck(open_html, html)
    assert [page.get_attribute(s, "aria-pressed") for s in ("#b-run", "#b-prep")] == ["true", "false"]
    page.click("#b-prep")
    page.wait_for_function("() => document.querySelector('#b-prep').getAttribute('aria-pressed') === 'true'")
    assert page.get_attribute("#b-run", "aria-pressed") == "false"
