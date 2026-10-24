"""Shared fixtures for the html-canvas tests.

Browser tests share one headless chromium per session and skip cleanly when
playwright or its browser is not installed. Pages are always opened through
file:// from a fresh temp dir, which is what proves the single-file, offline
contract: nothing the page needs may live next to it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from canvas_testlib import FIXTURES, REPO, SKILL


@pytest.fixture(scope="session")
def skill_root() -> Path:
    return SKILL


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


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


@pytest.fixture
def open_page(browser, tmp_path):
    """open_page(html, **context_opts) -> page, loaded from file:// in a fresh dir.

    Width stays at 500 px or more: a narrower headless viewport is clamped and
    would measure a layout nobody sees. Page errors are collected on `page.errors`.
    """
    contexts = []
    counter = [0]

    def _open(html: str, **opts):
        opts.setdefault("viewport", {"width": 900, "height": 800})
        init_script = opts.pop("init_script", None)
        ctx = browser.new_context(**opts)
        contexts.append(ctx)
        if init_script:
            ctx.add_init_script(init_script)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        counter[0] += 1
        d = tmp_path / ("page%d" % counter[0])
        d.mkdir()
        f = d / "index.html"
        f.write_text(html, encoding="utf-8")
        page.goto(f.as_uri())
        return page

    yield _open
    for c in contexts:
        c.close()
