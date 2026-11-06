"""Deck module `motion` (assets/modules/motion.js, reference/modules.md § Module: motion).

Motion that plays when its slide becomes active and resets when it leaves: count-up
numbers (data-count), staggered entrances (data-stagger), SVG line drawing
(data-draw) and the canvas message flow (.msg-fwd / .msg-back / .flow-line). Under
reduced motion, in print, in the reading view and in a presenter preview everything
stands at its end state.
"""
from __future__ import annotations

import re

from engine_testlib import SHIPPED_MODULES, module_deck, new_deck, open_deck, slide, wait_settled
from slides_testlib import SKILL

COUNT = '<p class="kpi"><span data-count="1200" data-count-duration="900">1200</span> users</p>'
STAGGER = '<ul data-stagger><li>One</li><li>Two</li><li>Three</li></ul>'
DRAW = ('<svg data-draw viewBox="0 0 200 20" width="200" height="20" aria-hidden="true">'
        '<path d="M0 10 H200" stroke="var(--accent)" stroke-width="2" fill="none"/></svg>')
FLOW = ('<div class="mflow"><svg viewBox="0 0 600 130" aria-hidden="true">'
        '<line class="flow-line" x1="162" y1="56" x2="430" y2="56" stroke="var(--accent)"/>'
        '<circle class="msg-fwd" cx="162" cy="56" r="6" fill="var(--accent)" style="--d:268px"/>'
        '<circle class="msg-back" cx="438" cy="74" r="6" fill="var(--accent)" style="--d:268px"/></svg></div>')


def motion_deck(modules=("motion",), **kw):
    slides = [slide("Start", ' id="a"'), slide("Count", ' id="b"', COUNT + STAGGER),
              slide("Draw", ' id="c"', DRAW + FLOW), slide("End", ' id="d"')]
    return module_deck(list(modules), slides, **kw)


def text(page, sel):
    return page.evaluate("(s) => document.querySelector(s).textContent", sel)


def opacities(page, sel):
    return page.evaluate("(s) => [...document.querySelectorAll(s)].map(e => getComputedStyle(e).opacity)", sel)


def dashoffset(page):
    return page.evaluate("() => parseFloat(getComputedStyle(document.querySelector('#c path')).strokeDashoffset) || 0")


def anim(page, sel):
    return page.evaluate("(s) => getComputedStyle(document.querySelector(s)).animationName", sel)


def go(page, i):
    page.evaluate("(i) => window.SlideDeck.goTo(i)", i)
    wait_settled(page, i)


# --- playing and resetting ------------------------------------------------------------------

def test_count_up_runs_on_arrival_and_ends_on_the_written_value(open_html):
    page = open_deck(open_html, motion_deck())
    assert text(page, "#b [data-count]") == "1200", "a slide not shown keeps the final value"
    page.evaluate("() => window.SlideDeck.goTo(1)")
    page.wait_for_function("() => { const v = parseInt(document.querySelector('#b [data-count]').textContent, 10);"
                           " return v > 0 && v < 1200; }", timeout=3000)
    page.wait_for_function("() => document.querySelector('#b [data-count]').textContent === '1200'", timeout=3000)
    assert page.errors == []


def test_count_up_replays_after_the_slide_was_left(open_html):
    page = open_deck(open_html, motion_deck())
    go(page, 1)
    page.wait_for_function("() => document.querySelector('#b [data-count]').textContent === '1200'", timeout=3000)
    go(page, 2)
    assert text(page, "#b [data-count]") == "1200"
    page.evaluate("() => window.SlideDeck.goTo(1)")
    page.wait_for_function("() => parseInt(document.querySelector('#b [data-count]').textContent, 10) < 1200",
                           timeout=3000)


def test_count_keeps_the_text_around_the_number(open_html):
    html = motion_deck().replace(COUNT, '<p><span data-count="42.5">42.5 %</span></p>')
    page = open_deck(open_html, html)
    page.evaluate("() => window.SlideDeck.goTo(1)")
    page.wait_for_function("() => / %$/.test(document.querySelector('#b [data-count]').textContent)")
    page.wait_for_function("() => document.querySelector('#b [data-count]').textContent === '42.5 %'", timeout=3000)


def test_stagger_children_enter_one_after_another_and_hide_again(open_html):
    page = open_deck(open_html, motion_deck())
    assert opacities(page, "#b [data-stagger] > li") == ["0", "0", "0"]
    delays = page.evaluate("() => [...document.querySelectorAll('#b [data-stagger] > li')]"
                           ".map(e => e.style.getPropertyValue('--motion-i'))")
    assert delays == ["0", "1", "2"]
    go(page, 1)
    page.wait_for_function("() => [...document.querySelectorAll('#b [data-stagger] > li')]"
                           ".every(e => getComputedStyle(e).opacity === '1')", timeout=3000)
    go(page, 2)
    assert opacities(page, "#b [data-stagger] > li") == ["0", "0", "0"], "reset on leaving, so it replays"


def test_lines_draw_on_arrival(open_html):
    page = open_deck(open_html, motion_deck())
    assert dashoffset(page) > 100, "undrawn while its slide is away"
    go(page, 2)
    page.wait_for_function("() => (parseFloat(getComputedStyle(document.querySelector('#c path')).strokeDashoffset)"
                           " || 0) < 0.5", timeout=3000)


def test_message_flow_runs_only_on_the_active_slide(open_html):
    page = open_deck(open_html, motion_deck())
    assert anim(page, "#c .msg-fwd") == "none"
    go(page, 2)
    assert anim(page, "#c .msg-fwd") == "deck-msg-fwd"
    assert anim(page, "#c .msg-back") == "deck-msg-back"
    assert anim(page, "#c .flow-line") == "deck-flow"
    go(page, 3)
    assert anim(page, "#c .msg-fwd") == "none"


def test_without_markup_the_module_changes_nothing(open_html):
    page = open_deck(open_html, module_deck(["motion"], [slide("One"), slide("Two")]))
    page.keyboard.press("ArrowRight")
    wait_settled(page, 1)
    assert page.errors == []


# --- end state wherever nothing should move -------------------------------------------------

def test_reduced_motion_shows_the_end_state(open_html, page):
    page.emulate_media(reduced_motion="reduce")
    try:
        pg = open_deck(open_html, motion_deck())
        assert not pg.evaluate("() => document.documentElement.classList.contains('motion-ready')")
        assert opacities(pg, "#b [data-stagger] > li") == ["1", "1", "1"]
        assert dashoffset(pg) < 0.5
        pg.evaluate("() => window.SlideDeck.goTo(1)")
        pg.wait_for_timeout(200)
        assert text(pg, "#b [data-count]") == "1200"
    finally:
        page.emulate_media(reduced_motion="no-preference")


def test_print_shows_the_end_state(open_html, page):
    pg = open_deck(open_html, motion_deck())
    page.emulate_media(media="print")
    try:
        assert opacities(pg, "#b [data-stagger] > li") == ["1", "1", "1"]
        assert dashoffset(pg) < 0.5
        assert text(pg, "#b [data-count]") == "1200"
    finally:
        page.emulate_media(media="screen")


def test_reading_view_shows_the_end_state(open_html):
    page = open_deck(open_html, motion_deck(("motion", "read")))
    go(page, 1)
    page.keyboard.press("r")
    page.wait_for_function("() => document.documentElement.classList.contains('deck-read')")
    page.wait_for_timeout(100)
    assert text(page, "#b [data-count]") == "1200"
    assert opacities(page, "[data-stagger] > li") == ["1", "1", "1"]
    assert dashoffset(page) < 0.5
    assert anim(page, "#c .msg-fwd") == "none"


def test_a_presenter_preview_does_not_move(open_html):
    page = open_deck(open_html, motion_deck(html_attrs='data-deck-preview=""'))
    assert not page.evaluate("() => document.documentElement.classList.contains('motion-ready')")
    go(page, 2)
    assert anim(page, "#c .msg-fwd") == "none"
    assert opacities(page, "#b [data-stagger] > li") == ["1", "1", "1"]


# --- the files ------------------------------------------------------------------------------

def test_motion_is_splice_safe_and_token_only():
    region = new_deck().module_region("motion", SHIPPED_MODULES)
    assert "<style>" in region and "<script>" in region
    for name in ("motion.js", "motion.css"):
        src = (SKILL / "assets" / "modules" / name).read_text("utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", src), name
    css = (SKILL / "assets" / "modules" / "motion.css").read_text("utf-8")
    assert "@media screen" in css and "deck-read" in css


def test_documented_in_modules_md_and_skill_md():
    doc = (SKILL / "reference" / "modules.md").read_text("utf-8")
    m = re.search(r"^## Module: motion\n(.*?)(?=^## |\Z)", doc, re.S | re.M)
    assert m, "modules.md has a motion section"
    for word in ("data-count", "data-stagger", "data-draw", "msg-fwd", "reduced", "print", "read"):
        assert word in m.group(1), word
    assert "--with motion" in (SKILL / "SKILL.md").read_text("utf-8")
