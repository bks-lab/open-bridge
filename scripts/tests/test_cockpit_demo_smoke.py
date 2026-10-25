# SPDX-License-Identifier: MIT
"""Browser smoke test of the cockpit demo on the website (docs/cockpit-demo/).

A headless Chromium opens the demo, clicks every tab of the page bar (and every page behind the
More menu, should the bar fold), in English and in German, and fails on a console error or warning,
an uncaught exception, a failed request or an HTTP error. It proves what the node suites cannot:
that every page of the real modules mounts in a real browser without throwing.

Needs the Python package `playwright` and its Chromium (`python -m playwright install chromium`).
Without them the test skips; with COCKPIT_DEMO_SMOKE=require (set in CI) it fails instead, so the
CI job cannot go green by skipping.
"""
from __future__ import annotations

import functools
import http.server
import os
import re
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
REQUIRED = os.environ.get("COCKPIT_DEMO_SMOKE") == "require"

try:
    from playwright.sync_api import TimeoutError as PageTimeout, sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    if REQUIRED:
        raise
    pytest.skip("playwright is not installed", allow_module_level=True)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - the test output stays readable
        pass


class _Server(http.server.ThreadingHTTPServer):
    # the page loads some 40 modules at once; the default backlog of 5 resets connections on macOS
    request_queue_size = 128
    daemon_threads = True


@pytest.fixture(scope="module")
def base_url():
    """docs/ over HTTP (ES modules do not load from file://), so ../assets resolves as on Pages."""
    srv = _Server(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(DOCS)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/cockpit-demo/index.html"
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on the machine
            if REQUIRED:
                raise
            pytest.skip(f"no Chromium for playwright: {exc}")
        yield b
        b.close()


def _watch(page, problems: list[str], where: list[str]):
    """Record every sign of a broken page, tagged with the page that was open at the time."""
    at = lambda: where[0]  # noqa: E731
    page.on("console", lambda m: m.type in ("error", "warning") and problems.append(f"{at()}: console.{m.type}: {m.text}"))
    page.on("pageerror", lambda e: problems.append(f"{at()}: uncaught: {e}"))
    page.on("requestfailed", lambda r: problems.append(f"{at()}: request failed: {r.url} ({r.failure})"))
    page.on("response", lambda r: r.status >= 400 and problems.append(f"{at()}: HTTP {r.status}: {r.url}"))


def _open(page, tab, label: str):
    tab.click()
    page.wait_for_function(
        "label => [...document.querySelectorAll('.pagebar-tabs [role=tab][aria-selected=true]')]"
        ".some(t => t.textContent.includes(label))",
        arg=label,
    )
    page.wait_for_function("() => (document.getElementById('main')?.textContent ?? '').trim().length > 0")
    page.wait_for_timeout(250)  # an effect that fails after the first paint still reports in time


@pytest.mark.parametrize("lang", ["en", "de"])
def test_every_demo_page_opens_without_console_errors(base_url, browser, lang):
    problems: list[str] = []
    where = ["load"]
    # wide, so every tab stands in the bar; a fold behind More is still walked below
    ctx = browser.new_context(viewport={"width": 2400, "height": 1200})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang={lang}")
    page.wait_for_selector(".pagebar-tabs [role=tab]")

    tabs = page.locator(".pagebar-tabs > [role=tab]")
    labels = [tabs.nth(i).locator("span").first.inner_text().strip() for i in range(tabs.count())]
    page.set_default_timeout(10_000)
    try:
        for i, label in enumerate(labels):
            where[0] = label
            _open(page, tabs.nth(i), label)
    except PageTimeout:
        pytest.fail(f"page {where[0]!r} did not render\n" + "\n".join(problems))

    more = page.locator(".ptab-more > [role=tab]")
    if more.count():
        more.click()
        hidden = [x.locator("span").first.inner_text().strip() for x in page.locator(".more-menu [role=menuitem]").all()]
        page.keyboard.press("Escape")
        for label in hidden:
            where[0] = label
            more.click()
            page.locator(".more-menu [role=menuitem]", has_text=label).first.click()
            page.wait_for_function("() => (document.getElementById('main')?.textContent ?? '').trim().length > 0")
            page.wait_for_timeout(250)
        labels += hidden
    ctx.close()

    # the mock profile carries the fixed tabs plus its pages; fewer means the bar itself broke
    assert len(labels) >= 8, labels
    assert len(set(labels)) == len(labels), labels
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_every_start_page_view_mounts_without_console_errors(base_url, browser, lang):
    # the four views of the start page (bridge, tiles, list, focus) are separate components; a view only
    # mounts once chosen in Settings, so the walk over the tabs above never reaches three of them
    problems: list[str] = []
    where = ["load"]
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang={lang}")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    start = page.locator(".pagebar-tabs > [role=tab]").first
    word = re.compile("Settings|Einstellungen")

    def open_settings():
        bar = page.locator(".pagebar-tabs > [role=tab]").filter(has_text=word)
        if bar.count():
            bar.first.click()
            return
        page.locator(".ptab-more > [role=tab]").click()
        page.locator(".more-menu [role=menuitem]").filter(has_text=word).first.click()

    shown = []
    for i in range(4):
        where[0] = f"view {i}"
        open_settings()
        opts = page.locator(".view-opt")
        opts.first.wait_for()
        assert opts.count() == 4, opts.count()
        opts.nth(i).click()
        page.wait_for_timeout(200)
        start.click()
        page.wait_for_function("() => (document.getElementById('main')?.textContent ?? '').trim().length > 0")
        page.wait_for_timeout(250)
        shown.append(page.locator("#main .home, #main .hl, #main .fx, #main .stage").count())
    ctx.close()
    assert all(shown), shown
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_the_demo_opens_the_work_tab_on_the_files_view_the_config_names(base_url, browser, lang):
    # ?work=files and ?focus_to_files=1 stand for cockpit.work_view: files and cockpit.focus_to_files: true
    problems: list[str] = []
    where = ["files"]
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang={lang}&work=files&focus_to_files=1")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    page.evaluate("() => window.localStorage.clear()")   # a fresh browser: nothing remembered, nothing seen
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.locator(".pagebar-tabs > [role=tab]").nth(1).click()   # the work tab stands right after Start
    page.wait_for_selector("#main .dz .fx-hero")
    assert page.locator("#main .dz .fx-hero").count() == 1
    page.wait_for_timeout(250)

    # a click on Due holds on the next visit, the config unchanged (logic.js workViewWrites)
    where[0] = "click holds"
    page.locator("#main .fchip").first.click()
    page.wait_for_selector("#main .dz", state="detached")
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.locator(".pagebar-tabs > [role=tab]").nth(1).click()
    page.wait_for_function("() => (document.getElementById('main')?.textContent ?? '').trim().length > 0")
    page.wait_for_timeout(250)
    assert page.locator("#main .dz").count() == 0
    assert "is-on" in (page.locator("#main .fchip").first.get_attribute("class") or "")

    # the focus of the start page, walked with its bar to the end, leads on into the files view (focus_to_files)
    where[0] = "focus to files"
    word = re.compile("Settings|Einstellungen")
    bar = page.locator(".pagebar-tabs > [role=tab]").filter(has_text=word)
    if bar.count():
        bar.first.click()
    else:
        page.locator(".ptab-more > [role=tab]").click()
        page.locator(".more-menu [role=menuitem]").filter(has_text=word).first.click()
    page.locator(".view-opt").nth(3).click()   # bridge, tiles, list, focus
    page.locator(".pagebar-tabs > [role=tab]").first.click()
    page.wait_for_selector("#main .fx .fx-work")
    onward = page.locator("#main .fx-work button").filter(has_text=re.compile("Continue with the files|Weiter mit den Akten"))
    for _ in range(40):
        if onward.count():
            break
        page.locator("#main .fx-work .next-up-go button").click()
        page.wait_for_timeout(50)
    onward.first.click()
    page.wait_for_selector("#main .dz")
    page.wait_for_timeout(250)
    ctx.close()
    assert not problems, "\n".join(problems)
