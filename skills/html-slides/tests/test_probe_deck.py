"""The probe deck, one slide of every documented type, renders cleanly offline.

It is built from the docs (reference/slide-types.md), a preset and the CURRENT
engine, and opened from an empty temp dir, so a pass proves the single-file
contract: embedded fonts load, nothing is requested from a network, nothing
overflows at a desktop or a narrow viewport.
"""
from __future__ import annotations

import re

import pytest

from slides_testlib import build_probe_deck, preset_files, slide_type_snippets

VIEWPORTS = [{"width": 1280, "height": 720}, {"width": 600, "height": 900}]


def test_probe_deck_has_every_slide_type(probe_deck):
    assert probe_deck.count('<section class="slide') == len(slide_type_snippets())
    assert "data:font/woff2;base64," in probe_deck


@pytest.mark.parametrize("viewport", VIEWPORTS, ids=lambda v: "%dx%d" % (v["width"], v["height"]))
def test_probe_deck_renders_offline(open_html, page, probe_deck, viewport):
    requests = []
    handler = lambda req: requests.append(req.url) if not req.url.startswith(("file:", "data:")) else None
    page.on("request", handler)
    try:
        open_html(probe_deck, viewport=viewport)
        page.wait_for_selector(".deck-counter", state="attached")
        page.evaluate("() => document.fonts.ready")
        assert page.errors == []
        assert requests == [], "network requests from a single-file deck: %s" % requests
        total = int(re.search(r"/\s*(\d+)", page.locator(".deck-counter").first.inner_text()).group(1))
        assert total == len(slide_type_snippets())
        assert page.evaluate("() => document.fonts.check('700 16px \"Inter Tight\"')")
        overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, "horizontal overflow of %d px" % overflow
    finally:
        page.remove_listener("request", handler)


@pytest.mark.parametrize("slug", [p.stem for p in preset_files()])
def test_every_preset_builds_a_clean_deck(open_html, page, slug):
    open_html(build_probe_deck(slug))
    page.wait_for_selector(".deck-counter", state="attached")
    page.evaluate("() => document.fonts.ready")
    assert page.errors == []
    assert page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") != ""
