"""Brand fidelity of the `design` preset, measured on the rendered deck.

A deck built with the design preset follows the rules a DESIGN.md of the
current shape writes down, whatever a slide's markup asks for: status colours
(success, warning, danger, info) carry state only, never a chapter colour or a
glow; a primary button is the `primary` fill with `on-primary` text in both
modes; code is set in the mono family, also inline, and a code chip sits on the
muted surface, not on the accent tint; no line is heavier than 1px; chrome text
casts no shadow; headings are in the heading colour and keep their distance to
the text below; split panels share one ground; the chapter number of a divider
is a quiet display numeral that does not touch the heading.

The probe is every documented slide type with `{color}` set to a STATUS colour,
the way a deck reaches for green or amber to tell its chapters apart, plus one
slide with the controls the docs teach. Style presets keep their own look, so
the counter-checks run the same probe with a style preset and expect the
decoration back.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import FIXTURES, SKILL, slide_type_snippets

NEW_DECK = SKILL / "scripts" / "new-deck.py"
DESIGN = FIXTURES / "tooling" / "DESIGN.md"

EXTRA = """
<section class="slide slide--content" id="probe-controls">
  <div class="slide__inner">
    <div>
      <p class="slide__label reveal" style="color:var(--amber);">Controls</p>
      <h2 class="slide__heading reveal">Buttons and inline code</h2>
      <p class="slide__body reveal">Body text with <code>data-deck="next"</code> inline.</p>
      <div class="slide__actions reveal">
        <button type="button" class="slide__btn slide__btn--primary" data-deck="help">Open the help</button>
        <button type="button" class="slide__btn" data-deck="track:short">short</button>
        <button type="button" class="slide__btn" data-deck="track:full">full</button>
      </div>
    </div>
  </div>
</section>
<section class="slide slide--table" id="probe-table">
  <h2 class="slide__heading">Table with code</h2>
  <div class="table-wrap"><div class="table-scroll"><table class="data-table">
    <thead><tr><th>Class</th></tr></thead>
    <tbody><tr><td><code>slide--table</code></td></tr><tr><td>row</td></tr></tbody>
  </table></div></div>
</section>
"""


def build(tmp_path: Path, *extra: str, color: str = "green") -> Path:
    shutil.copyfile(DESIGN, tmp_path / "DESIGN.md")
    frag = tmp_path / "probe.html"
    slides = "\n".join(h.replace("{color}", color) for _, h in slide_type_snippets())
    frag.write_text(slides + EXTRA, encoding="utf-8")
    out = tmp_path / ("deck-%s.html" % ("-".join(a.strip("-") for a in extra) or "design"))
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Fidelity probe", "--slides", str(frag),
                    "--out", str(out), "--force", "--deck-attr", "data-tracks-cycle=short full",
                    "--deck-attr", "data-tracks-default=full", *extra], check=True, capture_output=True)
    return out


def set_theme(page, theme: str) -> None:
    page.evaluate("""(t) => { const r = document.documentElement;
      r.classList.remove('theme-light', 'theme-dark'); r.classList.add('theme-' + t); }""", theme)
    page.wait_for_timeout(350)   # background-color fades over 200ms, the text colour does not


# Resolves a custom property to the computed colour string a real element reports.
RESOLVE = """(name) => { const p = document.createElement('i');
  p.style.color = 'var(--' + name + ')'; document.body.appendChild(p);
  const c = getComputedStyle(p).color; p.remove(); return c; }"""


def var_colour(page, name: str) -> str:
    return page.evaluate(RESOLVE, name)


def style_of(page, sel: str) -> dict:
    return page.evaluate("""(s) => { const e = document.querySelector(s);
      if (!e) return null; const cs = getComputedStyle(e);
      return {bg: cs.backgroundColor, color: cs.color, font: cs.fontFamily, weight: parseInt(cs.fontWeight, 10),
              shadow: cs.textShadow, align: cs.textAlign, image: cs.backgroundImage}; }""", sel)


@pytest.fixture
def deck(open_html, page, tmp_path):
    open_html(build(tmp_path).read_text("utf-8"))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


@pytest.fixture
def style_deck(open_html, page, tmp_path):
    open_html(build(tmp_path, "--preset", "swiss-modern").read_text("utf-8"))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


THEMES = ("light", "dark")


# --- buttons ----------------------------------------------------------------------------

@pytest.mark.parametrize("theme", THEMES)
def test_primary_button_is_the_primary_fill_with_on_primary_text(deck, theme):
    set_theme(deck, theme)
    b = style_of(deck, ".slide__btn--primary")
    assert b["bg"] == var_colour(deck, "primary"), b
    assert b["color"] == var_colour(deck, "on-primary"), b
    assert b["bg"] != var_colour(deck, "accent"), "the text accent is not the button fill"


def test_secondary_button_is_a_surface_with_a_line(deck):
    b = style_of(deck, ".slide__btn:not(.slide__btn--primary)")
    assert b["bg"] in (var_colour(deck, "surface"), var_colour(deck, "bg")), b
    assert b["color"] == var_colour(deck, "text"), b


def test_track_buttons_mark_the_active_track(deck):
    assert deck.get_attribute('[data-deck="track:full"]', "aria-pressed") == "true"
    assert deck.get_attribute('[data-deck="track:short"]', "aria-pressed") == "false"
    # inactive slides are inert, so the buttons are used on their own slide
    deck.evaluate("() => SlideDeck.goTo(SlideDeck.slides().findIndex(s => s.id === 'probe-controls'))")
    deck.wait_for_function("() => !document.getElementById('probe-controls').inert")
    deck.click('[data-deck="track:short"]')
    deck.wait_for_function("() => document.querySelector('[data-deck=\"track:short\"]').getAttribute('aria-pressed') === 'true'")
    assert deck.get_attribute('[data-deck="track:full"]', "aria-pressed") == "false"


# --- code -------------------------------------------------------------------------------

def mono_family(page) -> str:
    return page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--font-mono').trim()")


@pytest.mark.parametrize("sel", [".slide__body code", ".data-table code", ".cheat-card__item code",
                                 ".pipeline__file", ".slide__code-block code", ".slide__code-block pre"])
def test_code_is_set_in_the_mono_family(deck, sel):
    fam = style_of(deck, sel)["font"]
    first = mono_family(deck).split(",")[0].strip().strip("'\"")
    assert first and fam.split(",")[0].strip().strip("'\"") == first, (sel, fam, first)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("sel", [".data-table code", ".cheat-card__item code", ".pipeline__file"])
def test_code_chips_sit_on_the_muted_surface(deck, sel, theme):
    set_theme(deck, theme)
    s = style_of(deck, sel)
    assert s["bg"] == var_colour(deck, "code-bg"), (sel, s)
    assert s["bg"] != var_colour(deck, "accent-dim"), (sel, s)


def test_code_filename_tab_is_no_solid_accent_fill(deck):
    s = style_of(deck, ".slide__code-filename")
    assert s["bg"] != var_colour(deck, "accent"), s
    assert s["bg"] in (var_colour(deck, "code-bg"), var_colour(deck, "surface2"), var_colour(deck, "surface")), s


# --- colour carries state only ----------------------------------------------------------

STATUS = ("green", "red", "amber", "cyan")

COLOURS_IN_USE = """() => { const out = [];
  document.querySelectorAll('.deck *').forEach(e => {
    const cs = getComputedStyle(e), st = getComputedStyle(e, '::before');
    out.push({tag: e.tagName.toLowerCase() + '.' + (e.className && e.className.baseVal === undefined ? e.className : ''),
              color: cs.color, bg: cs.backgroundColor, image: cs.backgroundImage + ' ' + st.backgroundImage,
              borders: [cs.borderTopColor, cs.borderRightColor, cs.borderBottomColor, cs.borderLeftColor]});
  });
  document.querySelectorAll('.slide').forEach(s => out.push({tag: 'slide#' + s.id, color: '', bg: getComputedStyle(s).backgroundColor,
    image: getComputedStyle(s).backgroundImage, borders: []}));
  return out; }"""


def status_users(page) -> list:
    """Elements whose colours change when the status variables change: they draw with one."""
    before = page.evaluate(COLOURS_IN_USE)
    page.evaluate("""(names) => { const r = document.documentElement.style;
      names.forEach((n, i) => { r.setProperty('--' + n, 'rgb(' + (250 - i) + ', 0, 250)');
                                r.setProperty('--' + n + '-dim', 'rgb(0, ' + (250 - i) + ', 250)'); }); }""", list(STATUS))
    after = page.evaluate(COLOURS_IN_USE)
    page.evaluate("(names) => names.forEach(n => { document.documentElement.style.removeProperty('--' + n); "
                  "document.documentElement.style.removeProperty('--' + n + '-dim'); })", list(STATUS))
    return [b["tag"] for b, a in zip(before, after) if a != b]


@pytest.mark.parametrize("theme", THEMES)
def test_no_status_colour_decorates_anything(deck, theme):
    set_theme(deck, theme)
    assert status_users(deck) == []


def test_style_preset_draws_with_status_colours(style_deck):
    """Counter-check for the probe itself: the snippets do reach for status colours."""
    assert status_users(style_deck)


def test_style_preset_keeps_its_chapter_colours(style_deck):
    """Counter-check: the neutralising is the design preset's, a style preset keeps its look."""
    head = style_of(style_deck, ".slide--divider .slide__heading")
    assert head["color"] == var_colour(style_deck, "green")


@pytest.mark.parametrize("theme", THEMES)
def test_headings_take_the_heading_colour(deck, theme):
    set_theme(deck, theme)
    want = var_colour(deck, "primary" if theme == "light" else "text")
    for sel in (".slide--title .slide__display", ".slide--divider .slide__heading", "#probe-controls .slide__heading"):
        assert style_of(deck, sel)["color"] == want, sel
    assert style_of(deck, "#probe-controls .slide__label")["color"] == var_colour(deck, "accent")


# --- lines and shadows ------------------------------------------------------------------

HEAVY_LINES = """() => { const out = [];
  document.querySelectorAll('.deck *, .deck-notes, .deck-progress ~ *').forEach(e => {
    const cs = getComputedStyle(e);
    const w = ['Top', 'Right', 'Bottom', 'Left'].map(s => cs['border' + s + 'Style'] === 'none' ? 0 : parseFloat(cs['border' + s + 'Width']));
    if (Math.max(...w) > 1.01) out.push(e.tagName.toLowerCase() + '.' + e.className + ' ' + w.join('/'));
  });
  return out; }"""


def test_no_line_is_heavier_than_1px(deck):
    assert deck.evaluate(HEAVY_LINES) == []


def test_style_preset_keeps_its_accent_bars(style_deck):
    assert style_deck.evaluate(HEAVY_LINES), "swiss-modern draws 3px accent bars, the counter-check must see them"


def test_chrome_casts_no_text_shadow(deck):
    for sel in (".deck-counter", ".deck-hints", ".deck-track"):
        s = style_of(deck, sel)
        assert s is not None and s["shadow"] == "none", (sel, s)


def test_hint_bar_matches_the_other_chrome_labels(deck):
    hint, counter = style_of(deck, ".deck-hints"), style_of(deck, ".deck-counter")
    size = deck.evaluate("""() => [...document.querySelectorAll('.deck-hints, .deck-counter')].map(e => getComputedStyle(e).fontSize)""")
    assert size[0] == size[1], size
    assert hint["color"] == counter["color"]


def test_no_dotted_texture(deck):
    for sel in (".slide--title", ".slide--with-grid:not(.slide--title)"):
        img = deck.evaluate("(s) => getComputedStyle(document.querySelector(s), '::before').backgroundImage", sel)
        assert img == "none", (sel, img)


def test_title_is_left_aligned(deck):
    assert style_of(deck, ".slide--title")["align"] in ("left", "start")


# --- spacing and composition ------------------------------------------------------------

def gap_below_heading(page, slide_sel: str) -> float:
    return page.evaluate("""(s) => { const h = document.querySelector(s + ' .slide__heading');
      const n = h.nextElementSibling; const a = n.tagName === 'UL' ? n.firstElementChild : n;
      const r = document.createRange(); r.selectNodeContents(a);
      return r.getBoundingClientRect().top - h.getBoundingClientRect().bottom; }""", slide_sel)


@pytest.mark.parametrize("slide", ["#probe-controls", ".slide--content:not(#probe-controls)"])
def test_heading_keeps_its_distance_to_the_text_below(deck, slide):
    deck.evaluate("(s) => document.querySelector(s).scrollIntoView()", slide)
    gap = gap_below_heading(deck, slide)
    assert 12 <= gap <= 48, gap


@pytest.mark.parametrize("theme", THEMES)
def test_split_panels_share_one_ground_and_one_top(deck, theme):
    set_theme(deck, theme)
    s = deck.evaluate("""() => { const ps = [...document.querySelectorAll('.slide--split .slide__panel')];
      document.querySelector('.slide--split').scrollIntoView();
      return ps.map(p => ({bg: getComputedStyle(p).backgroundColor,
                           top: p.firstElementChild.getBoundingClientRect().top})); }""")
    assert s[0]["bg"] == s[1]["bg"], s
    assert s[0]["bg"] != var_colour(deck, "surface2"), "the muted surface is never a ground"
    assert abs(s[0]["top"] - s[1]["top"]) < 2, s


@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 720}, {"width": 600, "height": 900}],
                         ids=["1280", "600"])
def test_chapter_number_is_a_quiet_display_numeral_clear_of_the_heading(open_html, page, tmp_path, viewport):
    open_html(build(tmp_path).read_text("utf-8"), viewport=viewport)
    page.wait_for_selector(".deck-counter", state="attached")
    page.evaluate("() => document.querySelector('.slide--divider').scrollIntoView()")
    n = page.evaluate("""() => { const s = document.querySelector('.slide--divider');
      const num = s.querySelector('.slide__number'), cs = getComputedStyle(num);
      const a = num.getBoundingClientRect(), r = document.createRange();
      r.selectNodeContents(s.querySelector('.slide__heading'));
      const b = r.getBoundingClientRect(), r2 = document.createRange();
      r2.selectNodeContents(s.querySelector('.slide__subtitle'));
      const c = r2.getBoundingClientRect();
      const meet = (x, y) => !(x.right <= y.left || y.right <= x.left || x.bottom <= y.top || y.bottom <= x.top);
      return {weight: parseInt(cs.fontWeight, 10), font: cs.fontFamily,
              display: getComputedStyle(document.documentElement).getPropertyValue('--font-display'),
              touches: meet(a, b) || meet(a, c)}; }""")
    assert n["weight"] > 300, n
    assert n["font"].split(",")[0].strip("'\" ") == n["display"].split(",")[0].strip("'\" "), n
    assert not n["touches"], n
