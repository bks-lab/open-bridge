"""Engine v2 speaker notes and the overview slide type (plan item S10)."""
from __future__ import annotations

from engine_testlib import fixture, open_deck, wait_settled
from slides_testlib import slide_type_snippets

PANEL_TEXT = "() => document.querySelector('.deck-notes__body').textContent.trim()"


def test_notes_hidden_on_the_slide(open_html):
    page = open_deck(open_html, fixture("overview-notes.html"))
    assert page.evaluate("() => [...document.querySelectorAll('aside.notes')].every(a => getComputedStyle(a).display === 'none')")
    assert not page.locator(".deck-notes").is_visible()


def test_n_toggles_panel_that_follows_navigation(open_html):
    page = open_deck(open_html, fixture("overview-notes.html"))
    page.keyboard.press("n")
    assert page.locator(".deck-notes").is_visible()
    assert page.evaluate(PANEL_TEXT) == "Note one: open with the overview."
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('.deck-notes__body').textContent.includes('Note two')")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => !document.querySelector('.deck-notes__body').textContent.includes('Note two')")
    assert page.locator(".deck-notes__body .deck-notes__empty").count() == 1
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('.deck-notes__body').textContent.includes('Note four')")
    page.keyboard.press("n")
    assert not page.locator(".deck-notes").is_visible()
    assert page.errors == []


def test_notes_button_and_hidden_in_print(open_html, page):
    open_deck(open_html, fixture("overview-notes.html"))
    page.evaluate("() => window.SlideDeck.toggleNotes()")
    assert page.locator(".deck-notes").is_visible()
    page.emulate_media(media="print")
    try:
        assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-notes')).display") == "none"
        assert page.evaluate("() => [...document.querySelectorAll('aside.notes')].every(a => getComputedStyle(a).display === 'none')")
    finally:
        page.emulate_media(media="null")


def test_overview_tile_jumps_to_its_slide(open_html):
    page = open_deck(open_html, fixture("overview-notes.html"))
    page.click(".overview-tile[data-deck='goto:4']")
    wait_settled(page, 3)
    page.wait_for_function("() => location.hash === '#4'")
    page.keyboard.press("Home")
    wait_settled(page, 0)
    page.click(".overview-tile[data-deck='goto:2']")
    wait_settled(page, 1)


def test_slide_types_document_overview_and_notes():
    snippets = dict(slide_type_snippets())
    overview = [h for h in snippets if h.lower().startswith("overview")]
    notes = [h for h in snippets if "notes" in h.lower()]
    assert overview and notes
    assert 'data-deck="goto:' in snippets[overview[0]] and "slide--overview" in snippets[overview[0]]
    assert '<aside class="notes">' in snippets[notes[0]]
