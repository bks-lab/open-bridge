"""Deck module `steps` (assets/modules/steps.js, reference/modules.md § steps).

data-step reveals one element per forward move, data-steps makes every child of a
container a step, data-lines walks a code block through line groups, and the deep
link carries the step. Probe decks come from engine_testlib.module_deck.
"""
from __future__ import annotations

from engine_testlib import current, deck, module_deck, open_deck, slide, wait_settled

CODE = ('<div class="slide__code-block"><pre><code data-lines="%s">'
        '<span class="kw">def</span> a():\n    return 1\n<span class="cm"># two\nlines</span>\nend\n'
        '</code></pre></div>')


def frags(i: int, n: int = 3) -> str:
    return "".join('<p data-step class="f%d">Item %d</p>' % (k, k) for k in range(1, n + 1))


def steps_deck(extra_b: str | None = None, **kw):
    slides = [slide("One", ' id="a"'),
              slide("Two", ' id="b"', extra_b if extra_b is not None else frags(1)),
              slide("Three", ' id="c"'),
              slide("Four", ' id="d"', frags(2, 2))]
    return module_deck(["steps"], slides, **kw)


def shown(page, slide_id: str) -> list[bool]:
    """Per [data-step] element of the slide: is it visible to the eye?"""
    return page.evaluate("""(id) => [...document.querySelectorAll('#' + id + ' [data-step]')]
      .map(e => getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).opacity !== '0')""", slide_id)


def wait_shown(page, slide_id: str, want: list[bool]):
    page.wait_for_function("""([id, want]) => JSON.stringify([...document.querySelectorAll('#' + id + ' [data-step]')]
      .map(e => getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).opacity !== '0')) === JSON.stringify(want)""",
                           arg=[slide_id, want], timeout=3000)


def step(page) -> int:
    return page.evaluate("() => window.SlideDeck.step()")


def test_forward_reveals_one_step_per_key_then_moves_on(open_html):
    page = open_deck(open_html, steps_deck())
    assert shown(page, "b") == [False, False, False], "fragments start hidden"
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    for k in range(1, 4):
        page.keyboard.press("ArrowRight")
        wait_shown(page, "b", [i < k for i in range(3)])
        assert current(page) == 1 and step(page) == k
    page.wait_for_function("() => location.hash === '#b.3'")
    page.keyboard.press("ArrowRight")
    wait_settled(page, 2)
    page.wait_for_function("() => location.hash === '#c'")
    assert page.errors == []


def test_backward_hides_and_coming_back_shows_everything(open_html):
    page = open_deck(open_html, steps_deck())
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    wait_shown(page, "b", [True, True, False])
    page.keyboard.press("ArrowLeft")
    wait_shown(page, "b", [True, False, False])
    assert current(page) == 1 and step(page) == 1
    page.evaluate("() => window.SlideDeck.goTo(2)")
    wait_settled(page, 2)
    page.keyboard.press("ArrowLeft")
    wait_settled(page, 1)
    wait_shown(page, "b", [True, True, True])
    assert step(page) == 3, "stepping back onto a slide starts at its last step"
    page.keyboard.press("ArrowLeft")
    wait_shown(page, "b", [True, True, False])
    assert page.errors == []


def test_a_jump_lands_on_step_zero(open_html):
    page = open_deck(open_html, steps_deck())
    page.evaluate("() => window.SlideDeck.goTo(3)")
    wait_settled(page, 3)
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    wait_shown(page, "b", [False, False, False])
    assert step(page) == 0


def test_deep_link_restores_the_step(open_html, page):
    html = steps_deck()
    open_deck(open_html, html)
    url = page.url.split("#")[0]
    page.goto(url + "#b.2")
    page.reload()
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.current() === 1")
    wait_shown(page, "b", [True, True, False])
    assert step(page) == 2
    page.evaluate("() => { location.hash = '#d.1'; }")
    wait_settled(page, 3)
    wait_shown(page, "d", [True, False])
    page.evaluate("() => { location.hash = '#d'; }")
    wait_shown(page, "d", [False, False])
    assert page.errors == []


def test_numbered_steps_reveal_together_and_data_steps_children(open_html):
    extra = ('<p data-step="2" class="x">late</p><p data-step="1" class="y">early</p>'
             '<p data-step="2" class="z">late too</p>'
             '<ul data-steps><li>a</li><li>b</li></ul>')
    page = open_deck(open_html, steps_deck(extra))
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    vis = """() => ['.x', '.y', '.z', 'li:nth-child(1)', 'li:nth-child(2)'].map(s =>
      getComputedStyle(document.querySelector('#b ' + s)).visibility !== 'hidden')"""
    assert page.evaluate(vis) == [False, False, False, False, False]
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.step() === 1")
    page.wait_for_function(vis.replace("() =>", "() => JSON.stringify(") + ") === '[false,true,false,false,false]'")
    page.keyboard.press("ArrowRight")
    page.wait_for_function(vis.replace("() =>", "() => JSON.stringify(") + ") === '[true,true,true,false,false]'")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.wait_for_function(vis.replace("() =>", "() => JSON.stringify(") + ") === '[true,true,true,true,true]'")
    assert current(page) == 1 and step(page) == 4
    page.keyboard.press("ArrowRight")
    wait_settled(page, 2)
    assert page.errors == []


def test_step_effects_mark_the_current_and_dim_earlier_ones(open_html):
    extra = '<p data-step data-step-effect="dim" class="p1">one</p><p data-step class="p2">two</p>'
    page = open_deck(open_html, steps_deck(extra))
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('#b .p1').classList.contains('step-current')")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('#b .p2').classList.contains('step-current')"
                           " && !document.querySelector('#b .p1').classList.contains('step-current')")
    page.wait_for_function("() => parseFloat(getComputedStyle(document.querySelector('#b .p1')).opacity) < 0.9")


def lines(page) -> list[tuple[str, str]]:
    return page.evaluate("""() => [...document.querySelectorAll('#b code .code-line')]
      .map(l => [l.textContent, l.classList.contains('is-on') ? 'on' : (l.classList.contains('is-dim') ? 'dim' : '')])""")


def test_data_lines_highlights_line_groups_step_by_step(open_html):
    page = open_deck(open_html, steps_deck(CODE % "1-2|4,5|*"))
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    ls = lines(page)
    assert [t for t, _ in ls] == ["def a():", "    return 1", "# two", "lines", "end"], "split per line, no empty tail"
    assert [s for _, s in ls] == ["on", "on", "dim", "dim", "dim"], "the first group shows with the block"
    spans = page.evaluate("""() => [...document.querySelectorAll('#b code .code-line')]
      .map(l => [...l.querySelectorAll('span')].map(s => s.className).join(' '))""")
    assert spans == ["kw", "", "cm", "cm", ""], "highlight spans survive the split, across lines too"
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.step() === 1")
    assert [s for _, s in lines(page)] == ["dim", "dim", "dim", "on", "on"]
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.step() === 2")
    assert [s for _, s in lines(page)] == ["", "", "", "", ""], "* shows every line"
    page.keyboard.press("ArrowRight")
    wait_settled(page, 2)
    page.keyboard.press("ArrowLeft")
    wait_settled(page, 1)
    assert step(page) == 2
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    page.wait_for_function("() => window.SlideDeck.step() === 0")
    assert [s for _, s in lines(page)] == ["on", "on", "dim", "dim", "dim"]
    assert page.errors == []


def test_code_block_with_its_own_step_shows_then_walks_lines(open_html):
    extra = ('<p data-step class="lead">lead</p>'
             + (CODE % "1|3").replace('<div class="slide__code-block">', '<div class="slide__code-block cb" data-step>'))
    page = open_deck(open_html, steps_deck(extra))
    page.evaluate("() => window.SlideDeck.goTo(1)")
    wait_settled(page, 1)
    hidden = "() => getComputedStyle(document.querySelector('#b .cb')).visibility === 'hidden'"
    assert page.evaluate(hidden)
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.step() === 2")
    page.wait_for_function(hidden.replace("=== 'hidden'", "!== 'hidden'"))
    assert [s for _, s in lines(page)][:3] == ["on", "dim", "dim"]
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.step() === 3")
    assert [s for _, s in lines(page)][:3] == ["dim", "dim", "on"]


def test_a_deck_without_steps_is_unchanged(open_html):
    page = open_deck(open_html, module_deck(["steps"], [slide("One"), slide("Two")]))
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert step(page) == 0
    assert page.errors == []


def test_without_the_module_fragments_stay_visible(open_html):
    page = open_deck(open_html, deck([slide("One", ' id="a"'), slide("Two", ' id="b"', frags(1))]))
    assert shown(page, "b") == [True, True, True]


def test_print_shows_every_step_and_line(open_html, page):
    open_deck(open_html, steps_deck(frags(1) + CODE % "1|3"))
    page.emulate_media(media="print")
    try:
        assert shown(page, "b") == [True, True, True]
        assert page.evaluate("""() => [...document.querySelectorAll('#b .code-line')]
          .every(l => getComputedStyle(l).opacity === '1')""")
    finally:
        page.emulate_media(media="null")


def test_reduced_motion_still_steps(open_html, page):
    page.emulate_media(reduced_motion="reduce")
    try:
        open_deck(open_html, steps_deck())
        page.evaluate("() => window.SlideDeck.goTo(1)")
        wait_settled(page, 1)
        page.keyboard.press("ArrowRight")
        assert shown(page, "b") == [True, False, False], "no transition to wait for"
    finally:
        page.emulate_media(reduced_motion="null")
