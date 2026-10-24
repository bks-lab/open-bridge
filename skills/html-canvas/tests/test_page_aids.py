"""Reading aids for pages: glossary popovers, a table of contents with scroll spy,
"show as table" for charts, and a print stylesheet. All optional blocks: a page
that does not ask for them carries none of their CSS or script.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from canvas_testlib import ASSETS, SCRIPTS, SKILL

SCRIPT = SCRIPTS / "new-page.py"
VERIFY = SCRIPTS / "verify-page.py"
SECTIONS_MD = SKILL / "references" / "sections.md"
SECTIONS_JS = ASSETS / "sections.js"
DESIGN = Path(__file__).resolve().parent / "fixtures" / "tokens" / "design-current.md"
JS_BLOCK = re.compile(r"^/\* @block: ([a-z0-9-]+) \*/$", re.M)
AIDS = ("glossary", "toc", "alt-table", "print")
DASHES = ("\u2014", "\u2013", " -- ")


def run(*args, scripts=SCRIPT) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(scripts), *map(str, args)], capture_output=True, text=True)


def build(tmp_path, *args, name="page.html") -> Path:
    out = tmp_path / name
    r = run("--out", out, "--design", DESIGN, *args)
    assert r.returncode == 0, r.stdout + r.stderr
    return out


def region(text: str, name: str) -> str:
    return text.split("/* %s:begin */" % name, 1)[1].split("/* %s:end */" % name, 1)[0]


TRIGGERS = ('<p id="usage"><span data-de>Die <a href="#gl-latency" data-term="latency">Latenz</a> hängt an der '
            '<dfn data-term="queue">Warteschlange</dfn>.</span><span data-en>The '
            '<a href="#gl-latency" data-term="latency">latency</a> depends on the '
            '<dfn data-term="queue">queue</dfn>.</span></p>')


def with_triggers(page: Path) -> str:
    """The built page with in-text glossary triggers in front of the glossary."""
    return page.read_text("utf-8").replace('<main class="wrap">', '<main class="wrap">\n' + TRIGGERS, 1)


# --- catalog and assets ------------------------------------------------------------------

def test_the_reading_aids_are_catalog_blocks():
    r = run("--list")
    for name in AIDS:
        assert re.search(r"^\s+%s\b" % name, r.stdout, re.M), name


def test_every_script_block_names_a_catalog_block():
    names = JS_BLOCK.findall(SECTIONS_JS.read_text("utf-8"))
    catalog = re.findall(r'^## <a id="([a-z0-9-]+)"></a>', SECTIONS_MD.read_text("utf-8"), re.M)
    assert set(names) == {"glossary", "toc", "alt-table", "print"}
    assert set(names) <= set(catalog)
    assert len(names) == len(set(names))


def test_no_dash_punctuation_in_the_script_asset():
    text = SECTIONS_JS.read_text("utf-8")
    for d in DASHES:
        assert d not in text


# --- what a page carries -------------------------------------------------------------------

def test_a_page_without_the_aids_carries_no_script_region(tmp_path):
    text = build(tmp_path, "--blocks", "doc-header,table,callout").read_text("utf-8")
    assert "section-scripts" not in text
    for name in AIDS:
        assert "@block: %s " % name not in text and "@block: %s\n" % name not in text


def test_glossary_brings_its_script_once_and_lands_at_the_end(tmp_path):
    text = build(tmp_path, "--blocks", "glossary,table,callout").read_text("utf-8")
    assert text.count("/* section-scripts:begin */") == 1
    js = region(text, "section-scripts")
    assert "@block: glossary" in js and "@block: toc" not in js
    main = re.search(r"<main.*?</main>", text, re.S).group(0)
    assert main.index('id="blk-glossary"') > main.index('id="blk-callout"') > main.index('id="blk-table"')


def test_toc_lists_the_blocks_of_the_page(tmp_path):
    text = build(tmp_path, "--blocks", "doc-header,toc,table,callout,glossary").read_text("utf-8")
    toc = re.search(r'<nav class="toc".*?</nav>', text, re.S).group(0)
    targets = re.findall(r'href="#([^"]+)"', toc)
    assert targets == ["blk-table", "blk-callout", "blk-glossary"]
    ids = set(re.findall(r'\bid="([^"]+)"', text))
    assert set(targets) <= ids


def test_print_block_has_no_markup_only_rules(tmp_path):
    text = build(tmp_path, "--blocks", "table,print").read_text("utf-8")
    assert 'id="blk-print"' not in text
    css = region(text, "sections")
    assert "@block: print" in css and "@media print" in css
    assert "@block: print" in region(text, "section-scripts")


def test_refresh_adds_and_drops_the_script_region_contents(tmp_path):
    page = build(tmp_path, "--blocks", "table")
    r = run("--refresh", page, "--design", DESIGN, "--blocks", "table,toc")
    assert r.returncode == 0, r.stdout + r.stderr
    text = page.read_text("utf-8")
    assert "@block: toc" in region(text, "section-scripts")
    once = page.read_bytes()
    assert run("--refresh", page, "--design", DESIGN).returncode == 0
    assert page.read_bytes() == once, "refresh of a current page changed it"
    assert run("--refresh", page, "--design", DESIGN, "--blocks", "table").returncode == 0
    assert region(page.read_text("utf-8"), "section-scripts").strip() == ""


def test_pages_with_the_aids_pass_the_static_gate(tmp_path):
    page = build(tmp_path, "--blocks", "doc-header,toc,alt-table,glossary,print")
    v = run(page, "--design", DESIGN, "--allow-sample", scripts=VERIFY)
    assert v.returncode == 0, v.stdout


# --- glossary in the browser ---------------------------------------------------------------

def test_glossary_link_opens_a_popover_with_the_definition(open_page, tmp_path):
    page = open_page(with_triggers(build(tmp_path, "--blocks", "glossary")))
    assert page.errors == []
    link = page.locator('#usage a[data-term="latency"]:visible')
    link.click()
    pop = page.locator(".gl-pop:popover-open")
    assert pop.count() == 1
    assert "Latency" in pop.inner_text()
    assert page.evaluate("location.hash") == "", "the link opened the popover instead of jumping"
    assert link.get_attribute("aria-expanded") == "true"
    page.keyboard.press("Escape")
    assert page.locator(".gl-pop:popover-open").count() == 0
    assert page.evaluate("document.activeElement.getAttribute('data-term')") == "latency"
    assert link.get_attribute("aria-expanded") == "false"


def test_glossary_dfn_is_reachable_and_opens_from_the_keyboard(open_page, tmp_path):
    page = open_page(with_triggers(build(tmp_path, "--blocks", "glossary")))
    dfn = page.locator('#usage dfn[data-term="queue"]:visible')
    assert dfn.get_attribute("tabindex") == "0" and dfn.get_attribute("role") == "button"
    dfn.focus()
    page.keyboard.press("Enter")
    pop = page.locator(".gl-pop:popover-open")
    assert pop.count() == 1 and "Queue" in pop.inner_text()
    page.keyboard.press("Escape")
    dfn.focus()
    page.keyboard.press(" ")
    assert page.locator(".gl-pop:popover-open").count() == 1


def test_glossary_popover_follows_the_language(open_page, tmp_path):
    page = open_page(with_triggers(build(tmp_path, "--blocks", "glossary")))
    page.keyboard.press("l")
    page.locator('#usage a[data-term="latency"]:visible').click()
    text = page.locator(".gl-pop:popover-open").inner_text()
    assert "Latenz" in text and "Latency" not in text


def test_glossary_popover_sits_next_to_its_trigger(open_page, tmp_path):
    page = open_page(with_triggers(build(tmp_path, "--blocks", "glossary")))
    link = page.locator('#usage a[data-term="latency"]:visible')
    link.click()
    t = link.bounding_box()
    p = page.locator(".gl-pop:popover-open").bounding_box()
    assert abs(p["y"] - (t["y"] + t["height"])) < 24, (t, p)
    assert p["x"] >= 0 and p["x"] + p["width"] <= 900


def test_glossary_without_popover_support_still_jumps(open_page, tmp_path):
    page = open_page(with_triggers(build(tmp_path, "--blocks", "glossary")),
                     init_script="delete HTMLElement.prototype.popover;"
                                 "delete HTMLElement.prototype.showPopover;")
    assert page.errors == []
    page.locator('#usage a[data-term="latency"]:visible').click()
    assert page.evaluate("location.hash") == "#gl-latency"


# --- table of contents ---------------------------------------------------------------------

def test_toc_marks_the_section_in_view(open_page, tmp_path):
    html = build(tmp_path, "--blocks", "doc-header,toc,table,callout,timeline,glossary").read_text("utf-8")
    # room between the blocks, so each one gets its turn at the top
    html = html.replace('<div class="blk" id="blk-', '<div style="height:900px"></div><div class="blk" id="blk-')
    page = open_page(html)
    assert page.errors == []
    page.evaluate("document.getElementById('blk-timeline').scrollIntoView({behavior:'instant'})")
    page.wait_for_function("(document.querySelector('.toc a[aria-current]') || {}).hash === '#blk-timeline'")
    assert page.locator(".toc a[aria-current]").count() == 1


def test_an_empty_auto_toc_fills_itself_from_the_headings(open_page, tmp_path):
    html = build(tmp_path, "--blocks", "toc,section-opener").read_text("utf-8")
    html = re.sub(r'(<nav class="toc"[^>]*)>(.*?)<ol>.*?</ol>', r'\1 data-toc="auto">\2<ol></ol>', html, flags=re.S)
    page = open_page(html)
    links = page.evaluate("[...document.querySelectorAll('.toc ol a')].map(a => a.getAttribute('href'))")
    assert links == ["#core-idea"]
    assert page.locator(".toc ol a [data-en]:visible").count() == 1


# --- show as table -------------------------------------------------------------------------

def test_alt_table_toggles_between_chart_and_table(open_page, tmp_path):
    page = open_page(build(tmp_path, "--blocks", "alt-table").read_text("utf-8"))
    assert page.errors == []
    btn = page.locator(".alt-toggle")
    chart = page.locator(".alt-chart")
    table_id = chart.get_attribute("aria-describedby")
    assert table_id and page.locator("#%s table" % table_id).count() == 1
    assert btn.is_visible() and btn.get_attribute("aria-expanded") == "false"
    assert chart.is_visible() and not page.locator("#" + table_id).is_visible()
    btn.click()
    assert btn.get_attribute("aria-expanded") == "true"
    assert page.locator("#" + table_id).is_visible() and not chart.is_visible()
    assert btn.locator(".alt-hide [data-en]").is_visible()
    btn.click()
    assert chart.is_visible() and not page.locator("#" + table_id).is_visible()


def test_alt_table_without_script_shows_both_and_no_button(open_page, tmp_path):
    html = build(tmp_path, "--blocks", "alt-table").read_text("utf-8")
    html = re.sub(r"<script>\s*/\* section-scripts:begin \*/.*?</script>", "", html, flags=re.S)
    page = open_page(html)
    assert not page.locator(".alt-toggle").is_visible()
    assert page.locator(".alt-chart").is_visible() and page.locator(".alt-table").is_visible()


def test_alt_table_prints_chart_and_table(open_page, tmp_path):
    page = open_page(build(tmp_path, "--blocks", "alt-table").read_text("utf-8"))
    page.emulate_media(media="print")
    assert page.locator(".alt-chart").is_visible() and page.locator(".alt-table").is_visible()
    assert not page.locator(".alt-toggle").is_visible()


# --- print ---------------------------------------------------------------------------------

def test_print_opens_details_and_closes_them_again(open_page, tmp_path):
    page = open_page(build(tmp_path, "--blocks", "collapsible,print").read_text("utf-8"))
    assert page.evaluate("document.querySelector('details').open") is False
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    assert page.evaluate("document.querySelector('details').open") is True
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert page.evaluate("document.querySelector('details').open") is False


def test_print_spells_out_external_links_and_hides_popovers(open_page, tmp_path):
    html = with_triggers(build(tmp_path, "--blocks", "glossary,print"))
    html = html.replace("</main>", '<p><a id="ext" href="https://example.com/x">source</a></p></main>', 1)
    page = open_page(html)
    page.locator('#usage a[data-term="latency"]:visible').click()
    page.emulate_media(media="print")
    after = page.evaluate("getComputedStyle(document.getElementById('ext'), '::after').content")
    assert "https://example.com/x" in after
    assert not page.locator(".gl-pop").is_visible()
    assert page.locator(".glossary").is_visible()
