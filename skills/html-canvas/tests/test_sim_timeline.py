"""Wave 4 C1: the simulation engine's timeline, scenario link, stage theme and table.

Every page here is assembled by new-simulation.py, never a hand copy, and opened
from file:// in an empty folder. The contract these tests hold:

  (a) scenario and control values live in the URL hash, only when they differ
      from the default, and come back on load; "copy link" carries them plus
      the current position.
  (b) a transport bar with a timeline scrubber. Seeking is deterministic: the
      model advances in fixed ticks, so the state at tick n is one state, and a
      seek that restores a ring-buffer snapshot lands on exactly the state a
      replay from the start reaches.
  (c) the child side of stage:theme and stage:lang.
  (d) under reduced motion nothing ever starts by itself.
  (e) a "show as table" text alternative for the state.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from canvas_testlib import ASSETS, SKILL, run_new_simulation

STAGE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "stage"
ENGINE = (ASSETS / "sim-engine.js").read_text("utf-8")
ARCHETYPES = ["flow", "worklist"]


def assemble(tmp_path: Path, archetype: str, lang: str = "en") -> Path:
    out = tmp_path / ("%s-%s.html" % (archetype, lang))
    r = run_new_simulation(out, "--archetype", archetype, "--title", "Timeline probe",
                           "--lang", lang, "--force")
    assert r.returncode == 0, r.stderr
    return out


@pytest.fixture
def sim(browser, tmp_path):
    """sim(archetype, hash='', reduced=False) -> page opened from file:// with that hash."""
    contexts = []

    def _open(archetype: str, hash: str = "", reduced: bool = False, lang: str = "en",
              fake_clock: bool = False):
        d = tmp_path / ("p%d" % len(contexts))
        d.mkdir()
        f = d / "index.html"
        f.write_text(assemble(tmp_path, archetype, lang).read_text("utf-8"), encoding="utf-8")
        opts = {"viewport": {"width": 1000, "height": 800}}
        if reduced:
            opts["reduced_motion"] = "reduce"
        ctx = browser.new_context(**opts)
        contexts.append(ctx)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        if fake_clock:
            page.clock.install()
        page.goto(f.as_uri() + (("#" + hash) if hash else ""))
        page.wait_for_function("window.Sim && Sim.active && Sim.active.clock")
        return page

    yield _open
    for c in contexts:
        c.close()


# The visible state of a page, as one comparable value: every visible text in
# <main>, plus where each SVG token is drawn and how it is marked.
FINGERPRINT = """() => {
  const main = document.querySelector('main').innerText;
  const tokens = [...document.querySelectorAll('.sim-token')].map(g =>
    [g.getAttribute('transform'), g.getAttribute('data-shown'), g.getAttribute('data-level')].join('|'));
  return main + '\\n' + tokens.join('\\n');
}"""


def fp(page) -> str:
    return page.evaluate(FINGERPRINT)


def state(page) -> str:
    return page.evaluate("document.querySelector('[data-sim-run]').getAttribute('data-state')")


def set_range(page, name: str, value) -> None:
    page.evaluate("""([n, v]) => { const i = document.querySelector('[data-sim-param="' + n + '"]');
      i.value = String(v); i.dispatchEvent(new Event('change', {bubbles: true})); }""", [name, value])


def replay(page, n: int) -> None:
    """Seek to tick n by a pure replay from the start: snapshots off, ring empty.

    seek() alone is no reference: it computes the length with a dry run that
    refills the ring, so both sides of a comparison would go through restore()."""
    page.evaluate("""(n) => { const c = Sim.active.clock, s = c._snapshot;
      c._snapshot = null; c.forget(); c.seek(0); c.seek(n); c._snapshot = s;
      if (c.ring().length) throw new Error('replay used the ring'); }""", n)


def ticks(page) -> int:
    return page.evaluate("Sim.active.clock.ticks")


# --- (b) determinism: the state at tick n is one state --------------------------------

@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_seek_through_a_snapshot_equals_a_replay_from_the_start(sim, archetype):
    page = sim(archetype)
    length = page.evaluate("Sim.active.clock.length()")
    assert length > 40
    for n in (length // 5, length // 2, length - 3, 7):
        page.evaluate("Sim.active.clock.forget(), Sim.active.clock.length()")  # refills the ring
        assert page.evaluate("Sim.active.clock.ring().length") > 0, "no snapshot was ever taken"
        page.evaluate("(n) => Sim.active.clock.seek(n)", n)
        via_ring = fp(page)
        assert ticks(page) == n
        replay(page, n)
        via_replay = fp(page)
        assert via_ring == via_replay, (archetype, n)
    assert page.errors == []


@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_seeking_backwards_restores_a_snapshot_instead_of_replaying(sim, archetype):
    page = sim(archetype)
    length = page.evaluate("Sim.active.clock.length()")
    page.evaluate("""() => { const c = Sim.active.clock; window.__restores = 0;
      const r = c._restore; c._restore = function (s) { window.__restores++; return r(s); }; }""")
    page.evaluate("(n) => Sim.active.clock.seek(n)", length - 2)
    page.evaluate("(n) => Sim.active.clock.seek(n)", length // 2)
    assert page.evaluate("window.__restores") >= 1


@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_a_live_run_paused_anywhere_matches_a_seek_to_the_same_tick(sim, archetype):
    page = sim(archetype)
    page.click("[data-sim-speed] button[data-speed='2']")
    page.click("[data-sim-run]")
    page.wait_for_timeout(1300)
    page.click("[data-sim-run]")
    assert state(page) == "paused"
    n = ticks(page)
    assert n > 10
    live = fp(page)
    replay(page, n)
    assert fp(page) == live


def test_length_is_the_tick_count_of_a_full_run(sim):
    page = sim("flow")
    length = page.evaluate("Sim.active.clock.length()")
    assert ticks(page) == 0 and state(page) == "idle"
    page.click("[data-sim-end]")
    assert state(page) == "done" and ticks(page) == length


# --- (b) the transport bar ------------------------------------------------------------

@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_the_scrubber_spans_the_run_and_moving_it_seeks_paused(sim, archetype):
    page = sim(archetype)
    scrub = page.locator("[data-sim-scrub]")
    assert scrub.is_visible()
    length = page.evaluate("Sim.active.clock.length()")
    assert int(scrub.get_attribute("max")) == length
    page.evaluate("""(v) => { const s = document.querySelector('[data-sim-scrub]');
      s.value = v; s.dispatchEvent(new Event('input', {bubbles: true})); }""", length // 2)
    assert ticks(page) == length // 2
    assert state(page) == "paused"
    assert scrub.get_attribute("aria-valuetext")
    page.click("[data-sim-run]")
    page.wait_for_timeout(400)
    assert int(page.evaluate("document.querySelector('[data-sim-scrub]').value")) > length // 2
    page.click("[data-sim-end]")
    assert int(page.evaluate("document.querySelector('[data-sim-scrub]').value")) == length
    assert page.errors == []


def test_worklist_steps_forward_and_back_one_plan_entry_at_a_time(sim):
    page = sim("worklist")
    page.locator("h1").first.click()
    assert page.inner_text("#stepNo").startswith("0 /")
    page.click("[data-sim-step]")
    assert page.inner_text("#stepNo").startswith("1 /")
    page.click("[data-sim-step]")
    assert page.inner_text("#stepNo").startswith("2 /")
    page.click("[data-sim-back]")
    assert page.inner_text("#stepNo").startswith("1 /")
    page.locator("h1").first.click()
    page.keyboard.press("ArrowLeft")
    assert page.inner_text("#stepNo").startswith("0 /")
    assert state(page) == "idle"
    page.keyboard.press("ArrowRight")
    assert page.inner_text("#stepNo").startswith("1 /")


def test_flow_steps_back_one_model_second(sim):
    page = sim("flow")
    page.evaluate("Sim.active.clock.seek(200)")
    page.click("[data-sim-back]")
    assert ticks(page) == 200 - page.evaluate("Sim.active.clock.backTicks")
    assert page.evaluate("Sim.active.clock.backTicks") > 0


def test_a_page_without_the_new_markup_still_runs(sim):
    """Every feature is optional: a page built before the timeline keeps working."""
    page = sim("flow")
    page.evaluate("""() => { ['[data-sim-scrub]', '[data-sim-back]', '[data-sim-copy-link]',
      '[data-sim-table-toggle]'].forEach(s => document.querySelectorAll(s).forEach(n => n.remove())); }""")
    page.click("[data-sim-end]")
    assert state(page) == "done"
    assert page.errors == []


def test_a_legacy_step_once_model_gets_no_scrubber(open_page):
    """A model that steps outside the clock cannot be replayed, so no dead control is offered."""
    html = """<!doctype html><meta charset=utf-8><main>
      <button data-sim-run data-state="idle">run</button><button data-sim-step>s</button>
      <button data-sim-back>b</button><input type="range" data-sim-scrub></main>
      <script>%s</script><script>
      var n = 0;
      var c = new Sim.Clock({ step: function () { return ++n > 50; }, stepOnce: function () { n += 5; return n > 50; },
        reset: function () { n = 0; } });
      var ctl = new Sim.Controls(c);
      </script>""" % ENGINE
    page = open_page(html)
    assert page.evaluate("document.querySelectorAll('[data-sim-scrub],[data-sim-back]').length") == 0
    assert page.evaluate("document.querySelectorAll('[data-sim-step]').length") == 1
    assert page.errors == []


# --- (a) scenario and control values in the hash --------------------------------------

def test_a_changed_param_goes_into_the_hash_and_a_default_leaves_it(sim):
    page = sim("flow")
    assert page.evaluate("location.hash") == ""
    set_range(page, "approach", 1)
    assert page.evaluate("location.hash") == "#approach=1"
    assert page.evaluate("Sim.active.params.get('approach')") == 1
    page.click("[data-sim-speed] button[data-speed='2']")
    assert page.evaluate("location.hash") == "#approach=1&speed=2"
    set_range(page, "approach", 3)
    page.click("[data-sim-speed] button[data-speed='1']")
    assert page.evaluate("location.hash") == ""


def test_a_changed_param_changes_the_run(sim):
    page = sim("flow")
    base = page.evaluate("Sim.active.clock.length()")
    set_range(page, "approach", 1)
    assert state(page) == "idle" and ticks(page) == 0
    assert page.evaluate("Sim.active.clock.length()") != base


def test_the_hash_is_restored_on_load(sim):
    page = sim("flow", hash="approach=2&speed=0.5")
    assert page.evaluate("Sim.active.params.get('approach')") == 2
    assert page.evaluate("document.querySelector('[data-sim-param=approach]').value") == "2"
    assert page.get_attribute("[data-sim-speed] button[data-speed='0.5']", "aria-pressed") == "true"
    assert page.evaluate("Sim.active.clock.speed") == 0.5


def test_a_position_in_the_hash_opens_paused_there_and_does_not_autostart(sim):
    page = sim("worklist", hash="t=120")
    assert ticks(page) == 120 and state(page) == "paused"
    page.wait_for_timeout(300)
    assert ticks(page) == 120


def test_autostart_runs_an_untouched_page_and_never_a_positioned_one(sim):
    plain = sim("worklist", fake_clock=True)
    plain.clock.run_for(7000)
    assert plain.evaluate("Sim.active.clock.running") is True, "autostart did not fire: the probe measures nothing"
    pinned = sim("worklist", hash="t=120", fake_clock=True)
    pinned.clock.run_for(7000)
    assert pinned.evaluate("Sim.active.clock.running") is False
    assert ticks(pinned) == 120
    touched = sim("worklist", fake_clock=True)
    touched.click("[data-sim-step]")
    touched.click("[data-sim-back]")
    assert ticks(touched) == 0
    touched.clock.run_for(7000)
    assert touched.evaluate("Sim.active.clock.running") is False


def test_reduced_motion_never_autostarts_even_after_scrubbing_back(sim):
    page = sim("flow", reduced=True, fake_clock=True)
    page.evaluate("Sim.active.clock.seek(0)")
    page.clock.run_for(7000)
    assert page.evaluate("Sim.active.clock.running") is False and ticks(page) == 0


def test_an_invalid_hash_value_is_ignored(sim):
    page = sim("worklist", hash="scenario=bogus&speed=9&t=-4")
    assert page.evaluate("Sim.active.params.get('scenario')") == "rework"
    assert page.evaluate("Sim.active.clock.speed") == 1
    assert ticks(page) == 0
    assert page.errors == []


def test_the_scenario_buttons_switch_the_worklist_plan(sim):
    page = sim("worklist", hash="scenario=clean")
    clean_btn = "[data-sim-param=scenario] button[data-value=clean]"
    assert page.get_attribute(clean_btn, "aria-pressed") == "true"
    page.click("[data-sim-end]")
    clean = page.inner_text("#stepNo")
    page.click("[data-sim-param=scenario] button[data-value=rework]")
    assert page.evaluate("location.hash") == ""
    assert state(page) == "idle"
    page.click("[data-sim-end]")
    assert page.inner_text("#stepNo") != clean


def test_copy_link_carries_params_speed_and_position(sim):
    page = sim("flow", hash="approach=2")
    page.evaluate("Sim.active.clock.seek(150)")
    link = page.evaluate("Sim.link()")
    assert link.endswith("#approach=2&t=150")
    page.click("[data-sim-copy-link]")
    page.wait_for_function("['copied','manual'].includes(document.querySelector('[data-sim-copy-link]').getAttribute('data-state'))")
    if page.get_attribute("[data-sim-copy-link]", "data-state") == "manual":
        assert page.evaluate("document.querySelector('[data-sim-link]').value") == link
        assert page.locator("[data-sim-link]").is_visible()


# --- (c) stage:theme and stage:lang, child side ---------------------------------------

@pytest.fixture
def framed(browser, tmp_path):
    d = tmp_path / "framed"
    d.mkdir()
    (d / "child.html").write_text(assemble(tmp_path, "flow").read_text("utf-8"), encoding="utf-8")
    (d / "index.html").write_text((STAGE_FIXTURES / "parent.html").read_text("utf-8"), encoding="utf-8")
    ctx = browser.new_context(viewport={"width": 1000, "height": 800})
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto((d / "index.html").as_uri())
    page.wait_for_function("window.received && window.received.some(m => m && m.type === 'stage:ready')")
    yield page
    ctx.close()


def test_stage_theme_from_the_parent_is_followed_and_not_stored(framed):
    frame = framed.frame(name="child")
    framed.evaluate("window.toChild({type: 'stage:theme', theme: 'dark'})")
    frame.wait_for_function("document.documentElement.classList.contains('dark')")
    assert frame.evaluate("document.querySelector('#themeToggle [data-en]').textContent") == "Light"
    assert frame.evaluate("(() => { try { return localStorage.getItem('html-canvas-theme'); } catch (e) { return null; } })()") is None
    framed.evaluate("window.viaForeign({type: 'stage:theme', theme: 'light'})")
    framed.wait_for_timeout(200)
    assert frame.evaluate("document.documentElement.classList.contains('dark')") is True
    framed.evaluate("window.toChild({type: 'stage:theme', theme: 'light'})")
    frame.wait_for_function("!document.documentElement.classList.contains('dark')")
    framed.evaluate("window.toChild({type: 'stage:theme', theme: 'neon'})")
    framed.wait_for_timeout(150)
    assert frame.evaluate("document.documentElement.classList.contains('dark')") is False


def test_stage_lang_from_the_parent_is_followed_and_not_stored(framed):
    frame = framed.frame(name="child")
    framed.evaluate("window.toChild({type: 'stage:lang', lang: 'de'})")
    frame.wait_for_function("document.documentElement.getAttribute('data-lang') === 'de'")
    assert frame.evaluate("document.documentElement.getAttribute('lang')") == "de"
    assert frame.evaluate("document.getElementById('langToggle').textContent") == "EN"
    assert frame.evaluate("document.querySelector('[data-sim-speed]').getAttribute('aria-label')") == "Tempo"
    assert frame.evaluate("(() => { try { return localStorage.getItem('html-canvas-lang'); } catch (e) { return null; } })()") is None
    framed.evaluate("window.viaForeign({type: 'stage:lang', lang: 'en'})")
    framed.wait_for_timeout(200)
    assert frame.evaluate("document.documentElement.getAttribute('data-lang')") == "de"
    assert framed.errors == []


# --- (d) reduced motion ---------------------------------------------------------------

@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_reduced_motion_arrives_finished_and_never_starts_by_itself(sim, archetype):
    page = sim(archetype, reduced=True)
    length = page.evaluate("Sim.active.clock.length()")
    assert ticks(page) == length and state(page) == "done"
    assert page.locator("[data-sim-reduced-note]").is_visible()
    page.evaluate("(n) => Sim.active.clock.seek(n)", length // 3)
    assert state(page) == "paused"
    page.wait_for_timeout(500)
    assert ticks(page) == length // 3 and page.evaluate("Sim.active.clock.running") is False
    assert page.errors == []


def test_reduced_motion_with_a_position_opens_there_without_the_end_note(sim):
    page = sim("flow", hash="t=90", reduced=True)
    assert ticks(page) == 90 and state(page) == "paused"
    assert not page.locator("[data-sim-reduced-note]").is_visible()


# --- (e) the state as a table ---------------------------------------------------------

@pytest.mark.parametrize("archetype,rows", [("flow", 6), ("worklist", 10)])
def test_show_as_table_reveals_the_state_and_follows_the_run(sim, archetype, rows):
    page = sim(archetype)
    btn = page.locator("[data-sim-table-toggle]")
    table_id = btn.get_attribute("aria-controls")
    assert btn.get_attribute("aria-expanded") == "false"
    assert not page.locator("#" + table_id).is_visible()
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    assert page.locator("#" + table_id).is_visible()
    body = page.locator("#%s tbody tr" % table_id)
    assert body.count() == rows
    before = page.inner_text("#" + table_id)
    page.click("[data-sim-end]")
    after = page.inner_text("#" + table_id)
    assert before != after
    # no cell shows both languages
    both = page.evaluate("""() => [...document.querySelectorAll('[data-de]')].filter(de => {
      const en = de.nextElementSibling;
      return en && en.hasAttribute('data-en') && getComputedStyle(de).display !== 'none'
        && getComputedStyle(en).display !== 'none'; }).length""")
    assert both == 0
    btn.click()
    assert not page.locator("#" + table_id).is_visible()
    assert page.errors == []


# --- engine-owned randomness ----------------------------------------------------------

def test_clock_owned_rng_is_reseeded_on_reset_and_restored_on_seek(open_page):
    html = """<!doctype html><meta charset=utf-8><main></main><script>%s</script><script>
      var draws, c = new Sim.Clock({ seed: 7, tick: 10,
        step: function () { draws.push(c.random.int(0, 1000)); return draws.length >= 300; },
        reset: function () { draws = []; },
        snapshot: function () { return draws.slice(); },
        restore: function (s) { draws = s.slice(); } });
      draws = [];
      </script>""" % ENGINE
    page = open_page(html)
    first = page.evaluate("c.runToEnd(), draws.slice()")
    second = page.evaluate("c.reset(), c.runToEnd(), draws.slice()")
    assert first == second and len(first) == 300
    assert page.evaluate("c.ring().length") > 0
    # ticks between snapshots: the draws after a restore come from the restored generator
    for n in (120, 290, 61):
        assert page.evaluate("(n) => (c.seek(n), draws.slice())", n) == first[:n], n


# --- docs and generator ---------------------------------------------------------------

def test_reference_documents_the_wave_4_engine_surface():
    text = (SKILL / "references" / "simulation.md").read_text("utf-8")
    for needle in ("## Timeline", "data-sim-scrub", "Sim.params", "Sim.link", "stage:theme",
                   "stage:lang", "data-sim-table-toggle", "snapshot", "tick", "seek("):
        assert needle in text, needle


@pytest.mark.parametrize("archetype", ARCHETYPES)
def test_generator_checks_the_transport_bar(archetype, tmp_path):
    text = assemble(tmp_path, archetype).read_text("utf-8")
    for needle in ("data-sim-scrub", "data-sim-back", "data-sim-copy-link", "data-sim-table-toggle", "Sim.params("):
        assert needle in text, needle


# --- review wave 4: the end of a run, and hostile hash names ---------------------------

END_MODEL = """<!doctype html><meta charset=utf-8><main>
  <button data-sim-run></button><button data-sim-step></button><button data-sim-back></button>
  <div data-sim-timeline><input type=range data-sim-scrub><span data-sim-scrub-time></span></div>
  <select data-sim-param="cap"><option>1</option><option>2</option></select></main>
  <script>%s</script><script>
  window.__err = null;
  try {
    var P = Sim.params({ cap: { value: 1, min: 1, max: 2 } });
    var n = 0;
    var clock = new Sim.Clock({ snapEvery: 25, step: function () { n++; return n >= 100; },
      render: function () {}, reset: function () { n = 0; },
      snapshot: function () { return n; }, restore: function (s) { n = s; } });
    P.bind(clock); Sim.Controls(clock); Sim.boot(clock, {});
  } catch (e) { window.__err = String(e); }
  </script>""" % ENGINE


@pytest.mark.parametrize("how", ["seek", "scrub"])
def test_a_seek_to_the_end_is_done_and_play_never_steps_past_it(open_page, how):
    page = open_page(END_MODEL)
    assert page.evaluate("clock.length()") == 100
    if how == "seek":
        page.evaluate("clock.seek(100)")
    else:
        page.evaluate("var r = document.querySelector('[data-sim-scrub]'); r.value = r.max;"
                      " r.dispatchEvent(new Event('input'))")
    assert page.evaluate("[clock.ticks, clock.finished, clock.state]") == [100, True, "done"]
    page.evaluate("clock.start()")
    page.wait_for_timeout(200)
    assert page.evaluate("[clock.ticks, n]") == [100, 100], "Play stepped a finished model past its end"
    assert page.errors == []


@pytest.mark.parametrize("hash_", ["#t=100", "#t=9999"])
def test_a_link_to_the_end_opens_done(open_page, hash_):
    page = open_page(END_MODEL)
    page.evaluate("(h) => { location.hash = h; location.reload(); }", hash_)
    page.wait_for_function("window.clock && clock.ticks > 0")
    assert page.evaluate("[window.__err, clock.ticks, clock.finished, clock.state]") == [None, 100, True, "done"]


@pytest.mark.parametrize("name", ["hasOwnProperty", "constructor", "__proto__", "toString"])
def test_a_hash_named_like_an_object_builtin_breaks_nothing(open_page, name):
    page = open_page(END_MODEL)
    page.evaluate("(h) => { location.hash = h; location.reload(); }", "#%s=1&cap=2" % name)
    page.wait_for_function("window.clock !== undefined || window.__err !== null")
    assert page.evaluate("window.__err") is None
    assert page.evaluate("P.get('cap')") == 2
    assert page.errors == []


@pytest.mark.parametrize("lang,name", [("en", "Review"), ("de", "Prüfung")])
def test_flow_names_every_station(sim, lang, name):
    """TXT carried `review` twice: the verdict labels overwrote the station name, and the
    gate station drew no title."""
    page = sim("flow", lang=lang)
    titles = page.evaluate("""() => [...document.querySelectorAll('.sim-t-title')]
      .filter(t => t.getClientRects().length).map(t => t.textContent.trim())""")
    assert "" not in titles and any(name in t for t in titles), titles
