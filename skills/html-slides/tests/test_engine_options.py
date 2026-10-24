"""Engine v2 localised controls and deck options (plan item S8).

Options are read from the deck root first, then from <html>. The German
expectations are matched by shape on purpose, so this file stays English.
"""
from __future__ import annotations

import re

import pytest

from engine_testlib import counter, deck, open_deck, wait_current, slide


def test_english_controls_by_default(open_html):
    page = open_deck(open_html, deck(3))
    assert page.locator(".deck-dot").nth(1).get_attribute("aria-label") == "Go to slide 2"
    assert page.locator(".theme-toggle").get_attribute("aria-label") == "Toggle light or dark theme"
    page.keyboard.press("ArrowRight")
    wait_current(page, 1)
    page.wait_for_function("() => document.querySelector('[aria-live=polite]').textContent.trim() === 'Slide 2 of 3'")


def test_german_controls_by_html_lang(open_html):
    en = open_deck(open_html, deck(3)).evaluate("() => window.SlideDeck.strings()")
    page = open_deck(open_html, deck(3, lang="de"))
    de = page.evaluate("() => window.SlideDeck.strings()")
    assert set(de) == set(en)
    same = sorted(k for k in en if en[k] == de[k] and re.search(r"[a-z]{3}", str(en[k])))
    assert not same, "untranslated: %s" % same
    page.keyboard.press("ArrowRight")
    wait_current(page, 1)
    page.wait_for_function("() => /^\\S+ 2 von 3$/.test(document.querySelector('[aria-live=polite]').textContent.trim())")
    label = page.locator(".deck-dot").nth(1).get_attribute("aria-label")
    assert label != "Go to slide 2" and "2" in label
    assert page.evaluate("() => document.querySelector('.slide').getAttribute('aria-roledescription')") == de["slide"].lower()
    page.keyboard.press("?")
    assert page.locator(".deck-help").is_visible()
    assert "Tastenkürzel" in page.locator(".deck-help").inner_text()


def test_lang_region_subtag_and_unknown_lang(open_html):
    page = open_deck(open_html, deck(2, lang="de-AT"))
    assert "von" in page.evaluate("() => window.SlideDeck.strings().status")
    page = open_deck(open_html, deck(2, lang="xx"))
    assert page.evaluate("() => window.SlideDeck.strings().status") == "Slide {n} of {m}"


@pytest.mark.parametrize("where", ["html", "deck"])
def test_padded_counter(open_html, where):
    attrs = {"html_attrs": 'data-counter-format="padded"'} if where == "html" else {"deck_attrs": 'data-counter-format="padded"'}
    page = open_deck(open_html, deck(9, **attrs))
    assert counter(page) == "01 / 09"
    page.keyboard.press("End")
    wait_current(page, 8)
    assert counter(page) == "09 / 09"


def test_dots_off(open_html):
    page = open_deck(open_html, deck(4, deck_attrs='data-dots="off"'))
    assert page.locator(".deck-dot").count() == 0
    assert counter(page) == "1 / 4"
    page.keyboard.press("ArrowRight")
    wait_current(page, 1)
    assert page.errors == []


def test_back_link(open_html):
    page = open_deck(open_html, deck(2, html_attrs='data-back-href="../index.html"'))
    link = page.locator("a.deck-back")
    assert link.count() == 1
    assert link.get_attribute("href") == "../index.html"
    assert "Back" in link.inner_text()
    page = open_deck(open_html, deck(2, lang="de", html_attrs='data-back-href="../index.html"'))
    assert "Zurück" in page.locator("a.deck-back").inner_text()
    page = open_deck(open_html, deck(2, html_attrs='data-back-href="#top" data-back-label="Overview page"'))
    assert "Overview page" in page.locator("a.deck-back").inner_text()


def test_no_back_link_without_option(open_html):
    page = open_deck(open_html, deck(2))
    assert page.locator("a.deck-back").count() == 0


def test_help_overlay_toggles_and_closes(open_html):
    page = open_deck(open_html, deck(3))
    assert not page.locator(".deck-help").is_visible()
    page.keyboard.press("?")
    help_box = page.locator(".deck-help")
    assert help_box.is_visible()
    text = help_box.inner_text()
    assert "Keyboard shortcuts" in text and "Next slide" in text
    page.keyboard.press("Escape")
    assert not help_box.is_visible()
    page.keyboard.press("?")
    page.keyboard.press("?")
    assert not help_box.is_visible()


def test_help_lists_page_keys_and_the_stage_key_only_with_a_stage(open_html):
    page = open_deck(open_html, deck(3))
    page.keyboard.press("?")
    kbds = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    assert "PgDn" in kbds and "PgUp" in kbds
    assert "V" not in kbds
    staged = slide("Live", extra='<div class="stage" data-src="sim.html"></div>')
    page = open_deck(open_html, deck([slide("One"), staged]))
    page.keyboard.press("?")
    kbds = page.evaluate("() => [...document.querySelectorAll('.deck-help kbd')].map(k => k.textContent)")
    assert "V" in kbds
