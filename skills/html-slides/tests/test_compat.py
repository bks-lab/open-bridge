"""Old decks keep working when their engine region is refreshed to the current engine.

Each fixture under fixtures/compat/ is a minimal, content-free deck that uses
one API pattern older decks rely on. The test splices the CURRENT
assets/slide-engine.{css,js} between the deck's engine markers, the same thing
a refresh does, and opens it from an empty temp dir.
"""
from __future__ import annotations

import re

import pytest

from slides_testlib import FIXTURES, splice_engine

COMPAT = FIXTURES / "compat"
CASES = sorted(p.name for p in COMPAT.glob("*.html"))


CURRENT = """() => {
  if (window.SlideDeck && typeof window.SlideDeck.current === 'function') return window.SlideDeck.current();
  const dots = [...document.querySelectorAll('.deck-dot')];
  return dots.findIndex(d => d.classList.contains('active'));
}"""


def load(open_html, name: str):
    return open_html(splice_engine((COMPAT / name).read_text("utf-8")))


def wait_current(page, index: int):
    page.wait_for_function("(i) => (%s)() === i" % CURRENT, arg=index, timeout=4000)


def test_fixtures_present():
    assert set(CASES) >= {"global-slideengine.html", "underscore-slideengine.html",
                          "theme-classes.html", "track-attribute.html"}


@pytest.mark.parametrize("name", CASES)
def test_loads_without_errors(open_html, name):
    page = load(open_html, name)
    page.wait_for_selector(".deck-progress", state="attached")
    page.wait_for_timeout(200)
    assert page.errors == []


@pytest.mark.parametrize("name", [
    "global-slideengine.html",
    "underscore-slideengine.html",
])
def test_one_engine_instance(open_html, name):
    """The aliases point at the engine's own instance, so the deck creates no second one."""
    page = load(open_html, name)
    page.wait_for_selector(".deck-progress", state="attached")
    assert page.locator(".deck-progress").count() == 1
    assert page.evaluate("() => window.slideEngine === window.__slideEngine && !!window.slideEngine")


def test_global_alias_goto(open_html):
    page = load(open_html, "global-slideengine.html")
    page.wait_for_selector(".deck-progress", state="attached")
    page.click(".jump")
    wait_current(page, 3)
    assert page.errors == []


def test_underscore_alias_next(open_html):
    page = load(open_html, "underscore-slideengine.html")
    page.wait_for_selector(".deck-progress", state="attached")
    page.click(".advance")
    wait_current(page, 1)
    assert page.errors == []


BG = "() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"


def test_theme_classes_toggle_and_persist(open_html, page):
    """No stored choice follows the OS; T sets .theme-dark, a reload keeps it, T again sets .theme-light."""
    page.emulate_media(color_scheme="light")
    load(open_html, "theme-classes.html")
    page.evaluate("() => localStorage.removeItem('slide-theme')")
    page.reload()
    page.wait_for_selector(".theme-toggle", state="attached")
    assert page.evaluate(BG) == "#fafafa"
    page.keyboard.press("t")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-dark')")
    assert page.evaluate(BG) == "#101010"
    page.reload()
    page.wait_for_selector(".theme-toggle", state="attached")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-dark')")
    assert page.evaluate(BG) == "#101010"
    page.keyboard.press("t")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-light')")
    assert page.evaluate(BG) == "#fafafa"
    assert page.errors == []


def _counter_total(page) -> int:
    text = page.locator(".deck-counter").first.inner_text()
    return int(re.search(r"/\s*(\d+)", text).group(1))


def test_track_attribute_filters_and_counts_visible(open_html):
    """data-spur is read as data-track: the default track hides the other track's slides."""
    page = load(open_html, "track-attribute.html")
    page.wait_for_selector(".deck-counter", state="attached")
    assert _counter_total(page) == 4
    page.emulate_media(media="print")
    shown = page.evaluate("() => [...document.querySelectorAll('.slide')]"
                          ".filter(s => getComputedStyle(s).display !== 'none').length")
    page.emulate_media(media="screen")
    assert shown == 6, "print shows every slide"
    assert page.errors == []
