"""Keynote forms: optional markup that lets a deck look like a corporate keynote.

A photo half panel (`slide--media`), gradient numbers (`slide__stat`,
`metrics--gradient`), a glowing arc under a heading (`slide__arc`), a quote slide,
a result card for decision slides, a numbered list with boxed numbers and a tinted
card grid. All of it is opt-in by class: a deck that uses none of the new classes
renders exactly as before, which the comparison below proves by rendering the old
slide types with and without the keynote region of the engine.

Every colour comes from deck tokens, light and dark both pass the contrast gate,
and print, forced colours and narrow screens each get their own answer.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

from engine_testlib import deck, open_deck
from slides_testlib import ASSETS, ENGINE_CSS_RE, FIXTURES, SKILL, load_script, slide_type_snippets
from test_new_deck import brand_dir, plain_dir, region, run  # noqa: F401  (fixtures)

ENGINE = ASSETS / "slide-engine.css"
CANVAS = SKILL.parent / "html-canvas"
GATE = CANVAS / "scripts" / "verify-page.py"
TOOLING = FIXTURES / "tooling"
REGION_RE = re.compile(r"/\* =+ KEYNOTE FORMS \(opt-in\) =+ \*/.*?/\* =+ END KEYNOTE FORMS =+ \*/\n?", re.S)
# Whole class names: a keynote rule has to need one of these outside any :not().
KEYNOTE_CLASSES = {"slide--media", "slide__media", "slide__stats", "slide__stat", "slide__stat-value",
                   "slide__stat-label", "metrics--gradient", "slide__arc", "slide__arc--center", "slide--quote",
                   "slide__quote", "slide__quote-source", "slide__result", "slide__result-label",
                   "slide__result-value", "slide__numbered", "slide__numbered--2col", "slide__numbered--3col",
                   "slide__numbered--stacked", "slide__arc--half", "slide__arc--quarter", "cards--tinted"}
OLD_TYPES = 11


def png(rgb: tuple[int, int, int], w: int = 48, h: int = 32) -> str:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


PHOTO = png((90, 70, 140))


def media(side: str | None = None, size: str | None = None, sid: str = "m", src: str | None = PHOTO) -> str:
    attrs = (' data-media="%s"' % side if side else "") + (' data-media-size="%s"' % size if size else "")
    img = ('<img class="slide__media" src="%s" alt="A team at work">' % src if src
           else '<img class="slide__media" data-image-prompt="A team at a table" data-image-ratio="4:3" alt="A team at work">')
    return ('<section class="slide slide--media" id="%s"%s>%s<div class="slide__content">'
            '<p class="slide__label reveal">Platform</p>'
            '<h2 class="slide__heading reveal">One platform for every invoice channel</h2>'
            '<ul class="slide__bullets"><li class="reveal">Inbound and outbound in one flow</li>'
            '<li class="reveal">Each document traced from receipt to archive</li>'
            '<li class="reveal">Errors reach a person within minutes</li></ul>'
            '</div></section>') % (sid, attrs, img)


STATS = """
<section class="slide" id="stats">
  <p class="slide__label reveal">Results</p>
  <h2 class="slide__heading reveal">What the first quarter delivered</h2>
  <div class="slide__arc" aria-hidden="true"></div>
  <div class="slide__stats reveal">
    <div class="slide__stat"><span class="slide__stat-value">98%</span><span class="slide__stat-label">documents delivered on the first attempt</span></div>
    <div class="slide__stat"><span class="slide__stat-value">4 min</span><span class="slide__stat-label">from receipt to booking</span></div>
    <div class="slide__stat"><span class="slide__stat-value">12</span><span class="slide__stat-label">countries connected</span></div>
  </div>
</section>
"""

KPI = """
<section class="slide" id="kpi">
  <h2 class="slide__heading">Throughput this month</h2>
  <div class="metrics metrics--gradient">
    <div class="metric"><div class="m-label">Documents</div><div class="m-val">18,400</div><div class="m-sub">all channels</div></div>
    <div class="metric"><div class="m-label">Error rate</div><div class="m-val">0.4%</div><div class="m-sub">down from 1.9%</div></div>
  </div>
</section>
"""

QUOTE = """
<section class="slide slide--quote" id="quote">
  <blockquote class="slide__quote reveal">
    <p>We stopped chasing invoices and started reading what they tell us.</p>
    <footer class="slide__quote-source">Head of finance operations</footer>
  </blockquote>
</section>
"""

DECISION = """
<section class="slide slide--content" id="decision">
  <div class="slide__inner">
    <div>
      <p class="slide__label reveal">Decision</p>
      <h2 class="slide__heading reveal">Move the archive to the shared platform</h2>
      <ul class="slide__bullets">
        <li class="reveal">One retention rule for every channel</li>
        <li class="reveal">Search across all documents</li>
      </ul>
    </div>
    <div class="slide__aside reveal">
      <div class="slide__result">
        <p class="slide__result-label">Result today</p>
        <p class="slide__result-value">Approved for the second quarter</p>
        <div class="slide__arc" aria-hidden="true"></div>
        <p class="slide__result-value">Budget within plan</p>
      </div>
    </div>
  </div>
</section>
"""

AGENDA = """
<section class="slide" id="agenda">
  <p class="slide__label reveal">Agenda</p>
  <h2 class="slide__heading reveal">Today</h2>
  <ol class="slide__numbered slide__numbered--2col reveal" id="agenda-list">
    <li><strong>Where we stand</strong><span>Numbers from the first quarter</span></li>
    <li><strong>What we learned</strong><span>Three findings from the rollout</span></li>
    <li><strong>The decision</strong><span>Archive on the shared platform</span></li>
    <li><strong>Next steps</strong></li>
  </ol>
</section>
"""

CARDS = """
<section class="slide" id="cards">
  <h2 class="slide__heading slide__heading--sm reveal">Three channels</h2>
  <div class="cheat-grid cards--tinted" id="tinted">
    <div class="cheat-card reveal"><div class="cheat-card__title">Mail</div><div class="cheat-card__item">Scanned and read</div></div>
    <div class="cheat-card reveal"><div class="cheat-card__title">Portal</div><div class="cheat-card__item">Uploaded by suppliers</div></div>
  </div>
  <div class="cheat-grid" id="plain">
    <div class="cheat-card"><div class="cheat-card__title">Network</div><div class="cheat-card__item">Received as data</div></div>
  </div>
</section>
"""


QUOTE_HEADED = """
<section class="slide slide--quote" id="quote-headed">
  <p class="slide__label reveal">Mandate</p>
  <h2 class="slide__heading reveal">The assignment in one sentence</h2>
  <blockquote class="slide__quote reveal"><p>The goal is to assess the cyber risks of the named areas continuously,
    to rate them and to recommend prioritised measures. This needs access to contacts, documents and systems.</p></blockquote>
  <div class="slide__arc reveal" aria-hidden="true"></div>
  <ul class="slide__bullets"><li class="reveal">Sponsor: the management board</li><li class="reveal">Contractor: the consortium</li></ul>
</section>
"""


def all_forms() -> str:
    return "\n".join([media(sid="m-right"), media("left", "1/3", sid="m-left"), STATS, QUOTE, QUOTE_HEADED, DECISION,
                      AGENDA, CARDS])


def rect(page, sel: str) -> dict:
    return page.evaluate("""(s) => { const r = document.querySelector(s).getBoundingClientRect();
      return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height}; }""", sel)


def text_rects(page, sel: str) -> list[dict]:
    """The rects the text inside `sel` actually occupies."""
    return page.evaluate("""(s) => { const out = [], w = document.createTreeWalker(document.querySelector(s), NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) { if (!n.textContent.trim()) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        for (const r of rg.getClientRects()) out.push({left: r.left, right: r.right, top: r.top, bottom: r.bottom}); }
      return out; }""", sel)


def go(page, sid: str) -> None:
    page.evaluate("(id) => { const s = document.getElementById(id); s.scrollIntoView({behavior: 'instant'}); }", sid)
    page.wait_for_timeout(80)


def meets(a: dict, b: dict) -> bool:
    return not (a["right"] <= b["left"] + 0.5 or b["right"] <= a["left"] + 0.5
                or a["bottom"] <= b["top"] + 0.5 or b["bottom"] <= a["top"] + 0.5)


# --- the engine source ---------------------------------------------------------------------

def engine_css() -> str:
    return ENGINE.read_text("utf-8")


def test_engine_has_no_colour_literal():
    css = re.sub(r"/\*.*?\*/", "", engine_css(), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css)


def test_keynote_rules_sit_in_one_marked_region():
    css = engine_css()
    assert len(REGION_RE.findall(css)) == 1
    body = REGION_RE.search(css).group(0)
    assert "var(--" in body and "color-mix(" in body


def _selectors(css: str) -> list[str]:
    """Every selector of every style rule, at-rule preludes skipped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"([^{};]+)\{", css):
        prelude = m.group(1).strip()
        if not prelude or prelude.startswith("@") or re.fullmatch(r"[\d.%]+|from|to", prelude):
            continue
        out += [s.strip() for s in prelude.split(",")]
    return out


def test_every_keynote_rule_needs_a_keynote_class():
    """A deck without the new classes cannot match a keynote rule."""
    body = REGION_RE.search(engine_css()).group(0)
    sels = _selectors(body)
    assert sels
    loose = [s for s in sels if not required_classes(s) & KEYNOTE_CLASSES]
    assert loose == [], loose


def _strip_not(sel: str) -> str:
    """The selector with every :not(...) argument removed, nested parentheses included."""
    out, i = [], 0
    while i < len(sel):
        if sel.startswith(":not(", i):
            depth, i = 1, i + 5
            while i < len(sel) and depth:
                depth += {"(": 1, ")": -1}.get(sel[i], 0)
                i += 1
            continue
        out.append(sel[i])
        i += 1
    return "".join(out)


def required_classes(sel: str) -> set[str]:
    """Whole class names an element must carry for `sel` to match (outside :not)."""
    return set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", _strip_not(sel)))


@pytest.mark.parametrize("sel,ok", [(".slide--media > .slide__media", True), (".slide__stat-value", True),
                                    (":not(.slide__media) p", False), (".slide__statement", False),
                                    (".slide:not(.slide--quote:not(.x)) p", False), (".cards--tinted > .cheat-card", True)])
def test_the_keynote_class_check_reads_whole_names_outside_not(sel, ok):
    assert bool(required_classes(sel) & KEYNOTE_CLASSES) is ok


SNAPSHOT = """() => { const props = [...getComputedStyle(document.body)].filter(p => !p.startsWith('transition') && !p.startsWith('animation'));
  return [...document.querySelectorAll('html, body, body *')].map(e => {
    const cs = getComputedStyle(e), b = getComputedStyle(e, '::before'), a = getComputedStyle(e, '::after');
    return e.tagName + '.' + (typeof e.className === 'string' ? e.className : '') + ' ' +
      props.map(p => cs.getPropertyValue(p)).join('|') + ' ' + b.content + b.backgroundImage + a.content + a.backgroundImage; }); }"""

STILL = "<style>*,*::before,*::after{transition:none!important;animation:none!important}</style>"


def _with_engine(html: str, css: str) -> str:
    sink = load_script("new-deck.py").CSS_SINK
    m = ENGINE_CSS_RE.search(html)
    start, end = m.group(1), m.group(3)
    return html[:m.start()] + start + "\n" + sink + css + "\n" + end + html[m.end():]


def baseline_engine() -> str:
    """slide-engine.css as origin/main ships it: the engine before the keynote forms."""
    try:
        proc = subprocess.run(["git", "-C", str(SKILL), "show", "origin/main:skills/html-slides/assets/slide-engine.css"],
                              capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        pytest.skip("git not available: %s" % exc)
    if proc.returncode != 0 or "slide-engine" not in proc.stdout:
        pytest.skip("no origin/main engine to compare with: %s" % proc.stderr.strip())
    return proc.stdout


@pytest.mark.parametrize("viewport,media,back", [
    ({"width": 1280, "height": 720}, "screen", False), ({"width": 1920, "height": 1080}, "screen", False),
    ({"width": 2400, "height": 1300}, "screen", False), ({"width": 600, "height": 900}, "screen", False),
    ({"width": 600, "height": 900}, "screen", True), ({"width": 1280, "height": 600}, "screen", False),
    ({"width": 1280, "height": 720}, "print", False)],
    ids=["1280", "1920", "2400", "600", "600-back-link", "short", "print"])
def test_a_deck_without_the_new_classes_renders_as_before(open_html, page, viewport, media, back):
    """The old slide types under the shipped engine and under origin/main's engine: every
    computed style equal, so neither the keynote region nor the :not() additions outside it
    change a deck that does not use the new classes."""
    before = baseline_engine()
    old = [h.replace("{color}", "accent") for _, h in slide_type_snippets()[:OLD_TYPES]]
    html = deck(old, deck_attrs='data-back-href="index.html"' if back else "")
    html = html.replace("</head>", STILL + "</head>", 1)
    snaps = []
    for css in (engine_css(), before):
        open_deck(open_html, _with_engine(html, css), viewport=viewport)
        page.emulate_media(media=media)
        page.wait_for_timeout(100)
        snaps.append(page.evaluate(SNAPSHOT))
        page.emulate_media(media="screen")
    assert len(snaps[0]) == len(snaps[1])
    diff = [a.split(" ", 1)[0] for a, b in zip(*snaps) if a != b]
    assert diff == [], diff[:5]


# --- media split ---------------------------------------------------------------------------

SIZES = [{"width": 1280, "height": 720}, {"width": 1920, "height": 1080}]


@pytest.mark.parametrize("viewport", SIZES, ids=["1280", "1920"])
@pytest.mark.parametrize("side,size,share", [(None, None, 0.4), ("right", "1/2", 0.5), ("left", "1/3", 1 / 3),
                                             ("left", "2/5", 0.4)])
def test_media_fills_its_share_edge_to_edge_beside_the_text(open_html, viewport, side, size, share):
    page = open_deck(open_html, deck([media(side, size)]), viewport=viewport)
    s, img = rect(page, "#m"), rect(page, "#m > .slide__media")
    assert abs(img["top"] - s["top"]) < 1 and abs(img["height"] - s["height"]) < 1, (img, s)
    assert abs(img["width"] - share * s["width"]) < 2, (img["width"], s["width"])
    if side == "left":
        assert abs(img["left"] - s["left"]) < 1
    else:
        assert abs(img["right"] - s["right"]) < 1
    info = page.evaluate("""() => { const c = getComputedStyle(document.querySelector('#m > .slide__media'));
      return {fit: c.objectFit, border: c.borderTopWidth, radius: c.borderTopLeftRadius}; }""")
    assert info == {"fit": "cover", "border": "0px", "radius": "0px"}, info
    texts = text_rects(page, "#m .slide__content")
    assert texts and not any(meets(t, img) for t in texts), "the text runs into the picture"
    gap = min(img["left"] - t["right"] for t in texts) if side != "left" else min(t["left"] - img["right"] for t in texts)
    assert gap >= 32, gap
    assert page.evaluate("() => { const s = document.getElementById('m'); return s.scrollHeight - s.clientHeight; }") <= 1


def test_media_is_never_zoomed_on_a_beamer(open_html):
    page = open_deck(open_html, deck([media()]), viewport={"width": 1920, "height": 1080})
    zoom = page.evaluate("() => [getComputedStyle(document.querySelector('#m > .slide__media')).zoom,"
                         " getComputedStyle(document.querySelector('#m > .slide__content')).zoom]")
    assert zoom == ["1", "1.2"], zoom


@pytest.mark.parametrize("side", [None, "left"])
def test_media_stacks_above_the_text_on_narrow_screens(open_html, side):
    page = open_deck(open_html, deck([media(side)]), viewport={"width": 600, "height": 900})
    s, img = rect(page, "#m"), rect(page, "#m > .slide__media")
    assert abs(img["top"] - s["top"]) < 1 and abs(img["width"] - s["width"]) < 1, (img, s)
    assert 200 <= img["height"] <= 400, img
    texts = text_rects(page, "#m .slide__content")
    assert min(t["top"] for t in texts) >= img["bottom"] + 16
    assert all(t["left"] >= s["left"] + 12 and t["right"] <= s["right"] - 12 for t in texts)
    assert page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0


def test_media_keeps_the_edge_with_a_back_link_on_narrow_screens(open_html):
    page = open_deck(open_html, deck([media()], deck_attrs='data-back-href="index.html"'),
                     viewport={"width": 600, "height": 900})
    assert abs(rect(page, "#m > .slide__media")["top"] - rect(page, "#m")["top"]) < 1


def test_media_stays_side_by_side_in_print(open_html, page):
    open_deck(open_html, deck([media(), media("left", sid="m2")]))
    page.emulate_media(media="print")
    try:
        for sid, left in (("m", False), ("m2", True)):
            s, img = rect(page, "#" + sid), rect(page, "#%s > .slide__media" % sid)
            assert abs(img["height"] - s["height"]) < 1 and abs(img["width"] - 0.4 * s["width"]) < 2, (sid, img, s)
            texts = text_rects(page, "#%s .slide__content" % sid)
            assert not any(meets(t, img) for t in texts), sid
            assert (abs(img["left"] - s["left"]) < 1) if left else (abs(img["right"] - s["right"]) < 1)
    finally:
        page.emulate_media(media="screen")


def test_an_unfilled_image_slot_keeps_the_layout_and_shows_the_surface(open_html):
    page = open_deck(open_html, deck([media(src=None)]))
    s, img = rect(page, "#m"), rect(page, "#m > .slide__media")
    assert abs(img["height"] - s["height"]) < 1 and abs(img["width"] - 0.4 * s["width"]) < 2
    bg = page.evaluate("""() => { const p = document.createElement('i'); p.style.color = 'var(--surface)';
      document.body.appendChild(p); const want = getComputedStyle(p).color; p.remove();
      return [getComputedStyle(document.querySelector('#m > .slide__media')).backgroundColor, want]; }""")
    assert bg[0] == bg[1], bg


# --- gradient numbers, arc, quote, result card, numbered list, tinted cards ------------------

LOOK = """(s) => { const e = document.querySelector(s), c = getComputedStyle(e);
  return {image: c.backgroundImage, clip: c.webkitBackgroundClip || c.backgroundClip, fill: c.webkitTextFillColor,
          color: c.color, display: c.display, size: parseFloat(c.fontSize), weight: parseInt(c.fontWeight, 10),
          bg: c.backgroundColor, radius: parseFloat(c.borderTopLeftRadius), left: c.borderLeftColor,
          leftw: parseFloat(c.borderLeftWidth), cols: c.gridTemplateColumns.split(' ').length,
          filter: c.filter, height: e.getBoundingClientRect().height}; }"""

RESOLVE = """(n) => { const p = document.createElement('i'); p.style.color = 'var(--' + n + ')';
  document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; }"""


def forms_deck(out: Path, *extra) -> Path:
    frag = out.parent / (out.stem + "-slides.html")
    frag.write_text(all_forms() + KPI, encoding="utf-8")
    run("--title", "Keynote", "--slides", frag, "--out", out, "--force", "--blocks", "kpi-row", *extra)
    return out


@pytest.fixture
def style_deck(open_html, page, plain_dir):
    open_html(forms_deck(plain_dir / "style.html", "--preset", "bold-signal").read_text("utf-8"))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


@pytest.fixture
def design_deck(open_html, page, brand_dir):
    open_html(forms_deck(brand_dir / "design.html").read_text("utf-8"))
    page.wait_for_selector(".deck-counter", state="attached")
    return page


@pytest.mark.parametrize("sel", ["#stats .slide__stat-value", "#kpi .m-val"])
def test_numbers_carry_a_text_gradient_with_an_accent_fallback(style_deck, sel):
    look = style_deck.evaluate(LOOK, sel)
    assert "linear-gradient" in look["image"] and look["clip"] == "text", look
    assert look["fill"] in ("rgba(0, 0, 0, 0)", "transparent"), look
    assert look["color"] == style_deck.evaluate(RESOLVE, "accent"), "the colour under the gradient is the accent"


@pytest.mark.parametrize("sel", ["#stats .slide__stat-value", "#kpi .m-val"])
def test_numbers_print_in_a_solid_colour(style_deck, sel):
    style_deck.emulate_media(media="print")
    try:
        look = style_deck.evaluate(LOOK, sel)
        assert look["image"] == "none" and look["fill"] == look["color"], look
        assert look["color"] == style_deck.evaluate(RESOLVE, "accent")
    finally:
        style_deck.emulate_media(media="screen")


def test_plain_metrics_keep_their_heading_colour(open_html, page, plain_dir):
    out = plain_dir / "plain.html"
    frag = plain_dir / "plain-slides.html"
    frag.write_text(KPI.replace(" metrics--gradient", ""), encoding="utf-8")
    run("--title", "Plain", "--slides", frag, "--out", out, "--force", "--blocks", "kpi-row", "--preset", "bold-signal")
    open_html(out.read_text("utf-8"))
    look = page.evaluate(LOOK, "#kpi .m-val")
    assert look["image"] == "none" and look["color"] == page.evaluate(RESOLVE, "heading")


@pytest.mark.parametrize("fixture", ["style_deck", "design_deck"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_both_gradient_ends_read_as_large_text(request, fixture, theme):
    page = request.getfixturevalue(fixture)
    page.evaluate("(t) => { const r = document.documentElement; r.classList.remove('theme-light', 'theme-dark');"
                  " r.classList.add('theme-' + t); }", theme)
    page.wait_for_timeout(300)
    ratios = page.evaluate("""() => {
      const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d');
      const rgb = c => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); return [...cx.getImageData(0, 0, 1, 1).data].slice(0, 3); };
      const lum = c => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
      const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      const out = [];
      for (const s of ['#stats .slide__stat-value', '#kpi .m-val']) {
        const e = document.querySelector(s), stops = getComputedStyle(e).backgroundImage.match(/(?:rgb|color|oklab|oklch|lab)\\([^()]*(?:\\([^()]*\\)[^()]*)*\\)/g);
        let g = e.parentElement; while (getComputedStyle(g).backgroundColor === 'rgba(0, 0, 0, 0)') g = g.parentElement;
        const ground = rgb(getComputedStyle(g).backgroundColor);
        for (const c of stops) out.push(ratio(rgb(c), ground));
      }
      return out; }""")
    assert len(ratios) >= 4 and min(ratios) >= 3, ratios


@pytest.mark.parametrize("fixture", ["style_deck", "design_deck"])
def test_the_arc_shows_in_every_preset(request, fixture):
    page = request.getfixturevalue(fixture)
    look = page.evaluate(LOOK, "#stats .slide__arc")
    assert look["display"] != "none" and look["height"] > 4, look
    assert "drop-shadow" in look["filter"], "the arc glows"


def test_forced_colours_hide_the_arc_and_drop_the_gradient(style_deck):
    style_deck.emulate_media(forced_colors="active")
    try:
        assert style_deck.evaluate(LOOK, "#stats .slide__arc")["display"] == "none"
        assert style_deck.evaluate(LOOK, "#decision .slide__arc")["display"] == "none"
        look = style_deck.evaluate(LOOK, "#stats .slide__stat-value")
        assert look["image"] == "none" and look["fill"] == look["color"], look
    finally:
        style_deck.emulate_media(forced_colors="none")


def test_quote_is_large_light_type_with_an_accent_bar(style_deck):
    look = style_deck.evaluate(LOOK, "#quote .slide__quote p")
    assert look["size"] >= 32 and look["weight"] <= 400, look
    bar = style_deck.evaluate(LOOK, "#quote .slide__quote")
    assert bar["left"] == style_deck.evaluate(RESOLVE, "accent") and bar["leftw"] >= 2, bar


@pytest.mark.parametrize("fixture", ["style_deck", "design_deck"])
def test_a_quote_under_a_heading_is_body_type_below_the_heading_with_room(request, fixture):
    page = request.getfixturevalue(fixture)
    go(page, "quote-headed")
    head = page.evaluate(LOOK, "#quote-headed .slide__heading")
    quote = page.evaluate(LOOK, "#quote-headed .slide__quote p")
    assert 18 <= quote["size"] <= 0.72 * head["size"], (quote["size"], head["size"])
    assert quote["color"] == page.evaluate(RESOLVE, "text-dim"), quote
    gap = rect(page, "#quote-headed .slide__quote")["top"] - rect(page, "#quote-headed .slide__heading")["bottom"]
    assert gap >= 20, gap


def test_quote_bar_is_a_hairline_under_the_design_preset(design_deck):
    bar = design_deck.evaluate(LOOK, "#quote .slide__quote")
    assert bar["leftw"] == 1 and bar["left"] == design_deck.evaluate(RESOLVE, "accent"), bar


@pytest.mark.parametrize("fixture", ["style_deck", "design_deck"])
def test_result_card_is_a_tall_tinted_card(request, fixture):
    page = request.getfixturevalue(fixture)
    go(page, "decision")
    card = page.evaluate(LOOK, "#decision .slide__result")
    assert card["bg"] not in (page.evaluate(RESOLVE, "surface"), page.evaluate(RESOLVE, "bg")), card
    assert card["radius"] >= 12 and card["height"] >= 0.45 * 720, card
    value = page.evaluate(LOOK, "#decision .slide__result-value")
    assert value["size"] >= 22, value
    assert page.evaluate("() => getComputedStyle(document.querySelector('.slide__result-label')).textTransform") == "uppercase"


def test_numbered_list_counts_in_boxed_two_digit_numbers(style_deck):
    nums = style_deck.evaluate("""() => [...document.querySelectorAll('#agenda-list > li')].map(li => {
      const b = getComputedStyle(li, '::before'); return [b.content, parseFloat(b.borderTopWidth), b.borderTopStyle]; })""")
    assert len(nums) == 4 and all(n[0] == "counter(slide-num, decimal-leading-zero)" for n in nums), nums
    assert all(n[1] >= 1 and n[2] == "solid" for n in nums), nums
    assert style_deck.evaluate(LOOK, "#agenda-list")["cols"] == 2


def test_numbered_two_columns_fold_to_one_on_narrow_screens(open_html):
    page = open_deck(open_html, deck([AGENDA]), viewport={"width": 600, "height": 900})
    assert page.evaluate(LOOK, "#agenda-list")["cols"] == 1


@pytest.mark.parametrize("fixture", ["style_deck", "design_deck"])
def test_tinted_cards_differ_from_plain_ones(request, fixture):
    page = request.getfixturevalue(fixture)
    tinted, plain = page.evaluate(LOOK, "#tinted .cheat-card"), page.evaluate(LOOK, "#plain .cheat-card")
    assert tinted["bg"] != plain["bg"] and tinted["radius"] > plain["radius"], (tinted, plain)


# --- the gate ------------------------------------------------------------------------------

def gate(path: Path, *extra) -> dict:
    proc = subprocess.run([sys.executable, str(GATE), str(path), "--json", "--allow-sample", *extra],
                          capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(proc.stdout)


def errors(data: dict) -> list[dict]:
    return [f for p in data["pages"] for f in p["findings"] if f["level"] == "error"]


@pytest.mark.parametrize("preset", ["design", "swiss-modern", "bold-signal"])
def test_a_deck_with_every_keynote_form_passes_the_gate(brand_dir, preset):
    pytest.importorskip("playwright.sync_api")
    out = forms_deck(brand_dir / ("keynote-%s.html" % preset), "--preset", preset)
    data = gate(out, "--deck")
    skipped = [f for f in errors(data) if f["rule"] == "browser-skipped"]
    if skipped:
        pytest.skip(skipped[0]["message"])
    assert errors(data) == [], errors(data)


def test_an_unfilled_media_slot_is_only_a_sample_warning(plain_dir):
    pytest.importorskip("playwright.sync_api")
    frag = plain_dir / "slot.html"
    frag.write_text(media(src=None), encoding="utf-8")
    out = plain_dir / "slot-deck.html"
    run("--title", "Slot", "--slides", frag, "--out", out, "--force", "--preset", "swiss-modern")
    data = gate(out, "--deck")
    assert errors(data) == [], errors(data)
    assert any(f["rule"] == "image-slot" for p in data["pages"] for f in p["findings"])


# --- fonts ---------------------------------------------------------------------------------

@pytest.mark.parametrize("family,weights", [("montserrat", (400, 500, 600, 700)), ("heebo", (300, 400, 500, 600, 700))])
def test_keynote_fonts_ship_with_their_license(family, weights):
    fonts = ASSETS / "fonts"
    for w in weights:
        f = fonts / ("%s-latin-%d-normal.woff2" % (family, w))
        assert f.read_bytes()[:4] == b"wOF2", f.name
    assert "SIL Open Font License" in (fonts / ("LICENSE-%s.txt" % family)).read_text("utf-8")


def test_a_design_md_naming_montserrat_and_heebo_gets_them_embedded(brand_dir):
    design = (TOOLING / "DESIGN.md").read_text("utf-8")
    design = design.replace("    fontFamily: Playfair Display\n    fontSize: 64px\n    fontWeight: 500\n",
                            "    fontFamily: Montserrat\n    fontSize: 64px\n    fontWeight: 700\n", 1)
    design = design.replace("    fontFamily: Inter\n    fontSize: 16px\n    fontWeight: 400\n",
                            "    fontFamily: Heebo\n    fontSize: 16px\n    fontWeight: 300\n", 1)
    assert "Montserrat" in design and "Heebo" in design
    (brand_dir.parent / "DESIGN.md").write_text(design, encoding="utf-8")
    out = brand_dir / "fonts.html"
    proc = run("--title", "Fonts", "--out", out, "--force")
    fonts = region(out.read_text("utf-8"), "deck-fonts")
    for family, w in (("Montserrat", 500), ("Montserrat", 700), ("Heebo", 300), ("Heebo", 400), ("Heebo", 600)):
        assert re.search(r'font-family: "%s"; font-style: normal; font-weight: %d;' % (family, w), fonts), (family, w)
    assert "Montserrat" not in proc.stderr and "Heebo" not in proc.stderr, proc.stderr


# --- the docs ------------------------------------------------------------------------------

def test_every_keynote_form_is_a_documented_slide_type():
    snippets = "\n".join(h for _, h in slide_type_snippets()[OLD_TYPES:])
    for cls in ("slide--media", "slide__media", "data-media-size", "slide__stat-value",
                "slide__arc", "slide--quote", "slide__quote-source", "slide__result-label", "slide__result-value",
                "slide__numbered", "slide__numbered--2col"):
        assert cls in snippets, cls
    doc = (SKILL / "reference" / "slide-types.md").read_text("utf-8")
    assert "cards--tinted" in doc and "metrics--gradient" in doc
