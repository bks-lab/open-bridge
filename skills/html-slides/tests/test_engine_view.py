"""The deck view (reference/slide-types.md § Engine Contract, data-view="deck").

A deck with data-view="deck" opens as stacked cards under a toolbar (title, language,
theme, help, downloads, Present); Present, P or F5 start the normal engine at the card
in view and Esc (or leaving full screen) returns to it. A deck without the attribute
behaves exactly as before. scripts/embed-downloads.py puts the PDF and PowerPoint into
the deck behind the download buttons, within a size guard.
"""
from __future__ import annotations

import argparse
import base64
import re
import subprocess
import sys

import pytest

from engine_testlib import (current, deck, module_deck, new_deck, open_deck, slide, wait_current,
                            wait_settled)
from slides_testlib import ASSETS, SKILL, load_script

EMBED = SKILL / "scripts" / "embed-downloads.py"
VIEW = 'data-view="deck"'


def notes(text: str) -> str:
    return '<aside class="notes"><p>%s</p></aside>' % text


def five_slides() -> list[str]:
    return [slide("One", ' id="a"', notes("Note A")), slide("Two", ' id="b"'),
            slide("Three", ' id="c"', notes("Note C")), slide("Four", ' id="d"'),
            slide("Five", ' id="e"')]


def view_deck(**kw) -> str:
    kw.setdefault("deck_attrs", VIEW)
    return deck(five_slides(), **kw)


def view(page) -> str:
    return page.evaluate("() => window.SlideDeck.view()")


def wait_view(page, name: str):
    page.wait_for_function("(v) => window.SlideDeck.view() === v", arg=name, timeout=4000)


def inert_count(page) -> int:
    return page.evaluate("() => document.querySelectorAll('.slide[inert]').length")


def card_top(page, sel: str) -> float:
    return page.evaluate("(s) => document.querySelector(s).getBoundingClientRect().top", sel)


def bar_height(page) -> float:
    return page.evaluate("() => document.querySelector('.deck-view-bar').getBoundingClientRect().height")


def scroll_to_card(page, sel: str):
    """Scroll the deck so that card sits under the toolbar, as a reader would."""
    page.evaluate("""(s) => { const d = document.querySelector('.deck'), c = document.querySelector(s);
      d.scrollTop += c.getBoundingClientRect().top - 90; }""", sel)
    page.wait_for_timeout(250)


def embed_args(**kw):
    base = dict(pdf=None, pptx=None, pdf_url=None, pptx_url=None, name=None,
                max_total=14 * 1024 * 1024, remove=False, out=None)
    base.update(kw)
    return argparse.Namespace(**base)


# --- off by default --------------------------------------------------------------------------

def test_without_the_attribute_nothing_changes(open_html):
    page = open_deck(open_html, deck(five_slides()))
    assert page.evaluate("() => document.querySelectorAll('.deck-view-bar').length") == 0
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-view')")
    assert view(page) == "present"
    assert inert_count(page) == 4, "the engine presents: only the active slide is live"
    page.keyboard.press("p")
    page.wait_for_timeout(200)
    assert view(page) == "present" and not page.evaluate("() => !!document.fullscreenElement")
    help_keys = page.evaluate("() => [...document.querySelectorAll('.deck-help dt')].map(d => d.innerText)")
    assert not any("F5" in k for k in help_keys), "no deck view row in the help"
    snap = page.evaluate("() => getComputedStyle(document.querySelector('.deck')).scrollSnapType")
    assert "mandatory" in snap
    assert page.errors == []


def test_deck_view_css_waits_for_the_class():
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    block = css[css.index("/* ============ DECK VIEW"):css.index("/* reduced motion: every animation */")]
    for sel in re.findall(r"([^{}]+)\{", re.sub(r"/\*.*?\*/", "", block, flags=re.S)):
        sel = sel.strip()
        if sel.startswith("@") or not sel:
            continue
        for part in sel.split(","):
            part = part.strip()
            assert ".deck-view" in part, "a deck view rule without the deck view class: %r" % part


# --- the cards ---------------------------------------------------------------------------------

def test_cards_are_stacked_scaled_and_live(open_html):
    page = open_deck(open_html, view_deck())
    assert view(page) == "deck"
    assert page.evaluate("() => document.documentElement.classList.contains('deck-view')")
    assert inert_count(page) == 0, "every card takes clicks, none inert"
    geo = page.evaluate("""() => {
      const d = document.querySelector('.deck'), cs = [...document.querySelectorAll('.slide')];
      const r = cs.map(c => c.getBoundingClientRect());
      return { cw: d.clientWidth, w: r[0].width, h: r[0].height, left: r[0].left, gap: r[1].top - r[0].bottom,
               snap: getComputedStyle(d).scrollSnapType, scroll: d.scrollWidth - d.clientWidth };
    }""")
    expect = min(1280, geo["cw"] - 48)
    assert abs(geo["w"] - expect) < 2, "scaled to the window width: %r" % geo
    assert abs(geo["w"] / geo["h"] - 16 / 9) < 0.01, "a 16:9 card"
    assert abs(geo["left"] - (geo["cw"] - geo["w"]) / 2) < 2, "centred"
    assert 10 < geo["gap"] < 40, "cards stand apart, without the unscaled layout gap"
    assert geo["snap"] in ("none", "")
    assert geo["scroll"] <= 0, "no horizontal scroll"
    assert card_top(page, "#a") >= bar_height(page), "the first card starts below the toolbar"
    assert page.errors == []


def test_never_above_full_size_on_a_wide_window(open_html):
    page = open_deck(open_html, view_deck(), viewport={"width": 1800, "height": 1000})
    w = page.evaluate("() => document.querySelector('.slide').getBoundingClientRect().width")
    assert abs(w - 1280) < 1, "100 % at most"
    page.set_viewport_size({"width": 1280, "height": 720})


def test_toolbar_holds_title_theme_help_and_present(open_html):
    page = open_deck(open_html, view_deck())
    bar = page.evaluate("""() => { const b = document.querySelector('.deck-view-bar');
      return { title: b.querySelector('.deck-view-title').innerText, role: b.getAttribute('role'),
               buttons: [...b.querySelectorAll('button')].map(x => x.getAttribute('data-deck')),
               present: b.querySelector('.deck-view-present').innerText,
               fixed: getComputedStyle(b).position }; }""")
    assert bar["title"] == "Engine fixture", "the deck title"
    assert bar["role"] == "toolbar" and bar["fixed"] == "fixed"
    assert bar["buttons"] == ["theme", "help", "present"], "no language button in a deck of one language"
    assert bar["present"] == "Present"
    theme = page.evaluate("() => window.SlideDeck.state().theme")
    page.click(".deck-view-theme")
    assert page.evaluate("() => window.SlideDeck.state().theme") != theme
    page.click(".deck-view-help")
    assert page.evaluate("() => !document.querySelector('.deck-help').hidden")
    keys = page.evaluate("() => [...document.querySelectorAll('.deck-help dt')].map(d => d.innerText.replace(/\\s+/g, ' '))")
    assert "P F5" in keys
    page.keyboard.press("Escape")
    assert page.evaluate("() => document.querySelector('.deck-help').hidden")
    assert view(page) == "deck", "Esc closes the help, the cards stay"
    assert page.errors == []


def test_bilingual_deck_gets_a_language_button_and_german_labels(open_html):
    pair = '<p><span data-de>Hallo</span><span data-en>Hello</span></p>'
    html = deck([slide("One", ' id="a"', pair), slide("Two", ' id="b"')], deck_attrs=VIEW
                + ' data-view-title-de="Quartalsbericht" data-view-title-en="Quarterly review"', lang="en")
    page = open_deck(open_html, html)
    assert page.evaluate("() => document.querySelector('.deck-view-title').innerText") == "Quarterly review"
    page.click(".deck-view-lang")
    page.wait_for_function("() => window.SlideDeck.state().lang === 'de'")
    labels = page.evaluate("""() => ({ title: document.querySelector('.deck-view-title').innerText,
      present: document.querySelector('.deck-view-present').innerText })""")
    assert labels == {"title": "Quartalsbericht", "present": "Präsentieren"}
    page.keyboard.press("l")
    page.wait_for_function("() => window.SlideDeck.state().lang === 'en'")
    assert page.errors == []


def test_scroll_picks_the_card_and_the_deep_link(open_html):
    page = open_deck(open_html, view_deck())
    scroll_to_card(page, "#c")
    wait_current(page, 2)
    page.wait_for_function("() => location.hash === '#c'")
    page.keyboard.press("n")
    assert "Note C" in page.evaluate("() => document.querySelector('.deck-notes').innerText"), \
        "the notes of the card in view"
    page.keyboard.press("n")
    assert page.errors == []


def test_deep_link_opens_the_cards_at_that_slide(open_html, tmp_path):
    page = open_deck(open_html, view_deck())
    url = page.url + "#d"
    page.goto(url)
    page.wait_for_function("() => window.SlideDeck && window.SlideDeck.current() === 3")
    assert view(page) == "deck"
    top = card_top(page, "#d")
    assert bar_height(page) - 2 <= top < bar_height(page) + 40, "the linked card sits under the toolbar"


def test_digits_and_tracks_work_on_the_cards(open_html):
    slides = five_slides()
    slides[1] = slide("Two", ' id="b" data-track="long"')
    page = open_deck(open_html, deck(slides, deck_attrs=VIEW + ' data-tracks-default="long"'))
    page.keyboard.press("4")
    page.keyboard.press("Enter")
    wait_current(page, 3)
    page.wait_for_timeout(800)
    assert abs(card_top(page, "#d") - bar_height(page)) < 40, "the number jump scrolls to the card"
    shown = lambda: page.evaluate("() => document.querySelectorAll('.slide:not(.is-filtered)').length")
    assert shown() == 5
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.track() === 'all'")
    page.keyboard.press("f")
    page.wait_for_function("() => window.SlideDeck.track() === 'long'")
    assert shown() == 5
    assert view(page) == "deck"
    assert page.errors == []


# --- present and back ----------------------------------------------------------------------------

@pytest.mark.parametrize("how", ["button", "p", "F5"])
def test_present_starts_at_the_card_in_view_and_esc_returns(open_html, how):
    page = open_deck(open_html, view_deck())
    scroll_to_card(page, "#c")
    if how == "button":
        page.click(".deck-view-present")
    else:
        page.keyboard.press(how)
    wait_view(page, "present")
    wait_settled(page, 2)
    assert inert_count(page) == 4, "presenting: only the active slide is live"
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-view')")
    assert page.evaluate("() => getComputedStyle(document.querySelector('.deck-view-bar')).display") == "none"
    page.keyboard.press("ArrowDown")
    wait_settled(page, 3)
    if page.evaluate("() => !!document.fullscreenElement"):
        page.evaluate("() => document.exitFullscreen()")   # what Esc does in full screen
    else:
        page.keyboard.press("Escape")
    wait_view(page, "deck")
    assert current(page) == 3, "back on the cards at the slide presented last"
    assert abs(card_top(page, "#d") - bar_height(page)) < 40
    assert inert_count(page) == 0
    assert page.evaluate("() => location.hash") == "#d"
    assert page.errors == []


def test_esc_without_full_screen_closes_panels_first(open_html):
    page = open_deck(open_html, view_deck())
    page.evaluate("() => window.SlideDeck.setView('present')")
    wait_view(page, "present")
    assert not page.evaluate("() => !!document.fullscreenElement"), "a script call never asks for full screen"
    page.keyboard.press("n")
    page.keyboard.press("Escape")
    assert view(page) == "present", "the first Esc closes the notes"
    page.keyboard.press("Escape")
    wait_view(page, "deck")
    assert page.errors == []


def test_viewchange_event_and_state(open_html):
    page = open_deck(open_html, view_deck())
    page.evaluate("""() => { window.__views = [];
      window.SlideDeck.on('viewchange', d => window.__views.push(d.view)); }""")
    assert page.evaluate("() => window.SlideDeck.state().view") == "deck"
    page.evaluate("() => window.SlideDeck.setView('present')")
    page.evaluate("() => window.SlideDeck.setView('deck')")
    assert page.evaluate("() => window.__views") == ["present", "deck"]
    assert page.errors == []


def test_modules_keep_working_while_presenting(open_html):
    html = module_deck(["read", "draw", "presenter"], five_slides(), deck_attrs=VIEW + " data-read-default")
    page = open_deck(open_html, html)
    assert view(page) == "deck", "the deck view wins over data-read-default"
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-read')")
    page.keyboard.press("r")
    page.keyboard.press("d")
    assert not page.evaluate("() => document.documentElement.classList.contains('deck-read')"), \
        "module keys wait while the cards show"
    page.keyboard.press("p")
    wait_view(page, "present")
    assert len(page.context.pages) == 1, "P on the cards presents, it opens no presenter window"
    page.keyboard.press("r")
    page.wait_for_function("() => document.documentElement.classList.contains('deck-read')")
    page.keyboard.press("r")
    page.wait_for_function("() => !document.documentElement.classList.contains('deck-read')")
    assert view(page) == "present"
    if page.evaluate("() => !!document.fullscreenElement"):
        page.evaluate("() => document.exitFullscreen()")
    else:
        page.keyboard.press("Escape")
    wait_view(page, "deck")
    assert page.errors == []


def test_presenter_preview_copy_ignores_the_deck_view(open_html):
    page = open_deck(open_html, deck(five_slides(), html_attrs="data-deck-preview", deck_attrs=VIEW))
    assert view(page) == "present"
    assert page.evaluate("() => document.querySelectorAll('.deck-view-bar').length") == 0


# --- print ---------------------------------------------------------------------------------------

def test_print_hides_the_toolbar_and_keeps_one_slide_per_page(open_html):
    page = open_deck(open_html, view_deck())
    page.emulate_media(media="print")
    try:
        geo = page.evaluate("""() => ({ bar: getComputedStyle(document.querySelector('.deck-view-bar')).display,
          transform: getComputedStyle(document.querySelector('.slide')).transform })""")
        assert geo["bar"] == "none"
        assert geo["transform"] in ("none", ""), "print shows slides unscaled"
        pdf = page.pdf(prefer_css_page_size=True, print_background=True)
        assert len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", pdf)) == 5
    finally:
        page.emulate_media(media="screen")


# --- downloads -----------------------------------------------------------------------------------

PDF = b"%PDF-1.4\n% sample bytes for the test\n" + bytes(range(256)) + b"\n%%EOF\n"
PPTX = b"PK\x03\x04" + bytes(range(256)) * 4


def embedded(html: str, **kw) -> str:
    mod = load_script("embed-downloads.py")
    return mod.build(html, embed_args(**kw), say=lambda m: None)


def test_embedded_downloads_give_the_exact_bytes(open_html, tmp_path):
    (tmp_path / "x.pdf").write_bytes(PDF)
    (tmp_path / "x.pptx").write_bytes(PPTX)
    html = embedded(view_deck(), pdf=str(tmp_path / "x.pdf"), pptx=str(tmp_path / "x.pptx"))
    page = open_deck(open_html, html)
    labels = page.evaluate("() => [...document.querySelectorAll('.deck-view-download')].map(b => b.innerText)")
    assert labels == ["PDF", "PowerPoint"]
    for kind, want, name in (("pdf", PDF, "Engine-fixture.pdf"), ("pptx", PPTX, "Engine-fixture.pptx")):
        with page.expect_download() as info:
            page.click(".deck-view-download[data-kind=%s]" % kind)
        dl = info.value
        assert dl.suggested_filename == name
        assert open(dl.path(), "rb").read() == want
    assert page.errors == []


def test_download_works_in_a_sandboxed_frame(browser, tmp_path):
    (tmp_path / "x.pdf").write_bytes(PDF)
    html = embedded(view_deck(), pdf=str(tmp_path / "x.pdf"))
    (tmp_path / "deck.html").write_text(html, encoding="utf-8")
    (tmp_path / "host.html").write_text(
        '<!doctype html><iframe sandbox="allow-scripts allow-downloads" src="deck.html" '
        'style="width:1200px;height:700px;border:0"></iframe>', encoding="utf-8")
    ctx = browser.new_context(viewport={"width": 1280, "height": 760}, accept_downloads=True)
    try:
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto((tmp_path / "host.html").as_uri())
        frame = page.frame_locator("iframe")
        frame.locator(".deck-view-download").wait_for()
        with page.expect_download() as info:
            frame.locator(".deck-view-download").click()
        assert open(info.value.path(), "rb").read() == PDF
        assert errors == []
    finally:
        ctx.close()


def test_slide_button_downloads_in_any_deck(open_html, tmp_path):
    (tmp_path / "x.pdf").write_bytes(PDF)
    btn = '<button class="slide__btn" data-deck="download:pdf">PDF</button>'
    html = embedded(deck([slide("One", ' id="a"', btn), slide("Two")]), pdf=str(tmp_path / "x.pdf"))
    page = open_deck(open_html, html)
    with page.expect_download() as info:
        page.click(".slide__btn")
    assert open(info.value.path(), "rb").read() == PDF
    assert page.evaluate("() => window.SlideDeck.download('docx')") is False
    assert page.errors == []


def test_url_downloads_link_the_file(open_html):
    html = embedded(view_deck(), pdf_url="files/deck.pdf")
    assert "data-href=\"files/deck.pdf\"" in html
    page = open_deck(open_html, html)
    assert page.evaluate("() => document.querySelectorAll('.deck-view-download').length") == 1


def test_downloads_hidden_in_print(open_html, tmp_path):
    (tmp_path / "x.pdf").write_bytes(PDF)
    page = open_deck(open_html, embedded(view_deck(), pdf=str(tmp_path / "x.pdf")))
    page.emulate_media(media="print")
    try:
        shown = page.evaluate("""() => [...document.querySelectorAll('.deck-view-bar, .deck-view-download')]
          .filter(e => e.getClientRects().length).length""")
        assert shown == 0
    finally:
        page.emulate_media(media="screen")


# --- embed-downloads.py ------------------------------------------------------------------------

def test_embed_names_the_files_after_the_title_and_replaces_its_region(tmp_path):
    (tmp_path / "x.pdf").write_bytes(PDF)
    html = deck(2).replace("<title>Engine fixture</title>", "<title>Quarterly review: Q3 &amp; Q4</title>")
    once = embedded(html, pdf=str(tmp_path / "x.pdf"))
    assert 'data-file="Quarterly-review-Q3-Q4.pdf"' in once
    twice = embedded(once, pdf=str(tmp_path / "x.pdf"))
    assert twice == once, "a second run replaces the region, it does not add one"
    payload = re.search(r'data-kind="pdf"[^>]*>(.*?)</script>', once, re.S).group(1)
    assert base64.b64decode("".join(payload.split())) == PDF
    removed = embedded(once, remove=True)
    assert "deck-downloads" not in removed and removed.strip() == html.strip()
    assert 'data-file="slides.pdf"' in embedded(html, pdf=str(tmp_path / "x.pdf"), name="slides")


def test_size_guard_skips_the_powerpoint_then_refuses(tmp_path):
    mod = load_script("embed-downloads.py")
    (tmp_path / "x.pdf").write_bytes(PDF)
    (tmp_path / "big.pptx").write_bytes(b"\0" * 200_000)
    html = deck(2)
    said = []
    limit = len(html.encode("utf-8")) + 50_000
    out = mod.build(html, embed_args(pdf=str(tmp_path / "x.pdf"), pptx=str(tmp_path / "big.pptx"), max_total=limit),
                    say=said.append)
    assert 'data-kind="pdf"' in out and 'data-kind="pptx"' not in out
    assert any("PowerPoint is skipped" in m for m in said)
    with pytest.raises(mod.Refused, match="--pdf-url"):
        mod.build(html, embed_args(pdf=str(tmp_path / "big.pptx"), max_total=limit), say=said.append)
    assert mod.size_arg("14MiB") == 14 * 1024 * 1024 and mod.size_arg("500k") == 512000


def test_embed_cli_refuses_without_files_and_writes_out(tmp_path):
    src = tmp_path / "deck.html"
    src.write_text(view_deck(), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(EMBED), str(src)], capture_output=True, text=True)
    assert proc.returncode == 1 and "nothing to embed" in proc.stderr
    (tmp_path / "x.pdf").write_bytes(PDF)
    out = tmp_path / "send.html"
    proc = subprocess.run([sys.executable, str(EMBED), str(src), "--pdf", str(tmp_path / "x.pdf"), "--out", str(out)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "deck-downloads:start" in out.read_text("utf-8")
    assert "deck-downloads" not in src.read_text("utf-8"), "--out leaves the source alone"


def test_refresh_keeps_the_download_region(tmp_path):
    out = tmp_path / "deck.html"
    nd = SKILL / "scripts" / "new-deck.py"
    subprocess.run([sys.executable, str(nd), "--title", "Sample deck", "--preset", "swiss-modern",
                    "--deck-attr", "data-view=deck", "--no-verify", "--out", str(out)], check=True,
                   capture_output=True)
    assert 'data-view="deck"' in out.read_text("utf-8")
    (tmp_path / "x.pdf").write_bytes(PDF)
    subprocess.run([sys.executable, str(EMBED), str(out), "--pdf", str(tmp_path / "x.pdf")], check=True,
                   capture_output=True)
    before = out.read_text("utf-8")
    subprocess.run([sys.executable, str(nd), "--refresh", str(out), "--no-verify"], check=True, capture_output=True)
    after = out.read_text("utf-8")
    region = re.compile(r"<!-- deck-downloads:start -->.*?<!-- deck-downloads:end -->", re.S)
    assert region.search(after).group(0) == region.search(before).group(0)
