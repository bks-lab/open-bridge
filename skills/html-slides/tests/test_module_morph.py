"""Deck module `morph` (assets/modules/morph.js, reference/modules.md § morph).

Elements sharing a data-morph name on the slide left and the slide reached get a
view-transition-name for the transition and morph through
document.startViewTransition. A spy around startViewTransition records what the
module does; no support or reduced motion means an instant change.
"""
from __future__ import annotations

from engine_testlib import current, module_deck, open_deck, slide, wait_settled

SPY = """() => {
  const orig = document.startViewTransition && document.startViewTransition.bind(document);
  const log = window.__vt = { calls: 0, skips: 0, during: [], after: null };
  document.startViewTransition = (cb) => {
    log.calls++;
    const t = orig(() => {
      cb();
      log.during.push([...document.querySelectorAll('[data-morph]')]
        .filter(e => e.style.viewTransitionName)
        .map(e => e.closest('.slide').id + ':' + e.style.viewTransitionName));
    });
    const skip = t.skipTransition.bind(t);
    t.skipTransition = () => { log.skips++; skip(); };
    t.finished.then(() => setTimeout(() => { log.after = [...document.querySelectorAll('[data-morph]')]
      .filter(e => e.style.viewTransitionName).length; }));
    return t;
  };
}"""


def box(name: str, cls: str = "") -> str:
    return '<div data-morph="%s" class="%s" style="width:120px;height:60px;background:var(--accent)"></div>' % (name, cls)


def morph_deck(**kw):
    slides = [slide("One", ' id="a"', box("hero card")),
              slide("Two", ' id="b"', box("hero card") + box("hero card", "dup")),
              slide("Three", ' id="c"', box("hero card")),
              slide("Four", ' id="d"', box("other")),
              slide("Five", ' id="e"')]
    return module_deck(["morph"], slides, **kw)


def vt(page):
    return page.evaluate("() => window.__vt")


def test_shared_names_morph_through_a_view_transition(open_html):
    page = open_deck(open_html, morph_deck())
    page.evaluate(SPY)
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    page.wait_for_function("() => window.__vt.after !== null")
    log = vt(page)
    assert log["calls"] == 1
    assert log["during"] == [["b:morph-hero_card"]], "only the reached slide carries the name, the first of a duplicate"
    assert log["after"] == 0, "names are cleared once the transition finished"
    assert page.errors == []


def test_no_shared_name_means_no_view_transition(open_html):
    page = open_deck(open_html, morph_deck())
    page.evaluate("() => window.SlideDeck.goTo(2)")
    wait_settled(page, 2)
    page.evaluate(SPY)
    page.keyboard.press("ArrowRight")
    wait_settled(page, 3)
    page.keyboard.press("ArrowRight")
    wait_settled(page, 4)
    assert vt(page)["calls"] == 0


def test_fast_presses_skip_the_running_transition(open_html):
    page = open_deck(open_html, morph_deck())
    page.evaluate(SPY)
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 2)
    log = vt(page)
    assert log["calls"] == 2 and log["skips"] >= 1
    page.wait_for_function("() => [...document.querySelectorAll('[data-morph]')].every(e => !e.style.viewTransitionName)")
    assert page.errors == []


def test_without_view_transitions_the_change_is_instant(open_html):
    page = open_deck(open_html, morph_deck())
    page.evaluate("() => { document.startViewTransition = undefined; }")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert current(page) == 1
    assert page.errors == []


def test_reduced_motion_never_starts_a_transition(open_html, page):
    page.emulate_media(reduced_motion="reduce")
    try:
        open_deck(open_html, morph_deck())
        page.evaluate(SPY)
        page.keyboard.press("ArrowRight")
        wait_settled(page, 1)
        assert vt(page)["calls"] == 0
    finally:
        page.emulate_media(reduced_motion="null")


def test_morph_duration_option(open_html):
    page = open_deck(open_html, morph_deck(deck_attrs='data-morph-duration="900"'))
    assert page.evaluate("() => getComputedStyle(document.documentElement)"
                         ".getPropertyValue('--morph-duration').trim()") == "900ms"


def test_steps_and_morph_together(open_html):
    slides = [slide("One", ' id="a"', box("k") + '<p data-step class="s">x</p>'),
              slide("Two", ' id="b"', box("k"))]
    page = open_deck(open_html, module_deck(["morph", "steps"], slides))
    page.evaluate(SPY)
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.step() === 1")
    assert current(page) == 0
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert vt(page)["calls"] == 1
    assert page.errors == []
