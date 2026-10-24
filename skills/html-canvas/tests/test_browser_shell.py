"""Rendered behaviour of the shell, the simulation engine and the documented snippets.

Every test opens a single file through file:// from a fresh temp dir. Tests that
need a browser skip cleanly when playwright or chromium is missing; the static
hygiene tests at the end need neither.
"""
from __future__ import annotations

import re

import pytest

from canvas_testlib import ASSETS, FIXTURES, SKILL, md_snippet, render_shell, run_new_simulation

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
        shown = [k for k in kids if k["display"] != "none"]
        assert [k["lang"] for k in shown] == ["en"], pid
        # the old swap forced display:block here; the default language keeps its own
        assert shown[0]["display"] == NATIVE[pid], (pid, kids)


DUAL = ('<p id="dual-value" data-de="Start" data-en="Start">Start</p>'
        '<p><span id="dual-empty" data-de data-en>Same in both</span></p>'
        '<p data-de>Nur deutsch</p><p data-en>English only</p>')


@pytest.mark.parametrize("default_lang", ["en", "de"])
def test_elements_with_both_language_attributes_show_in_both_languages(open_page, default_lang):
    page = open_page(render_shell(DUAL, lang=default_lang))
    for _ in range(2):
        for sel in ("#dual-value", "#dual-empty"):
            assert page.evaluate("s => document.querySelector(s).getClientRects().length > 0", sel), \
                (sel, page.evaluate("document.documentElement.getAttribute('data-lang')"))
        page.click("#langToggle")
    assert page.errors == []


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


def test_theme_button_aria_label_names_the_target_mode_after_each_toggle(open_page):
    page = open_page(render_shell("<p data-de>Inhalt</p><p data-en>Content</p>"))
    label = lambda: page.get_attribute("#themeToggle", "aria-label")
    assert "dark" in label().lower()
    page.click("#themeToggle")
    assert page.evaluate("document.documentElement.classList.contains('dark')") is True
    assert "light" in label().lower() and page.get_attribute("#themeToggle", "title") == label()
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press("t")
    assert "dark" in label().lower()
    page.click("#langToggle")                      # en -> de
    assert "dunkel" in label().lower()
    page.click("#themeToggle")
    assert "hell" in label().lower()


LABELS = """() => [...document.querySelectorAll('.topbar button')].map(b => ({
  id: b.id, text: b.innerText, label: b.getAttribute('aria-label') || ''}))"""


def test_every_topbar_button_name_contains_its_visible_label(open_page):
    # WCAG 2.5.3, label in name: a voice user says what they see
    page = open_page(render_shell("<p data-de>Inhalt</p><p data-en>Content</p>"))
    for step in ("start", "#themeToggle", "#langToggle", "#themeToggle"):
        if step != "start":
            page.click(step)
        for b in page.evaluate(LABELS):
            words = re.findall(r"[^\W\d_]+", b["text"])
            assert words, b
            for w in words:
                assert w.lower() in b["label"].lower(), (step, b)


def test_os_theme_change_follows_without_writing_storage(open_page):
    page = open_page(render_shell("<p data-de>Inhalt</p><p data-en>Content</p>"), color_scheme="light")
    stored = "localStorage.getItem('html-canvas-theme')"
    assert page.evaluate("document.documentElement.classList.contains('dark')") is False
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(50)
    assert page.evaluate("document.documentElement.classList.contains('dark')") is True
    assert page.evaluate(stored) is None
    assert "light" in page.get_attribute("#themeToggle", "aria-label").lower()
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(50)
    assert page.evaluate("document.documentElement.classList.contains('dark')") is False
    assert page.evaluate(stored) is None
    page.click("#themeToggle")                     # an explicit choice is stored and wins
    assert page.evaluate(stored) == "dark"
    page.emulate_media(color_scheme="light")
    page.wait_for_timeout(50)
    assert page.evaluate("document.documentElement.classList.contains('dark')") is True


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

ANIM_CSS = (ASSETS / "animations.css").read_text("utf-8")
NO_IO = "delete window.IntersectionObserver;"


def reveal_page(open_page, **opts):
    interactivity = SKILL / "references" / "interactivity.md"
    body = md_snippet(interactivity, "Scroll reveal")
    html = render_shell((FIXTURES / "reveal.html").read_text("utf-8"), extra_css=ANIM_CSS, extra_body=body)
    return open_page(html, **opts)


def visible_opacity(page, selector):
    return page.evaluate("s => [...document.querySelectorAll(s)].map(e => getComputedStyle(e).opacity)", selector)


def test_reveals_are_visible_without_intersection_observer(open_page):
    page = reveal_page(open_page, init_script=NO_IO)
    assert page.evaluate("'IntersectionObserver' in window") is False
    page.wait_for_timeout(900)                      # longer than the .5s entrance transition
    assert visible_opacity(page, ".reveal") == ["1", "1"]
    assert page.errors == []


def test_reveals_still_go_through_the_observer_when_it_exists(open_page):
    page = reveal_page(open_page)
    page.wait_for_timeout(900)
    assert page.evaluate("document.getElementById('r1').classList.contains('visible')") is True
    assert page.errors == []


def test_animations_carry_no_deck_mode_rules():
    """Slides belong to html-slides; nothing in html-canvas adds .visible to a .slide."""
    assert not re.search(r"(^|[\s,}])\.slide\b", ANIM_CSS)
    assert "SlideEngine" not in ANIM_CSS
    assert "\u2014" not in ANIM_CSS and "\u2013" not in ANIM_CSS


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


def _swap_rules(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(":root") and "{display:none}" in ln]


def _flip(rule: str) -> str:
    return rule.replace("de", "\0").replace("en", "de").replace("\0", "en")


def test_migration_note_lives_in_build_workflow_and_matches_the_shell():
    shell_rules = _swap_rules((ASSETS / "shell.html").read_text("utf-8"))
    assert len(shell_rules) == 2 and all(":not([data-" in r for r in shell_rules)
    workflow = SKILL / "references" / "build-workflow.md"
    assert _swap_rules(md_snippet(workflow, "Migrating an older page")) == shell_rules
    text = workflow.read_text("utf-8")
    german = text.split("German default:", 1)[1].split("```", 2)[1]
    assert _swap_rules(german) == [_flip(r) for r in shell_rules]
    sim = (SKILL / "references" / "simulation.md").read_text("utf-8")
    assert "## Migrating an older page" not in sim
    assert "Or rebuild it" not in sim and "Or rebuild it" not in text


def test_build_workflow_names_the_gate_and_scopes_touch_targets_to_coarse_pointers():
    text = (SKILL / "references" / "build-workflow.md").read_text("utf-8")
    assert "verify-page.py" in text and "theme-contract.md" in text and "--embed-fonts" in text
    touch = next(ln for ln in text.splitlines() if "**Touch targets:**" in ln)
    assert "pointer:coarse" in touch


def test_mono_text_shows_cli_flags_without_ligatures():
    """JetBrains Mono joins `--` into one glyph; a CLI flag must read as two hyphens."""
    shell = (ASSETS / "shell.html").read_text("utf-8")
    sections = (ASSETS / "sections.css").read_text("utf-8")
    assert re.search(r"code,kbd\{[^}]*font-variant-ligatures:none", shell)
    assert re.search(r"\.term\{[^}]*font-variant-ligatures:none", sections)
