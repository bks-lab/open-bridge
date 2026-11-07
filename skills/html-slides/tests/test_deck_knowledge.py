"""The html-canvas knowledge block in a deck: a term on a slide opens its knowledge on
the right, the slide shrinks to the left (scaled, so its layout stays as designed),
the deck keeps navigating, K lists the terms of the slide, Esc closes."""
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

SLIDES = """
<section class="slide slide--content" id="one">
  <h2 class="slide__heading">Warum es dauert</h2>
  <p class="slide__body">Die Latenz steigt mit der Warteschlange.</p>
</section>
<section class="slide slide--content" id="two">
  <h2 class="slide__heading">Was zählt</h2>
  <p class="slide__body">Der Durchsatz allein sagt wenig.</p>
</section>
"""


def knowledge_deck(tmp: Path, *extra) -> Path:
    frag = tmp / "slides.html"
    frag.write_text(SLIDES, encoding="utf-8")
    out = tmp / "deck.html"
    run("--title", "Wissen", "--lang", "de", "--out", out, "--no-embed-fonts", "--slides", frag,
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


def test_a_term_on_a_slide_opens_the_panel_and_the_slide_moves_left(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport={"width": 1440, "height": 900})
    ready(page)
    page.locator('#one [data-know="latency"]').click()
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert page.locator(".kp-title").inner_text().strip() == "Latenz"
    page.wait_for_function("""() => document.querySelector('#one').getBoundingClientRect().right
        <= document.querySelector('.kp-panel').getBoundingClientRect().left + 1""", timeout=3000)
    assert page.evaluate("window.SlideDeck.current()") == 0
    assert page.errors == []


def test_the_deck_still_navigates_and_k_lists_the_slide_terms(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"), viewport={"width": 1440, "height": 900})
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


def test_the_help_names_the_key(open_html, plain_dir):
    page = open_html(knowledge_deck(plain_dir).read_text("utf-8"))
    ready(page)
    page.keyboard.press("?")
    assert "Wissen" in page.locator(".deck-help").inner_text()


def test_the_deck_passes_the_static_gate(plain_dir):
    out = knowledge_deck(plain_dir)
    gate = CANVAS / "scripts" / "verify-page.py"
    r = subprocess.run([sys.executable, str(gate), str(out), "--allow-sample"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
