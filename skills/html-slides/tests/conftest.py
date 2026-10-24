"""Shared fixtures for the html-slides tests.

The probe deck is assembled from the documented slide types and a preset, the
same pieces SKILL.md tells a generator to stitch together, so a test exercises
what the docs promise rather than a hand-written copy of it.

Browser tests share one headless chromium per module and skip cleanly when
playwright or its browser is not installed. Pages are always opened through
file:// from a fresh temp dir, which proves the single-file, offline contract:
nothing the page needs may live next to it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from slides_testlib import FIXTURES, SKILL, build_probe_deck


@pytest.fixture(scope="session")
def skill_root() -> Path:
    return SKILL


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def probe_deck() -> str:
    return build_probe_deck()


@pytest.fixture(scope="module")
def browser():
    # Module scope on purpose: a live sync playwright instance owns an event loop,
    # and a test in another module that starts its own would fail inside it.
    sync_api = pytest.importorskip("playwright.sync_api")
    pw = sync_api.sync_playwright().start()
    try:
        b = pw.chromium.launch(headless=True)
    except Exception as exc:  # browser binary not installed
        pw.stop()
        pytest.skip("chromium not available: %s" % str(exc).splitlines()[0])
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def page(browser):
    """One module-scoped page; `page.errors` collects page errors and console errors.

    Use `open_html` to load a document into it from a fresh temp dir.
    """
    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append("pageerror: %s" % e))
    pg.on("console", lambda m: pg.errors.append("console: %s" % m.text) if m.type == "error" else None)
    yield pg
    ctx.close()


@pytest.fixture
def open_html(page, tmp_path):
    """open_html(html, viewport=None) -> page, loaded via file:// from an empty dir.

    Width stays at 500 px or more: a narrower headless viewport is clamped and
    would measure a layout nobody sees.
    """
    counter = [0]

    def _open(html: str, viewport: dict | None = None):
        page.errors.clear()
        if viewport:
            assert viewport["width"] >= 500
            page.set_viewport_size(viewport)
        counter[0] += 1
        d = tmp_path / ("deck%d" % counter[0])
        d.mkdir()
        f = d / "index.html"
        f.write_text(html, encoding="utf-8")
        page.goto(f.as_uri())
        page.wait_for_load_state("load")
        return page

    return _open
