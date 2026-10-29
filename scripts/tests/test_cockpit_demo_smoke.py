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


def _steady(page):
    """Wait until the page bar holds still: its tabs come with the state and fold behind More only after a
    measure, so a tab read or clicked before that may be gone a moment later (two reads 200 ms apart agree)."""
    page.wait_for_function(
        "() => { const sig = [...document.querySelectorAll('.pagebar-tabs > [role=tab]')].map(t => t.textContent).join('|');"
        " const same = sig !== '' && window.__barSig === sig; window.__barSig = sig;"
        " return same && document.fonts.status === 'loaded' }",
        polling=200,
    )


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
    _steady(page)

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
    # the five views of the start page (overview, bridge, tiles, list, focus) are separate components; a view
    # only mounts once chosen in Settings, so the walk over the tabs above never reaches four of them
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
        _steady(page)
        bar = page.locator(".pagebar-tabs > [role=tab]").filter(has_text=word)
        if bar.count():
            bar.first.click()
            return
        page.locator(".ptab-more > [role=tab]").click()
        page.locator(".more-menu [role=menuitem]").filter(has_text=word).first.click()

    shown = []
    for i in range(5):
        where[0] = f"view {i}"
        open_settings()
        opts = page.locator(".view-opt")
        opts.first.wait_for()
        assert opts.count() == 5, opts.count()
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
def test_the_demo_opens_the_files_tab_once_where_the_config_names_the_files_view(base_url, browser, lang):
    # ?work=files and ?focus_to_files=1 stand for cockpit.work_view: files and cockpit.focus_to_files: true; since
    # round 6c the files are a tab of their own: the work tab's first visit lands there once (logic.js filesMoved)
    problems: list[str] = []
    where = ["files"]
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang={lang}&work=files&focus_to_files=1")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    # the first visit has settled (its first state moved the files and wrote the work tab's view): a write after the
    # clear below would otherwise leave the reload a remembered view, the way a slower first state did
    page.wait_for_function("() => window.localStorage.getItem('bridge-cockpit.workTab') !== null")
    # a fresh browser that was on the work tab: nothing else remembered, nothing seen; the reload keeps the page
    page.evaluate("() => { window.localStorage.clear(); window.localStorage.setItem('bridge-cockpit.page', 'briefing') }")
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    files_tab = page.locator(".pagebar-tabs > [role=tab]").filter(has_text=re.compile("^(Files|Akten)"))
    assert files_tab.count() == 1
    page.wait_for_selector("#main .dz-side")
    assert files_tab.first.get_attribute("aria-selected") == "true"
    page.wait_for_timeout(250)

    # once only: the work tab now shows its own view, also after a reload, the config unchanged
    where[0] = "work tab after"
    for reload in (False, True):
        if reload:
            page.reload()
            page.wait_for_selector(".pagebar-tabs [role=tab]")
        page.locator(".pagebar-tabs > [role=tab]").nth(1).click()   # the work tab stands right after Start
        page.wait_for_function("() => (document.getElementById('main')?.textContent ?? '').trim().length > 0")
        page.wait_for_timeout(250)
        assert page.locator("#main .dz-side").count() == 0
        assert page.locator("#main .dz").count() == 0

    # the focus of the start page, walked with its bar to the end, leads on into the files view (focus_to_files)
    where[0] = "focus to files"
    word = re.compile("Settings|Einstellungen")
    bar = page.locator(".pagebar-tabs > [role=tab]").filter(has_text=word)
    if bar.count():
        bar.first.click()
    else:
        page.locator(".ptab-more > [role=tab]").click()
        page.locator(".more-menu [role=menuitem]").filter(has_text=word).first.click()
    page.locator(".view-opt").nth(4).click()   # areas, bridge, tiles, list, focus
    page.locator(".pagebar-tabs > [role=tab]").first.click()
    page.wait_for_selector("#main .fx .fx-work")
    onward = page.locator("#main .fx-work button").filter(has_text=re.compile("Continue with the files|Weiter mit den Akten"))
    for _ in range(40):
        if onward.count():
            break
        page.locator("#main .fx-work .next-up-go button").click()
        page.wait_for_timeout(50)
    onward.first.click()
    page.wait_for_selector("#main .dz .fx-hero")   # the walk, not the search start
    page.wait_for_timeout(250)
    ctx.close()
    assert not problems, "\n".join(problems)


def test_area_name_opens_the_files_for_this_visit_only(base_url, browser):
    """A click on an area's name in the overview opens its files with the filter set; the view the work tab
    opens on (kept in the browser) stays as it was"""
    problems: list[str] = []
    where = ["overview"]
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang=en")
    page.wait_for_selector(".desk .home-area-pick")
    before = page.evaluate("() => localStorage.getItem('bridge-cockpit.workTab')")
    page.locator("tbody .home-area-pick").nth(1).click()
    page.wait_for_selector(".dz")
    assert page.locator(".area-bar").count() == 1
    assert page.evaluate("() => localStorage.getItem('bridge-cockpit.workTab')") == before
    ctx.close()
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("width", [1680, 1280, 900])
def test_work_through_opens_as_a_view_of_the_work_tab_and_walks_its_points(base_url, browser, lang, width):
    """?work=flow stands for cockpit.work_view: flow. The view shows its left column (a select on a narrow screen) and
    the overview of all points; a theme entered, two points ticked, a point opened with its card, the Activity tab under
    it, the walk bar, back to the overview and a batch planned: no console error on the way. Down to 1180px the right
    column (what you can do, the fields) stands beside the middle"""
    problems: list[str] = []
    where = ["flow"]
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang={lang}&work=flow")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    page.evaluate("() => window.localStorage.clear()")
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.locator(".pagebar-tabs > [role=tab]").nth(1).click()
    page.wait_for_selector("#main .flow-grid .flow-overview")
    assert page.locator("#main .flow-tabs").count() == 0
    where[0] = "a theme"
    if width > 960:
        page.locator("#main .flow-side-item:not(.is-all)").first.click()
    else:
        page.locator("#main .flow-side-select select").select_option(index=1)
    page.wait_for_selector("#main .flow-overview .flow-ov-pick")
    where[0] = "two ticked"
    page.locator("#main .flow-overview .flow-ov-row .flow-ov-pick").nth(0).check()
    page.locator("#main .flow-overview .flow-ov-row .flow-ov-pick").nth(1).check()
    # the boxes stand in the middle only (round 5: the left column lists no point)
    assert page.locator("#main .flow-overview .flow-ov-row .flow-ov-pick:checked").count() == 2
    assert page.locator("#main .flow-side .flow-pt").count() == 0
    where[0] = "a point"
    page.locator("#main .flow-ov-open").first.click()
    page.wait_for_selector("#main .flow-card .fx-hero")
    assert page.locator("#main .flow-walk .dz-walk").count() == 1
    assert page.locator("#main .flow-picked-line").count() == 1
    page.locator("#main .flow-ptabs [role=tab][data-tab=activity]").click()
    page.wait_for_selector("#main .flow-act")
    page.wait_for_timeout(200)
    if width >= 1280:
        card = page.locator("#main .flow-main").bounding_box()
        aside = page.locator("#main .flow-aside").bounding_box()
        assert aside["x"] >= card["x"] + card["width"], "the right column stands beside the middle"
    where[0] = "the overview"
    page.locator("#main .flow-back").click()
    page.wait_for_selector("#main .flow-overview")
    page.locator("#main .flow-ov-verbs .btn-primary").click()
    page.wait_for_selector("#main .flow-list-confirm")
    page.wait_for_timeout(250)
    ctx.close()
    assert not problems, "\n".join(problems)


# the demo's question about a task whose Activity holds every kind of row (mock.js: an inbox row naming a task reads
# that task's feed); its title in the page's language comes from the demo's own words
REPORT_KEY = "inbox:20261009-0900-review-demo-a1b2"
TITLE_OF = """async key => {
  const lang = new URLSearchParams(location.search).get('lang') || 'en'
  const t = (await import('./mock.js')).createMockTransport({ lang, latency: 0 })
  const state = (await t.get('/api/state')).data
  return state.model.sections.flatMap(x => x.rows).find(r => r.key === key).title
}"""


def _open_report_point(page, base_url, lang):
    """Work through on a clean page, at the level of all themes: the demo's question about its task open"""
    page.goto(f"{base_url}?lang={lang}&work=flow")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    page.evaluate("() => window.localStorage.clear()")
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.locator(".pagebar-tabs > [role=tab]").nth(1).click()
    page.wait_for_selector("#main .flow-grid .flow-overview .flow-ov-open")
    page.locator("#main .flow-ov-open", has_text=page.evaluate(TITLE_OF, REPORT_KEY)).click()
    page.wait_for_selector("#main .flow-card .fx-hero")


@pytest.mark.parametrize("lang", ["en", "de"])
@pytest.mark.parametrize("width", [1680, 900])
def test_an_open_point_has_its_tabs_its_activity_its_fields_and_the_instruction_line(base_url, browser, lang, width):
    """Round 3 of Work through. The card carries content only (no verbs in it); the verbs and the fields stand in the
    right column, without a Status field. Under the card the tabs, Description first; Activity filtered to Documents
    shows only document rows, each a link that opens in a new tab; the tab chosen stays on the next point. The
    instruction line turns a sentence into a plan: Change gives the sentence back, Discard drops the plan, Run runs it
    and leaves one undo under the line. No console error on the way"""
    problems: list[str] = []
    where = ["a point"]
    ctx = browser.new_context(viewport={"width": width, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    _open_report_point(page, base_url, lang)
    assert page.locator("#main .flow-card .verbbar").count() == 0, "the card carries no verbs"
    assert page.locator("#main .flow-aside .flow-can .verbbar.is-stack").count() == 1
    assert page.locator("#main .flow-aside .flow-meta [data-field=who]").count() == 1
    assert page.locator("#main .flow-aside .flow-meta [data-field=status]").count() == 0
    tabs = page.locator("#main .flow-ptabs [role=tab]")
    assert tabs.count() >= 2
    assert tabs.first.get_attribute("data-tab") == "desc" and tabs.first.get_attribute("aria-selected") == "true"
    where[0] = "activity"
    page.locator("#main .flow-ptabs [role=tab][data-tab=activity]").click()
    page.wait_for_selector("#main .flow-act-rows .flow-act-row")
    page.locator("#main .flow-act-filters .seg-btn").nth(2).click()
    page.wait_for_selector("#main .flow-act-rows .flow-act-row.is-doc")
    assert page.locator("#main .flow-act-rows .flow-act-row").count() == page.locator("#main .flow-act-rows .flow-act-row.is-doc").count()
    link = page.locator("#main .flow-act-rows .flow-act-links a").first
    assert link.get_attribute("target") == "_blank" and link.get_attribute("href")
    where[0] = "the next point"
    page.locator("#main .flow-walk .dz-walk button").last.click()
    page.wait_for_timeout(200)
    assert page.locator("#main .flow-ptabs [role=tab][data-tab=activity]").get_attribute("aria-selected") == "true"
    where[0] = "the instruction line"
    sentence = "done"                       # the demo reads its verbs in either language
    box = page.locator("#main #flow-instruct-text")
    box.fill(sentence)
    page.locator("#main .flow-instruct-row button").click()
    page.wait_for_selector("#main .flow-instruct-plan .flow-instruct-step")
    acts = page.locator("#main .flow-instruct-plan .verbbar-acts button")
    assert acts.count() == 3
    acts.nth(1).click()
    page.wait_for_timeout(100)
    assert page.locator("#main .flow-instruct-plan").count() == 0 and box.input_value() == sentence
    page.locator("#main .flow-instruct-row button").click()
    page.wait_for_selector("#main .flow-instruct-plan")
    page.locator("#main .flow-instruct-plan .verbbar-acts button").nth(2).click()
    page.wait_for_timeout(100)
    assert page.locator("#main .flow-instruct-plan").count() == 0
    box.fill(sentence)
    page.locator("#main .flow-instruct-row button").click()
    page.wait_for_selector("#main .flow-instruct-plan")
    page.locator("#main .flow-instruct-plan .verbbar-acts .btn-primary").click()
    page.wait_for_selector("#main .flow-instruct-done button")
    page.wait_for_timeout(250)
    ctx.close()
    assert not problems, "\n".join(problems)


def test_a_note_and_an_attached_document_land_in_the_activity_of_the_point(base_url, browser):
    """The foot of Activity: a note goes out through the verb note and stands as a note row; a file picked is attached
    to the task's deliverables and stands as a document row marked attached, with its link"""
    problems: list[str] = []
    where = ["activity"]
    ctx = browser.new_context(viewport={"width": 1680, "height": 1000})
    page = ctx.new_page()
    _watch(page, problems, where)
    _open_report_point(page, base_url, "en")
    page.locator("#main .flow-ptabs [role=tab][data-tab=activity]").click()
    page.wait_for_selector("#main .flow-act-rows .flow-act-row")
    page.locator("#main .flow-act-filters .seg-btn").nth(1).click()
    notes = page.locator("#main .flow-act-rows .flow-act-row").count()
    page.locator("#main .flow-act-note").fill("Checked the outline, fine")
    page.locator("#main .flow-act-noteform button").click()
    page.wait_for_function(f"() => document.querySelectorAll('#main .flow-act-rows .flow-act-row').length > {notes}")
    assert page.locator("#main .flow-act-rows", has_text="Checked the outline, fine").count() == 1
    page.locator("#main .flow-act-filters .seg-btn").nth(2).click()
    page.locator("#main .flow-act-file").set_input_files(
        files=[{"name": "notes for review.txt", "mimeType": "text/plain", "buffer": b"invented notes\n"}])
    page.wait_for_selector("#main .flow-act-rows a:has-text('notes for review.txt')")
    page.wait_for_timeout(250)
    ctx.close()
    assert not problems, "\n".join(problems)


def test_a_batch_of_the_work_through_overview_says_itself_in_one_toast_with_one_undo(base_url, browser):
    """A batch confirmed in the overview of Work through: the server's note of each step lands in the notes, never as a
    toast of its own; one toast says the batch, and the batch has one undo, in the overview's line (not in the toast)"""
    ctx = browser.new_context(viewport={"width": 1680, "height": 1000})
    page = ctx.new_page()
    page.goto(f"{base_url}?lang=en&work=flow")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    page.evaluate("() => window.localStorage.clear()")
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.locator(".pagebar-tabs > [role=tab]").nth(1).click()
    page.wait_for_selector("#main .flow-grid .flow-overview")
    page.locator("#main .flow-ov-bar .btn-secondary").first.click()
    page.locator("#main .flow-ov-verbs .btn-primary").click()
    page.wait_for_selector("#main .flow-list-confirm")
    page.locator("#main .flow-list-confirm .btn-primary").click()
    page.wait_for_selector("#main .flow-list-done")
    page.wait_for_timeout(600)
    toasts = page.locator(".toast .toast-text").all_text_contents()
    # the demo's note of each step (mock.js MOCK_NOTES), or the verb's name where it has none
    steps = [t for t in toasts if re.match(r"Mock: (settle|later|shelve|do_it|decided|put off|shelved|an agent starts on it)\b", t)]
    undos = page.locator(".toast button", has_text="Undo").count() + page.locator("#main button", has_text="Undo the batch").count()
    ctx.close()
    assert not steps, toasts
    assert undos == 1


# the scroller of an element: its nearest ancestor that scrolls (the page column of the cockpit)
LAYOUT = """() => {
  const scroller = el => { for (let n = el.parentElement; n; n = n.parentElement) { const o = getComputedStyle(n).overflowY
    if ((o === 'auto' || o === 'scroll') && n.scrollHeight > n.clientHeight) return n } return document.scrollingElement }
  const aside = document.querySelector('#main .flow-aside')
  const s = scroller(aside)
  s.scrollTop = s.scrollHeight
  const box = el => el.getBoundingClientRect()
  const sb = box(s), ab = box(aside), head = box(aside.querySelector('.flow-can > h3')), first = box(aside.querySelector('.flow-can .btn'))
  return { scrolled: s.scrollTop, top: sb.top, bottom: Math.min(sb.bottom, innerHeight), aside: [ab.top, ab.bottom], head: head.top, first: first.bottom }
}"""


@pytest.mark.parametrize("size", [(1680, 1000), (1280, 900)])
def test_the_right_column_stays_whole_and_an_asking_point_keeps_its_tabs_in_view(base_url, browser, size):
    """Round 3 after review. A point whose tab asks holds one set of answers on its card (the guide folded), so the tabs
    under it start in view. With Activity open and the middle scrolled to its end, the right column stays inside the
    scroller: What you can do whole on top, its first button in view, the column's foot not cut"""
    w, h = size
    problems: list[str] = []
    where = ["an asking point"]
    ctx = browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    _watch(page, problems, where)
    page.goto(f"{base_url}?lang=de&work=flow")
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.set_default_timeout(10_000)
    page.evaluate("() => window.localStorage.clear()")
    page.reload()
    page.wait_for_selector(".pagebar-tabs [role=tab]")
    page.locator(".pagebar-tabs > [role=tab]").nth(1).click()
    page.wait_for_selector("#main .flow-grid .flow-overview .flow-ov-open")
    page.locator("#main .flow-ov-open").first.click()
    page.wait_for_selector("#main .flow-card .reply-btns")
    page.wait_for_timeout(200)
    bar = page.locator("#main .flow-ptabs-bar").bounding_box()
    assert bar["y"] + bar["height"] <= h, f"the tabs under the card start below the fold: {bar}"
    where[0] = "the right column"
    _open_report_point(page, base_url, "de")
    page.locator("#main .flow-ptabs [role=tab][data-tab=activity]").click()
    page.wait_for_selector("#main .flow-act-rows .flow-act-row")
    page.wait_for_timeout(200)
    got = page.evaluate(LAYOUT)
    page.wait_for_timeout(100)
    got = page.evaluate(LAYOUT)
    ctx.close()
    assert got["scrolled"] > 0, got
    assert got["head"] >= got["top"] - 0.5, f"What you can do is cut at the top: {got}"
    assert got["aside"][0] >= got["top"] - 0.5 and got["aside"][1] <= got["bottom"] + 0.5, f"the right column leaves the scroller: {got}"
    assert got["first"] <= got["bottom"], got
    assert not problems, "\n".join(problems)
