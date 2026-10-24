"""Engine plugin API (reference/modules.md): SlideDeck.use, state, steps, events.

The probe module in fixtures/modules/probe.js is spliced exactly as
new-deck.py --with would splice a shipped module, through engine_testlib.
"""
from __future__ import annotations

from engine_testlib import (MODULE_FIXTURES, current, deck, module_deck, open_deck, slide,
                            wait_current, wait_settled)


def probe_deck(slides=None, **kw):
    if slides is None:
        slides = [slide("One", ' id="a"'), slide("Two", ' id="b" data-probe-steps="2"'),
                  slide("Three", ' id="c"'), slide("Four", ' id="d"')]
    return module_deck(["probe"], slides, root=MODULE_FIXTURES, **kw)


def log(page):
    return page.evaluate("() => { const l = window.__probe; return {inits: l.inits, keys: l.keys,"
                         " steps: l.steps, transitions: l.transitions, api: l.api}; }")


def test_init_runs_once_with_the_api(open_html):
    page = open_deck(open_html, probe_deck())
    assert log(page)["inits"] == 1 and log(page)["api"] is True
    page.evaluate("""() => { window.__late = 0;
      window.SlideDeck.use({ name: 'late', init: () => { window.__late++; } }); }""")
    assert page.evaluate("() => window.__late") == 1, "use() after ready calls init at once"
    page.evaluate("() => window.SlideDeck.use({ name: 'late', init: () => { window.__late++; } })")
    assert page.evaluate("() => window.__late") == 1, "a second module with the same name is ignored"
    assert page.errors == []


def test_module_keys_true_handles_false_falls_through(open_html):
    page = open_deck(open_html, probe_deck())
    page.keyboard.press("p")
    page.keyboard.press("Shift+P")
    assert log(page)["keys"] == ["p", "p"], "keys are matched lower-case"
    page.keyboard.press("Control+p")
    page.keyboard.press("Alt+p")
    assert log(page)["keys"] == ["p", "p"], "modifier keys never reach a module"
    page.focus("body")
    page.evaluate("""() => { const i = document.createElement('input'); i.id = 'inp';
      document.querySelector('.slide').appendChild(i); }""")
    page.focus("#inp")
    page.keyboard.press("p")
    assert log(page)["keys"] == ["p", "p"], "keys inside inputs never reach a module"
    page.evaluate("() => document.activeElement.blur()")


def test_step_consumes_forward_and_back_before_the_slide_moves(open_html):
    page = open_deck(open_html, probe_deck())
    page.evaluate("() => { window.__steps = []; window.SlideDeck.on('stepchange', e => window.__steps.push(e.step)); }")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert current(page) == 1, "two steps on slide b are consumed"
    assert page.evaluate("() => window.SlideDeck.state().step") == 2
    page.wait_for_function("() => location.hash === '#b.2'")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 2)
    assert page.evaluate("() => window.SlideDeck.state().step") == 0, "a new slide starts at step 0"
    page.wait_for_function("() => location.hash === '#c'")
    page.keyboard.press("ArrowLeft")
    wait_settled(page, 1)
    page.evaluate("() => window.SlideDeck.setStep(2)")
    page.keyboard.press("ArrowLeft")
    assert current(page) == 1 and page.evaluate("() => window.SlideDeck.step()") == 1
    assert page.evaluate("() => window.__steps") == [1, 2, 2, 1]
    assert page.errors == []


def test_api_next_also_steps(open_html):
    page = open_deck(open_html, probe_deck())
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    page.evaluate("() => window.SlideDeck.next()")
    assert current(page) == 1 and page.evaluate("() => window.SlideDeck.step()") == 1


def test_deep_link_with_step_is_read_on_load(open_html, page):
    open_deck(open_html, probe_deck())
    page.goto(page.url.split("#")[0] + "#b.2")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 4")
    wait_settled(page, 1)
    assert page.evaluate("() => window.SlideDeck.state().step") == 2
    page.evaluate("() => { location.hash = '#3'; }")
    wait_settled(page, 2)
    page.evaluate("() => { location.hash = '#2.1'; }")
    wait_settled(page, 1)
    page.wait_for_function("() => window.SlideDeck.step() === 1")


def test_a_dotted_id_is_an_id_before_it_is_a_step(open_html, page):
    slides = [slide("One", ' id="a"'), slide("Two", ' id="v1.2"'), slide("Three", ' id="c"')]
    open_deck(open_html, probe_deck(slides))
    page.goto(page.url.split("#")[0] + "#v1.2")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.count() === 3")
    wait_settled(page, 1)
    assert page.evaluate("() => window.SlideDeck.step()") == 0


def test_transition_wraps_navigation_and_apply_runs_once(open_html):
    page = open_deck(open_html, probe_deck())
    page.keyboard.press("End")
    wait_settled(page, 3)
    assert log(page)["transitions"] == [["a", "d"]]
    page.evaluate("() => { window.__probeInstant = true; }")
    page.keyboard.press("Home")
    wait_settled(page, 0)
    assert log(page)["transitions"][-1] == ["d", "a"]
    page.evaluate("""() => { window.__applies = 0;
      window.SlideDeck.use({ name: 'twice', transition: (f, t, apply) => { apply(); apply(); window.__applies++; } }); }""")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert page.evaluate("() => window.__applies") == 1
    assert page.errors == []


def test_transition_skipped_under_reduced_motion(open_html, page):
    page.emulate_media(reduced_motion="reduce")
    try:
        open_deck(open_html, probe_deck())
        page.keyboard.press("End")
        wait_settled(page, 3)
        assert log(page)["transitions"] == []
        assert page.evaluate("() => window.SlideDeck.reducedMotion()") is True
    finally:
        page.emulate_media(reduced_motion="no-preference")


def test_a_transition_that_never_applies_does_not_strand_the_deck(open_html):
    page = open_deck(open_html, deck(4))
    page.evaluate("() => window.SlideDeck.use({ name: 'lost', transition: () => {} })")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1, timeout=5000)


def test_help_lists_module_rows_in_the_deck_language(open_html):
    page = open_deck(open_html, probe_deck())
    page.keyboard.press("?")
    assert "Probe key" in page.locator(".deck-help").inner_text()
    page = open_deck(open_html, probe_deck(lang="de"))
    page.keyboard.press("?")
    assert "Sonde" in page.locator(".deck-help").inner_text()


def test_state_and_slides(open_html):
    page = open_deck(open_html, probe_deck())
    st = page.evaluate("() => window.SlideDeck.state()")
    assert st["index"] == 0 and st["id"] == "a" and st["step"] == 0 and st["track"] == "all"
    assert st["theme"] in ("light", "dark") and st["lang"] == "en" and st["notes"] is False
    assert page.evaluate("() => window.SlideDeck.slides().map(s => s.id)") == ["a", "b", "c", "d"]
    page.evaluate("() => window.SlideDeck.toggleNotes(true)")
    assert page.evaluate("() => window.SlideDeck.state().notes") is True


def test_themechange_event(open_html):
    page = open_deck(open_html, deck(3))
    page.evaluate("() => { window.__t = []; window.SlideDeck.on('themechange', e => window.__t.push(e.theme)); }")
    page.keyboard.press("t")
    page.keyboard.press("t")
    seen = page.evaluate("() => window.__t")
    assert len(seen) == 2 and seen[0] != seen[1] and set(seen) == {"light", "dark"}
    assert page.evaluate("() => window.SlideDeck.state().theme") == seen[1]
    page.evaluate("() => window.SlideDeck.setTheme('light')")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-light')")


def test_events_are_also_dispatched_on_document(open_html):
    page = open_deck(open_html, probe_deck())
    page.evaluate("""() => { window.__doc = [];
      ['stepchange', 'themechange'].forEach(n => document.addEventListener('slidedeck:' + n, () => window.__doc.push(n))); }""")
    page.evaluate("() => { window.SlideDeck.goTo(1); }")
    wait_current(page, 1)
    page.evaluate("() => { window.SlideDeck.setStep(1); window.SlideDeck.toggleTheme(); }")
    assert page.evaluate("() => window.__doc") == ["stepchange", "themechange"]
