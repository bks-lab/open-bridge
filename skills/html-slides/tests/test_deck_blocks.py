"""new-deck.py --blocks: the html-canvas section blocks inside a deck (reference/blocks.md).

The block CSS comes from html-canvas assets/sections.css, resolved with its
`requires`, behind an alias layer that maps the canvas token names onto the deck
tokens, so one block reads the same under a style preset and the design preset, in
light and dark. Blocks with a behaviour bring their script from sections.js. The
deck records the block list in its region, so a refresh keeps it current.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import FIXTURES, SKILL, load_script
from test_new_deck import brand_dir, plain_dir, region, run  # noqa: F401  (fixtures)

ND = load_script("new-deck.py")
CANVAS = SKILL.parent / "html-canvas"
GATE = CANVAS / "scripts" / "verify-page.py"
SECTIONS_CSS = (CANVAS / "assets" / "sections.css").read_text("utf-8")
SECTIONS_JS = (CANVAS / "assets" / "sections.js").read_text("utf-8")
TOOLING = FIXTURES / "tooling"

CSS = "deck-blocks"
JS = "deck-blocks:js"


def deck(out: Path, *extra) -> str:
    run("--title", "Blocks", "--out", out, "--no-embed-fonts", *extra)
    return out.read_text("utf-8")


def has(html: str, name: str) -> bool:
    return ("<!-- %s:start -->" % name) in html


def css_block(name: str) -> str:
    m = re.search(r"^/\* @block: %s(?: requires: [^*]*)? \*/$\n(.*?)(?=^/\* @block: |\Z)" % re.escape(name),
                  SECTIONS_CSS, re.S | re.M)
    assert m, name
    return m.group(1).strip()


# --- the region ----------------------------------------------------------------------------

def test_blocks_bring_their_css_once_behind_the_alias_layer(plain_dir):
    html = deck(plain_dir / "deck.html", "--blocks", "kpi-row,callout")
    body = region(html, CSS)
    assert "/* blocks: kpi-row, callout */" in body
    assert css_block("kpi-row") in body and css_block("callout") in body
    assert body.count(".metrics{") == 1
    alias = body.index("--ink:")
    assert alias < body.index(".metrics{"), "the alias layer comes before the block rules"
    assert not has(html, JS), "no block here has a script"
    assert html.index("<!-- deck-preset-css:end -->") < html.index("<!-- deck-blocks:start -->"), \
        "block rules come after the engine and the preset"


def test_requires_are_resolved_like_new_page(plain_dir):
    body = region(deck(plain_dir / "deck.html", "--blocks", "decision-page"), CSS)
    for dep in ("table", "matrix", "callout", "doc-header"):
        assert css_block(dep) in body, dep


def test_the_alias_layer_maps_every_canvas_token_a_block_reads(plain_dir):
    """Every var() without a fallback a deck block reads is a deck token, an alias, or a block's own."""
    html = deck(plain_dir / "deck.html", "--blocks", "all")
    body = region(html, CSS)
    read = set(re.findall(r"var\(--([a-z0-9-]+)\)", body))
    defined = set(re.findall(r"--([a-z0-9-]+)\s*:", html))
    missing = sorted(v for v in read - defined if v not in {"d", "motion-i", "motion-len"})
    assert not missing, missing


def test_alias_layer_holds_no_colour_literal(plain_dir):
    body = region(deck(plain_dir / "deck.html", "--blocks", "all"), CSS)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", body)


def test_design_preset_keeps_its_own_heading_colour(brand_dir):
    html = deck(brand_dir / "deck.html", "--blocks", "kpi-row")
    body = region(html, CSS)
    assert "--heading:" not in body, "the design preset sets --heading; the alias must not override it"
    style = deck(brand_dir / "style.html", "--blocks", "kpi-row", "--preset", "swiss-modern")
    assert "--heading:" in region(style, CSS) and "--on-primary:" in region(style, CSS)


def test_scripted_blocks_bring_their_script(plain_dir):
    html = deck(plain_dir / "deck.html", "--blocks", "glossary,alt-table")
    js = region(html, JS)
    assert "/* @block: glossary */" in js and "/* @block: alt-table */" in js
    assert "/* @block: toc */" not in js
    assert html.index("<!-- slide-engine:js:end -->") < html.index("<!-- deck-blocks:js:start -->")


def test_sample_slides_are_marked_and_wrap_one_block_each(plain_dir):
    html = deck(plain_dir / "deck.html", "--blocks", "kpi-row,timeline")
    slides = re.findall(r'<section class="slide[^"]*"[^>]*>', html)
    assert len(slides) == 3, "the title slide, then one slide per block"
    assert html.count("data-sample") == 2
    assert 'id="blk-kpi-row"' in html and 'id="blk-timeline"' in html


def test_own_slides_get_the_css_without_sample_slides(plain_dir):
    html = deck(plain_dir / "deck.html", "--blocks", "kpi-row", "--slides", TOOLING / "slides.html")
    assert "data-sample" not in html and ".metrics{" in region(html, CSS)


# --- what a deck refuses ---------------------------------------------------------------------

@pytest.mark.parametrize("name", ["toc", "print", "section-nav", "index", "hero", "section-opener"])
def test_blocks_a_deck_has_its_own_answer_for_are_refused(plain_dir, name):
    proc = run("--title", "x", "--out", plain_dir / "deck.html", "--blocks", name, check=False)
    assert proc.returncode != 0
    assert name in proc.stderr and "deck" in proc.stderr, proc.stderr
    assert not (plain_dir / "deck.html").exists()


def test_all_omits_them_and_says_so(plain_dir):
    out = plain_dir / "deck.html"
    proc = run("--title", "x", "--out", out, "--no-embed-fonts", "--blocks", "all")
    line = re.search(r"/\* blocks: .*? \*/", region(out.read_text("utf-8"), CSS)).group(0)[:-3]
    for name in ("toc", "print", "section-nav", "index"):
        assert name not in line.split(": ", 1)[1].split(", "), line
        assert name in proc.stderr
    assert "kpi-row" in line and "glossary" in line


def test_unknown_block_is_refused(plain_dir):
    proc = run("--title", "x", "--out", plain_dir / "deck.html", "--blocks", "kpi-row,nope", check=False)
    assert proc.returncode != 0 and "nope" in proc.stderr


def test_the_canvas_animation_layer_never_reaches_a_deck(plain_dir):
    """Its .reveal would fight the engine's; the deck's motion module carries the message flow."""
    html = deck(plain_dir / "deck.html", "--blocks", "message-flow")
    assert "@block: animations" not in html and "hc-msg-fwd" not in html
    assert has(html, "deck-module:motion"), "message-flow brings the motion module"


# --- refresh ---------------------------------------------------------------------------------

def test_refresh_keeps_the_block_set_and_is_idempotent(plain_dir):
    out = plain_dir / "deck.html"
    html = deck(out, "--blocks", "glossary,kpi-row")
    body = region(html, CSS)
    out.write_text(html.replace(body, body.replace(".metrics{", ".metrics-stale{"), 1), encoding="utf-8")
    run("--refresh", out)
    once = out.read_text("utf-8")
    assert region(once, CSS) == body
    run("--refresh", out)
    assert out.read_text("utf-8") == once


def test_refresh_with_blocks_swaps_the_set(plain_dir):
    out = plain_dir / "deck.html"
    html = deck(out, "--blocks", "kpi-row")
    run("--refresh", out, "--blocks", "callout,glossary")
    new = out.read_text("utf-8")
    assert "/* blocks: callout, glossary */" in region(new, CSS)
    assert ".metrics{" not in region(new, CSS)
    assert "/* @block: glossary */" in region(new, JS), "the script region is added when the set needs it"
    assert new.count("data-sample") == html.count("data-sample"), "the slides are never touched"
    run("--refresh", out, "--blocks", "kpi-row")
    assert region(out.read_text("utf-8"), JS).strip() == ""


def test_refresh_with_blocks_needs_the_region(plain_dir):
    out = plain_dir / "deck.html"
    deck(out)
    proc = run("--refresh", out, "--blocks", "kpi-row", check=False)
    assert proc.returncode != 0 and "--blocks" in proc.stderr


def test_list_shows_which_blocks_a_deck_takes():
    out = run("--list").stdout
    assert re.search(r"^\s+kpi-row\b", out, re.M)
    assert re.search(r"^\s+print\b.*not in a deck", out, re.M)


# --- in the browser --------------------------------------------------------------------------

def gate(path: Path, *extra) -> dict:
    proc = subprocess.run([sys.executable, str(GATE), str(path), "--json", "--allow-sample", *extra],
                          capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(proc.stdout)


def errors(data: dict) -> list[dict]:
    return [f for p in data["pages"] for f in p["findings"] if f["level"] == "error"]


@pytest.mark.parametrize("preset", ["design", "swiss-modern"])
def test_every_block_slide_fits_and_reads_in_both_themes(brand_dir, preset):
    pytest.importorskip("playwright.sync_api")
    out = brand_dir / ("blocks-%s.html" % preset)
    deck(out, "--blocks", "all", "--preset", preset)
    data = gate(out, "--deck")
    skipped = [f for f in errors(data) if f["rule"] == "browser-skipped"]
    if skipped:
        pytest.skip(skipped[0]["message"])
    assert errors(data) == [], errors(data)


GLOSSARY_SLIDES = """
<section class="slide slide--content" id="talk">
  <h2 class="slide__heading"><span data-de>Warum es dauert</span><span data-en>Why it takes long</span></h2>
  <p class="slide__body"><span data-de>Die <a href="#gl-latency" data-term="latency">Latenz</a> zählt.</span><span data-en>The <a href="#gl-latency" data-term="latency">latency</a> counts.</span></p>
</section>
<section class="slide slide--content" id="chart">
  <div class="blk">%s</div>
</section>
<section class="slide slide--content" id="terms">
  <section class="glossary" aria-labelledby="glossary-h">
    <h2 id="glossary-h"><span data-de>Glossar</span><span data-en>Glossary</span></h2>
    <dl class="gl-list">
      <dt id="gl-latency"><dfn><span data-de>Latenz</span><span data-en>Latency</span></dfn></dt>
      <dd><span data-de>Zeit bis zur Antwort.</span><span data-en>Time until the answer.</span></dd>
    </dl>
  </section>
</section>
"""


def alt_table_markup() -> str:
    md = (CANVAS / "references" / "sections.md").read_text("utf-8")
    body = md[md.index('<a id="alt-table"></a>'):]
    return re.search(r"```html\n(.*?)```", body, re.S).group(1)


def scripted_deck(tmp: Path, *extra) -> str:
    frag = tmp / "slides.html"
    frag.write_text(GLOSSARY_SLIDES % alt_table_markup(), encoding="utf-8")
    out = tmp / "scripted.html"
    run("--title", "Terms", "--out", out, "--no-embed-fonts", "--slides", frag,
        "--blocks", "glossary,alt-table", *extra)
    return out.read_text("utf-8")


def wait_ready(page):
    page.wait_for_function("() => !!(window.SlideDeck && window.SlideDeck.count() > 0)")


def test_glossary_popover_opens_inside_a_slide_and_follows_the_language(open_html, plain_dir):
    page = open_html(scripted_deck(plain_dir))
    wait_ready(page)
    page.locator("#talk a[data-term]:visible").click()
    page.wait_for_function("() => { const p = document.querySelector('.gl-pop'); return p && p.matches(':popover-open'); }")
    assert page.evaluate("() => window.SlideDeck.current()") == 0, "the term opens, the deck stays"
    head = page.locator(".gl-pop-h")
    assert head.inner_text().strip() == "Latency"
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.querySelector('.gl-pop').matches(':popover-open')")
    page.keyboard.press("l")
    page.wait_for_function("() => document.documentElement.getAttribute('data-lang') === 'de'")
    page.locator("#talk a[data-term]:visible").click()
    page.wait_for_function("() => document.querySelector('.gl-pop').matches(':popover-open')")
    assert head.inner_text().strip() == "Latenz"
    assert page.errors == []


def test_glossary_popover_works_in_the_read_module(open_html, plain_dir):
    page = open_html(scripted_deck(plain_dir, "--with", "read"))
    wait_ready(page)
    page.keyboard.press("r")
    page.wait_for_function("() => document.documentElement.classList.contains('deck-read')")
    page.locator("#talk a[data-term]:visible").click()
    page.wait_for_function("() => document.querySelector('.gl-pop').matches(':popover-open')")
    assert page.locator(".gl-pop-h").inner_text().strip() == "Latency"
    assert page.errors == []


def test_alt_table_toggle_switches_chart_and_table(open_html, plain_dir):
    page = open_html(scripted_deck(plain_dir))
    wait_ready(page)
    page.evaluate("() => window.SlideDeck.goTo(1)")
    page.wait_for_function("() => document.querySelector('#chart').classList.contains('is-active')")
    btn = page.locator("#chart .alt-toggle")
    assert btn.is_visible() and not page.locator("#chart .alt-table").is_visible()
    btn.click()
    assert page.locator("#chart .alt-table").is_visible() and not page.locator("#chart .alt-chart").is_visible()
    assert btn.get_attribute("aria-expanded") == "true"
    page.keyboard.press("l")
    assert "Grafik" in btn.inner_text()
    assert page.errors == []
