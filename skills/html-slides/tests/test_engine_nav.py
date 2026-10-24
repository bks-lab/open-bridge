"""Engine v2 navigation (plan item S6): fast keys, deep links, guards, start, API, ARIA.

Every check opens a spliced deck from an empty temp dir via file://.
"""
from __future__ import annotations

import re

from engine_testlib import (DESKTOP, current, counter, deck, open_deck, slide, wait_current,
                            wait_settled)
from slides_testlib import ASSETS


def test_version_stamp_on_both_assets():
    for name in ("slide-engine.js", "slide-engine.css"):
        first = (ASSETS / name).read_text("utf-8").splitlines()[0]
        assert re.search(r"slide-engine v2\b", first), name


def test_five_fast_arrows_land_on_slide_six(open_html):
    page = open_deck(open_html, deck(9))
    for _ in range(5):
        page.keyboard.press("ArrowRight")
    assert current(page) == 5, "the target index is set at once, not when the scroll lands"
    wait_settled(page, 5)
    page.wait_for_timeout(600)
    assert current(page) == 5
    assert counter(page) == "6 / 9"
    assert page.errors == []


def test_deep_link_written_and_survives_reload(open_html):
    page = open_deck(open_html, deck(9))
    page.evaluate("() => window.SlideDeck.goTo(4)")
    wait_settled(page, 4)
    page.wait_for_function("() => location.hash === '#5'", timeout=3000)
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 9")
    wait_settled(page, 4)
    assert counter(page) == "5 / 9"
    assert page.errors == []


def test_deep_link_on_first_open(open_html, page):
    open_deck(open_html, deck(9))
    page.goto(page.url.split("#")[0] + "#3")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 9")
    wait_settled(page, 2)


def test_goto_out_of_range_never_throws(open_html):
    page = open_deck(open_html, deck(9))
    page.evaluate("""() => { const d = window.SlideDeck;
      d.goTo(99); d.goTo(-4); d.goTo('x'); d.goTo(undefined); d.goTo(null); d.goTo(99); }""")
    wait_settled(page, 8)
    page.evaluate("() => { window.slideEngine.goTo(1e9); window.__slideEngine.goTo(-1); }")
    wait_settled(page, 0)
    assert page.errors == []


def test_reduced_motion_scrolls_with_behavior_auto(open_html, page):
    page.emulate_media(reduced_motion="reduce")
    try:
        open_deck(open_html, deck(5))
        page.evaluate("""() => { window.__behaviors = [];
          const orig = Element.prototype.scrollIntoView;
          Element.prototype.scrollIntoView = function (o) { window.__behaviors.push(o && o.behavior); return orig.call(this, o); }; }""")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        behaviors = page.evaluate("() => window.__behaviors")
        assert behaviors and all(b == "auto" for b in behaviors), behaviors
    finally:
        page.emulate_media(reduced_motion="no-preference")


def test_starts_when_document_already_complete(open_html, page):
    html = deck(4)
    js = re.search(r"<!-- slide-engine:js:start -->\n<script>\n(.*?)\n</script>", html, re.S).group(1)
    html = re.sub(r"(<!-- slide-engine:js:start -->).*?(<!-- slide-engine:js:end -->)", r"\1\2", html, flags=re.S)
    open_html(html, viewport=DESKTOP)
    assert page.evaluate("() => document.readyState") == "complete"
    page.evaluate("(src) => { const s = document.createElement('script'); s.textContent = src; document.body.appendChild(s); }", js)
    assert page.evaluate("() => window.SlideDeck.count()") == 4
    assert page.locator(".deck-progress").count() == 1
    assert page.errors == []


def test_aria_roles_current_dot_and_live_region(open_html):
    page = open_deck(open_html, deck(4))
    roles = page.evaluate("() => [...document.querySelectorAll('.slide')].map(s => [s.getAttribute('role'), s.getAttribute('aria-roledescription')])")
    assert roles == [["group", "slide"]] * 4
    page.keyboard.press("ArrowRight")
    wait_current(page, 1)
    marked = page.evaluate("() => [...document.querySelectorAll('.deck-dot')].map(d => d.getAttribute('aria-current'))")
    assert marked == [None, "true", None, None]
    live = page.locator("[aria-live=polite]")
    assert live.count() == 1
    page.wait_for_function("() => document.querySelector('[aria-live=polite]').textContent.trim() === 'Slide 2 of 4'")


def test_shift_space_goes_back(open_html):
    page = open_deck(open_html, deck(5))
    page.keyboard.press(" ")
    page.keyboard.press(" ")
    wait_current(page, 2)
    page.keyboard.press("Shift+ ")
    wait_settled(page, 1)


def test_modifier_keys_are_ignored(open_html):
    page = open_deck(open_html, deck(5))
    for combo in ("Control+ArrowRight", "Meta+ArrowRight", "Alt+ArrowRight", "Control+t", "Meta+ArrowDown"):
        page.keyboard.press(combo)
    page.wait_for_timeout(300)
    assert current(page) == 0
    assert not page.evaluate("() => document.documentElement.classList.contains('theme-light')"
                             " || document.documentElement.classList.contains('theme-dark')")


def test_keys_ignored_in_inputs_editables_and_marked_regions(open_html):
    extra = ('<input id="field" type="text"><div id="editable" contenteditable="true">edit</div>'
             '<div id="ignored" tabindex="0" data-key-ignore>region</div>')
    page = open_deck(open_html, deck([slide("Form", extra=extra), slide("Two"), slide("Three")]))
    for sel in ("#field", "#editable", "#ignored"):
        page.focus(sel)
        page.keyboard.press("ArrowRight")
        page.keyboard.press(" ")
        page.keyboard.press("End")
    page.wait_for_timeout(300)
    assert current(page) == 0


def test_public_api_aliases_and_events(open_html):
    page = open_deck(open_html, deck(5))
    shape = page.evaluate("""() => { const d = window.SlideDeck;
      return ['goTo','next','prev','current','count','setTrack','on'].every(k => typeof d[k] === 'function')
        && window.slideEngine === window.__slideEngine && !!window.slideEngine; }""")
    assert shape
    page.evaluate("""() => { window.__seen = [];
      window.SlideDeck.on('slidechange', e => window.__seen.push(e.index + '/' + e.count)); }""")
    page.evaluate("() => window.SlideDeck.next()")
    page.evaluate("() => window.SlideDeck.goTo(3)")
    page.evaluate("() => window.SlideDeck.prev()")
    assert page.evaluate("() => window.__seen") == ["1/5", "3/5", "2/5"]
    assert page.evaluate("() => window.SlideDeck.count()") == 5
    assert page.evaluate("() => new SlideEngine() === window.slideEngine")
    assert page.locator(".deck-progress").count() == 1


def test_declarative_buttons(open_html):
    buttons = ('<button id="b-next" data-deck="next">n</button><button id="b-goto" data-deck="goto:4">g</button>'
               '<button id="b-theme" data-deck="theme">t</button>')
    back = '<button id="b-prev" data-deck="prev">p</button>'
    page = open_deck(open_html, deck([slide("One", extra=buttons), slide("Two"), slide("Three"), slide("Four", extra=back)]))
    page.click("#b-goto")
    wait_settled(page, 3)
    page.click("#b-prev")
    wait_settled(page, 2)
    page.evaluate("() => window.SlideDeck.goTo(0)")
    wait_settled(page, 0)
    page.click("#b-next")
    wait_settled(page, 1)
    page.evaluate("() => window.SlideDeck.goTo(0)")
    wait_settled(page, 0)
    page.click("#b-theme")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-light')"
                         " || document.documentElement.classList.contains('theme-dark')")
    assert page.errors == []


def test_space_on_a_focused_dot_does_not_also_advance(open_html):
    page = open_deck(open_html, deck(5))
    page.focus(".deck-dots button:nth-child(1)")
    page.keyboard.press(" ")
    page.wait_for_timeout(300)
    assert current(page) == 0, "Space activates the focused dot, it does not also step the deck"
    page.evaluate("() => document.activeElement.blur()")
    page.keyboard.press(" ")
    wait_current(page, 1)
