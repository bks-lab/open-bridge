"""The child side of the stage contract, and the flow archetype's stack chips.

A simulation embedded in a slide talks to the slide through postMessage. The
engine speaks only when it is framed (window.parent !== window) and accepts
only what its own parent sends. tests/fixtures/stage/parent.html is the
smallest parent that records what arrives; the real one is
html-slides/assets/slide-stage.js, tested in html-slides/tests/test_stage.py.

The child is a real page assembled by new-simulation.py, never a hand copy.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from canvas_testlib import ASSETS, SKILL, run_new_simulation

STAGE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stage"
ENGINE = (ASSETS / "sim-engine.js").read_text("utf-8")


def assemble(tmp_path: Path, archetype: str = "flow") -> str:
    out = tmp_path / ("%s-built.html" % archetype)
    r = run_new_simulation(out, "--archetype", archetype, "--title", "Stage probe", "--force")
    assert r.returncode == 0, r.stderr
    return out.read_text("utf-8")


@pytest.fixture
def framed(browser, tmp_path):
    """The parent fixture with an assembled flow simulation as child.html beside it."""
    d = tmp_path / "framed"
    d.mkdir()
    (d / "child.html").write_text(assemble(tmp_path), encoding="utf-8")
    (d / "index.html").write_text((STAGE_FIXTURES / "parent.html").read_text("utf-8"), encoding="utf-8")
    ctx = browser.new_context(viewport={"width": 1000, "height": 800})
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto((d / "index.html").as_uri())
    page.wait_for_function("window.received && window.received.some(m => m && m.type === 'stage:ready')")
    yield page
    ctx.close()


def child(page):
    return page.frame(name="child")


def run_state(frame) -> str:
    return frame.evaluate("document.querySelector('[data-sim-run]').getAttribute('data-state')")


def received(page, kind: str) -> list:
    return page.evaluate("(k) => window.received.filter(m => m && m.type === k)", kind)


# --- G7: the contract, child side ----------------------------------------------------

def test_ready_arrives_once_with_the_contract_version(framed):
    ready = received(framed, "stage:ready")
    assert len(ready) == 1
    assert ready[0].get("contract") == 1
    assert framed.errors == []


def test_v_key_inside_the_frame_is_forwarded_to_the_parent(framed):
    framed.frame_locator("#child").locator("h1").first.click()
    framed.keyboard.press("v")
    framed.wait_for_function("window.received.some(m => m && m.type === 'stage:key')")
    keys = [m["key"] for m in received(framed, "stage:key")]
    assert keys == ["v"]
    # Space stays with the simulation: it is the run key, not a deck key.
    framed.keyboard.press("Escape")
    framed.wait_for_function("window.received.filter(m => m && m.type === 'stage:key').length === 2")
    assert [m["key"] for m in received(framed, "stage:key")] == ["v", "Escape"]


def test_forwarded_page_keys_are_consumed_inside_the_frame(framed):
    """PageDown/PageUp go to the deck; scrolling the simulation as well would move two things."""
    frame = child(framed)
    frame.evaluate("""() => { window.__prevented = {};
      document.addEventListener('keydown', e => { window.__prevented[e.key] = e.defaultPrevented; }); }""")
    framed.frame_locator("#child").locator("h1").first.click()
    for key in ("PageDown", "PageUp", "v"):
        framed.keyboard.press(key)
    framed.wait_for_function("window.received.filter(m => m && m.type === 'stage:key').length === 3")
    assert [m["key"] for m in received(framed, "stage:key")] == ["PageDown", "PageUp", "v"]
    assert frame.evaluate("window.__prevented") == {"PageDown": True, "PageUp": True, "v": False}


def test_simulation_keys_are_not_forwarded(framed):
    framed.frame_locator("#child").locator("h1").first.click()
    for key in ("r", "s", "1", "ArrowDown"):
        framed.keyboard.press(key)
    framed.wait_for_timeout(150)
    assert received(framed, "stage:key") == []


def test_restart_from_a_foreign_source_is_ignored_and_from_the_parent_obeyed(framed):
    frame = child(framed)
    frame.click("[data-sim-end]")
    assert run_state(frame) == "done"
    framed.evaluate("window.viaForeign({type: 'stage:restart'})")
    framed.wait_for_timeout(250)
    assert run_state(frame) == "done", "a sibling frame restarted the run"
    framed.evaluate("window.toChild({type: 'stage:restart'})")
    frame.wait_for_function("document.querySelector('[data-sim-run]').getAttribute('data-state') !== 'done'")
    assert run_state(frame) in ("running", "idle")


def test_maximize_button_posts_a_request_and_reflects_the_reported_state(framed):
    frame = child(framed)
    btn = frame.locator("[data-sim-maximize]")
    assert btn.is_visible()
    btn.click()
    framed.wait_for_function("window.received.some(m => m && m.type === 'stage:maximize')")
    framed.evaluate("window.toChild({type: 'stage:maximize', on: true})")
    frame.wait_for_function("document.documentElement.getAttribute('data-sim-maximized') === 'yes'")
    assert btn.get_attribute("aria-pressed") == "true"
    framed.evaluate("window.viaForeign({type: 'stage:maximize', on: false})")
    framed.wait_for_timeout(200)
    assert frame.evaluate("document.documentElement.getAttribute('data-sim-maximized')") == "yes"


def test_inside_a_stage_the_page_hides_its_own_toolbar(framed):
    """The slide owns theme, language and print; a second toolbar inside the frame is noise."""
    frame = child(framed)
    assert frame.evaluate("document.documentElement.getAttribute('data-sim-embedded')") == "yes"
    assert frame.evaluate("getComputedStyle(document.querySelector('.topbar')).display") == "none"


def test_the_slide_sets_theme_and_language_and_nothing_is_stored(framed):
    frame = child(framed)
    framed.evaluate("window.toChild({type: 'stage:look', dark: true, lang: 'de'})")
    frame.wait_for_function("document.documentElement.classList.contains('dark')")
    assert frame.evaluate("[document.documentElement.getAttribute('data-lang'), document.documentElement.lang]") == ["de", "de"]
    framed.evaluate("window.toChild({type: 'stage:look', dark: false, lang: 'en'})")
    frame.wait_for_function("!document.documentElement.classList.contains('dark')")
    assert frame.evaluate("document.documentElement.getAttribute('data-lang')") == "en"
    assert frame.evaluate("[localStorage.getItem('html-canvas-theme'), localStorage.getItem('html-canvas-lang')]") == [None, None]
    framed.evaluate("window.viaForeign({type: 'stage:look', dark: true})")
    framed.wait_for_timeout(200)
    assert not frame.evaluate("document.documentElement.classList.contains('dark')"), "a sibling frame set the theme"


def test_a_standalone_page_keeps_its_toolbar(open_page, tmp_path):
    page = open_page(assemble(tmp_path))
    assert page.evaluate("getComputedStyle(document.querySelector('.topbar')).display") != "none"


def test_a_standalone_page_posts_nothing_and_offers_no_maximize_button(open_page, tmp_path):
    page = open_page(assemble(tmp_path),
                     init_script="window.__posted = []; addEventListener('message', e => __posted.push(e.data));")
    page.wait_for_timeout(300)
    assert page.evaluate("Sim.stage.embedded") is False
    assert page.evaluate("window.__posted") == []
    assert page.evaluate("document.querySelectorAll('[data-sim-maximize]').length") == 0
    assert page.errors == []


@pytest.mark.parametrize("archetype", ["flow", "worklist"])
def test_both_archetypes_ship_the_maximize_control_hidden_by_default(archetype):
    text = (ASSETS / ("sim-%s.html" % archetype)).read_text("utf-8")
    m = re.search(r"<button[^>]*data-sim-maximize[^>]*>", text)
    assert m and " hidden" in m.group(0)


def test_engine_speaks_only_when_framed_and_checks_the_source():
    assert "global.parent !== global" in ENGINE or "window.parent !== window" in ENGINE
    assert "e.source !== global.parent" in ENGINE


def test_simulation_reference_documents_every_message():
    text = (SKILL / "references" / "simulation.md").read_text("utf-8")
    assert "## Embedding in a slide: the stage contract" in text
    for kind in ("stage:ready", "stage:maximize", "stage:key", "stage:restart", "stage:look", "event.source"):
        assert kind in text, kind


# --- C6: the clock starts at 00:00, truncated stacks say how many they hide ----------

def test_clock_reads_00_00_before_the_run_starts(open_page, tmp_path):
    page = open_page(assemble(tmp_path))
    assert run_state(page) == "idle"
    assert page.inner_text("#clock") == "00:00"
    page.click("[data-sim-end]")
    assert page.inner_text("#clock") != "00:00"
    assert re.search(r'<b id="clock">00:00</b>', (ASSETS / "sim-flow.html").read_text("utf-8"))


STACKS = """() => {
  const model = window.__model();
  return Object.keys(model).map(key => {
    const drawn = document.querySelectorAll('.sim-token[data-at="' + key + '"][data-shown="yes"]').length;
    const chip = document.querySelector('.sim-more[data-stack="' + key + '"]');
    const shown = !!chip && chip.getAttribute('data-shown') === 'yes';
    const n = shown ? parseInt(chip.textContent.replace('+', ''), 10) : 0;
    return {key, drawn, n, model: model[key], chipText: shown ? chip.textContent : ''};
  });
}"""


# The fragment's script runs inside an IIFE, so the test opens a window onto the
# model by splicing a probe in front of Sim.boot. Nothing of this ships.
PROBE = """window.__model = function () {
  return {in: qIn.length, cls: qCls.length, rev: qRev.length, spec0: qSpec[0].length,
          spec1: qSpec[1].length, spec2: qSpec[2].length, bin0: binned[0].length, bin1: binned[1].length};
};
window.__advance = function (n) { for (var k = 0; k < n; k++) if (step(60)) break; render(); };
"""


def probed(text: str) -> str:
    anchor = "Sim.boot(clockEngine"
    assert text.count(anchor) == 1
    return text.replace(anchor, PROBE + anchor)


def crowded(text: str, count: int = 24) -> str:
    rows = ",\n".join(
        "  { id: 'Q-%03d', spawn: %d, lane: %d, verdict: '%s', bin: %d }"
        % (i, 100 + i * 20, i % 3, ("ok", "corrected", "ok")[i % 3], i % 2)
        for i in range(count))
    out, n = re.subn(r"var ITEMS = \[.*?\n\];", lambda _: "var ITEMS = [\n%s\n];" % rows, text, flags=re.S)
    assert n == 1
    return out


def test_drawn_tokens_plus_chip_equal_every_stack_and_counter(open_page, tmp_path):
    page = open_page(probed(crowded(assemble(tmp_path))))
    truncated = set()
    for _ in range(40):
        page.evaluate("window.__advance(8)")
        for s in page.evaluate(STACKS):
            assert s["drawn"] + s["n"] == s["model"], s
            if s["n"]:
                truncated.add(s["key"])
                assert s["chipText"] == "+%d" % s["n"]
        assert int(page.inner_text("#cIn")) == page.evaluate("window.__model().in")
    page.click("[data-sim-end]")
    end = {s["key"]: s for s in page.evaluate(STACKS)}
    for b in (0, 1):
        assert end["bin%d" % b]["drawn"] + end["bin%d" % b]["n"] == int(page.inner_text("#cB%d" % b))
    assert end["bin0"]["n"] > 0 and end["bin1"]["n"] > 0
    assert "in" in truncated, "the crowded run never cut the intake stack, so the probe measured nothing"
    assert page.errors == []


def test_no_chip_shows_before_the_run(open_page, tmp_path):
    page = open_page(probed(crowded(assemble(tmp_path))))
    for s in page.evaluate(STACKS):
        assert s["n"] == 0 and s["drawn"] == s["model"] == 0, s
