"""slide-stage: the parent side of the stage contract, one test per scar.

A stage is a live simulation inside a slide. The five scars it carries were
each paid for once in a real deck (N1 to N5 below), and every test here is
written so that it goes red when its scar is reopened. Where a test could stay
green by accident, it reopens the scar on purpose and checks that it does.

The child pages run the real html-canvas sim-engine.js, so the contract is
tested end to end, not against a mock of the other side. Pages open through
file:// from a fresh temp dir; a data-src stage needs its child file beside the
deck by design, the srcdoc stage proves the single-file path.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

import pytest

from slides_testlib import ASSETS, FIXTURES, SKILL

STAGE_FX = FIXTURES / "stage"
STAGE_JS = (ASSETS / "slide-stage.js") if (ASSETS / "slide-stage.js").exists() else None
STAGE_CSS = (ASSETS / "slide-stage.css") if (ASSETS / "slide-stage.css").exists() else None
SIM_ENGINE = SKILL.parent / "html-canvas" / "assets" / "sim-engine.js"


def _asset(path: Path | None) -> str:
    assert path is not None and path.exists(), "slide-stage asset missing"
    return path.read_text("utf-8")


def child_html() -> str:
    return (STAGE_FX / "child.html").read_text("utf-8").replace("/*SIM_ENGINE*/", SIM_ENGINE.read_text("utf-8"))


def deck_html(name: str = "deck.html", lang: str | None = None) -> str:
    text = (STAGE_FX / name).read_text("utf-8")
    text = text.replace("/*STAGE_CSS*/", _asset(STAGE_CSS)).replace("/*STAGE_JS*/", _asset(STAGE_JS))
    text = text.replace("/*SRCDOC_C*/", base64.b64encode(child_html().encode("utf-8")).decode("ascii"))
    if lang:
        text = re.sub(r'<html lang="\w+">', '<html lang="%s">' % lang, text, count=1)
    return text


@pytest.fixture
def open_deck(browser, tmp_path):
    """open_deck(name='deck.html', lang=None, **context_opts) -> page."""
    contexts = []
    counter = [0]

    def _open(name: str = "deck.html", lang: str | None = None, **opts):
        opts.setdefault("viewport", {"width": 900, "height": 700})
        ctx = browser.new_context(**opts)
        ctx.set_default_timeout(8000)
        contexts.append(ctx)
        # Any use of the Fullscreen API is recorded, so a test can prove there was none.
        ctx.add_init_script("""
          window.__fullscreenCalls = 0;
          for (const name of ['requestFullscreen', 'webkitRequestFullscreen']) {
            if (Element.prototype[name]) Element.prototype[name] = function () {
              window.__fullscreenCalls++; return Promise.resolve();
            };
          }""")
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        counter[0] += 1
        d = tmp_path / ("deck%d" % counter[0])
        d.mkdir()
        (d / "child.html").write_text(child_html(), encoding="utf-8")
        (d / "index.html").write_text(deck_html(name, lang), encoding="utf-8")
        page.goto((d / "index.html").as_uri())
        page.wait_for_function("window.SlideStage && window.SlideStage.list().length > 0")
        return page

    yield _open
    for c in contexts:
        c.close()


def stage(page, sid: str) -> dict:
    return page.evaluate("""(id) => {
      const el = document.getElementById(id);
      const f = el.querySelector('iframe');
      return {loaded: el.hasAttribute('data-loaded'), ready: el.getAttribute('data-ready') === 'yes',
              frames: el.querySelectorAll('iframe').length, mode: el.getAttribute('data-mode'),
              scale: el.getAttribute('data-scale'), max: el.classList.contains('is-max'),
              transform: f ? getComputedStyle(f).transform : null,
              src: f ? f.getAttribute('src') : null, srcdoc: f ? f.hasAttribute('srcdoc') : false};
    }""", sid)


def rect(page, selector: str) -> dict:
    return page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect();"
                         " return {x: r.left, y: r.top, w: r.width, h: r.height}; }", selector)


def go(page, i: int):
    page.evaluate("(i) => window.SlideDeck.goTo(i)", i)


def wait_loaded(page, sid: str, ready: bool = True):
    attr = "data-ready" if ready else "data-loaded"
    page.wait_for_function("(a) => document.getElementById(a[0]).hasAttribute(a[1])", arg=[sid, attr])


def child_frame(page, sid: str):
    return page.query_selector("#%s iframe" % sid).content_frame()


# --- static: the module ships as one more engine asset ---------------------------------

def test_assets_exist_and_carry_the_engine_stamp():
    for path in (STAGE_JS, STAGE_CSS):
        first = _asset(path).splitlines()[0]
        assert re.search(r"slide-engine v2\b", first), first


def test_no_fullscreen_api_anywhere_in_the_module():
    # N3, static half: not even a comment may name it, so the search really runs empty.
    for path in (STAGE_JS, STAGE_CSS):
        text = _asset(path)
        for name in ("requestFullscreen", "webkitRequestFullscreen", "exitFullscreen", "allowfullscreen"):
            assert name not in text, "%s in %s" % (name, path.name)


def test_assets_are_english_ascii_punctuation_without_dashes():
    for path in (STAGE_JS, STAGE_CSS):
        text = _asset(path)
        assert chr(0x2014) not in text and chr(0x2013) not in text
        assert " %s " % ("-" * 2) not in text
        assert "/%s/" % "Users" not in text
    # Spliced inline into a deck: a closing script tag, even in a comment, ends the block.
    assert "</script" not in _asset(STAGE_JS).lower()


# --- N5: lazy load on the active slide, unload when two or more slides away -----------

def test_n5_stages_load_on_arrival_and_unload_two_slides_away(open_deck):
    page = open_deck()
    page.wait_for_timeout(200)
    for sid in ("stageA", "stageB", "stageC"):
        assert stage(page, sid)["frames"] == 0, sid
    go(page, 2)
    wait_loaded(page, "stageA")
    assert stage(page, "stageB")["frames"] == 0
    go(page, 3)                                   # one away: kept, not restarted
    page.wait_for_timeout(250)
    assert stage(page, "stageA")["frames"] == 1
    go(page, 4)                                   # two away: unloaded
    page.wait_for_function("!document.getElementById('stageA').querySelector('iframe')")
    assert not stage(page, "stageA")["loaded"]
    go(page, 5)
    wait_loaded(page, "stageB")
    assert stage(page, "stageA")["frames"] == 0
    assert page.errors == []


def test_n5_reduced_motion_loads_every_stage_at_once(open_deck):
    page = open_deck(reduced_motion="reduce")
    for sid in ("stageA", "stageB", "stageC"):
        wait_loaded(page, sid, ready=False)


def test_n5_print_loads_every_stage(open_deck):
    page = open_deck()
    page.emulate_media(media="print")
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    for sid in ("stageA", "stageB", "stageC"):
        wait_loaded(page, sid, ready=False)


# --- the contract, parent side --------------------------------------------------------

def test_ready_from_the_child_marks_the_stage(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    assert stage(page, "stageA")["ready"]


def test_message_from_a_foreign_source_is_ignored(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.evaluate("""document.getElementById('foreign').contentWindow
                       .postMessage({relay: {type: 'stage:maximize', on: true}}, '*')""")
    page.evaluate("window.postMessage({type: 'stage:maximize', on: true}, '*')")
    page.wait_for_timeout(300)
    assert not stage(page, "stageA")["max"]
    assert page.evaluate("document.querySelectorAll('.stage.is-max').length") == 0


def test_v_inside_the_frame_toggles_the_stage_through_the_child(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.click("#stageA iframe")                   # focus moves into the child
    page.keyboard.press("v")
    page.wait_for_function("document.getElementById('stageA').classList.contains('is-max')")
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('stageA').classList.contains('is-max')")


def test_child_maximize_button_and_reported_state(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    frame = child_frame(page, "stageA")
    frame.click("[data-sim-maximize]")
    page.wait_for_function("document.getElementById('stageA').classList.contains('is-max')")
    frame.wait_for_function("document.documentElement.getAttribute('data-sim-maximized') === 'yes'")
    page.click(".stage-close")
    frame.wait_for_function("document.documentElement.getAttribute('data-sim-maximized') === 'no'")


def test_restart_resets_the_running_child_in_place(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    frame = child_frame(page, "stageA")
    frame.evaluate("window.__sameWindow = true")
    before = frame.evaluate("window.resets")
    page.click("#s2 [data-stage='restart']")
    frame.wait_for_function("(n) => window.resets > n", arg=before)
    assert frame.evaluate("window.__sameWindow") is True


def test_srcdoc_stage_runs_from_inside_the_deck_with_utf8_intact(open_deck):
    page = open_deck()
    go(page, 6)
    wait_loaded(page, "stageC")
    s = stage(page, "stageC")
    assert s["srcdoc"] and s["src"] is None
    assert child_frame(page, "stageC").inner_text("#greeting") == "Café déjà vu, 5 €"


# --- N4: two kinds of stage -----------------------------------------------------------

def test_n4_fit_stage_scales_down_never_up_and_stays_inside(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    s = stage(page, "stageA")
    assert s["mode"] == "fit"
    assert 0 < float(s["scale"]) < 1
    assert s["transform"].startswith("matrix(")
    frame, inner = rect(page, "#stageA"), rect(page, "#stageA iframe")
    assert inner["x"] >= frame["x"] - 1 and inner["y"] >= frame["y"] - 1
    assert inner["x"] + inner["w"] <= frame["x"] + frame["w"] + 1
    assert inner["y"] + inner["h"] <= frame["y"] + frame["h"] + 1
    # The declared viewport is the least the child lays out in; it grows along the
    # axis the frame has to spare, so the page fills the frame instead of sitting
    # in a band of empty stage on two sides.
    vw, vh = child_frame(page, "stageA").evaluate("[innerWidth, innerHeight]")
    assert vw >= 1600 and vh >= 1000 and (vw == 1600 or vh == 1000), (vw, vh)
    assert abs(inner["w"] - frame["w"]) <= 3 and abs(inner["h"] - frame["h"]) <= 3, (inner, frame)


def test_n4_fit_follows_the_frame_without_a_window_resize(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    before = stage(page, "stageA")["scale"]
    page.evaluate("document.querySelector('#s2 .lead').style.paddingTop = '220px'")
    page.wait_for_function("(b) => document.getElementById('stageA').getAttribute('data-scale') !== b", arg=before)
    assert float(stage(page, "stageA")["scale"]) < float(before)


def test_n4_read_stage_is_not_scaled_and_fills_its_frame(open_deck):
    page = open_deck()
    go(page, 5)
    wait_loaded(page, "stageB")
    s = stage(page, "stageB")
    assert s["mode"] == "read" and s["scale"] is None and s["transform"] == "none"
    frame, inner = rect(page, "#stageB"), rect(page, "#stageB iframe")
    assert abs(inner["w"] - frame["w"]) <= 2 and abs(inner["h"] - frame["h"]) <= 2


# --- N1: in reading mode the placeholder must not swallow the click --------------------

CENTRE_HIT = """(sel) => {
  const r = document.querySelector(sel).getBoundingClientRect();
  const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return el ? el.tagName + (el.className ? '.' + el.className : '') : null;
}"""


def test_n1_click_reaches_the_simulation_in_reading_mode(open_deck):
    page = open_deck()
    go(page, 5)
    wait_loaded(page, "stageB")
    assert page.evaluate(CENTRE_HIT, "#stageB") == "IFRAME"
    r = rect(page, "#stageB")
    page.mouse.click(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
    child_frame(page, "stageB").wait_for_function("window.clicks === 1")
    # Reopen the scar: with both bolts gone the placeholder takes the click.
    page.add_style_tag(content=".stage .stage__placeholder{pointer-events:auto !important;display:flex !important}")
    assert page.evaluate(CENTRE_HIT, "#stageB") == "DIV.stage__placeholder"


# --- N2 and N3: large without the Fullscreen API, fixed against the window -------------

def test_n2_n3_large_stage_fills_the_window_on_a_later_slide(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.keyboard.press("v")
    page.wait_for_function("document.getElementById('stageA').classList.contains('is-max')")
    vw, vh = page.evaluate("[innerWidth, innerHeight]")
    r = rect(page, "#stageA")
    assert (round(r["x"]), round(r["y"]), round(r["w"]), round(r["h"])) == (0, 0, vw, vh)
    assert page.evaluate("document.fullscreenElement") is None
    assert page.evaluate("window.__fullscreenCalls") == 0
    assert page.evaluate("getComputedStyle(document.getElementById('s2')).transform") == "none"
    assert float(stage(page, "stageA")["scale"]) > 0
    # Reopen the scar: give the slide its transform back and the stage no longer fills.
    page.evaluate("document.getElementById('s2').style.setProperty('transform', 'translateZ(0)', 'important')")
    r2 = rect(page, "#stageA")
    assert (round(r2["x"]), round(r2["w"])) != (0, vw)
    page.evaluate("document.getElementById('s2').style.removeProperty('transform')")
    page.keyboard.press("Escape")
    page.wait_for_function("!document.getElementById('stageA').classList.contains('is-max')")
    assert rect(page, "#stageA")["w"] < vw
    assert page.evaluate("document.querySelectorAll('.stage-max-host').length") == 0


def test_n3_three_ways_back_and_arrows_stay_put_while_large(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.click("#s2 [data-stage='maximize']")
    assert stage(page, "stageA")["max"]
    assert page.get_attribute("#s2 [data-stage='maximize']", "aria-pressed") == "true"
    top = page.evaluate("document.querySelector('.deck').scrollTop")
    page.keyboard.press("ArrowDown")            # focus still sits on the maximize button
    page.wait_for_timeout(150)
    assert page.evaluate("window.SlideDeck.current()") == 2
    assert page.evaluate("document.querySelector('.deck').scrollTop") == top, "the deck scrolled behind the stage"
    page.click(".stage-close")
    assert not stage(page, "stageA")["max"]
    assert page.evaluate("document.querySelectorAll('.stage-close').length") == 0
    page.keyboard.press("v")
    assert stage(page, "stageA")["max"]
    page.keyboard.press("v")
    assert not stage(page, "stageA")["max"]
    page.keyboard.press("ArrowDown")
    page.wait_for_function("window.SlideDeck.current() === 3")
    assert page.evaluate("window.__fullscreenCalls") == 0


def test_a_large_stage_is_never_unloaded(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.keyboard.press("v")
    go(page, 5)
    page.wait_for_timeout(300)
    assert stage(page, "stageA")["frames"] == 1


@pytest.mark.parametrize("lang,label", [("en", "Exit full view"), ("de", "Vollbild beenden")])
def test_close_control_speaks_the_deck_language(open_deck, lang, label):
    page = open_deck(lang=lang)
    go(page, 2)
    wait_loaded(page, "stageA", ready=False)
    page.keyboard.press("v")
    assert page.inner_text(".stage-close").strip() == label


# --- compat: the older attribute names --------------------------------------------------

def test_older_markup_is_read_as_an_alias(open_deck):
    page = open_deck("legacy.html")
    page.wait_for_function("document.querySelector('#old .buehne__rahmen iframe')")
    assert page.evaluate("document.querySelector('#old .buehne__rahmen').getAttribute('data-mode')") == "read"
    page.wait_for_function("document.querySelector('#old .buehne__rahmen').hasAttribute('data-ready')")
    assert page.evaluate(CENTRE_HIT, "#old .buehne__rahmen") == "IFRAME"
    page.evaluate("document.getElementById('mixed').scrollIntoView({behavior: 'instant'})")
    wait_loaded(page, "aliased")
    s = stage(page, "aliased")
    assert s["mode"] == "fit" and s["src"] == "child.html"
    assert child_frame(page, "aliased").evaluate("innerWidth") == 1200


def test_print_hides_the_stage_buttons(open_deck):
    """Paper cannot enlarge or restart a run; the buttons would be dead ink."""
    page = open_deck()
    assert page.locator('[data-stage="maximize"]').count() > 0
    page.emulate_media(media="print")
    shown = page.evaluate("""() => [...document.querySelectorAll('[data-stage]')]
      .filter(b => getComputedStyle(b).display !== 'none').length""")
    assert shown == 0


# --- the slide's look reaches the page inside ------------------------------------------

def test_stage_hands_theme_and_language_to_the_page(open_deck):
    """The page's own toolbar is hidden inside a stage, so the slide sets its theme and language."""
    page = open_deck(lang="de")
    go(page, 2)
    wait_loaded(page, "stageA")
    child = child_frame(page, "stageA")
    deck_dark = page.evaluate("document.documentElement.classList.contains('theme-dark')")
    child.wait_for_function("(d) => document.documentElement.classList.contains('dark') === d", arg=deck_dark)
    assert child.evaluate("document.documentElement.getAttribute('data-lang')") == "de"
    # what the engine's T key does: swap the theme class on <html>
    page.evaluate("""() => { const r = document.documentElement, d = r.classList.contains('theme-dark');
      r.classList.toggle('theme-dark', !d); r.classList.toggle('theme-light', d); }""")
    child.wait_for_function("(d) => document.documentElement.classList.contains('dark') === d", arg=not deck_dark)
    assert page.errors == []


# --- theme and language reach the child (stage:theme, stage:lang) ---------------------

def child_msgs(page, sid: str, kind: str) -> list:
    return child_frame(page, sid).evaluate("(k) => window.__msgs.filter(m => m.type === k)", kind)


def test_theme_and_lang_are_sent_after_ready_and_on_change(open_deck):
    page = open_deck(color_scheme="light")
    go(page, 2)
    wait_loaded(page, "stageA")
    frame_wait = "(k) => window.__msgs.some(m => m.type === k)"
    child_frame(page, "stageA").wait_for_function(frame_wait, arg="stage:theme")
    child_frame(page, "stageA").wait_for_function(frame_wait, arg="stage:lang")
    assert child_msgs(page, "stageA", "stage:theme")[-1]["theme"] == "light", "no class yet: the OS decides"
    assert child_msgs(page, "stageA", "stage:lang")[-1]["lang"] == "en"
    page.evaluate("() => document.documentElement.classList.add('theme-dark')")
    child_frame(page, "stageA").wait_for_function(
        "() => window.__msgs.filter(m => m.type === 'stage:theme').slice(-1)[0].theme === 'dark'")
    page.evaluate("() => { document.documentElement.setAttribute('data-lang', 'de'); }")
    child_frame(page, "stageA").wait_for_function(
        "() => window.__msgs.filter(m => m.type === 'stage:lang').slice(-1)[0].lang === 'de'")
    n = len(child_msgs(page, "stageA", "stage:theme"))
    page.evaluate("() => document.documentElement.classList.add('unrelated')")
    page.wait_for_timeout(150)
    assert len(child_msgs(page, "stageA", "stage:theme")) == n, "only a real change is sent"
    assert page.errors == []


# --- one protocol end to end: a real simulation inside a real stage -------------------

def test_a_real_simulation_in_a_stage_hides_its_toolbar_and_follows_the_deck(open_deck, tmp_path):
    """slide-stage.js sends stage:theme and stage:lang, sim-engine.js applies them.

    The child is a flow simulation assembled by html-canvas new-simulation.py, so the
    toolbar rule in simulation.css and the child listener are the shipped ones."""
    import subprocess
    import sys
    from urllib.parse import urlparse, unquote
    built = tmp_path / "sim-flow-built.html"
    tool = SKILL.parent / "html-canvas" / "scripts" / "new-simulation.py"
    r = subprocess.run([sys.executable, str(tool), "--archetype", "flow", "--title", "Stage probe",
                        "--out", str(built), "--force"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    page = open_deck(color_scheme="light")
    deck_dir = Path(unquote(urlparse(page.url).path)).parent
    (deck_dir / "child.html").write_text(built.read_text("utf-8"), encoding="utf-8")
    go(page, 2)
    wait_loaded(page, "stageA")
    child = child_frame(page, "stageA")
    assert child.evaluate("document.documentElement.getAttribute('data-sim-embedded')") == "yes"
    assert child.evaluate("getComputedStyle(document.querySelector('.topbar')).display") == "none"
    child.wait_for_function("() => !document.documentElement.classList.contains('dark')")
    page.evaluate("() => document.documentElement.classList.add('theme-dark')")
    child.wait_for_function("() => document.documentElement.classList.contains('dark')")
    page.evaluate("() => document.documentElement.setAttribute('data-lang', 'de')")
    child.wait_for_function("() => document.documentElement.getAttribute('data-lang') === 'de'")
    assert child.evaluate("[localStorage.getItem('html-canvas-theme'), localStorage.getItem('html-canvas-lang')]") == [None, None]
    assert page.errors == []


# --- Keys while a stage fills the window (review wave 4) --------------------------------

def test_enter_on_a_button_still_works_while_large(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.keyboard.press("v")
    assert stage(page, "stageA")["max"]
    page.focus(".stage-close")
    page.keyboard.press("Enter")
    page.wait_for_function("!document.getElementById('stageA').classList.contains('is-max')")
    assert page.evaluate("document.querySelectorAll('.stage-close').length") == 0


def test_single_key_shortcuts_never_reach_the_deck_behind_a_large_stage(open_deck):
    page = open_deck()
    go(page, 2)
    wait_loaded(page, "stageA")
    page.evaluate("""window.__seen = [];
      document.addEventListener('keydown', function (e) { if (e.key.length === 1 || e.key === 'Enter') window.__seen.push(e.key); });""")
    page.keyboard.press("v")
    assert stage(page, "stageA")["max"]
    for k in ["d", "r", "b", "w", "q", "p", "n", "2", "Enter", "?", "Shift+P"]:
        page.keyboard.press(k)
    assert page.evaluate("window.__seen") == []
    assert stage(page, "stageA")["max"], "a key closed the stage"
    # The look keys still reach the deck: the stage follows them.
    page.keyboard.press("t")
    page.keyboard.press("l")
    assert page.evaluate("window.__seen") == ["t", "l"]
    assert stage(page, "stageA")["max"]


def test_t_and_l_inside_a_real_simulation_go_to_the_slide_and_store_nothing(open_deck, tmp_path):
    """T and L pressed inside the frame belong to the slide: the frame never flips on
    its own and never writes the page's stored choice (review wave 4)."""
    import subprocess
    import sys
    from urllib.parse import urlparse, unquote
    built = tmp_path / "sim-flow-keys.html"
    tool = SKILL.parent / "html-canvas" / "scripts" / "new-simulation.py"
    r = subprocess.run([sys.executable, str(tool), "--archetype", "flow", "--title", "Stage keys",
                        "--out", str(built), "--force"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    page = open_deck(color_scheme="light")
    deck_dir = Path(unquote(urlparse(page.url).path)).parent
    (deck_dir / "child.html").write_text(built.read_text("utf-8"), encoding="utf-8")
    # The fixture deck stands in for the engine: T and L as the engine does them.
    page.evaluate("""() => { const r = document.documentElement;
      window.__calls = [];
      document.body.insertAdjacentHTML('beforeend', '<span data-de hidden>bilingual</span>');
      window.SlideDeck.toggleTheme = function () { window.__calls.push('theme');
        const d = r.classList.contains('theme-dark'); r.classList.toggle('theme-dark', !d); r.classList.toggle('theme-light', d); };
      window.SlideDeck.setLang = function (l) { window.__calls.push('lang:' + l); r.setAttribute('data-lang', l); };
      window.SlideDeck.state = function () { return { lang: r.getAttribute('data-lang') || 'en' }; }; }""")
    go(page, 2)
    wait_loaded(page, "stageA")
    child = child_frame(page, "stageA")
    child.wait_for_function("() => !document.documentElement.classList.contains('dark')")
    page.click("#stageA iframe")
    page.keyboard.press("t")
    page.wait_for_function("window.__calls.length === 1")
    child.wait_for_function("() => document.documentElement.classList.contains('dark')")
    assert page.evaluate("document.documentElement.classList.contains('theme-dark')")
    page.keyboard.press("l")
    page.wait_for_function("window.__calls.length === 2")
    child.wait_for_function("() => document.documentElement.getAttribute('data-lang') === 'de'")
    assert page.evaluate("window.__calls") == ["theme", "lang:de"]
    assert child.evaluate("[localStorage.getItem('html-canvas-theme'), localStorage.getItem('html-canvas-lang')]") == [None, None]
    assert page.errors == []


def test_a_large_stage_covers_the_deck_chrome_of_an_isolated_slide(open_deck):
    """The engine gives every slide isolation: isolate, a stacking context that kept the large
    stage under the deck's fixed chrome (back link, dots, counter) on top of it."""
    page = open_deck()
    page.evaluate("""() => {
      document.querySelectorAll('.slide').forEach(s => { s.style.isolation = 'isolate'; s.style.position = 'relative'; s.style.zIndex = '1'; });
      const c = document.createElement('div'); c.id = 'chrome';
      c.style.cssText = 'position:fixed;left:0;bottom:0;width:120px;height:40px;z-index:100;background:red';
      document.body.appendChild(c); }""")
    go(page, 2)
    wait_loaded(page, "stageA")
    page.keyboard.press("v")
    assert stage(page, "stageA")["max"]
    vh = page.evaluate("innerHeight")
    hit = page.evaluate("(y) => { const e = document.elementFromPoint(20, y); return e && (e.id || e.tagName); }", vh - 10)
    assert hit != "chrome", "the deck chrome sits on top of the large stage"
