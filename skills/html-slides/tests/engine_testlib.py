"""Helpers for the engine v2 browser tests (test_engine_*.py).

Decks are built from fixtures/engine/base.html with the CURRENT engine spliced
in, so every test exercises the shipped assets, never a copy of them.
"""
from __future__ import annotations

import re

from slides_testlib import FIXTURES, splice_engine

ENGINE_FIXTURES = FIXTURES / "engine"
DESKTOP = {"width": 1280, "height": 720}


def slide(title: str, attrs: str = "", extra: str = "", cls: str = "slide--content") -> str:
    return ('<section class="slide %s"%s><div class="slide__inner"><div>'
            '<h2 class="slide__heading reveal">%s</h2><p class="slide__body reveal">Neutral sample text.</p>'
            '%s</div></div></section>') % (cls, attrs, title, extra)


def deck(slides: int | list[str] = 9, html_attrs: str = "", deck_attrs: str = "", lang: str = "en") -> str:
    """A spliced deck from base.html; `slides` is a count or a list of slide markup."""
    if isinstance(slides, int):
        slides = [slide("Slide %d" % (i + 1)) for i in range(slides)]
    html = (ENGINE_FIXTURES / "base.html").read_text("utf-8")
    html = html.replace('<html lang="en" data-fixture-html>', '<html lang="%s"%s>' % (lang, html_attrs and " " + html_attrs))
    html = html.replace(' data-fixture-deck', deck_attrs and " " + deck_attrs)
    html = html.replace("<!-- fixture:slides -->", "\n".join(slides))
    return splice_engine(html)


def fixture(name: str) -> str:
    return splice_engine((ENGINE_FIXTURES / name).read_text("utf-8"))


def open_deck(open_html, html: str, viewport: dict | None = None):
    page = open_html(html, viewport=viewport or DESKTOP)
    page.wait_for_function("() => !!(window.SlideDeck && window.SlideDeck.count && window.SlideDeck.count() > 0)",
                           timeout=4000)
    return page


def current(page) -> int:
    return page.evaluate("() => window.SlideDeck.current()")


def wait_current(page, index: int, timeout: int = 4000):
    page.wait_for_function("(i) => window.SlideDeck.current() === i", arg=index, timeout=timeout)


def wait_settled(page, index: int, timeout: int = 4000):
    """The engine reports `index` AND the scroll position shows that slide at the top."""
    page.wait_for_function("""(i) => {
      if (window.SlideDeck.current() !== i) return false;
      const s = [...document.querySelectorAll('.slide')].filter(x => getComputedStyle(x).display !== 'none')[i];
      const deck = document.querySelector('.deck');
      return s && Math.abs(s.getBoundingClientRect().top - deck.getBoundingClientRect().top) < 2;
    }""", arg=index, timeout=timeout)


def counter(page) -> str:
    return page.locator(".deck-counter").first.inner_text().strip()


def counter_parts(page) -> tuple[int, int]:
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", counter(page))
    return int(m.group(1)), int(m.group(2))


def shown_slides(page) -> int:
    return page.evaluate("() => [...document.querySelectorAll('.slide')]"
                         ".filter(s => getComputedStyle(s).display !== 'none').length")


def pdf_pages(pdf: bytes) -> list[tuple[float, float]]:
    """(width, height) in points of every page in a Chromium PDF (one MediaBox per page)."""
    out = []
    for m in re.finditer(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", pdf):
        out.append((float(m.group(3)) - float(m.group(1)), float(m.group(4)) - float(m.group(2))))
    return out
