"""The html-canvas knowledge block in a deck: a term on a slide opens its knowledge on
the right, the slide shrinks to the left (scaled, so its layout stays as designed),
the deck keeps navigating, K lists the terms of the slide, Esc closes the panel
before anything else, and a closed panel never keeps the focus on its term."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import SKILL
from test_new_deck import plain_dir, run  # noqa: F401  (fixtures)

CANVAS = SKILL.parent / "html-canvas"
PACK = CANVAS / "scripts" / "knowledge-pack.py"
FIX = CANVAS / "tests" / "fixtures" / "knowledge"
sys.path.insert(0, str(CANVAS / "tests"))
from canvas_testlib import CONTRAST, PANEL_TEXT  # noqa: E402

SLIDES = """
<section class="slide slide--content" id="one">
  <h2 class="slide__heading">Why it takes long</h2>
  <p class="slide__body">The latency rises with the queue.</p>
</section>
<section class="slide slide--content" id="two">
  <h2 class="slide__heading">What counts</h2>
  <p class="slide__body">Throughput alone says little.</p>
</section>
<section class="slide slide--content" id="three">
  <h2 class="slide__heading">The end</h2>
  <p class="slide__body">No term here.</p>
</section>
"""


def knowledge_deck(tmp: Path, *extra) -> Path:
    frag = tmp / "slides.html"
    frag.write_text(SLIDES, encoding="utf-8")
    out = tmp / "deck.html"
    run("--title", "Knowledge", "--lang", "en", "--out", out, "--no-embed-fonts", "--slides", frag,
        "--blocks", "knowledge", *extra)
    pack = tmp / "pack.json"
    for args in (("build", "--terms", FIX / "terms.yaml", "--corpus", FIX / "corpus", "--out", pack),
                 ("mark", out, "--pack", pack, "--write"),
                 ("embed", out, "--pack", pack)):
        r = subprocess.run([sys.executable, str(PACK), *map(str, args)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    return out


def ready(page):
    page.wait_for_function("() => !!(window.SlideDeck && window.SlideDeck.count() > 0)")


def is_open(page) -> bool:
    return page.evaluate("document.documentElement.classList.contains('kp-open')")


WIDE = {"width": 1440, "height": 900}


def test_a_term_on_a_slide_opens_the_panel_and_the_slide_moves_left(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport=WIDE)
    ready(page)
    page.locator('#one [data-know="latency"]').click()
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert page.locator(".kp-title").inner_text().strip() == "Latency"
    page.wait_for_function("""() => document.querySelector('#one').getBoundingClientRect().right
        <= document.querySelector('.kp-panel').getBoundingClientRect().left + 1""", timeout=3000)
    assert page.evaluate("window.SlideDeck.current()") == 0
    assert page.errors == []


def test_the_deck_still_navigates_and_k_lists_the_slide_terms(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport=WIDE)
    ready(page)
    page.keyboard.press("k")
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert page.locator('.kp-list button[data-kp-go="latency"]').count() == 1
    assert page.locator('.kp-list button[data-kp-go="throughput"]').count() == 0
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => window.SlideDeck.current() === 1")
    page.wait_for_function("() => !!document.querySelector('.kp-list button[data-kp-go=\"throughput\"]')")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    assert page.evaluate("window.SlideDeck.current()") == 1, "Esc closes the panel, the deck stays"


def test_after_a_pointer_open_and_esc_space_moves_the_slides_on(open_html, plain_dir):
    """The focus must not stay on the term: Space would reopen the panel instead of
    moving to the next slide."""
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport=WIDE)
    ready(page)
    page.locator('#one [data-know="latency"]').click()
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    page.keyboard.press(" ")
    page.wait_for_function("() => window.SlideDeck.current() === 1")
    assert not is_open(page)


def test_space_moves_on_while_the_panel_is_open(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport=WIDE)
    ready(page)
    page.locator('#one [data-know="latency"]').click()
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    page.keyboard.press(" ")
    page.wait_for_function("() => window.SlideDeck.current() === 1")
    assert is_open(page), "the panel stays while the talk goes on"


def test_from_the_keyboard_the_focus_returns_to_the_term(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport=WIDE)
    ready(page)
    page.locator('#one [data-know="latency"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert page.evaluate("window.SlideDeck.current()") == 0
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    assert page.evaluate("document.activeElement.getAttribute('data-know')") == "latency"


def test_esc_in_the_reading_view_closes_the_panel_first(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir, "--with", "read").read_text("utf-8"), viewport=WIDE)
    ready(page)
    page.keyboard.press("r")
    page.wait_for_function("() => document.documentElement.classList.contains('deck-read')")
    page.locator('#two [data-know="throughput"]').click()
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    assert page.evaluate("document.documentElement.classList.contains('deck-read')"), "reading view stays"
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('deck-read')")


def test_the_help_names_the_key(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"))
    ready(page)
    page.keyboard.press("?")
    assert "Knowledge" in page.locator(".deck-help").inner_text()


@pytest.mark.parametrize("preset", ["swiss-modern", "terminal-mono"])
def test_every_panel_text_reads_in_both_themes(open_html, plain_dir, preset):
    page = open_html(knowledge_deck(plain_dir, "--preset", preset).read_text("utf-8"), viewport=WIDE)
    ready(page)
    for theme in ("light", "dark"):
        if page.evaluate("window.SlideDeck.state().theme") != theme:
            page.keyboard.press("t")
        page.locator('#one [data-know="latency"]').click()
        page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
        low = [(s, round(v, 2)) for s, v in page.evaluate(CONTRAST, PANEL_TEXT) if v is not None and v < 4.5]
        assert low == [], (preset, theme, low)
        page.keyboard.press("Escape")


def test_the_deck_passes_the_static_gate(plain_dir):
    out = knowledge_deck(plain_dir)
    gate = CANVAS / "scripts" / "verify-page.py"
    r = subprocess.run([sys.executable, str(gate), str(out), "--allow-sample"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
