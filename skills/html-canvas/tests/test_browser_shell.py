"""Rendered behaviour of the shell, the simulation engine and the documented snippets.

Every test opens a single file through file:// from a fresh temp dir. Tests that
need a browser skip cleanly when playwright or chromium is missing; the static
hygiene tests at the end need neither.
"""
from __future__ import annotations

import re

import pytest

from conftest import ASSETS, FIXTURES, SKILL, md_snippet, render_shell, run_new_simulation

PAIR_IDS = ["pair-li", "pair-td", "pair-span", "pair-tspan", "pair-div", "pair-flex", "pair-p", "pair-legend"]
# What each pair must compute to when it is the visible language.
NATIVE = {"pair-li": "list-item", "pair-td": "table-cell", "pair-span": "inline", "pair-tspan": "inline",
          "pair-div": "block", "pair-flex": "flex", "pair-p": "block", "pair-legend": "inline-flex"}

PROBE = """(ids) => ids.map(id => {
  const host = document.getElementById(id);
  const kids = [...host.querySelectorAll('[data-de],[data-en]')];
  return kids.map(k => ({lang: k.hasAttribute('data-de') ? 'de' : 'en',
                         display: getComputedStyle(k).display}));
})"""


@pytest.fixture
def sim_html(tmp_path):
    """A freshly assembled worklist simulation, German default."""
    out = tmp_path / "sim-de.html"
    r = run_new_simulation(out, "--archetype", "worklist", "--lang", "de",
                           "--title-de", "Lauf", "--title-en", "Run")
    assert r.returncode == 0, r.stderr
    return out.read_text("utf-8")


# --- G2: the language switch only hides the inactive language --------------------------

@pytest.mark.parametrize("default_lang", ["en", "de"])
def test_pairs_keep_their_native_display_and_exactly_one_language_shows(open_page, default_lang):
    page = open_page(render_shell((FIXTURES / "lang-pairs.html").read_text("utf-8"), lang=default_lang))
    other = "de" if default_lang == "en" else "en"
    for active in (default_lang, other):
        if active != default_lang:
            page.click("#langToggle")
        assert page.evaluate("document.documentElement.getAttribute('data-lang')") == active
        for pid, kids in zip(PAIR_IDS, page.evaluate(PROBE, PAIR_IDS)):
            shown = [k for k in kids if k["display"] != "none"]
            assert len(shown) == 1 and shown[0]["lang"] == active, (pid, active, kids)
            assert shown[0]["display"] == NATIVE[pid], (pid, active, kids)
    assert page.errors == []


def test_without_data_lang_only_the_default_language_shows(open_page):
    page = open_page(render_shell((FIXTURES / "lang-pairs.html").read_text("utf-8")))
    page.evaluate("document.documentElement.removeAttribute('data-lang')")
    for pid, kids in zip(PAIR_IDS, page.evaluate(PROBE, PAIR_IDS)):
        assert [k["lang"] for k in kids if k["display"] != "none"] == ["en"], pid


# --- G3: space does not fire the clock from a control that already owns it -------------

def clock_state(page):
    return page.evaluate("document.querySelector('[data-sim-run]').getAttribute('data-state')")


def test_space_on_the_theme_button_toggles_theme_not_the_clock(open_page, sim_html):
    page = open_page(sim_html)
    assert clock_state(page) == "idle"
    page.focus("#themeToggle")
    page.keyboard.press("Space")
    assert page.evaluate("document.documentElement.classList.contains('dark')") is True
    assert clock_state(page) == "idle"


@pytest.mark.parametrize("markup", [
    '<a id="probe" href="#top">link</a>',
    '<details><summary id="probe">more</summary>text</details>',
    '<div id="probe" contenteditable="true">edit</div>',
    '<button id="probe" type="button">button</button>',
])
def test_space_on_native_controls_leaves_the_clock_alone(open_page, sim_html, markup):
    page = open_page(sim_html)
    page.evaluate("m => document.querySelector('main').insertAdjacentHTML('afterbegin', m)", markup)
    page.focus("#probe")
    page.keyboard.press("Space")
    assert clock_state(page) == "idle"


def test_space_elsewhere_still_runs_the_clock(open_page, sim_html):
    page = open_page(sim_html)
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Space")
    assert clock_state(page) == "running"
    page.keyboard.press("Space")
    assert clock_state(page) == "paused"


# --- G3: theme button is bilingual through spans, aria text follows the language -------

def test_theme_button_text_is_bilingual_not_english_only(open_page, sim_html):
    page = open_page(sim_html)
    assert page.evaluate("document.documentElement.lang") == "de"
    assert page.inner_text("#themeToggle").strip().endswith("Dunkel")
    assert "Dark" not in page.inner_text("#themeToggle")
    assert page.evaluate("document.querySelectorAll('#themeToggle [data-de]').length") == 1
    page.click("#langToggle")
    assert page.inner_text("#themeToggle").strip().endswith("Dark")
    page.click("#themeToggle")
    assert page.inner_text("#themeToggle").strip().endswith("Light")
    page.click("#langToggle")
    assert page.inner_text("#themeToggle").strip().endswith("Hell")


def test_aria_helper_sets_label_and_title_on_language_switch(open_page, sim_html):
    page = open_page(sim_html)
    page.evaluate("""document.body.insertAdjacentHTML('beforeend',
        '<button id="late" data-aria-de="Hallo" data-aria-en="Hello">x</button>')""")
    page.click("#langToggle")                      # de -> en
    for sel, want in (("#late", "Hello"), ("#printBtn", "Print as PDF")):
        assert page.get_attribute(sel, "aria-label") == want, sel
        assert page.get_attribute(sel, "title") == want, sel
    page.click("#langToggle")                      # en -> de
    assert page.get_attribute("#late", "aria-label") == "Hallo"
    assert page.get_attribute("#themeToggle", "aria-label") not in (None, "")
    assert not re.search(r"\b(Switch|theme)\b", page.get_attribute("#themeToggle", "aria-label"))
    assert page.errors == []


# --- G3: 44 px targets only for coarse pointers -----------------------------------------

BOX = """() => [...document.querySelectorAll('.topbar button, .sim-btn, .sim-seg button')]
  .filter(b => b.offsetParent !== null)
  .map(b => { const r = b.getBoundingClientRect(); return {id: b.id || b.className, w: r.width, h: r.height}; })"""


def test_touch_targets_are_44px_for_coarse_pointers(open_page, sim_html):
    page = open_page(sim_html, has_touch=True, is_mobile=True, viewport={"width": 600, "height": 900})
    assert page.evaluate("matchMedia('(pointer: coarse)').matches") is True
    boxes = page.evaluate(BOX)
    assert boxes
    assert all(b["w"] >= 44 and b["h"] >= 44 for b in boxes), boxes


def test_fine_pointers_keep_the_compact_controls(open_page, sim_html):
    page = open_page(sim_html)
    assert page.evaluate("matchMedia('(pointer: coarse)').matches") is False
    assert any(b["h"] < 44 for b in page.evaluate(BOX))


# --- G3: content that animations.css hides is visible when IntersectionObserver is missing

DECK_CSS = (ASSETS / "animations.css").read_text("utf-8")
NO_IO = "delete window.IntersectionObserver;"


def deck_page(open_page, **opts):
    interactivity = SKILL / "references" / "interactivity.md"
    body = "\n".join([md_snippet(interactivity, "Slide-deck engine"), md_snippet(interactivity, "Scroll reveal")])
    html = render_shell((FIXTURES / "deck.html").read_text("utf-8"), extra_css=DECK_CSS, extra_body=body)
    return open_page(html, **opts)


def visible_opacity(page, selector):
    return page.evaluate("s => [...document.querySelectorAll(s)].map(e => getComputedStyle(e).opacity)", selector)


def test_slides_and_reveals_are_visible_without_intersection_observer(open_page):
    page = deck_page(open_page, init_script=NO_IO)
    assert page.evaluate("'IntersectionObserver' in window") is False
    page.wait_for_timeout(900)                      # longer than the .6s entrance transition
    assert visible_opacity(page, ".slide") == ["1", "1", "1"]
    assert visible_opacity(page, ".reveal") == ["1", "1"]
    assert page.errors == []


def test_deck_still_reveals_through_the_observer_when_it_exists(open_page):
    page = deck_page(open_page)
    page.wait_for_timeout(900)
    assert page.evaluate("document.getElementById('s1').classList.contains('visible')") is True
    assert page.errors == []


def test_space_on_a_deck_dot_does_not_also_advance_the_deck(open_page):
    page = deck_page(open_page)
    page.evaluate("""() => { window.__nexts = 0; const n = SlideEngine.prototype.next;
        SlideEngine.prototype.next = function () { window.__nexts++; return n.apply(this, arguments); }; }""")
    page.focus(".deck-dots button:nth-child(1)")
    page.keyboard.press("Space")
    assert page.evaluate("window.__nexts") == 0
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Space")
    assert page.evaluate("window.__nexts") == 1


# --- hygiene of the shipped sources (no browser needed) ----------------------------------

def test_shell_has_no_html_entities():
    assert not re.findall(r"&#?\w+;", (ASSETS / "shell.html").read_text("utf-8"))


def test_shell_declares_44px_targets_only_for_coarse_pointers():
    shell = (ASSETS / "shell.html").read_text("utf-8")
    assert re.search(r"@media\s*\(pointer:\s*coarse\)\s*\{[^}]*44px", shell)
    outside = re.sub(r"@media\s*\(pointer:\s*coarse\)\s*\{.*?\}\s*\}", "", shell, flags=re.S)
    assert "min-height:44px" not in outside.replace(" ", "")


def test_sections_reference_uses_tokens_and_no_dashes_in_example_texts():
    text = (SKILL / "references" / "sections.md").read_text("utf-8")
    assert "rgba(" not in text
    for line in text.splitlines():
        if "data-de" in line or "data-en" in line:
            assert "\u2014" not in line and "\u2013" not in line, line


def test_animations_show_hidden_content_when_scripting_is_off():
    css = (ASSETS / "animations.css").read_text("utf-8")
    assert re.search(r"@media\s*\(scripting:\s*none\)\s*\{[^}]*\.reveal[^}]*opacity:1", css)
