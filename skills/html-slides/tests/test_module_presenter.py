"""Deck module `presenter` (reference/modules.md § presenter).

Presenter window (key P), per-slide time budget from data-time, total budget per
track, rehearsal (plan vs actual), and the optional floating timer (Shift+P,
Document Picture-in-Picture). Every test opens the deck through file://, so the
origin is opaque, the case the module's message checks are built for.

These tests use their own browser context: a popup belongs to the context of the
page that opened it, and the clock tests install a fake clock on the context
before the first page loads.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from engine_testlib import DESKTOP, SHIPPED_MODULES, deck, module_deck, slide, wait_current, wait_settled
from slides_testlib import REFERENCE, SKILL

DECK_ID = "probe-talk"


def notes(text: str) -> str:
    return '<aside class="notes"><p>%s</p></aside>' % text


SLIDES = [
    slide("Opening", ' id="a" data-time="60"', notes("Greet the room")),
    slide("Problem", ' id="b" data-time="90"', notes("Name the cost")),
    slide("Plan", ' id="c" data-time="120" data-track="long"', notes("Three steps")),
    slide("Short cut", ' id="e" data-time="30" data-track="short"'),
    slide("Close", ' id="d"'),
]


# A minimal step module: data-test-steps="n" on a slide gives it n steps.
STEP_MODULE = """<script>
SlideDeck.use({ name: 'test-steps', step: function (dir) {
  var d = SlideDeck, s = d.state(), sl = d.slides()[s.index];
  var max = sl ? parseInt(sl.getAttribute('data-test-steps') || '0', 10) : 0, n = s.step + dir;
  if (n < 0 || n > max) return false;
  d.setStep(n); return true; } });
</script>"""


def presenter_deck(slides=None, lang="en", deck_attrs=' data-deck-id="%s"' % DECK_ID, steps=False):
    html = module_deck(["presenter"], slides or SLIDES, lang=lang, deck_attrs=deck_attrs)
    if steps:
        head, _, tail = html.rpartition("</body>")
        html = head + STEP_MODULE + "\n</body>" + tail
    return html


@pytest.fixture
def ctx(browser):
    c = browser.new_context(viewport=DESKTOP)
    c.errors = []
    c.on("page", lambda p: _watch(c, p))
    yield c
    c.close()


def _watch(c, p):
    p.on("pageerror", lambda e: c.errors.append("pageerror: %s" % e))
    p.on("console", lambda m: c.errors.append("console: %s" % m.text) if m.type == "error" else None)


@pytest.fixture
def load(ctx, tmp_path):
    counter = [0]

    def _load(html: str):
        counter[0] += 1
        d = tmp_path / ("deck%d" % counter[0])
        d.mkdir()
        f = d / "index.html"
        f.write_text(html, encoding="utf-8")
        pg = ctx.new_page()
        pg.goto(f.as_uri())
        wf(pg, "() => window.SlideDeck && window.SlideDeck.count() > 0", timeout=4000)
        return pg

    return _load


def wf(page, expression, arg=None, timeout=4000):
    """wait_for_function on a timer, not on animation frames: a window in the background
    gets no frames, and the presenter window is in the background whenever the deck is not."""
    return page.wait_for_function(expression, arg=arg, polling=100, timeout=timeout)


def open_presenter(pg):
    with pg.expect_popup() as info:
        pg.keyboard.press("p")
    pop = info.value
    wf(pop, "() => document.documentElement.hasAttribute('data-deck-presenter')"
                          " && document.querySelector('[data-pp=count]').textContent.trim() !== ''",
                          timeout=4000)
    return pop


def text(pop, name: str) -> str:
    return pop.locator("[data-pp=%s]" % name).inner_text().strip()


def wait_text(pop, name: str, pattern: str, timeout=4000):
    wf(pop, "([n, p]) => new RegExp(p).test(document.querySelector('[data-pp=' + n + ']').textContent)",
                          arg=[name, pattern], timeout=timeout)


def frame_state(pop, name: str):
    return pop.evaluate("""(n) => {
      const f = document.querySelector('[data-pp=' + n + '] iframe');
      const d = f && f.contentWindow && f.contentWindow.SlideDeck;
      return d && d.count() ? d.state() : null; }""", name)


def wait_frame(pop, name: str, index: int, step: int = 0):
    wf(pop, """([n, i, s]) => {
      const f = document.querySelector('[data-pp=' + n + '] iframe');
      const d = f && f.contentWindow && f.contentWindow.SlideDeck;
      return !!(d && d.count() && d.state().index === i && d.state().step === s); }""",
                          arg=[name, index, step], timeout=6000)


def token_rgb(pg, token: str) -> str:
    return pg.evaluate("""(t) => { const e = document.createElement('span'); e.style.color = 'var(' + t + ')';
      document.body.appendChild(e); const c = getComputedStyle(e).color; e.remove(); return c; }""", token)


# --- off means absent -----------------------------------------------------------------------

def test_listed_but_unused_the_deck_is_unchanged(ctx, load):
    plain = load(deck(SLIDES, deck_attrs=' data-deck-id="%s"' % DECK_ID))
    body = ("() => [...document.body.children].filter(e => !/^(SCRIPT|STYLE)$/.test(e.tagName))"
            ".map(e => e.tagName + '.' + e.classList[0]).join(' ')")
    want = plain.evaluate(body)
    pg = load(presenter_deck())
    pg.keyboard.press("ArrowRight")
    wait_settled(pg, 1)
    assert pg.evaluate(body) == want, "no element of its own until P is pressed"
    assert len(ctx.pages) == 2, "no window opened"
    help_text = pg.locator(".deck-help").inner_text()
    assert "Presenter view" in help_text
    assert ctx.errors == []


# --- the window and sync -------------------------------------------------------------------

def test_p_opens_current_next_notes_and_previews(ctx, load):
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    assert text(pop, "count") == "1 / 5"
    assert "Greet the room" in text(pop, "notes")
    assert "Problem" in text(pop, "next-title")
    wait_frame(pop, "cur", 0)
    wait_frame(pop, "next", 1)
    assert pop.title().startswith("Presenter")
    chrome = pop.evaluate("""() => { const d = document.querySelector('[data-pp=cur] iframe').contentDocument;
      const c = d.querySelector('.deck-counter'); return c ? getComputedStyle(c).display : 'none'; }""")
    assert chrome == "none", "the previews show the slide, not the deck chrome"
    assert ctx.errors == []


def test_sync_both_ways_exactly_once(ctx, load):
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    pg.bring_to_front()
    pg.keyboard.press("ArrowRight")
    wait_text(pop, "count", r"^\s*2 / 5")
    assert "Name the cost" in text(pop, "notes")
    wait_frame(pop, "cur", 1)
    pop.bring_to_front()
    pop.keyboard.press("ArrowRight")
    wait_current(pg, 2)
    pop.wait_for_timeout(600)
    assert pg.evaluate("() => SlideDeck.current()") == 2, "one key in the presenter moves the deck once"
    wait_text(pop, "count", r"^\s*3 / 5")
    pop.keyboard.press("End")
    wait_current(pg, 4)
    pop.keyboard.press("2")
    pop.keyboard.press("Enter")
    wait_current(pg, 1)
    pop.click("[data-act=prev]")
    wait_current(pg, 0)
    pg.bring_to_front()
    pg.keyboard.press("p")
    pg.wait_for_timeout(300)
    assert len(ctx.pages) == 2, "P again focuses the open presenter, never a second one"
    assert ctx.errors == []


def test_messages_from_anyone_else_are_ignored(ctx, load):
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    nonce = pop.evaluate("() => window.__deckPresenter.deckNonce()")
    forged = {"deck-presenter": 1, "role": "presenter", "deck": DECK_ID, "type": "cmd",
              "action": "next", "from": "x", "seq": 1, "to": nonce}
    pg.evaluate("(m) => window.postMessage(m, '*')", forged)
    pg.evaluate("""(m) => { const f = document.createElement('iframe'); document.body.appendChild(f);
      f.contentWindow.eval('parent.postMessage(' + JSON.stringify(m) + ', "*")'); }""", forged)
    pg.wait_for_timeout(500)
    assert pg.evaluate("() => SlideDeck.current()") == 0, "only the window the deck opened may steer it"
    pop.evaluate("(m) => opener.postMessage(Object.assign({}, m, {deck: 'other-deck', seq: 9}), '*')", forged)
    pg.wait_for_timeout(300)
    assert pg.evaluate("() => SlideDeck.current()") == 0, "a message for another deck is ignored"
    assert ctx.errors == []


def test_lang_and_theme_follow_the_deck(ctx, load):
    pg = load(presenter_deck(lang="de"))
    pop = open_presenter(pg)
    assert "Notizen" in pop.locator(".pp-notes .pp-label").text_content()
    before = pop.evaluate("() => getComputedStyle(document.body).backgroundColor")
    pg.bring_to_front()
    pg.keyboard.press("t")
    want = token_rgb(pg, "--bg")
    wf(pop, "(c) => getComputedStyle(document.body).backgroundColor === c", arg=want, timeout=4000)
    assert want != before
    pg.evaluate("() => SlideDeck.setLang('en')")
    wf(pop, "() => /Notes/.test(document.querySelector('.pp-notes .pp-label').textContent)")
    assert ctx.errors == []


def test_next_preview_takes_the_next_step(ctx, load):
    slides = [slide("One", ' id="a"'), slide("Two", ' id="b" data-test-steps="2"'), slide("Three", ' id="c"')]
    pg = load(presenter_deck(slides, steps=True))
    pg.evaluate("() => SlideDeck.goTo(1)")
    wait_settled(pg, 1)
    pop = open_presenter(pg)
    wait_frame(pop, "cur", 1, 0)
    wait_frame(pop, "next", 1, 1)
    pg.evaluate("() => SlideDeck.setStep(2)")
    wait_frame(pop, "cur", 1, 2)
    wait_frame(pop, "next", 2, 0)
    pg.evaluate("() => SlideDeck.goTo(2)")
    wf(pop, "() => !document.querySelector('[data-pp=end]').hidden", timeout=4000)
    assert ctx.errors == []


# --- time budget ------------------------------------------------------------------------------

def test_slide_budget_turns_amber_then_red_in_deck_colours(ctx, load):
    ctx.clock.install()
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    assert text(pop, "elapsed") == "0:00", "the clock waits for the first slide change"
    pg.bring_to_front()
    pg.keyboard.press("ArrowRight")
    wait_settled(pg, 1)   # a jump of the fake clock mid-scroll would settle the deck on the old slide
    wait_text(pop, "count", r"^\s*2 / 5")
    ctx.clock.fast_forward(30_000)
    wait_text(pop, "slide-left", r"(1:00|0:5\d) left")
    assert pop.get_attribute("[data-pp=slide-budget]", "data-state") == "ok"
    ctx.clock.fast_forward(45_000)
    wf(pop, "() => document.querySelector('[data-pp=slide-budget]').dataset.state === 'low'")
    amber = token_rgb(pg, "--amber")
    assert pop.evaluate("() => getComputedStyle(document.querySelector('[data-pp=slide-left]')).color") == amber
    ctx.clock.fast_forward(20_000)
    wf(pop, "() => document.querySelector('[data-pp=slide-budget]').dataset.state === 'over'")
    assert re.search(r"0:\d\d over", text(pop, "slide-left"))
    red = token_rgb(pg, "--red")
    assert pop.evaluate("() => getComputedStyle(document.querySelector('[data-pp=slide-left]')).color") == red
    pg.bring_to_front()
    pg.keyboard.press("ArrowRight")
    wait_text(pop, "count", r"^\s*3 / 5")
    wait_text(pop, "slide-left", r"2:00")
    assert re.search(r"0:[45]\d ahead", text(pop, "pace")), "95 s spent where the plan had 60 + 90 s"
    pg.keyboard.press("End")
    wf(pop, "() => document.querySelector('[data-pp=slide-budget]').dataset.state === 'none'")
    assert ctx.errors == []


def test_timer_pause_and_reset_from_the_presenter(ctx, load):
    ctx.clock.install()
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    pop.keyboard.press("s")
    ctx.clock.fast_forward(65_000)
    wait_text(pop, "elapsed", r"^1:0\d$")
    pop.keyboard.press("s")
    paused = text(pop, "elapsed")
    ctx.clock.fast_forward(30_000)
    pop.wait_for_timeout(700)
    assert text(pop, "elapsed") == paused, "paused means paused"
    pop.keyboard.press("x")
    wait_text(pop, "elapsed", r"^0:00$")
    assert ctx.errors == []


def test_total_budget_is_recomputed_for_the_track(ctx, load):
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    assert text(pop, "total-plan") == "5:00", "60 + 90 + 120 + 30, the close has no budget"
    pg.bring_to_front()
    pg.keyboard.press("f")
    wait_text(pop, "total-plan", r"^4:30$")
    assert "long" in text(pop, "track")
    pg.keyboard.press("f")
    wait_text(pop, "total-plan", r"^3:00$")
    assert ctx.errors == []


# --- rehearsal ------------------------------------------------------------------------------

def test_rehearsal_records_actual_time_per_slide(ctx, load):
    ctx.clock.install()
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    pop.keyboard.press("r")
    wf(pop, "() => document.documentElement.classList.contains('pp-recording')")
    ctx.clock.fast_forward(40_000)
    pop.keyboard.press("ArrowRight")
    wait_settled(pg, 1)
    ctx.clock.fast_forward(100_000)
    pop.keyboard.press("r")
    wf(pop, "() => !document.documentElement.classList.contains('pp-recording')"
                          " && !document.querySelector('[data-pp=table]').hidden")
    rows = pop.evaluate("""() => [...document.querySelectorAll('[data-pp=table] tbody tr')]
      .map(r => [...r.cells].map(c => c.textContent.trim()))""")
    assert rows[0][1:3] == ["Opening", "1:00"] and re.match(r"0:4\d$", rows[0][3]) and rows[0][4].startswith("-0:")
    assert rows[1][1:3] == ["Problem", "1:30"] and re.match(r"1:4\d$", rows[1][3]) and rows[1][4].startswith("+0:1")
    assert pop.get_attribute("[data-pp=table] tbody tr:nth-child(2)", "data-state") == "over"
    stored = json.loads(pg.evaluate("(k) => localStorage.getItem(k)", "deck-rehearsal:" + DECK_ID))
    rec = stored["all"]
    got = [r["actual"] for r in rec["rows"][:2]]
    assert 40 <= got[0] <= 45 and 100 <= got[1] <= 105, got   # real time keeps flowing beside the fake jumps
    pop.keyboard.press("Escape")
    wf(pop, "() => document.querySelector('[data-pp=table]').hidden")
    pop.keyboard.press("a")
    wf(pop, "() => !document.querySelector('[data-pp=table]').hidden")
    assert ctx.errors == []


def test_blocked_storage_does_not_break_it(ctx, load):
    ctx.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('blocked'); }});")
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    pop.keyboard.press("r")
    pop.keyboard.press("ArrowRight")
    wait_current(pg, 1)
    pop.keyboard.press("r")
    wf(pop, "() => !document.querySelector('[data-pp=table]').hidden")
    pop.keyboard.press("+")
    assert [e for e in ctx.errors if "blocked" in e] == []


# --- robustness -----------------------------------------------------------------------------

def test_presenter_survives_a_deck_reload(ctx, load):
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    pg.reload()
    wf(pg, "() => window.SlideDeck && window.SlideDeck.count() > 0")
    pg.keyboard.press("ArrowRight")
    wait_text(pop, "count", r"^\s*2 / 5", timeout=8000)
    pop.bring_to_front()
    pop.keyboard.press("ArrowRight")
    wait_current(pg, 2, timeout=6000)
    assert ctx.errors == []


def test_reloading_the_presenter_window_brings_it_back(ctx, load):
    pg = load(presenter_deck())
    pop = open_presenter(pg)
    pop.reload()
    wf(pop, "() => document.documentElement.hasAttribute('data-deck-presenter')"
                          " && /1 \\/ 5/.test(document.querySelector('[data-pp=count]').textContent)",
                          timeout=8000)
    pg.bring_to_front()
    pg.keyboard.press("ArrowRight")
    wait_text(pop, "count", r"^\s*2 / 5", timeout=6000)
    assert ctx.errors == []


def test_blocked_popup_says_so(ctx, load):
    ctx.add_init_script("window.open = function () { return null; };")
    pg = load(presenter_deck())
    pg.keyboard.press("p")
    toast = pg.locator(".deck-presenter-toast")
    toast.wait_for(state="visible", timeout=3000)
    assert "pop-up" in toast.inner_text().lower()
    assert pg.evaluate("() => getComputedStyle(document.querySelector('.deck-presenter-toast')).position") == "fixed"
    assert ctx.errors == []


# --- floating timer (Document Picture-in-Picture) -------------------------------------------

PIP_STUB = """
window.__pipCalls = 0;
Object.defineProperty(window, 'documentPictureInPicture', { configurable: true, value: {
  requestWindow: function () {
    window.__pipCalls++;
    var f = document.createElement('iframe'); f.id = 'pipstub';
    document.body.appendChild(f);
    return Promise.resolve(f.contentWindow);
  } } });
"""


def test_shift_p_opens_a_floating_timer_where_supported(ctx, load):
    ctx.add_init_script(PIP_STUB)
    pg = load(presenter_deck())
    assert "Floating timer" in pg.locator(".deck-help").inner_text()
    pg.keyboard.press("ArrowRight")
    wait_settled(pg, 1)
    pg.keyboard.press("Shift+P")
    wf(pg, "() => { const f = document.getElementById('pipstub');"
                         " return f && f.contentDocument.querySelector('[data-pp=elapsed]'); }")
    pip_text = pg.evaluate("() => document.getElementById('pipstub').contentDocument.body.textContent")
    assert "2 / 5" in pip_text
    assert len(ctx.pages) == 1, "a floating timer, not a presenter window"
    assert ctx.errors == []


def test_shift_p_is_silently_absent_without_support(ctx, load):
    ctx.add_init_script("Object.defineProperty(window, 'documentPictureInPicture', {value: undefined});")
    pg = load(presenter_deck())
    assert "Floating timer" not in pg.locator(".deck-help").inner_text()
    pg.keyboard.press("Shift+P")
    pg.wait_for_timeout(300)
    assert len(ctx.pages) == 1
    assert ctx.errors == []


# --- files, build and docs ------------------------------------------------------------------

def test_module_files_follow_the_module_rules():
    js = (SHIPPED_MODULES / "presenter.js").read_text("utf-8")
    css = (SHIPPED_MODULES / "presenter.css").read_text("utf-8")
    for src in (js, css):
        assert "</script" not in src.lower() and "</style" not in src.lower()
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "colours come from the deck tokens"
        assert not re.search(r"rgba?\(|hsla?\(", src)
    assert "@media print" in css


def test_new_deck_with_presenter_passes_the_static_gate(tmp_path):
    out = tmp_path / "deck.html"
    nd = SKILL / "scripts" / "new-deck.py"
    subprocess.run([sys.executable, str(nd), "--title", "Talk", "--out", str(out), "--no-embed-fonts",
                    "--with", "presenter"], check=True, capture_output=True, text=True)
    html = out.read_text("utf-8")
    assert "<!-- deck-module:presenter:start -->" in html
    gate = SKILL.parent / "html-canvas" / "scripts" / "verify-page.py"
    proc = subprocess.run([sys.executable, str(gate), str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_documented_in_modules_md_and_skill_md():
    doc = (REFERENCE / "modules.md").read_text("utf-8")
    m = re.search(r"^## Module: presenter\n(.*?)(?=^## |\Z)", doc, re.S | re.M)
    assert m, "modules.md has a presenter section"
    body = m.group(1)
    for word in ("data-time", "Shift+P", "rehearsal", "postMessage", "BroadcastChannel", "Picture-in-Picture"):
        assert word in body, word
    skill = (SKILL / "SKILL.md").read_text("utf-8")
    assert "--with presenter" in skill
